"""MCP tools for BLS LAUS unemployment data."""

from __future__ import annotations

import re
from typing import Any

from mcp.server.fastmcp import Context
from thesma.errors import ThesmaError

from thesma_mcp.formatters import format_number, format_table
from thesma_mcp.server import AppContext, get_client, mcp

_DATE_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")

_MAX_COMPARE_FIPS = 10


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


def _validate_year_month(year: int | None, month: int | None) -> str | None:
    """Reject when exactly one of year/month is provided."""
    if (year is None) != (month is None):
        return (
            "Both year and month must be provided together, or both omitted "
            "(the API will resolve the latest available period)."
        )
    return None


def _validate_adjustment(adj: str | None) -> str | None:
    """Reject anything other than 'sa', 'nsa', or None."""
    if adj is not None and adj not in ("sa", "nsa"):
        return "adjustment must be 'sa', 'nsa', or omitted."
    return None


def _parse_fips_list(fips_str: str, *, unit: str) -> list[str] | str:
    """Split a comma-separated FIPS string. Returns the cleaned list or an error message."""
    items = [item.strip() for item in fips_str.split(",") if item.strip()]
    digits_label = "5-digit county" if unit == "county" else "2-digit state"
    if not items:
        return (
            f"compare_{unit}_unemployment requires at least one FIPS code. "
            f"Provide a comma-separated list of {digits_label} FIPS codes."
        )
    if len(items) > _MAX_COMPARE_FIPS:
        return (
            f"compare_{unit}_unemployment accepts at most {_MAX_COMPARE_FIPS} FIPS codes per call. "
            "Split into multiple calls."
        )
    return items


def _period_label(year: int, month: int) -> str:
    """Render an API year/month pair as a human label."""
    if month == 13:
        return f"{year} (annual)"
    return f"{year}-{month:02d}"


def _format_rate(value: float | None) -> str:
    """Format a unemployment rate (percent) or 'N/A'."""
    if value is None:
        return "N/A"
    return f"{value:.1f}%"


def _format_adjustment_label(obs_value: Any) -> str:
    """Render seasonal adjustment as 'SA' or 'NSA'."""
    s = str(obs_value)
    # Enum repr looks like 'SeasonalAdjustment.seasonally_adjusted'; plain value is 'seasonally_adjusted'.
    if s.endswith("not_seasonally_adjusted"):
        return "NSA"
    if s.endswith("seasonally_adjusted"):
        return "SA"
    return "NSA"


# --- Tool: get_county_unemployment ---


@mcp.tool(
    description=(
        "Get monthly LAUS unemployment data for a single US county (never seasonally adjusted — "
        "county LAUS has no SA/NSA option). "
        "Without dates, returns the latest available observation. "
        "Provide both from_date and to_date (YYYY-MM) for a time series. "
        "Set annual_only=True to return only annual averages (M13 rows). "
        "Params: fips is a 5-digit county FIPS code (e.g. '06085' for Santa Clara County, CA). "
        "For comparing multiple counties in a single period, use compare_county_unemployment instead. "
        "Source: US Bureau of Labor Statistics, Local Area Unemployment Statistics (public domain)."
    )
)
async def get_county_unemployment(
    fips: str,
    ctx: Context[Any, AppContext, Any],
    from_date: str | None = None,
    to_date: str | None = None,
    annual_only: bool = False,
) -> str:
    """Get LAUS unemployment data for a single US county."""
    client = get_client(ctx)
    fips = fips.zfill(5)

    err = _validate_dates(from_date, to_date)
    if err:
        return err

    try:
        if from_date and to_date:
            response = await client.bls.county_unemployment(  # type: ignore[misc]
                fips,
                from_date=from_date,
                to_date=to_date,
                annual_only=annual_only,
            )
            return _format_county_series(response.data, fips)
        else:
            response = await client.bls.county_unemployment(  # type: ignore[misc]
                fips,
                annual_only=annual_only,
                per_page=1,
            )
            if not response.data:
                return f"No LAUS data available for county FIPS {fips}."
            return _format_county_latest(response.data[0], fips)
    except ThesmaError as e:
        return str(e)


# --- Tool: compare_county_unemployment ---


