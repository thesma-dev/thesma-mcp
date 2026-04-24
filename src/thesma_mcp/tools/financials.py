"""MCP tools for financial statement data."""

from __future__ import annotations

import logging
from typing import Any

from mcp.server.fastmcp import Context
from thesma.errors import ThesmaError

from thesma_mcp.formatters import format_currency, format_percent, format_source, format_table
from thesma_mcp.server import AppContext, get_client, mcp

logger = logging.getLogger(__name__)


def _resolve_currency_from_value(raw: Any, context: str = "unknown") -> str:
    """Validate a raw currency value (from an SDK attribute or a dict field)
    and default to ``USD`` with a WARNING log when missing or empty.
    """
    if raw is None or not isinstance(raw, str) or not raw.strip():
        logger.warning(
            "currency field absent from SDK response (context=%s); defaulting to USD — "
            "check SDK hoist status (IFRS-01 risk #7)",
            context,
        )
        return "USD"
    return str(raw)


def _resolve_currency(response_data: Any, context: str = "unknown") -> str:
    """Extract ``currency`` from an SDK response, falling back to ``USD``
    with a WARNING log if the field is missing or None.

    IFRS-06: silent fallback would reproduce the original hardcode bug
    invisibly. Emit a WARNING so operations can correlate the fallback
    with an SDK-version skew or a legacy cached response.
    """
    return _resolve_currency_from_value(getattr(response_data, "currency", None), context)


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
    "all": "Financial Statements",
}


def _validate_period_quarter(period: str, quarter: int | None) -> str | None:
    """Validate period/quarter combination. Returns error message or None."""
    if period == "quarterly" and quarter is None:
        return "Quarter (1-4) is required when period is 'quarterly'."
    if period == "annual" and quarter is not None:
        return "Quarter should not be specified when period is 'annual'."
    return None


def _validate_years(years: int | None, year: int | None, quarter: int | None) -> str | None:
    """Validate the ``years`` kwarg and its mutual-exclusion with ``year`` / ``quarter``.

    MCP-side cap at [1, 10] vs the SDK's [1, 20] cap. Token-budget guardrail —
    3 statements × 20 periods × 15 fields exceeds safe LLM-context envelopes.
    Direct SDK consumers retain the 20-period ceiling.
    """
    if years is None:
        return None
    if years < 1 or years > 10:
        return "years must be between 1 and 10."
    if year is not None or quarter is not None:
        return "Cannot combine 'years' with 'year' or 'quarter'. Pass 'years' alone for multi-period trend data."
    return None


@mcp.tool(
    description=(
        "Get financial statements (income statement, balance sheet, cash flow, or all three) for a "
        "US public company from SEC filings. Pass statement='all' to get all three in one call or "
        "years=N (1-10) to get the last N annual periods for trend analysis. "
        "Responses carry taxonomy ('us-gaap' or 'ifrs-full'), native-reported currency, and "
        "presentation-format metadata."
    )
)
async def get_financials(
    ticker: str,
    ctx: Context[Any, AppContext, Any],
    statement: str = "income",
    period: str = "annual",
    year: int | None = None,
    quarter: int | None = None,
    years: int | None = None,
) -> str:
    """Get financial statements for a company."""
    # `years` validation runs BEFORE `period/quarter` validation — if the user
    # passed years=5 alongside period="quarterly" their intent is clearly
    # multi-period; the more helpful error is the years-specific mutual-exclusion
    # message, not "Quarter (1-4) is required".
    years_error = _validate_years(years, year, quarter)
    if years_error:
        return years_error

    if years is None:
        validation_error = _validate_period_quarter(period, quarter)
        if validation_error:
            return validation_error

    app = _get_ctx(ctx)
    client = get_client(ctx)

    try:
        cik = await app.resolver.resolve(ticker, client=client)
    except ThesmaError as e:
        return str(e)

    try:
        if years is not None:
            result = await client.financials.get(  # type: ignore[misc]
                cik, statement=statement, period=period, per_page=years
            )
        else:
            result = await client.financials.get(  # type: ignore[misc]
                cik, statement=statement, period=period, year=year, quarter=quarter
            )
    except ThesmaError as e:
        return str(e)

    # Dispatch on (statement, years) to match the SDK's response shape.
    if statement == "all" and years is not None:
        return _format_multi_statement_history(result, ticker)
    if statement == "all":
        return _format_multi_statement(result, ticker, period)
    if years is not None:
        return _format_statement_history(result, ticker, statement)
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

    lines = [f"{company_name} ({company_ticker}) \u2014 {title}, {period_label}", ""]

    # IFRS-06: hoist currency resolution BEFORE the formatting loop so it
    # can be threaded into format_currency. Missing / null currency still
    # defaults to USD with a WARNING (see _resolve_currency).
    currency = _resolve_currency(data, context=f"get_financials:{ticker}:{statement}")

    fields = STATEMENT_FIELDS.get(statement, [])
    line_items = data.line_items
    revenue = line_items.get("revenue")

    for key, label in fields:
        value = line_items.get(key)
        if value is None:
            continue

        if key in ("eps_basic", "eps_diluted"):
            formatted = format_currency(value, decimals=2, currency=currency)
        elif key == "common_shares_outstanding":
            formatted = f"{int(value):,}"
        else:
            formatted = format_currency(value, currency=currency)

        margin_str = ""
        if statement == "income" and key in MARGIN_FIELDS and revenue and revenue != 0:
            margin_pct = (value / revenue) * 100
            margin_str = f"  ({format_percent(margin_pct)})"

        lines.append(f"{label + ':':<24}{formatted}{margin_str}")

    lines.append("")
    lines.append(f"Currency: {currency}")
    lines.append(format_source(filing_type, accession=filing_accession, data_source=data_source))
    if fiscal_year:
        period_desc = "fiscal year ending" if period == "annual" else f"Q{fiscal_quarter} of fiscal year"
        lines.append(f"Data covers {period_desc} {fiscal_year}.")

    return "\n".join(lines)


