"""MCP tools for BLS occupation and wage data."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import Context
from thesma.errors import ThesmaError

from thesma_mcp.formatters import format_currency, format_table
from thesma_mcp.server import AppContext, mcp


def _get_ctx(ctx: Context[Any, AppContext, Any]) -> AppContext:
    return ctx.request_context.lifespan_context


@mcp.tool(
    description=(
        "Search BLS occupations by name. "
        "Use this to find SOC occupation codes before querying wage data. "
        "Params: query is a text search (e.g. 'software developer'), "
        "group is 'major' (broad categories like 15-0000 Computer and Mathematical) "
        "or 'detailed' (specific jobs like 15-1252)."
    )
)
async def search_occupations(
    ctx: Context[Any, AppContext, Any],
    query: str | None = None,
    group: str | None = None,
) -> str:
    """Search for BLS occupations by name."""
    app = _get_ctx(ctx)

    try:
        response = await app.client.bls.occupations(search=query, group=group, per_page=25)
    except ThesmaError as e:
        return str(e)

    data = response.data

    if not data:
        if query:
            return f"No occupations found matching '{query}'."
        return "No occupations found."

    rows = [[d.soc_code, d.title, d.major_group] for d in data]
    table = format_table(["SOC", "Title", "Major Group"], rows)

    count = len(data)
    header = f"Found {count} occupation{'s' if count != 1 else ''}"
    if query:
        header += f" matching '{query}'"

    lines = [header, "", table, "", "Source: BLS Occupational Employment and Wage Statistics (OEWS)."]
    return "\n".join(lines)


@mcp.tool(
    description=(
        "Get wage data for a BLS occupation including percentile distribution. "
        "SOC code format is XX-XXXX (e.g. '15-1252' for Software Developers). "
        "Optionally filter by NAICS industry, geography, or year. "
        "Returns median wage plus 10th/25th/75th/90th percentiles."
    )
)
async def get_occupation_wages(
    soc: str,
    ctx: Context[Any, AppContext, Any],
    industry: str | None = None,
    geo: str | None = None,
    state: str | None = None,
    metro: str | None = None,
    year: int | None = None,
) -> str:
    """Get wage data for a BLS occupation."""
    app = _get_ctx(ctx)

    # Normalize SOC code — insert hyphen if missing
    if "-" not in soc and len(soc) == 6:
        soc = f"{soc[:2]}-{soc[2:]}"

    try:
        response = await app.client.bls.occupation_wages(
            soc, industry=industry, geo=geo or "national", state=state, metro=metro, year=year
        )
    except ThesmaError as e:
        return str(e)

    data = response.data

    if not data:
        return f"No wage data available for SOC {soc}."

    headers = ["SOC", "Area", "Mean Annual", "Mean Hourly", "Median Annual", "Median Hourly"]
    rows: list[list[str]] = []
    for d in data:
        rows.append(
            [
                d.soc_code,
                getattr(d, "area_name", ""),
                format_currency(getattr(d, "mean_annual_wage", None), decimals=0),
                format_currency(getattr(d, "mean_hourly_wage", None), decimals=2),
                format_currency(getattr(d, "median_annual_wage", None), decimals=0),
                format_currency(getattr(d, "median_hourly_wage", None), decimals=2),
            ]
        )

    table = format_table(headers, rows)

    # Percentile detail for first result
    first = data[0]
    pct_lines: list[str] = []
    percentile_fields = [
        ("10th", "pct10_hourly"),
        ("25th", "pct25_hourly"),
        ("75th", "pct75_hourly"),
        ("90th", "pct90_hourly"),
    ]
    for label, key in percentile_fields:
        val = getattr(first, key, None)
        if val is not None:
            pct_lines.append(f"  {label}: {format_currency(val, decimals=2)}/hr")

    lines = [f"Occupation Wages — SOC {soc}", "", table]
    if pct_lines:
        lines.append("")
        lines.append("Hourly Wage Percentiles:")
        lines.extend(pct_lines)

    lines.append("")
    lines.append("Source: BLS Occupational Employment and Wage Statistics (OEWS).")
    return "\n".join(lines)