@mcp.tool(
    description=(
        "Compare LAUS unemployment metrics across up to 10 US counties for a single period "
        "(never seasonally adjusted). "
        "Params: fips is a comma-separated list of 5-digit county FIPS codes "
        "(e.g. '06085,48201,17031' for Santa Clara CA, Harris TX, Cook IL). "
        "Maximum 10 counties per call. "
        "year and month are both optional, but if one is provided the other must be too "
        "(omit both to get the latest period the API can resolve). "
        "Use month=13 for the annual-average row. "
        "Source: US Bureau of Labor Statistics, Local Area Unemployment Statistics (public domain)."
    )
)
async def compare_county_unemployment(
    fips: str,
    ctx: Context[Any, AppContext, Any],
    year: int | None = None,
    month: int | None = None,
) -> str:
    """Compare LAUS unemployment across up to 10 US counties."""
    client = get_client(ctx)

    parsed = _parse_fips_list(fips, unit="county")
    if isinstance(parsed, str):
        return parsed

    err = _validate_year_month(year, month)
    if err:
        return err

    try:
        response = await client.bls.county_unemployment_compare(  # type: ignore[misc]
            parsed,
            year=year,
            month=month,
        )
    except ThesmaError as e:
        return str(e)

    return _format_county_compare(response, parsed)


# --- Tool: get_state_unemployment ---


@mcp.tool(
    description=(
        "Get monthly LAUS unemployment data for a single US state. "
        "Defaults to seasonally adjusted (adjustment='sa'); pass adjustment='nsa' for the not-seasonally-adjusted "
        "series. "
        "Without dates, returns the latest available observation. "
        "Provide both from_date and to_date (YYYY-MM) for a time series. "
        "Set annual_only=True to return only annual averages (M13 rows). "
        "Params: fips is a 2-digit state FIPS code (e.g. '06' for California, '48' for Texas). "
        "State observations include labor force participation rate and employment-population ratio. "
        "For comparing multiple states in a single period, use compare_state_unemployment instead. "
        "Source: US Bureau of Labor Statistics, Local Area Unemployment Statistics (public domain)."
    )
)
async def get_state_unemployment(
    fips: str,
    ctx: Context[Any, AppContext, Any],
    from_date: str | None = None,
    to_date: str | None = None,
    adjustment: str | None = None,
    annual_only: bool = False,
) -> str:
    """Get LAUS unemployment data for a single US state."""
    client = get_client(ctx)
    fips = fips.zfill(2)

    err = _validate_dates(from_date, to_date)
    if err:
        return err
    err = _validate_adjustment(adjustment)
    if err:
        return err

    try:
        if from_date and to_date:
            response = await client.bls.state_unemployment(  # type: ignore[misc]
                fips,
                from_date=from_date,
                to_date=to_date,
                adjustment=adjustment or "sa",
                annual_only=annual_only,
            )
            return _format_state_series(response.data, fips)
        else:
            response = await client.bls.state_unemployment(  # type: ignore[misc]
                fips,
                adjustment=adjustment or "sa",
                annual_only=annual_only,
                per_page=1,
            )
            if not response.data:
                return f"No LAUS data available for state FIPS {fips}."
            return _format_state_latest(response.data[0], fips)
    except ThesmaError as e:
        return str(e)


# --- Tool: compare_state_unemployment ---


@mcp.tool(
    description=(
        "Compare LAUS unemployment metrics across up to 10 US states for a single period. "
        "Defaults to seasonally adjusted (adjustment='sa'); pass adjustment='nsa' for the NSA series. "
        "Params: fips is a comma-separated list of 2-digit state FIPS codes (e.g. '06,48,36' for CA, TX, NY). "
        "Maximum 10 states per call. "
        "year and month are both optional, but if one is provided the other must be too "
        "(omit both to get the latest period the API can resolve). "
        "Use month=13 for the annual-average row. "
        "Source: US Bureau of Labor Statistics, Local Area Unemployment Statistics (public domain)."
    )
)
async def compare_state_unemployment(
    fips: str,
    ctx: Context[Any, AppContext, Any],
    year: int | None = None,
    month: int | None = None,
    adjustment: str | None = None,
) -> str:
    """Compare LAUS unemployment across up to 10 US states."""
    client = get_client(ctx)

    parsed = _parse_fips_list(fips, unit="state")
    if isinstance(parsed, str):
        return parsed

    err = _validate_year_month(year, month)
    if err:
        return err
    err = _validate_adjustment(adjustment)
    if err:
        return err

    try:
        response = await client.bls.state_unemployment_compare(  # type: ignore[misc]
            parsed,
            year=year,
            month=month,
            adjustment=adjustment or "sa",
        )
    except ThesmaError as e:
        return str(e)

    return _format_state_compare(response, parsed)


# --- Formatters: county series ---

_COUNTY_FOOTER = "Source: BLS Local Area Unemployment Statistics (LAUS). County data is never seasonally adjusted."
_STATE_FOOTER = "Source: BLS Local Area Unemployment Statistics (LAUS)."


