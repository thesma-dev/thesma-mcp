"""MCP tools for US Census Bureau place-level metric data."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import Context
from thesma.errors import ThesmaError

from thesma_mcp.formatters import format_currency, format_number, format_table
from thesma_mcp.server import AppContext, get_client, mcp


@mcp.tool(
    description=(
        "Get the full set of US Census metrics for one place, grouped by category. "
        "Returns the latest available year by default (server-chosen). "
        "Use this as a 'Census profile' for a single place. "
        "Params: fips is the place's FIPS code (length varies by level: state=2, county=5, place=7, tract=11). "
        "Source: public-domain US Census Bureau data."
    )
)
async def get_census_place_metrics(
    fips: str,
    ctx: Context[Any, AppContext, Any],
) -> str:
    """Get all Census metrics for one place, grouped by category."""
    client = get_client(ctx)

    try:
        result = await client.census.place(fips)  # type: ignore[misc]
    except ThesmaError as e:
        return str(e)

    data = result.data
    header = f"{data.name} ({data.fips}) — {data.year} ({data.dataset})"

    if not data.metrics:
        return (
            f"{header}\n\nNo metric data available for this place in the requested year.\n\nSource: US Census Bureau."
        )

    groups: dict[str, list[Any]] = {}
    for m in data.metrics:
        key = (m.category.strip() if m.category else "") or "Other"
        groups.setdefault(key, []).append(m)

    keys = sorted(groups.keys(), key=lambda k: (k == "Other", k.lower()))

    parts: list[str] = [header, ""]
    for i, key in enumerate(keys):
        if i > 0:
            parts.append("")
        parts.append(f"### {key}")
        rows = []
        for m in groups[key]:
            metric_name = m.display_name or m.canonical_name
            value_str = "(suppressed)" if m.suppressed else _format_metric_value(m.value, m.unit)
            unit_str = m.unit or ""
            moe_str = _format_moe(m.moe)
            rows.append([metric_name, value_str, unit_str, moe_str])
        parts.append(
            format_table(
                ["Metric", "Value", "Unit", "MOE"],
                rows,
                alignments=["l", "r", "l", "r"],
            )
        )

    parts.append("")
    parts.append("Source: US Census Bureau.")
    return "\n".join(parts)


@mcp.tool(
    description=(
        "Get a time series for one US Census metric in one place. "
        "Omit year for the full series; provide year for a single observation. "
        "Params: fips is the place's FIPS code; metric is the canonical_name; "
        "dataset is optional ('acs1' or 'acs5'). "
        "Source: public-domain US Census Bureau data."
    )
)
async def get_census_place_metric_series(
    fips: str,
    metric: str,
    ctx: Context[Any, AppContext, Any],
    dataset: str | None = None,
    year: int | None = None,
) -> str:
    """Get a time series for one Census metric in one place."""
    if dataset is not None and dataset not in ("acs1", "acs5"):
        return "dataset must be 'acs1', 'acs5', or omitted."

    client = get_client(ctx)

    try:
        result = await client.census.place_metric(  # type: ignore[misc]
            fips, metric, dataset=dataset, year=year
        )
    except ThesmaError as e:
        return str(e)

    data = result.data
    unit = data.metric.unit

    if not data.series:
        return f"No time series data for metric '{metric}' at FIPS {fips} (dataset={data.dataset})."

    rows: list[list[str]] = []
    for p in data.series:
        year_str = str(p.year)
        value_str = "(suppressed)" if p.suppressed else _format_metric_value(p.value, unit)
        moe_str = _format_moe(p.moe)
        rows.append([year_str, value_str, moe_str, data.dataset])

    header = f"{data.metric.display_name} — {data.name} ({data.fips})"
    table = format_table(
        ["Year", "Value", "MOE", "Dataset"],
        rows,
        alignments=["l", "r", "r", "l"],
    )

    lines = [header, "", table, "", "Source: US Census Bureau."]
    return "\n".join(lines)


@mcp.tool(
    description=(
        "Break a US Census metric down across the child geographies of a parent place. "
        "For example, pass a state FIPS to get the metric for every county inside that state. "
        "Params: fips is the parent place's FIPS; metric is the canonical_name; "
        "dataset is optional ('acs1' or 'acs5'); year is optional. "
        "Source: public-domain US Census Bureau data."
    )
)
async def get_census_place_breakdown(
    fips: str,
    metric: str,
    ctx: Context[Any, AppContext, Any],
    dataset: str | None = None,
    year: int | None = None,
) -> str:
    """Break a Census metric down across the child geographies of a parent place."""
    if dataset is not None and dataset not in ("acs1", "acs5"):
        return "dataset must be 'acs1', 'acs5', or omitted."

    client = get_client(ctx)

    try:
        response = await client.census.breakdown(  # type: ignore[misc]
            fips, metric, dataset=dataset, year=year
        )
    except ThesmaError as e:
        return str(e)

    data = response.data
    unit = data.metric.unit

    rows: list[list[str]] = []
    for p in data.places:
        value_str = "(suppressed)" if p.suppressed else _format_metric_value(p.value, unit)
        moe_str = _format_moe(p.moe)
        rows.append([p.name, p.fips, value_str, moe_str])

    header = (
        f"{data.parent.name} ({data.parent.fips}) — {data.metric.display_name} "
        f"across {data.child_level} — {data.year} ({data.dataset})"
    )
    table = format_table(
        ["Place", "FIPS", "Value", "MOE"],
        rows,
        alignments=["l", "l", "r", "r"],
    )

    lines = [header, "", table, "", "Source: US Census Bureau."]
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
