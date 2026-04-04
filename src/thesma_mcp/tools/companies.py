"""MCP tools for company discovery."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import Context

from thesma_mcp.client import ThesmaAPIError
from thesma_mcp.formatters import format_currency, format_number, format_table
from thesma_mcp.server import AppContext, mcp


def _get_ctx(ctx: Context[Any, AppContext, Any]) -> AppContext:
    return ctx.request_context.lifespan_context


@mcp.tool(
    description=(
        "Find US public companies by name or ticker symbol. "
        "Use this to look up a company before querying its financials, ratios, or filings."
    )
)
async def search_companies(
    query: str,
    ctx: Context[Any, AppContext, Any],
    tier: str | None = None,
    limit: int = 20,
) -> str:
    """Search for companies by name, ticker, or sector."""
    app = _get_ctx(ctx)
    limit = min(limit, 50)

    # Try exact ticker match first
    try:
        response = await app.client.get("/v1/us/sec/companies", params={"ticker": query.upper()})
        companies = response.get("data", [])
        if companies:
            return _format_company_list(companies, query)
    except ThesmaAPIError:
        pass

    # Fall back to name search
    params: dict[str, Any] = {"search": query, "per_page": limit}
    if tier:
        params["tier"] = tier

    response = await app.client.get("/v1/us/sec/companies", params=params)
    companies = response.get("data", [])

    if not companies:
        return f'No companies found matching "{query}". Try a different search term or check the spelling.'

    return _format_company_list(companies, query)


def _format_company_list(companies: list[dict[str, Any]], query: str) -> str:
    """Format a list of companies as a table."""
    count = len(companies)
    lines = [f'Found {count} company{"" if count == 1 else "ies"} matching "{query}"', ""]

    headers = ["#", "Ticker", "CIK", "Company", "Index"]
    rows = []
    for i, c in enumerate(companies, 1):
        tier = c.get("company_tier", c.get("tier", ""))
        index_label = _tier_label(tier)
        rows.append([str(i), c.get("ticker", ""), c.get("cik", ""), c.get("name", ""), index_label])

    table = format_table(headers, rows, alignments=["r", "l", "l", "l", "l"])
    lines.append(table)
    lines.append("")
    lines.append("Source: SEC EDGAR company registry.")
    return "\n".join(lines)


def _tier_label(tier: str | None) -> str:
    """Convert tier value to display label."""
    if not tier:
        return "Other"
    mapping = {"sp500": "S&P 500", "russell1000": "Russell 1000"}
    return mapping.get(tier, tier)


@mcp.tool(
    description=(
        "Get company details including CIK, SIC code, fiscal year end, and index membership. Accepts ticker or CIK."
    )
)
async def get_company(ticker: str, ctx: Context[Any, AppContext, Any]) -> str:
    """Get details for a single company."""
    app = _get_ctx(ctx)

    try:
        cik = await app.resolver.resolve(ticker)
    except ThesmaAPIError as e:
        return str(e)

    try:
        response = await app.client.get(f"/v1/us/sec/companies/{cik}", params={"include": "labor_context"})
    except ThesmaAPIError as e:
        return str(e)

    data = response.get("data", {})
    name = data.get("name", "Unknown")
    tkr = data.get("ticker", ticker.upper())
    sic_code = data.get("sic_code", "")
    sic_description = data.get("sic_description", "")
    tier = data.get("company_tier", data.get("tier", ""))
    fiscal_year_end = data.get("fiscal_year_end", "")

    sic_line = f"{sic_code} — {sic_description}" if sic_description else str(sic_code)

    lines = [
        f"{name} ({tkr})",
        "",
        f"{'CIK:':<18}{data.get('cik', cik)}",
        f"{'Ticker:':<18}{tkr}",
        f"{'SIC Code:':<18}{sic_line}",
        f"{'Index:':<18}{_tier_label(tier)}",
        f"{'Fiscal Year End:':<18}{fiscal_year_end}",
        "",
        "Source: SEC EDGAR company registry.",
    ]

    labor_ctx = data.get("labor_context")
    if labor_ctx:
        lines.append("")
        lines.append(_format_labor_context(labor_ctx))

    return "\n".join(lines)


def _yoy_indicator(value: float | None) -> str:
    """Return arrow indicator for YoY percentage. Empty string if null or zero."""
    if value is None or value == 0:
        return ""
    if value > 0:
        return f"▲ {value:.1f}%"
    return f"▼ {abs(value):.1f}%"


def _format_labor_context(labor_ctx: dict[str, Any]) -> str:
    """Format the labor market context section from get_company response."""
    sections: list[str] = ["## Labor Market Context"]

    # Industry section
    industry = labor_ctx.get("industry")
    if industry:
        naics = industry.get("naics_code", "")
        desc = industry.get("naics_description", "")
        header = f"**Industry (NAICS {naics}"
        if desc:
            header += f" - {desc}"
        header += ")**"
        sections.append("")
        sections.append(header)

        emp = industry.get("total_employment_thousands")
        if emp is not None:
            emp_line = f"- Employment: {format_number(emp)}K"
            yoy = _yoy_indicator(industry.get("employment_yoy_pct"))
            if yoy:
                emp_line += f" ({yoy} YoY)"
            sections.append(emp_line)

        earnings = industry.get("avg_hourly_earnings")
        if earnings is not None:
            earn_line = f"- Avg Hourly Earnings: {format_currency(earnings, decimals=2)}"
            yoy = _yoy_indicator(industry.get("earnings_yoy_pct"))
            if yoy:
                earn_line += f" ({yoy} YoY)"
            sections.append(earn_line)

    # Local market section
    local = labor_ctx.get("local_market")
    if local:
        county_name = local.get("county_name", "")
        sections.append("")
        sections.append(f"**Local Market ({county_name})**")

        ind_emp = local.get("industry_employment")
        if ind_emp is not None:
            sections.append(f"- Industry Employment: {format_number(ind_emp)}")

        avg_wage = local.get("avg_weekly_wage")
        if avg_wage is not None:
            wage_line = f"- Avg Weekly Wage: {format_currency(avg_wage, decimals=0)}"
            yoy = _yoy_indicator(local.get("industry_wage_yoy_pct"))
            if yoy:
                wage_line += f" ({yoy} YoY)"
            sections.append(wage_line)

    # Compensation benchmark section
    comp = labor_ctx.get("compensation_benchmark")
    if comp:
        soc_code = comp.get("soc_code", "")
        soc_title = comp.get("soc_title", "")
        sections.append("")
        sections.append("**CEO Compensation Benchmark**")

        median = comp.get("market_median_annual_wage")
        if median is not None:
            sections.append(f"- Market Median: {format_currency(median, decimals=0)} (SOC {soc_code}, {soc_title})")

        p75 = comp.get("market_75th_percentile")
        if p75 is not None:
            sections.append(f"- Market 75th Percentile: {format_currency(p75, decimals=0)}")

        p90 = comp.get("market_90th_percentile")
        if p90 is not None:
            sections.append(f"- Market 90th Percentile: {format_currency(p90, decimals=0)}")

        ratio = comp.get("comp_to_market_ratio")
        if ratio is not None:
            sections.append(f"- Company CEO Comp-to-Market: {ratio:.1f}x")

    return "\n".join(sections)
