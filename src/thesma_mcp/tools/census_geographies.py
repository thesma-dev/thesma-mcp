"""MCP tools for US Census Bureau geography and place data."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import Context
from thesma.errors import ThesmaError

from thesma_mcp.formatters import format_currency, format_number, format_table
from thesma_mcp.server import AppContext, get_client, mcp


@mcp.tool(
    description=(
        "List available US Census geography levels (state, county, place, metro, etc.) "
        "and the number of places at each level. "
        "Use this first to discover what levels exist before calling search_census_places. "
        "Source: public-domain US Census Bureau data."
    )
)
async def explore_census_geographies(
    ctx: Context[Any, AppContext, Any],
) -> str:
    """List available US Census geography levels."""
    client = get_client(ctx)

    try:
        result = await client.census.geographies()  # type: ignore[misc]
    except ThesmaError as e:
        return str(e)

    data = result.data

    if not data:
        return "No Census geography levels available."

    rows = [[g.level, format_number(g.count, decimals=0)] for g in data]
    table = format_table(["Level", "Count"], rows, alignments=["l", "r"])

    lines = [
        table,
        "",
        "Use search_census_places(level) to list places at a level, "
        "or get_census_place(level, fips) for a specific place.",
        "",
        "Source: US Census Bureau.",
    ]
    return "\n".join(lines)


@mcp.tool(
    description=(
        "List US Census places at a given geography level, optionally filtered by name (case-insensitive). "
        "IMPORTANT: the SDK returns a single page of places per call and does not expose pagination controls, "
        "so the name filter only sees that page. For large levels like 'tract' (73k+ places), "
        "if you already know the FIPS code use get_census_place directly instead. "
        "Params: level is the geography level from explore_census_geographies (e.g. 'state', 'county', 'place'); "
        "query is an optional substring filter on place name. "
        "Returns up to 50 results. "
        "Source: public-domain US Census Bureau data."
    )
)
async def search_census_places(
    level: str,
    ctx: Context[Any, AppContext, Any],
    query: str | None = None,
) -> str:
    """List US Census places at a given geography level."""
    client = get_client(ctx)

    try:
        response = await client.census.geography(level)  # type: ignore[misc]
    except ThesmaError as e:
        return str(e)

    page: list[Any] = list(response.data)

    if query:
        q = query.lower()
        page = [d for d in page if q in (d.name or "").lower()]

    page_total = len(page)

    if page_total == 0:
        if query:
            return f"No places on the returned page of level '{level}' matching '{query}'."
        return f"No places on the returned page of level '{level}'."

    truncated = page[:50]

    rows = [
        [
            d.fips,
            d.name,
            d.parent_fips or "",
            format_number(d.population, decimals=0) if d.population is not None else "N/A",
        ]
        for d in truncated
    ]

    header = f"Places at level '{level}' (first page returned by SDK):"
    table = format_table(
        ["FIPS", "Name", "Parent FIPS", "Population"],
        rows,
        alignments=["l", "l", "l", "r"],
    )

    lines = [header, "", table]
    if page_total > 50:
        lines.append("")
        lines.append(f"Showing 50 of {page_total} results from this page — refine query to narrow down.")
    lines.append("")
    lines.append("Source: US Census Bureau.")
    return "\n".join(lines)


@mcp.tool(
    description=(
        "Get detailed geographic information for a single US Census place. "
        "Returns name, parent place, population, area, coordinates, and available child levels. "
        "Params: level is the geography level, fips is the place's FIPS code. "
        "FIPS length varies by level: state=2 digits, county=5 digits, place=7 digits, tract=11 digits. "
        "Source: public-domain US Census Bureau data."
    )
)
async def get_census_place(
    level: str,
    fips: str,
    ctx: Context[Any, AppContext, Any],
) -> str:
    """Get detailed information for a single Census place."""
    client = get_client(ctx)

    try:
        result = await client.census.geography_places(level, fips)  # type: ignore[misc]
    except ThesmaError as e:
        return str(e)

    data = result.data

    population_str = format_number(data.population, decimals=0) if data.population is not None else "N/A"
    area_str = f"{data.area_sq_mi}" if data.area_sq_mi is not None else "N/A"
    lat_str = f"{data.lat}" if data.lat is not None else "N/A"
    lon_str = f"{data.lon}" if data.lon is not None else "N/A"

    lines = [
        f"{data.name} ({data.fips})",
        "",
        f"{'fips:':<18}{data.fips}",
        f"{'name:':<18}{data.name}",
        f"{'level:':<18}{data.level}",
        f"{'parent_fips:':<18}{data.parent_fips or 'N/A'}",
        f"{'parent_name:':<18}{data.parent_name or 'N/A'}",
        f"{'population:':<18}{population_str}",
        f"{'area_sq_mi:':<18}{area_str}",
        f"{'lat:':<18}{lat_str}",
        f"{'lon:':<18}{lon_str}",
    ]

    children_levels = data.children_levels or []
    if children_levels:
        lines.append("")
        lines.append(f"Child levels: {', '.join(children_levels)}")

    lines.append("")
    lines.append("Source: US Census Bureau.")
    return "\n".join(lines)


def _format_latest_year(latest_year: Any) -> str:
    """Render a LatestYear model as 'YYYY (acs5) / YYYY (acs1)' or subset."""
    if latest_year is None:
        return "N/A"
    acs5 = getattr(latest_year, "acs5", None)
    acs1 = getattr(latest_year, "acs1", None)
    parts: list[str] = []
    if acs5 is not None:
        parts.append(f"{acs5} (acs5)")
    if acs1 is not None:
        parts.append(f"{acs1} (acs1)")
    return " / ".join(parts) if parts else "N/A"


def _format_metric_value(value: Any, unit: str | None) -> str:
    if value is None:
        return "N/A"
    # bool is a subclass of int — check it first
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, (int, float)):
        if unit == "USD":
            return format_currency(float(value), decimals=0)
        if unit == "pct":
            return f"{value:.1f}%"
        return format_number(float(value), decimals=0)
    return str(value)


def _format_moe(moe: float | None) -> str:
    if moe is None:
        return "N/A"
    if abs(moe) < 1:
        return f"±{moe:.2f}"
    return f"±{moe:,.0f}"
