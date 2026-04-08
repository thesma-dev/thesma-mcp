"""MCP tools for financial ratios."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import Context
from thesma.errors import ThesmaError

from thesma_mcp.formatters import format_percent
from thesma_mcp.server import AppContext, mcp

VALID_RATIOS = {
    "gross_margin",
    "operating_margin",
    "net_margin",
    "return_on_equity",
    "return_on_assets",
    "debt_to_equity",
    "current_ratio",
    "interest_coverage",
    "revenue_growth_yoy",
    "net_income_growth_yoy",
    "eps_growth_yoy",
}

RATIO_CATEGORIES: list[tuple[str, list[tuple[str, str]]]] = [
    (
        "Profitability",
        [
            ("gross_margin", "Gross Margin"),
            ("operating_margin", "Operating Margin"),
            ("net_margin", "Net Margin"),
        ],
    ),
    (
        "Returns",
        [
            ("return_on_equity", "Return on Equity"),
            ("return_on_assets", "Return on Assets"),
        ],
    ),
    (
        "Leverage",
        [
            ("debt_to_equity", "Debt to Equity"),
            ("current_ratio", "Current Ratio"),
            ("interest_coverage", "Interest Coverage"),
        ],
    ),
    (
        "Growth (YoY)",
        [
            ("revenue_growth_yoy", "Revenue Growth"),
            ("net_income_growth_yoy", "Net Income Growth"),
            ("eps_growth_yoy", "EPS Growth"),
        ],
    ),
]

PERCENTAGE_RATIOS = {
    "gross_margin",
    "operating_margin",
    "net_margin",
    "return_on_equity",
    "return_on_assets",
    "revenue_growth_yoy",
    "net_income_growth_yoy",
    "eps_growth_yoy",
}

MULTIPLIER_RATIOS = {
    "debt_to_equity",
    "current_ratio",
    "interest_coverage",
}


def _format_ratio_value(key: str, value: float | int | None) -> str:
    """Format a ratio value based on its type."""
    if value is None:
        return "N/A"
    if key in PERCENTAGE_RATIOS:
        return format_percent(value)
    if key in MULTIPLIER_RATIOS:
        return f"{value:.2f}x"
    return str(value)


def _validate_period_quarter(period: str, quarter: int | None) -> str | None:
    """Validate period/quarter combination. Returns error message or None."""
    if period == "quarterly" and quarter is None:
        return "Quarter (1-4) is required when period is 'quarterly'."
    if period == "annual" and quarter is not None:
        return "Quarter should not be specified when period is 'annual'."
    return None


def _get_ctx(ctx: Context[Any, AppContext, Any]) -> AppContext:
    return ctx.request_context.lifespan_context


@mcp.tool(
    description=(
        "Get computed financial ratios (margins, returns, leverage, growth) for a US public company. "
        "Derived from SEC filings."
    )
)
async def get_ratios(
    ticker: str,
    ctx: Context[Any, AppContext, Any],
    period: str = "annual",
    year: int | None = None,
    quarter: int | None = None,
) -> str:
    """Get financial ratios for a company."""
    validation_error = _validate_period_quarter(period, quarter)
    if validation_error:
        return validation_error

    app = _get_ctx(ctx)

    try:
        cik = await app.resolver.resolve(ticker)
    except ThesmaError as e:
        return str(e)

    try:
        result = await app.client.ratios.get(cik, period=period, year=year, quarter=quarter)
    except ThesmaError as e:
        return str(e)

    data = result.data
    ratios = data.ratios

    company_name = data.company.name if data.company else ticker.upper()
    company_ticker = data.company.ticker if data.company and data.company.ticker else ticker.upper()
    fiscal_year = data.fiscal_year
    fiscal_quarter = data.fiscal_quarter

    period_label = f"FY {fiscal_year}" if period == "annual" else f"Q{fiscal_quarter} {fiscal_year}"

    lines = [f"{company_name} ({company_ticker}) — Financial Ratios, {period_label}", ""]

    for category_name, category_ratios in RATIO_CATEGORIES:
        category_lines: list[str] = []
        for key, label in category_ratios:
            value = getattr(ratios, key, None)
            if value is None:
                continue
            formatted = _format_ratio_value(key, value)
            category_lines.append(f"  {label + ':':<24}{formatted}")

        if category_lines:
            lines.append(category_name)
            lines.extend(category_lines)
            lines.append("")

    filing_type = "annual" if period == "annual" else "quarterly"
    lines.append(f"Source: SEC EDGAR, derived from {filing_type} filings.")

    return "\n".join(lines)


@mcp.tool(
    description=(
        "Get a single financial ratio over time. Returns a time series for trend analysis. "
        "Valid ratios: gross_margin, operating_margin, net_margin, return_on_equity, return_on_assets, "
        "debt_to_equity, current_ratio, interest_coverage, revenue_growth_yoy, net_income_growth_yoy, eps_growth_yoy."
    )
)
async def get_ratio_history(
    ticker: str,
    ratio: str,
    ctx: Context[Any, AppContext, Any],
    period: str = "annual",
    from_year: int | None = None,
    to_year: int | None = None,
) -> str:
    """Get a single ratio over time."""
    if ratio not in VALID_RATIOS:
        return f"Invalid ratio '{ratio}'. Valid ratios are: {', '.join(sorted(VALID_RATIOS))}"

    app = _get_ctx(ctx)

    try:
        cik = await app.resolver.resolve(ticker)
    except ThesmaError as e:
        return str(e)

    try:
        result = await app.client.ratios.time_series(cik, ratio, period=period, from_year=from_year, to_year=to_year)
    except ThesmaError as e:
        return str(e)

    data = result.data
    series = data.series
    if not series:
        return f"No data found for ratio '{ratio}'."

    company_name = data.company.name if data.company else ticker.upper()
    company_ticker = data.company.ticker if data.company and data.company.ticker else ticker.upper()
    ratio_label = ratio.replace("_", " ").title()
    period_label = "Annual" if period == "annual" else "Quarterly"

    lines = [f"{company_name} ({company_ticker}) — {ratio_label} ({period_label})", ""]
    lines.append(f"{'Year':<8}Value")

    for dp in series:
        year = dp.fiscal_year
        value = dp.value
        formatted = _format_ratio_value(ratio, value)
        lines.append(f"{str(year):<8}{formatted}")

    count = len(series)
    years = [dp.fiscal_year for dp in series]
    min_year = min(years) if years else ""
    max_year = max(years) if years else ""

    lines.append("")
    lines.append(f"{count} data point{'s' if count != 1 else ''} from {min_year} to {max_year}.")
    filing_type = "annual" if period == "annual" else "quarterly"
    lines.append(f"Source: SEC EDGAR, derived from {filing_type} filings.")

    return "\n".join(lines)
