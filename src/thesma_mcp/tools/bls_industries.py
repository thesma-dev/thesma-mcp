"""MCP tools for BLS industry data."""

from __future__ import annotations

import re
from typing import Any

from mcp.server.fastmcp import Context

from thesma_mcp.client import ThesmaAPIError
from thesma_mcp.formatters import format_number, format_table
from thesma_mcp.server import AppContext, mcp


def _get_ctx(ctx: Context[Any, AppContext, Any]) -> AppContext:
    return ctx.request_context.lifespan_context


@mcp.tool(
    description=(
        "Search BLS industries by name or list by NAICS level. "
        "Use this to find NAICS industry codes before querying employment data. "
        "Params: query is a text search (e.g. 'software'), level is NAICS hierarchy depth "
        "(1=sector, 2=subsector, up to 6=national industry). "
        "Returns up to 25 results."
    )
)
async def search_industries(
    ctx: Context[Any, AppContext, Any],
    query: str | None = None,
    level: int | None = None,
) -> str:
    """Search for BLS industries by name or NAICS level."""
    app = _get_ctx(ctx)

    params: dict[str, Any] = {"per_page": 25}
    if query is not None:
        params["search"] = query
    if level is not None:
        params["level"] = level

    try:
        response = await app.client.get("/v1/us/bls/industries", params=params)
    except ThesmaAPIError as e:
        return str(e)

    data: list[dict[str, Any]] = response.get("data", [])

    if not data:
        if query:
            return f"No industries found matching '{query}'."
        return "No industries found."

    rows = [[str(d.get("naics_code", "")), str(d.get("title", "")), str(d.get("level", ""))] for d in data]
    table = format_table(["NAICS", "Title", "Level"], rows)

    count = len(data)
    header = f"Found {count} industr{'y' if count == 1 else 'ies'}"
    if query:
        header += f" matching '{query}'"

    lines = [header, "", table, "", "Source: BLS Quarterly Census of Employment and Wages."]
    return "\n".join(lines)


@mcp.tool(
    description=(
        "Get detailed information for a single BLS industry including child industries and data availability. "
        "Use this after search_industries to drill into a specific industry. "
        "Params: naics is the NAICS code (e.g. '5112' for Software Publishers)."
    )
)
async def get_industry_detail(
    naics: str,
    ctx: Context[Any, AppContext, Any],
) -> str:
    """Get details for a single BLS industry."""
    app = _get_ctx(ctx)

    try:
        response = await app.client.get(f"/v1/us/bls/industries/{naics}")
    except ThesmaAPIError as e:
        return str(e)

    data: dict[str, Any] = response.get("data", {})

    naics_code = data.get("naics_code", naics)
    title = data.get("title", "Unknown")
    level = data.get("level", "")
    parent_naics = data.get("parent_naics", "N/A")
    has_ces = data.get("has_ces_data", False)
    has_qcew = data.get("has_qcew_data", False)
    has_oews = data.get("has_oews_data", False)

    lines = [
        f"{title} (NAICS {naics_code})",
        "",
        f"{'NAICS Code:':<20}{naics_code}",
        f"{'Title:':<20}{title}",
        f"{'Level:':<20}{level}",
        f"{'Parent NAICS:':<20}{parent_naics}",
        f"{'CES Data:':<20}{'Yes' if has_ces else 'No'}",
        f"{'QCEW Data:':<20}{'Yes' if has_qcew else 'No'}",
        f"{'OEWS Data:':<20}{'Yes' if has_oews else 'No'}",
    ]

    children: list[dict[str, Any]] = data.get("children", [])
    if children:
        lines.append("")
        lines.append("Child Industries:")
        rows = [[str(c.get("naics_code", "")), str(c.get("title", "")), str(c.get("level", ""))] for c in children]
        lines.append(format_table(["NAICS", "Title", "Level"], rows))

    lines.append("")
    lines.append("Source: BLS industry classification.")
    return "\n".join(lines)


_DATE_RE = re.compile(r"^\d{4}-\d{2}$")


