"""MCP tools for company discovery."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import Context
from thesma.errors import ThesmaError

from thesma_mcp.formatters import format_currency, format_number, format_table
from thesma_mcp.server import AppContext, get_client, mcp


def _get_ctx(ctx: Context[Any, AppContext, Any]) -> AppContext:
    return ctx.request_context.lifespan_context


def _parse_exchange(value: str | None) -> str | list[str] | None:
    """Accept a comma-separated string of exchanges; return the shape the SDK expects."""
    if value is None:
        return None
    parts = [p.strip() for p in value.split(",") if p.strip()]
    if not parts:
        return None
    if len(parts) == 1:
        return parts[0]
    return parts


def _render_exchange(value: Any) -> str:
    """Render an Exchange/Domicile enum member, plain string, or None as a cell."""
    if value is None:
        return "—"
    return str(getattr(value, "value", value))


@mcp.tool(
    description=(
        "Find US public companies by name substring or ticker prefix (case-insensitive). "
        "Use this to look up a company before querying its financials, ratios, or filings. "
        "Optional filters: taxonomy='us-gaap' or 'ifrs-full' to narrow to US-GAAP 10-K vs "
        "IFRS 20-F filers; currency='<ISO-4217 code>' (e.g. 'USD', 'EUR') to narrow by "
        "presentation currency."
    )
)
async def search_companies(
    query: str,
    ctx: Context[Any, AppContext, Any],
    tier: str | None = None,
    exchange: str | None = None,
    domicile: str | None = None,
    taxonomy: str | None = None,
    currency: str | None = None,
    limit: int = 20,
) -> str:
    """Search for companies by name, ticker, or sector."""
    client = get_client(ctx)
    limit = min(limit, 50)
    exchange_value = _parse_exchange(exchange)

    # Try exact ticker match first
    try:
        response = await client.companies.list(  # type: ignore[misc]
            ticker=query.upper(),
            exchange=exchange_value,
            domicile=domicile,
            taxonomy=taxonomy,
            currency=currency,
        )
        if response.data:
            return _format_company_list(response.data, query)
    except ThesmaError:
        pass

    # Fall back to name search
    try:
        response = await client.companies.list(  # type: ignore[misc]
            search=query,
            tier=tier,
            exchange=exchange_value,
            domicile=domicile,
            taxonomy=taxonomy,
            currency=currency,
            per_page=limit,
        )
    except ThesmaError as e:
        return str(e)

    if not response.data:
        return f'No companies found matching "{query}". Try a different search term or check the spelling.'

    return _format_company_list(response.data, query)


def _format_company_list(companies: list[Any], query: str) -> str:
    """Format a list of companies as a table."""
    count = len(companies)
    lines = [f'Found {count} company{"" if count == 1 else "ies"} matching "{query}"', ""]

    headers = ["#", "Ticker", "CIK", "Company", "Index", "Exchange", "Domicile"]
    rows = []
    for i, c in enumerate(companies, 1):
        tier = str(c.company_tier.value) if hasattr(c.company_tier, "value") else str(c.company_tier or "")
        index_label = _tier_label(tier)
        rows.append(
            [
                str(i),
                c.ticker or "",
                c.cik,
                c.name,
                index_label,
                _render_exchange(getattr(c, "exchange", None)),
                _render_exchange(getattr(c, "domicile", None)),
            ]
        )

    table = format_table(headers, rows, alignments=["r", "l", "l", "l", "l", "l", "l"])
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
        result = await client.companies.get(cik, include="labor_context,lending_context")  # type: ignore[misc]
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
        f"{'Exchange:':<18}{_render_exchange(getattr(data, 'exchange', None))}",
        f"{'Domicile:':<18}{_render_exchange(getattr(data, 'domicile', None))}",
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

    lending_ctx = getattr(data, "lending_context", None)
    if lending_ctx is None and hasattr(data, "model_extra"):
        model_extra = data.model_extra or {}
        lending_ctx = model_extra.get("lending_context")
    # Treat empty dict {} identically to omitted key.
    if lending_ctx and (not isinstance(lending_ctx, dict) or len(lending_ctx) > 0):
        lines.append("")
        if isinstance(lending_ctx, dict):
            lines.append(_format_lending_context(lending_ctx))
        else:
            lines.append(_format_lending_context_model(lending_ctx))

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


def _yoy_signed(value: float | None) -> str:
    """Render a signed YoY percentage using the existing arrow indicator, or '—' if None."""
    if value is None:
        return "\u2014"
    return _yoy_indicator(value) or "0.0%"


def _format_lending_context_model(lending_ctx: Any) -> str:
    """Format the lending market context from a LendingContext Pydantic model."""
    sections: list[str] = ["## Lending Market Context"]

    local = getattr(lending_ctx, "local_market", None)
    industry = getattr(lending_ctx, "industry_lending", None)

    if local is None and industry is None:
        sections.append("")
        sections.append("_(no lending context available — county FIPS may be unmapped or no SBA data exists)_")
        return "\n".join(sections)

    if local is not None:
        county_name = getattr(local, "county_name", None) or "county unknown"
        county_fips = getattr(local, "county_fips", None) or "\u2014"
        sections.append("")
        sections.append(f"**Local Market ({county_name}, FIPS {county_fips})**")

        loan_count = getattr(local, "quarterly_loan_count", None)
        if loan_count is not None:
            sections.append(f"- Quarterly Loan Count: {format_number(loan_count, decimals=0)}")

        total_amount = getattr(local, "quarterly_total_amount", None)
        if total_amount is not None:
            sections.append(f"- Quarterly Total Amount: {format_currency(total_amount, decimals=0)}")

        avg_size = getattr(local, "avg_loan_size", None)
        if avg_size is not None:
            sections.append(f"- Avg Loan Size: {format_currency(avg_size, decimals=0)}")

        yoy = getattr(local, "quarterly_yoy_change_pct", None)
        sections.append(f"- YoY Change: {_yoy_signed(yoy)}")

        charge_off = getattr(local, "charge_off_rate_trailing_4q", None)
        if charge_off is not None:
            sections.append(f"- Charge-off Rate (trailing 4Q): {charge_off:.2f}%")

        top_naics = getattr(local, "top_industry_naics", None)
        top_name = getattr(local, "top_industry_name", None)
        if top_naics or top_name:
            sections.append(f"- Top Industry: NAICS {top_naics or '—'} — {top_name or '—'}")

        period = getattr(local, "data_period", None)
        if period:
            sections.append(f"- Data Period: {period}")

        # _render_exchange is a misnomer — body works for any enum/string/None.
        confidence = _render_exchange(getattr(local, "county_fips_confidence", None))
        sections.append(f"- Match Confidence: {confidence}")

    if industry is not None:
        naics = getattr(industry, "naics_code", "") or ""
        desc = getattr(industry, "naics_description", "") or ""
        sections.append("")
        sections.append(f"**Industry Lending (NAICS {naics} — {desc})**")

        match_level = getattr(industry, "naics_match_level", None)
        if match_level:
            sections.append(f"- Match Level: {match_level}")

        nat_count = getattr(industry, "national_quarterly_loan_count", None)
        if nat_count is not None:
            sections.append(f"- National Quarterly Loan Count: {format_number(nat_count, decimals=0)}")

        nat_amount = getattr(industry, "national_quarterly_total_amount", None)
        if nat_amount is not None:
            sections.append(f"- National Quarterly Total Amount: {format_currency(nat_amount, decimals=0)}")

        nat_avg = getattr(industry, "national_avg_loan_size", None)
        if nat_avg is not None:
            sections.append(f"- National Avg Loan Size: {format_currency(nat_avg, decimals=0)}")

        nat_yoy = getattr(industry, "national_yoy_change_pct", None)
        sections.append(f"- National YoY Change: {_yoy_signed(nat_yoy)}")

        nat_charge_off = getattr(industry, "national_charge_off_rate_trailing_4q", None)
        if nat_charge_off is not None:
            sections.append(f"- National Charge-off Rate (trailing 4Q): {nat_charge_off:.2f}%")

        period = getattr(industry, "data_period", None)
        if period:
            sections.append(f"- Data Period: {period}")

    return "\n".join(sections)


def _format_lending_context(lending_ctx: dict[str, Any]) -> str:
    """Format the lending market context from a dict (extra='allow' passthrough)."""
    sections: list[str] = ["## Lending Market Context"]

    local = lending_ctx.get("local_market")
    industry = lending_ctx.get("industry_lending")

    if not local and not industry:
        sections.append("")
        sections.append("_(no lending context available — county FIPS may be unmapped or no SBA data exists)_")
        return "\n".join(sections)

    if local:
        county_name = local.get("county_name") or "county unknown"
        county_fips = local.get("county_fips") or "\u2014"
        sections.append("")
        sections.append(f"**Local Market ({county_name}, FIPS {county_fips})**")

        loan_count = local.get("quarterly_loan_count")
        if loan_count is not None:
            sections.append(f"- Quarterly Loan Count: {format_number(loan_count, decimals=0)}")

        total_amount = local.get("quarterly_total_amount")
        if total_amount is not None:
            sections.append(f"- Quarterly Total Amount: {format_currency(total_amount, decimals=0)}")

        avg_size = local.get("avg_loan_size")
        if avg_size is not None:
            sections.append(f"- Avg Loan Size: {format_currency(avg_size, decimals=0)}")

        yoy = local.get("quarterly_yoy_change_pct")
        sections.append(f"- YoY Change: {_yoy_signed(yoy)}")

        charge_off = local.get("charge_off_rate_trailing_4q")
        if charge_off is not None:
            sections.append(f"- Charge-off Rate (trailing 4Q): {charge_off:.2f}%")

        top_naics = local.get("top_industry_naics")
        top_name = local.get("top_industry_name")
        if top_naics or top_name:
            sections.append(f"- Top Industry: NAICS {top_naics or '—'} — {top_name or '—'}")

        period = local.get("data_period")
        if period:
            sections.append(f"- Data Period: {period}")

        confidence = local.get("county_fips_confidence") or "\u2014"
        sections.append(f"- Match Confidence: {confidence}")

    if industry:
        naics = industry.get("naics_code", "") or ""
        desc = industry.get("naics_description", "") or ""
        sections.append("")
        sections.append(f"**Industry Lending (NAICS {naics} — {desc})**")

        match_level = industry.get("naics_match_level")
        if match_level:
            sections.append(f"- Match Level: {match_level}")

        nat_count = industry.get("national_quarterly_loan_count")
        if nat_count is not None:
            sections.append(f"- National Quarterly Loan Count: {format_number(nat_count, decimals=0)}")

        nat_amount = industry.get("national_quarterly_total_amount")
        if nat_amount is not None:
            sections.append(f"- National Quarterly Total Amount: {format_currency(nat_amount, decimals=0)}")

        nat_avg = industry.get("national_avg_loan_size")
        if nat_avg is not None:
            sections.append(f"- National Avg Loan Size: {format_currency(nat_avg, decimals=0)}")

        nat_yoy = industry.get("national_yoy_change_pct")
        sections.append(f"- National YoY Change: {_yoy_signed(nat_yoy)}")

        nat_charge_off = industry.get("national_charge_off_rate_trailing_4q")
        if nat_charge_off is not None:
            sections.append(f"- National Charge-off Rate (trailing 4Q): {nat_charge_off:.2f}%")

        period = industry.get("data_period")
        if period:
            sections.append(f"- Data Period: {period}")

    return "\n".join(sections)
