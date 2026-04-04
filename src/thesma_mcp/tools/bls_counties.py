"""MCP tools for BLS county-level employment and wage data."""

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
        "Get quarterly employment data for a US county from the BLS QCEW program. "
        "FIPS is a 5-digit county code (e.g. '12086' for Miami-Dade County, FL). "
        "Industry defaults to '10' (all industries). Ownership defaults to 'private'. "
        "Omit year/quarter for all available data."
    )
)
async def get_county_employment(
    fips: str,
    ctx: Context[Any, AppContext, Any],
    industry: str | None = None,
    ownership: str | None = None,
    year: int | None = None,
    quarter: int | None = None,
) -> str:
    """Get quarterly employment data for a US county."""
    app = _get_ctx(ctx)

    fips = fips.zfill(5)

    params: dict[str, Any] = {
        "industry": industry or "10",
        "ownership": ownership or "private",
    }
    if year is not None:
        params["year"] = year
    if quarter is not None:
        params["quarter"] = quarter

    try:
        response = await app.client.get(f"/v1/us/bls/counties/{fips}/employment", params=params)
    except ThesmaAPIError as e:
        return str(e)

    data: list[dict[str, Any]] = response.get("data", [])

    if not data:
        return f"No employment data available for county FIPS {fips}."

    headers = ["Year", "Qtr", "Month 1", "Month 2", "Month 3", "YoY %", "Establishments"]
    rows: list[list[str]] = []
    for d in data:
        rows.append(
            [
                str(d.get("year", "")),
                str(d.get("quarter", "")),
                format_number(d.get("month1_employment")),
                format_number(d.get("month2_employment")),
                format_number(d.get("month3_employment")),
                f"{d['employment_yoy_pct']:.1f}%" if d.get("employment_yoy_pct") is not None else "N/A",
                format_number(d.get("establishment_count")),
            ]
        )

    table = format_table(headers, rows)
    header = f"County Employment — FIPS {fips} ({len(data)} quarters)"
    lines = [header, "", table, "", "Source: BLS Quarterly Census of Employment and Wages (QCEW)."]
    return "\n".join(lines)


@mcp.tool(
    description=(
        "Get a wage snapshot for a US county including location quotients. "
        "FIPS is a 5-digit county code (e.g. '06037' for Los Angeles County, CA). "
        "A location quotient above 1.0 means the county has a higher concentration of that industry "
        "than the national average. "
        "Industry defaults to '10' (all industries)."
    )
)
async def get_county_wages(
    fips: str,
    ctx: Context[Any, AppContext, Any],
    industry: str | None = None,
    ownership: str | None = None,
    year: int | None = None,
    quarter: int | None = None,
) -> str:
    """Get wage snapshot for a US county."""
    app = _get_ctx(ctx)

    fips = fips.zfill(5)

    params: dict[str, Any] = {}
    if industry is not None:
        params["industry"] = industry
    if ownership is not None:
        params["ownership"] = ownership
    if year is not None:
        params["year"] = year
    if quarter is not None:
        params["quarter"] = quarter

    try:
        response = await app.client.get(f"/v1/us/bls/counties/{fips}/wages", params=params)
    except ThesmaAPIError as e:
        return str(e)

    data: dict[str, Any] = response.get("data", {})

    if not data:
        return f"No wage data available for county FIPS {fips}."

    area_fips = data.get("area_fips", fips)
    own = data.get("ownership", "")
    ind_code = data.get("industry_code", "")
    avg_weekly_wage = data.get("avg_weekly_wage")
    total_quarterly_wages = data.get("total_quarterly_wages")
    wage_yoy = data.get("wage_yoy_pct")
    lq_emp = data.get("location_quotient_employment")
    lq_wages = data.get("location_quotient_wages")
    lq_estab = data.get("location_quotient_establishments")

    lines = [
        f"County Wages — FIPS {area_fips}",
        "",
        f"{'Area FIPS:':<30}{area_fips}",
        f"{'Ownership:':<30}{own}",
        f"{'Industry Code:':<30}{ind_code}",
        f"{'Avg Weekly Wage:':<30}{format_currency(avg_weekly_wage, decimals=0)}",
        f"{'Total Quarterly Wages:':<30}{format_currency(total_quarterly_wages, decimals=0)}",
        f"{'Wage YoY:':<30}{f'{wage_yoy:.1f}%' if wage_yoy is not None else 'N/A'}",
        "",
        "Location Quotients:",
        f"{'  Employment:':<30}{f'{lq_emp:.2f}' if lq_emp is not None else 'N/A'}",
        f"{'  Wages:':<30}{f'{lq_wages:.2f}' if lq_wages is not None else 'N/A'}",
        f"{'  Establishments:':<30}{f'{lq_estab:.2f}' if lq_estab is not None else 'N/A'}",
        "",
        "Location quotient > 1.0 = above national average concentration.",
        "",
        "Source: BLS Quarterly Census of Employment and Wages (QCEW).",
    ]
    return "\n".join(lines)