def _get_ctx(ctx: Context[Any, AppContext, Any]) -> AppContext:
    return ctx.request_context.lifespan_context


# --- MCP-25: multi-period + multi-statement formatters ---


def _format_line_item_value(key: str, value: Any, currency: str | None = None) -> str:
    """Shared per-field formatting for statement rendering.

    Mirrors the formatting used in `_format_statement` so the wide-table
    renderers (multi-period, multi-statement) produce visually consistent cells.
    ``currency`` threads the per-row / per-period ISO code so IFRS filers
    render native symbols; falls back to USD when omitted.
    """
    if value is None:
        return ""
    if key in ("eps_basic", "eps_diluted"):
        return format_currency(value, decimals=2, currency=currency)
    if key == "common_shares_outstanding":
        return f"{int(value):,}"
    return format_currency(value, currency=currency)


def _resolve_list_item_fields(item: Any) -> dict[str, Any]:
    """Extract the wire fields from a ``FinancialStatementListItem``.

    The SDK-generated class is ``extra="allow"`` passthrough with zero typed
    fields — all values live in ``model_extra``. This helper centralizes the
    access pattern.
    """
    extra = getattr(item, "model_extra", None) or {}
    return {
        "fiscal_year": extra.get("fiscal_year"),
        "line_items": extra.get("line_items") or {},
        "currency": extra.get("currency"),
        "taxonomy": extra.get("taxonomy"),
        "company": extra.get("company") or {},
        "filing_accession": extra.get("filing_accession"),
        "metadata": extra.get("metadata") or {},
    }


def _format_drift_notes(items: list[dict[str, Any]], footer: list[str]) -> None:
    """Append currency / taxonomy drift notes when a multi-period response spans
    a transition. Collects the set of unique values across all periods; emits a
    one-line note when the set has more than one element (catches mid-series
    oscillation, not just first-to-last diffs).
    """
    unique_currencies = {r["currency"] for r in items if r.get("currency")}
    unique_taxonomies = {r["taxonomy"] for r in items if r.get("taxonomy")}
    if len(unique_currencies) > 1:
        footer.append(f"Currency changed across reported periods: {', '.join(sorted(unique_currencies))}.")
    if len(unique_taxonomies) > 1:
        footer.append(f"Taxonomy changed across reported periods: {', '.join(sorted(unique_taxonomies))}.")