@mcp.tool(
    description=(
        "Get employment data for a BLS industry. Shows the latest observation with year-over-year changes by default. "
        "Provide from_date and to_date (YYYY-MM format) for a time series. "
        "Params: naics is the NAICS code, adjustment is 'sa' (seasonally adjusted, default) or 'nsa', "
        "geo/state/metro narrow geography."
    )
)
async def get_industry_employment(
    naics: str,
    ctx: Context[Any, AppContext, Any],
    from_date: str | None = None,
    to_date: str | None = None,
    adjustment: str | None = None,
    geo: str | None = None,
    state: str | None = None,
    metro: str | None = None,
) -> str:
    """Get employment data for a BLS industry."""
    app = _get_ctx(ctx)

    # Validate date formats
    if from_date and not _DATE_RE.match(from_date):
        return f"Invalid from_date format '{from_date}'. Expected YYYY-MM (e.g. '2024-01')."
    if to_date and not _DATE_RE.match(to_date):
        return f"Invalid to_date format '{to_date}'. Expected YYYY-MM (e.g. '2024-12')."

    params: dict[str, Any] = {}
    if adjustment is not None:
        params["adjustment"] = adjustment
    if geo is not None:
        params["geo"] = geo
    if state is not None:
        params["state"] = state
    if metro is not None:
        params["metro"] = metro

    try:
        if from_date and to_date:
            params["from"] = from_date
            params["to"] = to_date
            response = await app.client.get(f"/v1/us/bls/industries/{naics}/employment", params=params)
            return _format_employment_series(response, naics)
        else:
            response = await app.client.get(f"/v1/us/bls/industries/{naics}/employment/latest", params=params)
            return _format_employment_latest(response, naics)
    except ThesmaAPIError as e:
        return str(e)


def _format_employment_latest(response: dict[str, Any], naics: str) -> str:
    """Format latest employment observation as key-value output."""
    data: dict[str, Any] = response.get("data", {})

    if not data:
        return f"No employment data available for NAICS {naics}."

    period = data.get("period", "")
    employment = data.get("all_employees_thousands")
    employment_yoy = data.get("employment_yoy_pct")
    avg_hourly_earnings = data.get("avg_hourly_earnings")
    earnings_yoy = data.get("earnings_yoy_pct")
    avg_weekly_hours = data.get("avg_weekly_hours")

    lines = [
        f"Employment — NAICS {naics} (Latest: {period})",
        "",
        f"{'Employment:':<25}{format_number(employment)}K" if employment is not None else "",
        f"{'Employment YoY:':<25}{_yoy_str(employment_yoy)}" if employment_yoy is not None else "",
        f"{'Avg Hourly Earnings:':<25}${avg_hourly_earnings:.2f}" if avg_hourly_earnings is not None else "",
        f"{'Earnings YoY:':<25}{_yoy_str(earnings_yoy)}" if earnings_yoy is not None else "",
        f"{'Avg Weekly Hours:':<25}{avg_weekly_hours}" if avg_weekly_hours is not None else "",
    ]
    lines = [ln for ln in lines if ln != ""]
    lines.append("")
    lines.append("Source: BLS Current Employment Statistics (CES).")
    return "\n".join(lines)


def _format_employment_series(response: dict[str, Any], naics: str) -> str:
    """Format employment time series as a table."""
    data: list[dict[str, Any]] = response.get("data", [])

    if not data:
        return f"No employment data available for NAICS {naics} in the specified date range."

    headers = ["Period", "Employment (K)", "YoY %", "Avg Hourly Earnings"]
    rows: list[list[str]] = []
    for d in data:
        period = str(d.get("period", ""))
        employment = d.get("all_employees_thousands")
        yoy = d.get("employment_yoy_pct")
        earnings = d.get("avg_hourly_earnings")
        rows.append(
            [
                period,
                format_number(employment) if employment is not None else "N/A",
                f"{yoy:.1f}%" if yoy is not None else "N/A",
                f"${earnings:.2f}" if earnings is not None else "N/A",
            ]
        )

    table = format_table(headers, rows)
    header = f"Employment — NAICS {naics} ({len(data)} observations)"
    lines = [header, "", table, "", "Source: BLS Current Employment Statistics (CES)."]
    return "\n".join(lines)


def _yoy_str(value: float | None) -> str:
    """Format a YoY percentage with sign."""
    if value is None:
        return "N/A"
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.1f}%"