def _format_county_series(rows: list[Any], fips: str) -> str:
    """Format a LAUS county time series as a table."""
    if not rows:
        return f"No LAUS data available for county FIPS {fips} in the requested period."

    first = rows[0]
    county_name = getattr(first, "county_name", "")
    state_name = getattr(first, "state_name", "")
    county_fips = getattr(first, "county_fips", fips)
    header = f"County Unemployment \u2014 {county_name}, {state_name} (FIPS {county_fips})"

    headers = ["Period", "Unemp Rate", "Unemployed", "Employed", "Labor Force", "Prelim"]
    alignments = ["l", "r", "r", "r", "r", "l"]
    table_rows: list[list[str]] = []
    for row in rows:
        year = getattr(row, "year", 0)
        month = getattr(row, "month", 0)
        table_rows.append(
            [
                _period_label(year, month),
                _format_rate(getattr(row, "unemployment_rate", None)),
                format_number(getattr(row, "unemployment", None), decimals=0),
                format_number(getattr(row, "employment", None), decimals=0),
                format_number(getattr(row, "labor_force", None), decimals=0),
                "Yes" if getattr(row, "preliminary", False) else "No",
            ]
        )

    table = format_table(headers, table_rows, alignments)
    lines = [f"{header} ({len(rows)} observations)", "", table, "", _COUNTY_FOOTER]
    return "\n".join(lines)


def _format_county_latest(row: Any, fips: str) -> str:
    """Format the latest LAUS county observation as key-value lines."""
    county_name = getattr(row, "county_name", "")
    state_name = getattr(row, "state_name", "")
    county_fips = getattr(row, "county_fips", fips)
    year = getattr(row, "year", 0)
    month = getattr(row, "month", 0)

    header = f"County Unemployment \u2014 {county_name}, {state_name} (FIPS {county_fips})"

    label_w = 22
    lines = [
        header,
        "",
        f"{'County:':<{label_w}}{county_name}",
        f"{'State:':<{label_w}}{state_name}",
        f"{'Period:':<{label_w}}{_period_label(year, month)}",
        f"{'Unemployment Rate:':<{label_w}}{_format_rate(getattr(row, 'unemployment_rate', None))}",
        f"{'Unemployed:':<{label_w}}{format_number(getattr(row, 'unemployment', None), decimals=0)}",
        f"{'Employed:':<{label_w}}{format_number(getattr(row, 'employment', None), decimals=0)}",
        f"{'Labor Force:':<{label_w}}{format_number(getattr(row, 'labor_force', None), decimals=0)}",
        f"{'Preliminary:':<{label_w}}{'Yes' if getattr(row, 'preliminary', False) else 'No'}",
        "",
        _COUNTY_FOOTER,
    ]
    return "\n".join(lines)


# --- Formatters: state series ---


def _format_state_series(rows: list[Any], fips: str) -> str:
    """Format a LAUS state time series as a table."""
    if not rows:
        return f"No LAUS data available for state FIPS {fips} in the requested period."

    first = rows[0]
    state_name = getattr(first, "state_name", "")
    state_fips = getattr(first, "state_fips", fips)
    adj_label = _format_adjustment_label(getattr(first, "seasonal_adjustment", "seasonally_adjusted"))
    header = f"State Unemployment \u2014 {state_name} (FIPS {state_fips}) [{adj_label}]"

    headers = ["Period", "Unemp Rate", "Unemployed", "Labor Force", "LFPR", "Emp/Pop", "Prelim"]
    alignments = ["l", "r", "r", "r", "r", "r", "l"]
    table_rows: list[list[str]] = []
    for row in rows:
        year = getattr(row, "year", 0)
        month = getattr(row, "month", 0)
        table_rows.append(
            [
                _period_label(year, month),
                _format_rate(getattr(row, "unemployment_rate", None)),
                format_number(getattr(row, "unemployment", None), decimals=0),
                format_number(getattr(row, "labor_force", None), decimals=0),
                _format_rate(getattr(row, "labor_force_participation_rate", None)),
                _format_rate(getattr(row, "employment_population_ratio", None)),
                "Yes" if getattr(row, "preliminary", False) else "No",
            ]
        )

    table = format_table(headers, table_rows, alignments)
    lines = [f"{header} ({len(rows)} observations)", "", table, "", _STATE_FOOTER]
    return "\n".join(lines)


