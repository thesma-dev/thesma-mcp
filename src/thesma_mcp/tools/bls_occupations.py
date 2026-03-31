"""MCP tools for BLS occupation and wage data."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import Context

from thesma_mcp.client import ThesmaAPIError
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

    params: dict[str, Any] = {"per_page": 25}
    if query is not None:
        params["search"] = query
    if group is not None:
        params["group"] = group

    try:
        response = await app.client.get("/v1/us/bls/occupations", params=params)
    except ThesmaAPIError as e:
        return str(e)

    data: list[dict[str, Any]] = response.get("data", [])

    if not data:
        if query:
            return f"No occupations found matching '{query}'."
        return "No occupations found."

    rows = [[str(d.get("soc_code", "")), str(d.get("title", "")), str(d.get("major_group", ""))] for d in data]
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

    params: dict[str, Any] = {}
    if industry is not None:
        params["industry"] = industry
    if geo is not None:
        params["geo"] = geo
    if state is not None:
        params["state"] = state
    if metro is not None:
        params["metro"] = metro
    if year is not None:
        params["year"] = year

    try:
        response = await app.client.get(f"/v1/us/bls/occupations/{soc}/wages", params=params)
    except ThesmaAPIError as e:
        return str(e)

    data: list[dict[str, Any]] = response.get("data", [])

    if not data:
        return f"No wage data available for SOC {soc}."

    headers = ["SOC", "Area", "Mean Annual", "Mean Hourly", "Median Annual", "Median Hourly"]
    rows: list[list[str]] = []
    for d in data:
        rows.append(
            [
                str(d.get("soc_code", "")),
                str(d.get("area_name", "")),
                format_currency(d.get("mean_annual_wage"), decimals=0),
                format_currency(d.get("mean_hourly_wage"), decimals=2),
                format_currency(d.get("median_annual_wage"), decimals=0),
                format_currency(d.get("median_hourly_wage"), decimals=2),
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
        val = first.get(key)
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
