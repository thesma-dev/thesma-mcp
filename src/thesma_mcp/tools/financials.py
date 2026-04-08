"""MCP tools for financial statement data."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import Context
from thesma.errors import ThesmaError

from thesma_mcp.formatters import format_currency, format_percent, format_source
from thesma_mcp.server import AppContext, mcp

INCOME_FIELDS = [
    ("revenue", "Revenue"),
    ("cost_of_revenue", "Cost of Revenue"),
    ("gross_profit", "Gross Profit"),
    ("operating_expenses", "Operating Expenses"),
    ("research_and_development", "  R&D"),
    ("selling_general_admin", "  SG&A"),
    ("operating_income", "Operating Income"),
    ("interest_expense", "Interest Expense"),
    ("interest_income", "Interest Income"),
    ("pre_tax_income", "Pre-Tax Income"),
    ("income_tax_expense", "Income Tax"),
    ("net_income", "Net Income"),
    ("eps_basic", "EPS (basic)"),
    ("eps_diluted", "EPS (diluted)"),
]

MARGIN_FIELDS = {
    "gross_profit": "margin",
    "operating_income": "margin",
    "net_income": "margin",
}

BALANCE_SHEET_FIELDS = [
    ("total_assets", "Total Assets"),
    ("current_assets", "Current Assets"),
    ("cash_and_equivalents", "  Cash & Equivalents"),
    ("accounts_receivable", "  Accounts Receivable"),
    ("inventory", "  Inventory"),
    ("non_current_assets", "Non-Current Assets"),
    ("property_plant_equipment", "  Property, Plant & Equipment"),
    ("goodwill", "  Goodwill"),
    ("intangible_assets", "  Intangible Assets"),
    ("total_liabilities", "Total Liabilities"),
    ("current_liabilities", "Current Liabilities"),
    ("accounts_payable", "  Accounts Payable"),
    ("short_term_debt", "  Short-Term Debt"),
    ("non_current_liabilities", "Non-Current Liabilities"),
    ("long_term_debt", "  Long-Term Debt"),
    ("total_equity", "Total Equity"),
    ("common_shares_outstanding", "Common Shares Outstanding"),
]

CASH_FLOW_FIELDS = [
    ("operating_cash_flow", "Operating Cash Flow"),
    ("investing_cash_flow", "Investing Cash Flow"),
    ("financing_cash_flow", "Financing Cash Flow"),
    ("net_change_in_cash", "Net Change in Cash"),
    ("capital_expenditures", "Capital Expenditures"),
    ("dividends_paid", "Dividends Paid"),
    ("share_repurchases", "Share Repurchases"),
]

VALID_METRICS: set[str] = set()
for _fields in [INCOME_FIELDS, BALANCE_SHEET_FIELDS, CASH_FLOW_FIELDS]:
    for _key, _label in _fields:
        VALID_METRICS.add(_key)
# Add shares fields
VALID_METRICS.update({"shares_basic", "shares_diluted"})

STATEMENT_FIELDS = {
    "income": INCOME_FIELDS,
    "balance-sheet": BALANCE_SHEET_FIELDS,
    "cash-flow": CASH_FLOW_FIELDS,
}

STATEMENT_TITLES = {
    "income": "Income Statement",
    "balance-sheet": "Balance Sheet",
    "cash-flow": "Cash Flow",
}


def _validate_period_quarter(period: str, quarter: int | None) -> str | None:
    """Validate period/quarter combination. Returns error message or None."""
    if period == "quarterly" and quarter is None:
        return "Quarter (1-4) is required when period is 'quarterly'."
    if period == "annual" and quarter is not None:
        return "Quarter should not be specified when period is 'annual'."
    return None


@mcp.tool(
    description=(
        "Get financial statements (income statement, balance sheet, or cash flow) for a US public company "
        "from SEC filings. Returns key line items with formatted values."
    )
)
async def get_financials(
    ticker: str,
    ctx: Context[Any, AppContext, Any],
    statement: str = "income",
    period: str = "annual",
    year: int | None = None,
    quarter: int | None = None,
) -> str:
    """Get financial statements for a company."""
    validation_error = _validate_period_quarter(period, quarter)
    if validation_error:
        return validation_error

    app = _get_ctx(ctx)

    try:
        cik = await app.resolver.resolve(ticker)
    except ThesmaError as e:
        return str(e)

    try:
        result = await app.client.financials.get(cik, statement=statement, period=period, year=year, quarter=quarter)
    except ThesmaError as e:
        return str(e)

    data = result.data
    if not data.line_items:
        title = STATEMENT_TITLES.get(statement, statement)
        return f"No financial data found for this company. The company may not have filed a {title} yet."

    return _format_statement(data, ticker, statement, period)


def _format_statement(data: Any, ticker: str, statement: str, period: str) -> str:
    """Format a financial statement response."""
    company_name = data.company.name if data.company else ticker.upper()
    company_ticker = data.company.ticker if data.company and data.company.ticker else ticker.upper()
    fiscal_year = data.fiscal_year
    fiscal_quarter = data.fiscal_quarter
    filing_accession = data.filing_accession
    data_source = data.metadata.source if data.metadata else "ixbrl"

    title = STATEMENT_TITLES.get(statement, statement)
    period_label = f"FY {fiscal_year}" if period == "annual" else f"Q{fiscal_quarter} {fiscal_year}"
    filing_type = "10-K" if period == "annual" else "10-Q"

    lines = [f"{company_name} ({company_ticker}) — {title}, {period_label}", ""]

    fields = STATEMENT_FIELDS.get(statement, [])
    line_items = data.line_items
    revenue = line_items.get("revenue")

    for key, label in fields:
        value = line_items.get(key)
        if value is None:
            continue

        if key in ("eps_basic", "eps_diluted"):
            formatted = format_currency(value, decimals=2)
        elif key == "common_shares_outstanding":
            formatted = f"{int(value):,}"
        else:
            formatted = format_currency(value)

        margin_str = ""
        if statement == "income" and key in MARGIN_FIELDS and revenue and revenue != 0:
            margin_pct = (value / revenue) * 100
            margin_str = f"  ({format_percent(margin_pct)})"

        lines.append(f"{label + ':':<24}{formatted}{margin_str}")

    lines.append("")
    lines.append("Currency: USD")
    lines.append(format_source(filing_type, accession=filing_accession, data_source=data_source))
    if fiscal_year:
        period_desc = "fiscal year ending" if period == "annual" else f"Q{fiscal_quarter} of fiscal year"
        lines.append(f"Data covers {period_desc} {fiscal_year}.")

    return "\n".join(lines)


def _get_ctx(ctx: Context[Any, AppContext, Any]) -> AppContext:
    return ctx.request_context.lifespan_context


@mcp.tool(
    description=(
        "Get a single financial metric over time. Returns a time series for trend analysis. "
        "Income metrics: revenue, cost_of_revenue, gross_profit, operating_expenses, "
        "research_and_development, selling_general_admin, operating_income, interest_expense, "
        "interest_income, pre_tax_income, income_tax_expense, net_income, eps_basic, eps_diluted, "
        "shares_basic, shares_diluted. "
        "Balance sheet: total_assets, current_assets, cash_and_equivalents, accounts_receivable, "
        "inventory, non_current_assets, property_plant_equipment, goodwill, intangible_assets, "
        "total_liabilities, current_liabilities, accounts_payable, short_term_debt, "
        "non_current_liabilities, long_term_debt, total_equity, common_shares_outstanding. "
        "Cash flow: operating_cash_flow, investing_cash_flow, financing_cash_flow, "
        "net_change_in_cash, capital_expenditures, dividends_paid, share_repurchases."
    )
)
async def get_financial_metric(
    ticker: str,
    metric: str,
    ctx: Context[Any, AppContext, Any],
    period: str = "annual",
    from_year: int | None = None,
    to_year: int | None = None,
) -> str:
    """Get a single financial metric over time."""
    if metric not in VALID_METRICS:
        return f"Invalid metric '{metric}'. Valid metrics are: {', '.join(sorted(VALID_METRICS))}"

    app = _get_ctx(ctx)

    try:
        cik = await app.resolver.resolve(ticker)
    except ThesmaError as e:
        return str(e)

    try:
        result = await app.client.financials.time_series(
            cik, metric, period=period, from_year=from_year, to_year=to_year
        )
    except ThesmaError as e:
        return str(e)

    data = result.data
    series = data.series
    if not series:
        return f"No data found for metric '{metric}'. The company may not report this field."

    company_name = data.company.name if data.company else ticker.upper()
    company_ticker = data.company.ticker if data.company and data.company.ticker else ticker.upper()
    metric_label = metric.replace("_", " ").title()
    period_label = "Annual" if period == "annual" else "Quarterly"

    lines = [f"{company_name} ({company_ticker}) — {metric_label} ({period_label})", ""]
    lines.append(f"{'Year':<8}Value")

    for dp in series:
        year = dp.fiscal_year
        value = dp.value
        if metric in ("eps_basic", "eps_diluted"):
            formatted = format_currency(value, decimals=2)
        else:
            formatted = format_currency(value)
        lines.append(f"{str(year):<8}{formatted}")

    count = len(series)
    years = [dp.fiscal_year for dp in series]
    min_year = min(years) if years else ""
    max_year = max(years) if years else ""

    lines.append("")
    lines.append(f"{count} data point{'s' if count != 1 else ''} from {min_year} to {max_year}.")
    lines.append("Source: SEC EDGAR, iXBRL filings. Currency: USD.")

    return "\n".join(lines)
