"""MCP tools for JOLTS labor market turnover data."""

from __future__ import annotations

import re
from typing import Any

from mcp.server.fastmcp import Context
from thesma._generated.models import JoltsMeasureValue
from thesma.errors import ThesmaError

from thesma_mcp.formatters import format_number, format_table
from thesma_mcp.server import AppContext, mcp

_DATE_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")

# Measures and their short labels for table display
_INDUSTRY_MEASURES: list[tuple[str, str]] = [
    ("job_openings", "Openings"),
    ("hires", "Hires"),
    ("quits", "Quits"),
    ("layoffs_and_discharges", "Layoffs"),
    ("total_separations", "Total Sep."),
    ("other_separations", "Other Sep."),
]

# State/region exclude other_separations
_STATE_REGION_MEASURES: list[tuple[str, str]] = [m for m in _INDUSTRY_MEASURES if m[0] != "other_separations"]


def _get_ctx(ctx: Context[Any, AppContext, Any]) -> AppContext:
    return ctx.request_context.lifespan_context


def _validate_dates(from_date: str | None, to_date: str | None) -> str | None:
    """Validate date parameters. Returns error message or None if valid."""
    if (from_date is None) != (to_date is None):
        return "Both from_date and to_date are required for a time series. Provide neither for the latest observation."
    if from_date and not _DATE_RE.match(from_date):
        return f"Invalid from_date format: '{from_date}'. Expected YYYY-MM."
    if to_date and not _DATE_RE.match(to_date):
        return f"Invalid to_date format: '{to_date}'. Expected YYYY-MM."
    return None


def _format_measure(value: Any) -> str:
    """Format a single JOLTS measure value as 'Level / Rate%'.

    The API returns level in thousands, so we multiply by 1000 for display.
    Handles JoltsMeasureValue model, dict, float, or None.
    """
    if value is None:
        return "N/A"
    if isinstance(value, JoltsMeasureValue):
        level = value.level
        rate = value.rate
        level_str = format_number(level * 1000) if level is not None else "N/A"
        rate_str = f"{rate:.1f}%" if rate is not None else "N/A"
        if level is not None and rate is not None:
            return f"{level_str} / {rate_str}"
        if level is not None:
            return level_str
        if rate is not None:
            return rate_str
        return "N/A"
    if isinstance(value, dict):
        level = value.get("level")
        rate = value.get("rate")
        level_str = format_number(level * 1000) if level is not None else "N/A"
        rate_str = f"{rate:.1f}%" if rate is not None else "N/A"
        if level is not None and rate is not None:
            return f"{level_str} / {rate_str}"
        if level is not None:
            return level_str
        if rate is not None:
            return rate_str
        return "N/A"
    return format_number(float(value))


def _format_latest(data: Any, measures: list[tuple[str, str]], title: str) -> str:
    """Format a latest observation as key-value pairs."""
    period = getattr(data, "period", "Unknown")
    adjustment = getattr(data, "adjustment", "sa")
    adj_label = "Seasonally adjusted" if adjustment == "sa" else "Not seasonally adjusted"

    lines = [title, "", f"Period: {period}", f"Adjustment: {adj_label}", ""]

    for key, label in measures:
        val = getattr(data, key, None)
        lines.append(f"{label}: {_format_measure(val)}")

    lines.append("")
    lines.append("Source: BLS Job Openings and Labor Turnover Survey (JOLTS).")
    return "\n".join(lines)


def _format_time_series(data_list: list[Any], measures: list[tuple[str, str]], title: str) -> str:
    """Format time series data as a table."""
    headers = ["Period"]
    alignments: list[str] = ["l"]
    for _, label in measures:
        headers.append(label)
        alignments.append("r")

    rows: list[list[str]] = []
    for point in data_list:
        row = [getattr(point, "period", "")]
        for key, _ in measures:
            row.append(_format_measure(getattr(point, key, None)))
        rows.append(row)

    table = format_table(headers, rows, alignments)
    count = len(data_list)

    lines = [f"{title} ({count} observations)", "", table, ""]
    lines.append("Source: BLS Job Openings and Labor Turnover Survey (JOLTS).")
    return "\n".join(lines)