def _format_state_latest(row: Any, fips: str) -> str:
    """Format the latest LAUS state observation as key-value lines."""
    state_name = getattr(row, "state_name", "")
    state_fips = getattr(row, "state_fips", fips)
    year = getattr(row, "year", 0)
    month = getattr(row, "month", 0)
    adj_label = _format_adjustment_label(getattr(row, "seasonal_adjustment", "seasonally_adjusted"))

    header = f"State Unemployment \u2014 {state_name} (FIPS {state_fips}) [{adj_label}]"

    label_w = 36
    lines = [
        header,
        "",
        f"{'State:':<{label_w}}{state_name}",
        f"{'Period:':<{label_w}}{_period_label(year, month)}",
        f"{'Adjustment:':<{label_w}}{adj_label}",
        f"{'Unemployment Rate:':<{label_w}}{_format_rate(getattr(row, 'unemployment_rate', None))}",
        f"{'Unemployed:':<{label_w}}{format_number(getattr(row, 'unemployment', None), decimals=0)}",
        f"{'Employed:':<{label_w}}{format_number(getattr(row, 'employment', None), decimals=0)}",
        f"{'Labor Force:':<{label_w}}{format_number(getattr(row, 'labor_force', None), decimals=0)}",
        f"{'Labor Force Participation Rate:':<{label_w}}"
        f"{_format_rate(getattr(row, 'labor_force_participation_rate', None))}",
        f"{'Employment-Population Ratio:':<{label_w}}{_format_rate(getattr(row, 'employment_population_ratio', None))}",
        f"{'Civilian Noninstitutional Population:':<{label_w}}"
        f"{format_number(getattr(row, 'civilian_noninstitutional_population', None), decimals=0)}",
        f"{'Preliminary:':<{label_w}}{'Yes' if getattr(row, 'preliminary', False) else 'No'}",
        "",
        _STATE_FOOTER,
    ]
    return "\n".join(lines)


# --- Formatters: compare ---


def _format_national_rate_line(rate: float | None) -> str:
    if rate is None:
        return "National unemployment rate: N/A"
    return f"National unemployment rate: {rate:.1f}%"


def _format_errors_section(errors: list[Any] | None) -> list[str]:
    if not errors:
        return []
    lines = ["", "Errors:"]
    for err in errors:
        err_fips = getattr(err, "fips", "")
        err_msg = getattr(err, "message", "")
        lines.append(f"- FIPS {err_fips}: {err_msg}")
    return lines


def _format_county_compare(response: Any, input_fips: list[str]) -> str:
    """Format a LausCountyComparisonResponse as a table."""
    year = getattr(response, "year", 0)
    month = getattr(response, "month", 0)
    items = getattr(response, "data", []) or []
    national_rate = getattr(response, "national_unemployment_rate", None)
    errors = getattr(response, "errors", None)

    period = _period_label(year, month)
    header_lines = [
        f"County Unemployment Comparison \u2014 {period}",
        _format_national_rate_line(national_rate),
    ]

    headers = ["County", "FIPS", "Unemp Rate", "Unemployed", "Employed", "Labor Force"]
    alignments = ["l", "l", "r", "r", "r", "r"]
    rows: list[list[str]] = []
    for item in items:
        rows.append(
            [
                getattr(item, "county_name", "") or "",
                getattr(item, "county_fips", "") or "",
                _format_rate(getattr(item, "unemployment_rate", None)),
                format_number(getattr(item, "unemployment", None), decimals=0),
                format_number(getattr(item, "employment", None), decimals=0),
                format_number(getattr(item, "labor_force", None), decimals=0),
            ]
        )

    if rows:
        table = format_table(headers, rows, alignments)
    else:
        table = "(no county data returned)"

    lines = [*header_lines, "", table]
    lines.extend(_format_errors_section(errors))
    lines.extend(["", _COUNTY_FOOTER])
    return "\n".join(lines)


def _format_state_compare(response: Any, input_fips: list[str]) -> str:
    """Format a LausStateComparisonResponse as a table."""
    year = getattr(response, "year", 0)
    month = getattr(response, "month", 0)
    items = getattr(response, "data", []) or []
    national_rate = getattr(response, "national_unemployment_rate", None)
    errors = getattr(response, "errors", None)
    adj_label = _format_adjustment_label(getattr(response, "seasonal_adjustment", "seasonally_adjusted"))

    period = _period_label(year, month)
    header_lines = [
        f"State Unemployment Comparison \u2014 {period} [{adj_label}]",
        _format_national_rate_line(national_rate),
    ]

    headers = ["State", "FIPS", "Unemp Rate", "Unemployed", "Labor Force", "LFPR", "Emp/Pop"]
    alignments = ["l", "l", "r", "r", "r", "r", "r"]
    rows: list[list[str]] = []
    for item in items:
        rows.append(
            [
                getattr(item, "state_name", "") or "",
                getattr(item, "state_fips", "") or "",
                _format_rate(getattr(item, "unemployment_rate", None)),
                format_number(getattr(item, "unemployment", None), decimals=0),
                format_number(getattr(item, "labor_force", None), decimals=0),
                _format_rate(getattr(item, "labor_force_participation_rate", None)),
                _format_rate(getattr(item, "employment_population_ratio", None)),
            ]
        )

    if rows:
        table = format_table(headers, rows, alignments)
    else:
        table = "(no state data returned)"

    lines = [*header_lines, "", table]
    lines.extend(_format_errors_section(errors))
    lines.extend(["", _STATE_FOOTER])
    return "\n".join(lines)
