"""MCP tools for US Census Bureau metric data."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import Context
from thesma.errors import ThesmaError

from thesma_mcp.formatters import format_currency, format_number, format_table
from thesma_mcp.server import AppContext, get_client, mcp


@mcp.tool(
    description=(
        "Discover available US Census Bureau metrics. "
        "Use this to find the canonical_name of a metric before calling the place or breakdown tools. "
        "Params: query filters by substring match on display_name or canonical_name; "
        "category filters by metric category (e.g. 'demographics', 'economy', 'housing'). "
        "Filters are case-insensitive. Returns up to 50 results. "
        "Source: public-domain US Census Bureau data."
    )
)
async def explore_census_metrics(
    ctx: Context[Any, AppContext, Any],
    query: str | None = None,
    category: str | None = None,
) -> str:
    """Discover available US Census Bureau metrics."""
    client = get_client(ctx)

    try:
        response = await client.census.metrics()  # type: ignore[misc]
    except ThesmaError as e:
        return str(e)

    data = response.data

    filtered: list[Any] = list(data)
    if query:
        q = query.lower()
        filtered = [d for d in filtered if q in (d.display_name or "").lower() or q in (d.canonical_name or "").lower()]
    if category:
        cat = category.lower()
        filtered = [d for d in filtered if (d.category or "").lower() == cat]

    if not filtered:
        msg = "No Census metrics found"
        if query:
            msg += f" matching '{query}'"
        if category:
            msg += f" in category '{category}'"
        return msg + "."

    total = len(filtered)
    truncated = filtered[:50]

    rows = [
        [
            d.canonical_name,
            d.display_name,
            d.category or "",
            d.unit or "",
            _format_latest_year(d.latest_year),
        ]
        for d in truncated
    ]
    table = format_table(["Metric", "Display Name", "Category", "Unit", "Latest Year"], rows)

    lines = [table]
    if total > 50:
        lines.append("")
        lines.append(f"Showing 50 of {total} — refine query to narrow down.")
    lines.append("")
    lines.append("Source: US Census Bureau.")
    return "\n".join(lines)


@mcp.tool(
    description=(
        "Get metadata for a single US Census metric, including the underlying source variables "
        "and margin-of-error formula type. "
        "Use this after explore_census_metrics to understand exactly what a metric measures. "
        "Params: metric is the canonical_name (e.g. 'median_household_income'). "
        "Source: public-domain US Census Bureau data."
    )
)
async def get_census_metric_detail(
    metric: str,
    ctx: Context[Any, AppContext, Any],
) -> str:
    """Get metadata for a single US Census metric."""
    client = get_client(ctx)

    try:
        result = await client.census.metric(metric)  # type: ignore[misc]
    except ThesmaError as e:
        return str(e)

    data = result.data

    lines = [
        f"{data.display_name} ({data.canonical_name})",
        "",
        f"{'canonical_name:':<22}{data.canonical_name}",
        f"{'display_name:':<22}{data.display_name}",
        f"{'category:':<22}{data.category or 'N/A'}",
        f"{'unit:':<22}{data.unit or 'N/A'}",
        f"{'is_computed:':<22}{'Yes' if data.is_computed else 'No'}",
        f"{'moe_formula_type:':<22}{data.moe_formula_type or 'N/A'}",
        f"{'latest_year:':<22}{_format_latest_year(data.latest_year)}",
        f"{'notes:':<22}{data.notes or 'N/A'}",
    ]

    source_variables = data.source_variables or []
    if source_variables:
        lines.append("")
        lines.append("Source variables:")
        for sv in source_variables:
            valid_to = sv.valid_to if sv.valid_to is not None else "present"
            lines.append(
                f"- {sv.variable_code} (role: {sv.role}, dataset: {sv.dataset}, years: {sv.valid_from}-{valid_to})"
            )

    lines.append("")
    lines.append("Source: US Census Bureau.")
    return "\n".join(lines)


@mcp.tool(
    description=(
        "Compare a single US Census metric across 2 to 25 places at the same geography level. "
        "Params: metric is the canonical_name; fips is a list of 2-25 FIPS codes; "
        "dataset is optional ('acs1' or 'acs5'); year is optional. "
        "Passing FIPS at mixed geography levels will likely produce an API error. "
        "Returns each place's value with margin of error. "
        "Source: public-domain US Census Bureau data."
    )
)
async def compare_census_metric(
    metric: str,
    fips: list[str],
    ctx: Context[Any, AppContext, Any],
    dataset: str | None = None,
    year: int | None = None,
) -> str:
    """Compare a single US Census metric across 2-25 places."""
    fips = list(dict.fromkeys(fips))

    if len(fips) < 2:
        return (
            "compare_census_metric requires at least 2 FIPS codes. "
            "Use get_census_place_metric_series for a single place."
        )
    if len(fips) > 25:
        return (
            "compare_census_metric accepts at most 25 FIPS codes per call. "
            "Split into multiple calls or use get_census_place_breakdown for child geographies."
        )
    if dataset is not None and dataset not in ("acs1", "acs5"):
        return "dataset must be 'acs1', 'acs5', or omitted."

    client = get_client(ctx)

    try:
        response = await client.census.compare(  # type: ignore[misc]
            metric, fips=fips, dataset=dataset, year=year
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

    header = f"Comparison: {data.metric.display_name} — {data.year} ({data.dataset})"
    table = format_table(["Place", "FIPS", "Value", "MOE"], rows, alignments=["l", "l", "r", "r"])

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
