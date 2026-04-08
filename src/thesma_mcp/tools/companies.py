"""MCP tools for company discovery."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import Context
from thesma.errors import ThesmaError

from thesma_mcp.formatters import format_currency, format_number, format_table
from thesma_mcp.server import AppContext, get_client, mcp


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
    client = get_client(ctx)
    limit = min(limit, 50)

    # Try exact ticker match first
    try:
        response = await client.companies.list(ticker=query.upper())  # type: ignore[misc]
        if response.data:
            return _format_company_list(response.data, query)
    except ThesmaError:
        pass

    # Fall back to name search
    try:
        response = await client.companies.list(search=query, tier=tier, per_page=limit)  # type: ignore[misc]
    except ThesmaError as e:
        return str(e)

    if not response.data:
        return f'No companies found matching "{query}". Try a different search term or check the spelling.'

    return _format_company_list(response.data, query)


def _format_company_list(companies: list[Any], query: str) -> str:
    """Format a list of companies as a table."""
    count = len(companies)
    lines = [f'Found {count} company{"" if count == 1 else "ies"} matching "{query}"', ""]

    headers = ["#", "Ticker", "CIK", "Company", "Index"]
    rows = []
    for i, c in enumerate(companies, 1):
        tier = str(c.company_tier.value) if hasattr(c.company_tier, "value") else str(c.company_tier or "")
        index_label = _tier_label(tier)
        rows.append([str(i), c.ticker or "", c.cik, c.name, index_label])

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
    client = get_client(ctx)

    try:
        cik = await app.resolver.resolve(ticker, client=client)
    except ThesmaError as e:
        return str(e)

    try:
        result = await client.companies.get(cik, include="labor_context")  # type: ignore[misc]
    except ThesmaError as e:
        return str(e)

    data = result.data
    # EnrichedCompanyData uses extra="allow", so access via attributes or model_extra
    name = getattr(data, "name", "Unknown")
    tkr = getattr(data, "ticker", ticker.upper())
    sic_code = getattr(data, "sic_code", "")
    sic_description = getattr(data, "sic_description", "")
    tier_raw = getattr(data, "company_tier", "")
    tier = str(tier_raw.value) if hasattr(tier_raw, "value") else str(tier_raw or "")
    fiscal_year_end = getattr(data, "fiscal_year_end", "")
    data_cik = getattr(data, "cik", cik)

    sic_line = f"{sic_code} — {sic_description}" if sic_description else str(sic_code)

    lines = [
        f"{name} ({tkr})",
        "",
        f"{'CIK:':<18}{data_cik}",
        f"{'Ticker:':<18}{tkr}",
        f"{'SIC Code:':<18}{sic_line}",
        f"{'Index:':<18}{_tier_label(tier)}",
        f"{'Fiscal Year End:':<18}{fiscal_year_end}",
        "",
        "Source: SEC EDGAR company registry.",
    ]

    labor_ctx = getattr(data, "labor_context", None)
    # Also check model_extra for labor_context if not a direct attribute
    if labor_ctx is None and hasattr(data, "model_extra"):
        labor_ctx = data.model_extra.get("labor_context")
    if labor_ctx:
        lines.append("")
        # labor_ctx might be a LaborContext model or a dict (from extra="allow")
        if isinstance(labor_ctx, dict):
            lines.append(_format_labor_context(labor_ctx))
        else:
            lines.append(_format_labor_context_model(labor_ctx))

    return "\n".join(lines)


def _yoy_indicator(value: float | None) -> str:
    """Return arrow indicator for YoY percentage. Empty string if null or zero."""
    if value is None or value == 0:
        return ""
    if value > 0:
        return f"\u25b2 {value:.1f}%"
    return f"\u25bc {abs(value):.1f}%"


def _format_labor_context_model(labor_ctx: Any) -> str:
    """Format the labor market context from a LaborContext Pydantic model."""
    sections: list[str] = ["## Labor Market Context"]

    industry = getattr(labor_ctx, "industry", None)
    if industry:
        naics = getattr(industry, "naics_code", "")
        desc = getattr(industry, "naics_description", "")
        header = f"**Industry (NAICS {naics}"
        if desc:
            header += f" - {desc}"
        header += ")**"
        sections.append("")
        sections.append(header)

        emp = getattr(industry, "total_employment_thousands", None)
        if emp is not None:
            emp_line = f"- Employment: {format_number(emp)}K"
            yoy = _yoy_indicator(getattr(industry, "employment_yoy_pct", None))
            if yoy:
                emp_line += f" ({yoy} YoY)"
            sections.append(emp_line)

        earnings = getattr(industry, "avg_hourly_earnings", None)
        if earnings is not None:
            earn_line = f"- Avg Hourly Earnings: {format_currency(earnings, decimals=2)}"
            yoy = _yoy_indicator(getattr(industry, "earnings_yoy_pct", None))
            if yoy:
                earn_line += f" ({yoy} YoY)"
            sections.append(earn_line)

    local = getattr(labor_ctx, "local_market", None)
    if local:
        county_name = getattr(local, "county_name", "")
        sections.append("")
        sections.append(f"**Local Market ({county_name})**")

        ind_emp = getattr(local, "industry_employment", None)
        if ind_emp is not None:
            sections.append(f"- Industry Employment: {format_number(ind_emp)}")

        avg_wage = getattr(local, "avg_weekly_wage", None)
        if avg_wage is None:
            avg_wage = getattr(local, "industry_avg_weekly_wage", None)
        if avg_wage is not None:
            wage_line = f"- Avg Weekly Wage: {format_currency(avg_wage, decimals=0)}"
            yoy = _yoy_indicator(getattr(local, "industry_wage_yoy_pct", None))
            if yoy:
                wage_line += f" ({yoy} YoY)"
            sections.append(wage_line)

    comp = getattr(labor_ctx, "compensation_benchmark", None)
    if comp:
        soc_code = getattr(comp, "soc_code", "")
        soc_title = getattr(comp, "soc_title", "")
        sections.append("")
        sections.append("**CEO Compensation Benchmark**")

        median = getattr(comp, "market_median_annual_wage", None)
        if median is not None:
            sections.append(f"- Market Median: {format_currency(median, decimals=0)} (SOC {soc_code}, {soc_title})")

        p75 = getattr(comp, "market_75th_percentile", None)
        if p75 is not None:
            sections.append(f"- Market 75th Percentile: {format_currency(p75, decimals=0)}")

        p90 = getattr(comp, "market_90th_percentile", None)
        if p90 is not None:
            sections.append(f"- Market 90th Percentile: {format_currency(p90, decimals=0)}")

        ratio = getattr(comp, "comp_to_market_ratio", None)
        if ratio is not None:
            sections.append(f"- Company CEO Comp-to-Market: {ratio:.1f}x")

    return "\n".join(sections)


def _format_labor_context(labor_ctx: dict[str, Any]) -> str:
    """Format the labor market context section from get_company response (dict form)."""
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