def _format_statement_history(result: Any, ticker: str, statement: str) -> str:
    """Render N periods of a single statement as a wide table (year columns).

    ``result`` is a ``PaginatedResponse[FinancialStatementListItem]``. Items are
    most-recent-first per the SDK contract. ``FinancialStatementListItem`` is an
    ``extra="allow"`` passthrough so all field reads go through ``model_extra``.

    Edge case: ``len(items) == 1``. Render as a 1-year wide table rather than
    delegating back to ``_format_statement`` — the latter reads nested typed
    attributes (``data.company.name``, ``data.metadata.source``) that are dict
    values in ``model_extra`` on the list-item shape, so delegation would
    AttributeError on the first dotted access.
    """
    items_raw = result.data
    if not items_raw:
        title = STATEMENT_TITLES.get(statement, statement)
        return f"No financial data found for this company. The company may not have filed a {title} yet."

    items = [_resolve_list_item_fields(i) for i in items_raw]
    stmt_title = STATEMENT_TITLES.get(statement, statement)

    first_company = items[0]["company"] or {}
    company_name = first_company.get("name") or ticker.upper()
    company_ticker = first_company.get("ticker") or ticker.upper()
    years = [str(r["fiscal_year"]) if r["fiscal_year"] is not None else "" for r in items]
    title = f"{company_name} ({company_ticker}) — {stmt_title} History ({len(items)} years, FY {years[-1]}-{years[0]})"

    headers = ["Line Item", *years]
    alignments = ["l", *["r" for _ in years]]
    fields = STATEMENT_FIELDS.get(statement, [])

    rows: list[list[str]] = []
    for key, label in fields:
        cells = [_format_line_item_value(key, r["line_items"].get(key), currency=r.get("currency")) for r in items]
        if not any(c for c in cells):
            continue
        rows.append([label, *cells])

    lines = [title, ""]
    lines.append(format_table(headers, rows, alignments=alignments))
    lines.append("")

    footer_currency = _resolve_currency_from_value(
        items[0].get("currency"), context=f"get_financials:{ticker}:{statement}:history"
    )
    footer = [f"Currency: {footer_currency}"]
    _format_drift_notes(items, footer)
    footer.append("Source: SEC EDGAR, iXBRL filings.")
    lines.extend(footer)
    return "\n".join(lines)


def _extract_multi_statement_data(result: Any) -> dict[str, Any]:
    """Extract the nested ``data`` dict from an ``EnrichedMultiStatementResponse``.

    The envelope is ``extra="allow"`` passthrough; ``.data`` sits in ``model_extra``.
    """
    extra = getattr(result, "model_extra", None) or {}
    data = extra.get("data") or {}
    return data if isinstance(data, dict) else {}


def _render_statement_section(
    label: str,
    statement_body: dict[str, Any] | None,
    field_list: list[tuple[str, str]],
    currency: str | None = None,
) -> list[str]:
    """Render one statement section inside a multi-statement block."""
    lines = [f"## {label}"]
    if statement_body is None:
        lines.append("(not available for this period)")
        return lines
    line_items = statement_body.get("line_items") or {}
    for key, display in field_list:
        value = line_items.get(key)
        if value is None:
            continue
        lines.append(f"{display + ':':<24}{_format_line_item_value(key, value, currency=currency)}")
    return lines


def _format_multi_statement(result: Any, ticker: str, period: str) -> str:
    """Render all three statements for a single period, stacked vertically."""
    data = _extract_multi_statement_data(result)
    if not data:
        return "No financial data found for this company."

    company = data.get("company") or {}
    company_name = company.get("name") or ticker.upper()
    company_ticker = company.get("ticker") or ticker.upper()
    fiscal_year = data.get("fiscal_year")
    fiscal_quarter = data.get("fiscal_quarter")
    filing_accession = data.get("filing_accession")
    metadata = data.get("metadata") or {}
    data_source = metadata.get("source") or "ixbrl"
    currency = _resolve_currency_from_value(
        data.get("currency"), context=f"get_financials:{ticker}:all:multi_statement"
    )
    period_label = f"FY {fiscal_year}" if period == "annual" else f"Q{fiscal_quarter} {fiscal_year}"
    filing_type = "10-K" if period == "annual" else "10-Q"

    lines = [f"{company_name} ({company_ticker}) — Financial Statements, {period_label}", ""]

    statements = data.get("statements") or {}
    for key, label, fields in (
        ("income", "Income Statement", INCOME_FIELDS),
        ("balance_sheet", "Balance Sheet", BALANCE_SHEET_FIELDS),
        ("cash_flow", "Cash Flow", CASH_FLOW_FIELDS),
    ):
        lines.append("")
        lines.extend(_render_statement_section(label, statements.get(key), fields, currency=currency))

    lines.append("")
    lines.append(f"Currency: {currency}")
    lines.append(format_source(filing_type, accession=filing_accession, data_source=data_source))
    if fiscal_year:
        period_desc = "fiscal year ending" if period == "annual" else f"Q{fiscal_quarter} of fiscal year"
        lines.append(f"Data covers {period_desc} {fiscal_year}.")
    return "\n".join(lines)