@mcp.tool(
    description=(
        "Get labor market turnover data (job openings, hires, quits, layoffs) for an industry by NAICS code. "
        "Shows the latest observation by default. Provide from_date and to_date (YYYY-MM) for a time series. "
        "Use search_industries first to find NAICS codes."
    )
)
async def get_industry_turnover(
    naics: str,
    ctx: Context[Any, AppContext, Any],
    from_date: str | None = None,
    to_date: str | None = None,
    adjustment: str | None = None,
    measures: str | None = None,
) -> str:
    """Get JOLTS turnover data for an industry."""
    app = _get_ctx(ctx)

    err = _validate_dates(from_date, to_date)
    if err:
        return err

    if measures:
        requested = [m.strip() for m in measures.split(",") if m.strip()]
        display_measures = [(k, label) for k, label in _INDUSTRY_MEASURES if k in requested]
    else:
        display_measures = _INDUSTRY_MEASURES

    try:
        if from_date and to_date:
            response = await app.client.bls.turnover(  # type: ignore[misc]
                naics, from_date=from_date, to_date=to_date, adjustment=adjustment or "sa", measures=measures
            )
            data_list = response.data
            if not data_list:
                return f"No JOLTS turnover data available for NAICS {naics} in the requested period."

            first = data_list[0]
            jolts_name = getattr(first, "jolts_industry_name", "")
            jolts_code = getattr(first, "jolts_industry_code", "")
            title = f"NAICS {naics} \u2192 JOLTS {jolts_name} ({jolts_code})"

            return _format_time_series(data_list, display_measures, title)
        else:
            result = await app.client.bls.turnover_latest(naics, adjustment=adjustment or "sa", measures=measures)  # type: ignore[misc]
            data = result.data

            jolts_name = getattr(data, "jolts_industry_name", "")
            jolts_code = getattr(data, "jolts_industry_code", "")
            title = f"NAICS {naics} \u2192 JOLTS {jolts_name} ({jolts_code})"

            return _format_latest(data, display_measures, title)
    except ThesmaError as e:
        return str(e)


@mcp.tool(
    description=(
        "Get state-level labor market turnover data. Total nonfarm only \u2014 no industry breakdown at state level. "
        "Data available from October 2021 onward. "
        "Params: fips is the 2-digit state FIPS code (e.g. '06' for California)."
    )
)
async def get_state_turnover(
    fips: str,
    ctx: Context[Any, AppContext, Any],
    from_date: str | None = None,
    to_date: str | None = None,
    adjustment: str | None = None,
) -> str:
    """Get JOLTS turnover data for a US state."""
    app = _get_ctx(ctx)

    err = _validate_dates(from_date, to_date)
    if err:
        return err

    try:
        if from_date and to_date:
            response = await app.client.bls.state_turnover(  # type: ignore[misc]
                fips, from_date=from_date, to_date=to_date, adjustment=adjustment or "sa"
            )
            data_list = response.data
            if not data_list:
                return f"No JOLTS turnover data available for state FIPS {fips} in the requested period."
            title = f"JOLTS Turnover \u2014 State FIPS {fips}"
            return _format_time_series(data_list, _STATE_REGION_MEASURES, title)
        else:
            response = await app.client.bls.state_turnover(fips, adjustment=adjustment or "sa", per_page=1)  # type: ignore[misc]
            data_list = response.data
            if not data_list:
                return f"No JOLTS turnover data available for state FIPS {fips}."
            title = f"JOLTS Turnover \u2014 State FIPS {fips}"
            return _format_latest(data_list[0], _STATE_REGION_MEASURES, title)
    except ThesmaError as e:
        return str(e)


@mcp.tool(
    description=(
        "Get regional labor market turnover data for one of the 4 Census regions. "
        "Params: region is 'northeast', 'south', 'midwest', or 'west'."
    )
)
async def get_regional_turnover(
    region: str,
    ctx: Context[Any, AppContext, Any],
    from_date: str | None = None,
    to_date: str | None = None,
    adjustment: str | None = None,
) -> str:
    """Get JOLTS turnover data for a Census region."""
    app = _get_ctx(ctx)

    err = _validate_dates(from_date, to_date)
    if err:
        return err

    try:
        if from_date and to_date:
            response = await app.client.bls.regional_turnover(  # type: ignore[misc]
                region, from_date=from_date, to_date=to_date, adjustment=adjustment or "sa"
            )
            data_list = response.data
            if not data_list:
                return f"No JOLTS turnover data available for {region} region in the requested period."
            title = f"JOLTS Turnover \u2014 {region.title()} Region"
            return _format_time_series(data_list, _STATE_REGION_MEASURES, title)
        else:
            response = await app.client.bls.regional_turnover(region, adjustment=adjustment or "sa", per_page=1)  # type: ignore[misc]
            data_list = response.data
            if not data_list:
                return f"No JOLTS turnover data available for {region} region."
            title = f"JOLTS Turnover \u2014 {region.title()} Region"
            return _format_latest(data_list[0], _STATE_REGION_MEASURES, title)
    except ThesmaError as e:
        return str(e)
