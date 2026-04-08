"""MCP tools for BLS county-level employment and wage data."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import Context
from thesma.errors import ThesmaError

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

    try:
        response = await app.client.bls.county_employment(
            fips,
            industry=industry or "10",
            ownership=ownership or "private",
            year=year,
            quarter=quarter,
        )
    except ThesmaError as e:
        return str(e)

    data = response.data

    if not data:
        return f"No employment data available for county FIPS {fips}."

    headers = ["Year", "Qtr", "Month 1", "Month 2", "Month 3", "YoY %", "Establishments"]
    rows: list[list[str]] = []
    for d in data:
        emp_yoy = getattr(d, "employment_yoy_pct", None)
        rows.append(
            [
                str(d.year),
                str(d.quarter),
                format_number(d.month1_employment),
                format_number(d.month2_employment),
                format_number(d.month3_employment),
                f"{emp_yoy:.1f}%" if emp_yoy is not None else "N/A",
                format_number(getattr(d, "establishment_count", None)),
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

    try:
        result = await app.client.bls.county_wages(
            fips,
            industry=industry or "10",
            ownership=ownership or "private",
            year=year,
            quarter=quarter,
        )
    except ThesmaError as e:
        return str(e)

    data = result.data

    area_fips = getattr(data, "area_fips", fips)
    own = getattr(data, "ownership", "")
    ind_code = getattr(data, "industry_code", "")
    avg_weekly_wage = getattr(data, "avg_weekly_wage", None)
    total_quarterly_wages = getattr(data, "total_quarterly_wages", None)
    wage_yoy = getattr(data, "wage_yoy_pct", None)
    lq_emp = getattr(data, "location_quotient_employment", None)
    lq_wages = getattr(data, "location_quotient_wages", None)
    lq_estab = getattr(data, "location_quotient_establishments", None)

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