def _format_multi_statement_history(result: Any, ticker: str) -> str:
    """Render all three statements, each as a wide table across N periods."""
    extra = getattr(result, "model_extra", None) or {}
    periods_raw = extra.get("data") or []
    if not isinstance(periods_raw, list) or not periods_raw:
        return "No financial data found for this company."

    periods = [p if isinstance(p, dict) else {} for p in periods_raw]
    first_company = periods[0].get("company") or {}
    company_name = first_company.get("name") or ticker.upper()
    company_ticker = first_company.get("ticker") or ticker.upper()
    years = [str(p.get("fiscal_year")) if p.get("fiscal_year") is not None else "" for p in periods]
    title = (
        f"{company_name} ({company_ticker}) — Financial Statements History ({len(periods)} years, "
        f"FY {years[-1]}-{years[0]})"
    )

    lines = [title, ""]

    for key, label, field_list in (
        ("income", "Income Statement", INCOME_FIELDS),
        ("balance_sheet", "Balance Sheet", BALANCE_SHEET_FIELDS),
        ("cash_flow", "Cash Flow", CASH_FLOW_FIELDS),
    ):
        # Collect per-statement line-item cells across periods.
        section_rows: list[list[str]] = []
        for field_key, display in field_list:
            cells: list[str] = []
            any_populated = False
            for p in periods:
                body = (p.get("statements") or {}).get(key)
                if body is None:
                    cells.append("")
                    continue
                value = (body.get("line_items") or {}).get(field_key)
                cells.append(_format_line_item_value(field_key, value, currency=p.get("currency")))
                if value is not None:
                    any_populated = True
            if not any_populated:
                continue
            section_rows.append([display, *cells])
        if not section_rows:
            # Every period lacked this statement — skip the section entirely.
            continue
        lines.append("")
        lines.append(f"## {label}")
        headers = ["Line Item", *years]
        alignments = ["l", *["r" for _ in years]]
        lines.append(format_table(headers, section_rows, alignments=alignments))

    lines.append("")
    # Footer — synthesize per-period records for the drift-note helper.
    synth = [{"currency": p.get("currency"), "taxonomy": p.get("taxonomy")} for p in periods]
    footer_currency = _resolve_currency_from_value(
        periods[0].get("currency"), context=f"get_financials:{ticker}:all:history"
    )
    footer = [f"Currency: {footer_currency}"]
    _format_drift_notes(synth, footer)
    footer.append("Source: SEC EDGAR, iXBRL filings.")
    lines.extend(footer)
    return "\n".join(lines)


@mcp.tool(
    description=(
        "Get a single financial metric over time. Returns a time series for trend analysis. "
        "Series points carry per-point currency and taxonomy metadata, authoritative over the "
        "envelope currency when a filer changes presentation currency mid-series. "
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
    client = get_client(ctx)

    try:
        cik = await app.resolver.resolve(ticker, client=client)
    except ThesmaError as e:
        return str(e)

    try:
        result = await client.financials.time_series(  # type: ignore[misc]
            cik, metric, period=period, from_year=from_year, to_year=to_year
        )
    except ThesmaError as e:
        return str(e)

    data = result.data
    series = data.series
    if not series:
        return f"No data found for metric '{metric}'. The company may not report this field."

    # IFRS-06: hoist envelope-level currency resolution before the
    # per-datapoint loop so format_currency can pick the right symbol.
    currency = _resolve_currency(data, context=f"get_financial_metric:{ticker}:{metric}")

    company_name = data.company.name if data.company else ticker.upper()
    company_ticker = data.company.ticker if data.company and data.company.ticker else ticker.upper()
    metric_label = metric.replace("_", " ").title()
    period_label = "Annual" if period == "annual" else "Quarterly"

    lines = [f"{company_name} ({company_ticker}) \u2014 {metric_label} ({period_label})", ""]
    lines.append(f"{'Year':<8}Value")

    for dp in series:
        year = dp.fiscal_year
        value = dp.value
        if metric in ("eps_basic", "eps_diluted"):
            formatted = format_currency(value, decimals=2, currency=currency)
        else:
            formatted = format_currency(value, currency=currency)
        lines.append(f"{str(year):<8}{formatted}")

    count = len(series)
    years = [dp.fiscal_year for dp in series]
    min_year = min(years) if years else ""
    max_year = max(years) if years else ""

    lines.append("")
    lines.append(f"{count} data point{'s' if count != 1 else ''} from {min_year} to {max_year}.")
    lines.append(f"Source: SEC EDGAR, iXBRL filings. Currency: {currency}.")

    return "\n".join(lines)
