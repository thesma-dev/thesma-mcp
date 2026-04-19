"""MCP tools for SBA 7(a) lending data."""

from __future__ import annotations

import re
from typing import Any

from mcp.server.fastmcp import Context
from thesma.errors import ThesmaError

from thesma_mcp.formatters import format_currency, format_number, format_table
from thesma_mcp.server import AppContext, get_client, mcp

_QUARTER_RE = re.compile(r"^\d{4}-Q[1-4]$")


def _get_ctx(ctx: Context[Any, AppContext, Any]) -> AppContext:
    return ctx.request_context.lifespan_context


def _normalize_period(value: str | None) -> str | None:
    """Strip whitespace and treat empty string as None."""
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _validate_quarter_period(value: str | None, *, field: str) -> str | None:
    """Validate YYYY-Qq format. Returns error message or None if valid/absent."""
    if value is None:
        return None
    if not _QUARTER_RE.match(value):
        return f"Invalid {field} format: '{value}'. Expected YYYY-Q[1-4] (e.g. 2025-Q3)."
    return None


def _validate_period_pair(from_period: str | None, to_period: str | None) -> str | None:
    """Reject when exactly one of from_period/to_period is provided, and validate format.

    Callers must normalise via ``_normalize_period`` BEFORE passing values here so
    empty strings / whitespace-only strings do not trigger false "both required"
    errors against a None counterpart.
    """
    if (from_period is None) != (to_period is None):
        return "Both from_period and to_period are required for a range (omit both for latest)."
    for name, value in (("from_period", from_period), ("to_period", to_period)):
        err = _validate_quarter_period(value, field=name)
        if err:
            return err
    return None


def _format_quarter_period(year: int, quarter: int) -> str:
    """Render year/quarter as 'YYYY-Qq'."""
    return f"{year}-Q{quarter}"


def _format_money(value: float | None, *, decimals: int = 0) -> str:
    """Format a dollar amount or 'N/A'."""
    if value is None:
        return "N/A"
    return format_currency(value, decimals=decimals)


def _format_pct(value: float | None) -> str:
    """Format a percentage value or 'N/A'."""
    if value is None:
        return "N/A"
    return f"{value:.2f}%"


_SBA_FOOTER = "Source: US Small Business Administration, 7(a) Loan Program (public domain)."


# --- Tool: get_county_lending ---


@mcp.tool(
    description=(
        "Get quarterly SBA 7(a) loan aggregates for a single US county — loan count, total amount, "
        "charge-off rate, average loan size, and jobs supported. "
        "Without period filters, returns the latest available quarterly observation. "
        "Provide both from_period and to_period (YYYY-Qq, e.g. '2024-Q1') for a time series. "
        "Params: fips is a 5-digit county FIPS code (e.g. '06037' for Los Angeles County, CA). "
        "Optional industry filter accepts a NAICS code to restrict aggregates to one industry. "
        "Source: US Small Business Administration, 7(a) Loan Program (public domain)."
    )
)
async def get_county_lending(
    fips: str,
    ctx: Context[Any, AppContext, Any],
    industry: str | None = None,
    year: int | None = None,
    quarter: int | None = None,
    from_period: str | None = None,
    to_period: str | None = None,
) -> str:
    """Get quarterly SBA 7(a) lending aggregates for a US county."""
    client = get_client(ctx)
    fips = fips.zfill(5)

    from_period = _normalize_period(from_period)
    to_period = _normalize_period(to_period)
    err = _validate_period_pair(from_period, to_period)
    if err:
        return err

    try:
        if from_period and to_period:
            response = await client.sba.county_lending(  # type: ignore[misc]
                fips,
                industry=industry,
                year=year,
                quarter=quarter,
                from_period=from_period,
                to_period=to_period,
                per_page=25,
            )
            return _format_county_lending_series(response.data, fips)
        else:
            response = await client.sba.county_lending(  # type: ignore[misc]
                fips,
                industry=industry,
                year=year,
                quarter=quarter,
                per_page=1,
            )
            if not response.data:
                return f"No SBA lending data available for county FIPS {fips}."
            return _format_county_lending_latest(response.data[0], fips)
    except ThesmaError as e:
        return str(e)


# --- Tool: get_state_lending ---


@mcp.tool(
    description=(
        "Get quarterly SBA 7(a) loan aggregates for a single US state — loan count, total amount, "
        "charge-off rate, average loan size, and jobs supported. "
        "Without period filters, returns the latest available quarterly observation. "
        "Provide both from_period and to_period (YYYY-Qq, e.g. '2024-Q1') for a time series. "
        "Params: fips is a 2-digit state FIPS code (e.g. '06' for California, '48' for Texas). "
        "Optional industry filter accepts a NAICS code to restrict aggregates to one industry. "
        "Source: US Small Business Administration, 7(a) Loan Program (public domain)."
    )
)
async def get_state_lending(
    fips: str,
    ctx: Context[Any, AppContext, Any],
    industry: str | None = None,
    year: int | None = None,
    quarter: int | None = None,
    from_period: str | None = None,
    to_period: str | None = None,
) -> str:
    """Get quarterly SBA 7(a) lending aggregates for a US state."""
    client = get_client(ctx)
    fips = fips.zfill(2)

    from_period = _normalize_period(from_period)
    to_period = _normalize_period(to_period)
    err = _validate_period_pair(from_period, to_period)
    if err:
        return err

    try:
        if from_period and to_period:
            response = await client.sba.state_lending(  # type: ignore[misc]
                fips,
                industry=industry,
                year=year,
                quarter=quarter,
                from_period=from_period,
                to_period=to_period,
                per_page=25,
            )
            return _format_state_lending_series(response.data, fips)
        else:
            response = await client.sba.state_lending(  # type: ignore[misc]
                fips,
                industry=industry,
                year=year,
                quarter=quarter,
                per_page=1,
            )
            if not response.data:
                return f"No SBA lending data available for state FIPS {fips}."
            return _format_state_lending_latest(response.data[0], fips)
    except ThesmaError as e:
        return str(e)


# --- Tool: get_industry_lending ---


@mcp.tool(
    description=(
        "Get quarterly SBA 7(a) loan aggregates for a NAICS industry. "
        "Default scope is national; pass geo='state' with state=<2-digit FIPS> or geo='county' with "
        "county=<5-digit FIPS> to scope the aggregate. "
        "Without period filters, returns the latest available quarterly observation. "
        "Provide both from_period and to_period (YYYY-Qq, e.g. '2024-Q1') for a time series. "
        "Params: naics is a NAICS code (2–6 digits, e.g. '541211' for Offices of Accountants). "
        "Source: US Small Business Administration, 7(a) Loan Program (public domain)."
    )
)
async def get_industry_lending(
    naics: str,
    ctx: Context[Any, AppContext, Any],
    geo: str | None = None,
    state: str | None = None,
    county: str | None = None,
    year: int | None = None,
    quarter: int | None = None,
    from_period: str | None = None,
    to_period: str | None = None,
) -> str:
    """Get quarterly SBA 7(a) lending aggregates for a NAICS industry."""
    client = get_client(ctx)

    if state is not None:
        state = state.zfill(2)
    if county is not None:
        county = county.zfill(5)

    from_period = _normalize_period(from_period)
    to_period = _normalize_period(to_period)
    err = _validate_period_pair(from_period, to_period)
    if err:
        return err

    try:
        if from_period and to_period:
            response = await client.sba.industry_lending(  # type: ignore[misc]
                naics,
                geo=geo,
                state=state,
                county=county,
                year=year,
                quarter=quarter,
                from_period=from_period,
                to_period=to_period,
                per_page=25,
            )
            return _format_industry_lending_series(response.data, naics, geo=geo, state=state, county=county)
        else:
            response = await client.sba.industry_lending(  # type: ignore[misc]
                naics,
                geo=geo,
                state=state,
                county=county,
                year=year,
                quarter=quarter,
                per_page=1,
            )
            if not response.data:
                return f"No SBA lending data available for NAICS {naics}."
            return _format_industry_lending_latest(response.data[0], naics, geo=geo, state=state, county=county)
    except ThesmaError as e:
        return str(e)


# --- Tool: get_lenders ---


@mcp.tool(
    description=(
        "List SBA 7(a) lenders ranked by loan count, total amount, or average loan size. "
        "Optional filters: state (2-digit FIPS), county (5-digit FIPS), industry (NAICS), "
        "year/quarter, and a from_period/to_period range (YYYY-Qq). "
        "sort accepts 'loan_count' (default), 'total_amount', or 'avg_amount'. "
        "limit is capped at 50. "
        "Source: US Small Business Administration, 7(a) Loan Program (public domain)."
    )
)
async def get_lenders(
    ctx: Context[Any, AppContext, Any],
    state: str | None = None,
    county: str | None = None,
    industry: str | None = None,
    year: int | None = None,
    quarter: int | None = None,
    from_period: str | None = None,
    to_period: str | None = None,
    sort: str = "loan_count",
    limit: int = 20,
) -> str:
    """List SBA 7(a) lenders ranked by loan volume."""
    client = get_client(ctx)

    if state is not None:
        state = state.zfill(2)
    if county is not None:
        county = county.zfill(5)

    from_period = _normalize_period(from_period)
    to_period = _normalize_period(to_period)
    err = _validate_period_pair(from_period, to_period)
    if err:
        return err

    per_page = min(limit, 50)

    try:
        response = await client.sba.lenders(  # type: ignore[misc]
            state=state,
            county=county,
            industry=industry,
            year=year,
            quarter=quarter,
            from_period=from_period,
            to_period=to_period,
            sort=sort,
            per_page=per_page,
        )
    except ThesmaError as e:
        return str(e)

    return _format_lenders_list(response.data, sort=sort)


# --- Tool: get_lender ---


@mcp.tool(
    description=(
        "Get details and quarterly history for a single SBA 7(a) lender by lender_id. "
        "Optional from_period/to_period filters the quarterly history range (YYYY-Qq). "
        "Both are required together for a range; omit both for full history. "
        "Source: US Small Business Administration, 7(a) Loan Program (public domain)."
    )
)
async def get_lender(
    lender_id: int,
    ctx: Context[Any, AppContext, Any],
    from_period: str | None = None,
    to_period: str | None = None,
) -> str:
    """Get details and quarterly history for a single SBA 7(a) lender."""
    client = get_client(ctx)

    from_period = _normalize_period(from_period)
    to_period = _normalize_period(to_period)
    err = _validate_period_pair(from_period, to_period)
    if err:
        return err

    try:
        response = await client.sba.lender(  # type: ignore[misc]
            lender_id,
            from_period=from_period,
            to_period=to_period,
        )
    except ThesmaError as e:
        return str(e)

    return _format_lender_detail(response.data)


# --- Tool: get_lending_characteristics ---


@mcp.tool(
    description=(
        "Get SBA 7(a) loan distributions for a single quarter — loan size buckets, term length buckets, "
        "interest rate histogram, sub-programme mix, business-type mix, and revolving-vs-term split. "
        "year and quarter are required by the API (pass them together). "
        "Optional state (2-digit FIPS), county (5-digit FIPS), or industry (NAICS) filters scope the distributions. "
        "Source: US Small Business Administration, 7(a) Loan Program (public domain)."
    )
)
async def get_lending_characteristics(
    ctx: Context[Any, AppContext, Any],
    year: int | None = None,
    quarter: int | None = None,
    state: str | None = None,
    county: str | None = None,
    industry: str | None = None,
) -> str:
    """Get SBA 7(a) loan characteristics distributions for a quarter."""
    client = get_client(ctx)

    if state is not None:
        state = state.zfill(2)
    if county is not None:
        county = county.zfill(5)

    try:
        response = await client.sba.lending_characteristics(  # type: ignore[misc]
            year=year,
            quarter=quarter,
            state=state,
            county=county,
            industry=industry,
        )
    except ThesmaError as e:
        return str(e)

    return _format_characteristics(response.data)


# --- Tool: get_lending_outcomes ---


@mcp.tool(
    description=(
        "Get SBA 7(a) vintage cohort charge-off outcomes — loans originated in a given year and their "
        "charge-off rates, maturity status, and gross charge-off amounts. "
        "vintage_from is required by the API; vintage_to defaults to vintage_from (single vintage) and "
        "the API enforces vintage_to - vintage_from <= 10. "
        "Optional state (2-digit FIPS), county (5-digit FIPS), or industry (NAICS) filters. "
        "Source: US Small Business Administration, 7(a) Loan Program (public domain)."
    )
)
async def get_lending_outcomes(
    ctx: Context[Any, AppContext, Any],
    vintage_from: int | None = None,
    vintage_to: int | None = None,
    state: str | None = None,
    county: str | None = None,
    industry: str | None = None,
) -> str:
    """Get SBA 7(a) vintage cohort charge-off outcomes."""
    client = get_client(ctx)

    if state is not None:
        state = state.zfill(2)
    if county is not None:
        county = county.zfill(5)

    try:
        response = await client.sba.lending_outcomes(  # type: ignore[misc]
            vintage_from=vintage_from,
            vintage_to=vintage_to,
            state=state,
            county=county,
            industry=industry,
            per_page=25,
        )
    except ThesmaError as e:
        return str(e)

    return _format_outcomes(response.data)


# --- Tool: explore_sba_metrics ---


@mcp.tool(
    description=(
        "Browse the SBA 7(a) metric catalog — discover available metrics by category or keyword. "
        "category accepts 'volume', 'outcomes', or 'characteristics'. "
        "query is a free-text search (minimum 2 characters). "
        "Returns metric canonical names with display name, category, unit, and update cadence. "
        "Use get_sba_metric_detail to fetch the full definition for a single metric. "
        "Source: US Small Business Administration, 7(a) Loan Program (public domain)."
    )
)
async def explore_sba_metrics(
    ctx: Context[Any, AppContext, Any],
    category: str | None = None,
    query: str | None = None,
    limit: int = 25,
) -> str:
    """Browse the SBA 7(a) metric catalog."""
    client = get_client(ctx)
    per_page = min(limit, 50)

    try:
        response = await client.sba.metrics(  # type: ignore[misc]
            category=category,
            search=query,
            per_page=per_page,
        )
    except ThesmaError as e:
        return str(e)

    return _format_metric_list(response.data)


# --- Tool: get_sba_metric_detail ---


@mcp.tool(
    description=(
        "Get the full definition for a single SBA 7(a) metric by canonical name. "
        "Returns display name, description, category, unit, update cadence, typical lag, "
        "data availability year range, and related endpoints. "
        "Use explore_sba_metrics to discover canonical names. "
        "Source: US Small Business Administration, 7(a) Loan Program (public domain)."
    )
)
async def get_sba_metric_detail(metric: str, ctx: Context[Any, AppContext, Any]) -> str:
    """Get the full definition for a single SBA 7(a) metric."""
    client = get_client(ctx)

    try:
        response = await client.sba.metric(metric)  # type: ignore[misc]
    except ThesmaError as e:
        return str(e)

    return _format_metric_detail(response.data)


# --- Formatters ---


def _lending_row_cells(row: Any) -> list[str]:
    """Shared cell extraction for county/state/industry lending tables."""
    year = getattr(row, "year", 0)
    quarter = getattr(row, "quarter", 0)
    period = getattr(row, "period", None) or _format_quarter_period(year, quarter)
    return [
        period,
        format_number(getattr(row, "loan_count", None), decimals=0),
        _format_money(getattr(row, "total_amount", None)),
        _format_money(getattr(row, "avg_amount", None)),
        _format_pct(getattr(row, "avg_guarantee_pct", None)),
        format_number(getattr(row, "jobs_supported", None), decimals=0),
        _format_pct(getattr(row, "charge_off_rate", None)),
    ]


_LENDING_HEADERS = [
    "Period",
    "Loans",
    "Total Amount",
    "Avg Amount",
    "Avg Guarantee %",
    "Jobs Supported",
    "Charge-off Rate",
]
_LENDING_ALIGNMENTS = ["l", "r", "r", "r", "r", "r", "r"]


def _format_county_lending_series(rows: list[Any], fips: str) -> str:
    """Format a multi-row county lending series."""
    if not rows:
        return f"No SBA lending data available for county FIPS {fips} in the requested period."
    first = rows[0]
    county_fips = getattr(first, "county_fips", fips) or fips
    header = f"SBA 7(a) Lending \u2014 County FIPS {county_fips}"
    table_rows = [_lending_row_cells(r) for r in rows]
    table = format_table(_LENDING_HEADERS, table_rows, _LENDING_ALIGNMENTS)
    return "\n".join([f"{header} ({len(rows)} observations)", "", table, "", _SBA_FOOTER])


def _format_county_lending_latest(row: Any, fips: str) -> str:
    """Format the latest county lending observation as key-value lines."""
    county_fips = getattr(row, "county_fips", fips) or fips
    year = getattr(row, "year", 0)
    quarter = getattr(row, "quarter", 0)
    period = getattr(row, "period", None) or _format_quarter_period(year, quarter)

    label_w = 24
    lines = [
        f"SBA 7(a) Lending \u2014 County FIPS {county_fips}",
        "",
        f"{'County FIPS:':<{label_w}}{county_fips}",
        f"{'Period:':<{label_w}}{period}",
        f"{'Loan Count:':<{label_w}}{format_number(getattr(row, 'loan_count', None), decimals=0)}",
        f"{'Total Amount:':<{label_w}}{_format_money(getattr(row, 'total_amount', None))}",
        f"{'Avg Loan Size:':<{label_w}}{_format_money(getattr(row, 'avg_amount', None))}",
        f"{'Median Loan Size:':<{label_w}}{_format_money(getattr(row, 'median_amount', None))}",
        f"{'Guaranteed Amount:':<{label_w}}{_format_money(getattr(row, 'guaranteed_amount', None))}",
        f"{'Avg Guarantee %:':<{label_w}}{_format_pct(getattr(row, 'avg_guarantee_pct', None))}",
        f"{'Jobs Supported:':<{label_w}}{format_number(getattr(row, 'jobs_supported', None), decimals=0)}",
        f"{'Charge-off Count:':<{label_w}}{format_number(getattr(row, 'charge_off_count', None), decimals=0)}",
        f"{'Charge-off Rate:':<{label_w}}{_format_pct(getattr(row, 'charge_off_rate', None))}",
        f"{'Charge-off Amount:':<{label_w}}{_format_money(getattr(row, 'charge_off_amount', None))}",
        "",
        _SBA_FOOTER,
    ]
    return "\n".join(lines)


def _format_state_lending_series(rows: list[Any], fips: str) -> str:
    """Format a multi-row state lending series."""
    if not rows:
        return f"No SBA lending data available for state FIPS {fips} in the requested period."
    first = rows[0]
    state_fips = getattr(first, "state_fips", fips) or fips
    header = f"SBA 7(a) Lending \u2014 State FIPS {state_fips}"
    table_rows = [_lending_row_cells(r) for r in rows]
    table = format_table(_LENDING_HEADERS, table_rows, _LENDING_ALIGNMENTS)
    return "\n".join([f"{header} ({len(rows)} observations)", "", table, "", _SBA_FOOTER])


def _format_state_lending_latest(row: Any, fips: str) -> str:
    """Format the latest state lending observation as key-value lines."""
    state_fips = getattr(row, "state_fips", fips) or fips
    year = getattr(row, "year", 0)
    quarter = getattr(row, "quarter", 0)
    period = getattr(row, "period", None) or _format_quarter_period(year, quarter)

    label_w = 24
    lines = [
        f"SBA 7(a) Lending \u2014 State FIPS {state_fips}",
        "",
        f"{'State FIPS:':<{label_w}}{state_fips}",
        f"{'Period:':<{label_w}}{period}",
        f"{'Loan Count:':<{label_w}}{format_number(getattr(row, 'loan_count', None), decimals=0)}",
        f"{'Total Amount:':<{label_w}}{_format_money(getattr(row, 'total_amount', None))}",
        f"{'Avg Loan Size:':<{label_w}}{_format_money(getattr(row, 'avg_amount', None))}",
        f"{'Median Loan Size:':<{label_w}}{_format_money(getattr(row, 'median_amount', None))}",
        f"{'Guaranteed Amount:':<{label_w}}{_format_money(getattr(row, 'guaranteed_amount', None))}",
        f"{'Avg Guarantee %:':<{label_w}}{_format_pct(getattr(row, 'avg_guarantee_pct', None))}",
        f"{'Jobs Supported:':<{label_w}}{format_number(getattr(row, 'jobs_supported', None), decimals=0)}",
        f"{'Charge-off Count:':<{label_w}}{format_number(getattr(row, 'charge_off_count', None), decimals=0)}",
        f"{'Charge-off Rate:':<{label_w}}{_format_pct(getattr(row, 'charge_off_rate', None))}",
        f"{'Charge-off Amount:':<{label_w}}{_format_money(getattr(row, 'charge_off_amount', None))}",
        "",
        _SBA_FOOTER,
    ]
    return "\n".join(lines)


def _industry_scope_label(
    *, naics: str, geo: str | None, state: str | None, county: str | None, row: Any = None
) -> str:
    """Build the header scope label for the industry endpoint."""
    # Prefer row-level fips when the row carries them (e.g. state/county-scoped responses).
    row_state = getattr(row, "state_fips", None) if row is not None else None
    row_county = getattr(row, "county_fips", None) if row is not None else None
    scope_parts = [f"NAICS {naics}"]
    if geo:
        scope_parts.append(f"geo={geo}")
    eff_state = row_state or state
    eff_county = row_county or county
    if eff_county:
        scope_parts.append(f"county FIPS {eff_county}")
    elif eff_state:
        scope_parts.append(f"state FIPS {eff_state}")
    return ", ".join(scope_parts)


def _format_industry_lending_series(
    rows: list[Any],
    naics: str,
    *,
    geo: str | None,
    state: str | None,
    county: str | None,
) -> str:
    """Format a multi-row industry lending series."""
    if not rows:
        return f"No SBA lending data available for NAICS {naics} in the requested period."
    scope = _industry_scope_label(naics=naics, geo=geo, state=state, county=county, row=rows[0])
    header = f"SBA 7(a) Lending \u2014 {scope}"
    table_rows = [_lending_row_cells(r) for r in rows]
    table = format_table(_LENDING_HEADERS, table_rows, _LENDING_ALIGNMENTS)
    return "\n".join([f"{header} ({len(rows)} observations)", "", table, "", _SBA_FOOTER])


def _format_industry_lending_latest(
    row: Any,
    naics: str,
    *,
    geo: str | None,
    state: str | None,
    county: str | None,
) -> str:
    """Format the latest industry lending observation as key-value lines."""
    scope = _industry_scope_label(naics=naics, geo=geo, state=state, county=county, row=row)
    year = getattr(row, "year", 0)
    quarter = getattr(row, "quarter", 0)
    period = getattr(row, "period", None) or _format_quarter_period(year, quarter)

    label_w = 24
    lines = [
        f"SBA 7(a) Lending \u2014 {scope}",
        "",
        f"{'NAICS:':<{label_w}}{getattr(row, 'naics_code', naics)}",
        f"{'Geo:':<{label_w}}{geo or 'national'}",
        f"{'Period:':<{label_w}}{period}",
        f"{'Loan Count:':<{label_w}}{format_number(getattr(row, 'loan_count', None), decimals=0)}",
        f"{'Total Amount:':<{label_w}}{_format_money(getattr(row, 'total_amount', None))}",
        f"{'Avg Loan Size:':<{label_w}}{_format_money(getattr(row, 'avg_amount', None))}",
        f"{'Avg Guarantee %:':<{label_w}}{_format_pct(getattr(row, 'avg_guarantee_pct', None))}",
        f"{'Jobs Supported:':<{label_w}}{format_number(getattr(row, 'jobs_supported', None), decimals=0)}",
        f"{'Charge-off Rate:':<{label_w}}{_format_pct(getattr(row, 'charge_off_rate', None))}",
        "",
        _SBA_FOOTER,
    ]
    return "\n".join(lines)


def _format_lenders_list(rows: list[Any], *, sort: str) -> str:
    """Format a ranked lender list."""
    if not rows:
        return "No SBA lenders matched the specified filters."

    header = f"SBA 7(a) Lenders (sorted by {sort})"
    headers = ["#", "Lender", "City, State", "Loans", "Total Amount", "Avg Amount", "Market Share %"]
    alignments = ["r", "l", "l", "r", "r", "r", "r"]
    table_rows: list[list[str]] = []
    for i, row in enumerate(rows, 1):
        city = getattr(row, "city", None) or ""
        state = getattr(row, "state", None) or ""
        loc = ", ".join(part for part in (city, state) if part)
        table_rows.append(
            [
                str(i),
                getattr(row, "display_name", None) or "",
                loc,
                format_number(getattr(row, "loan_count", None), decimals=0),
                _format_money(getattr(row, "total_amount", None)),
                _format_money(getattr(row, "avg_amount", None)),
                _format_pct(getattr(row, "market_share_pct", None)),
            ]
        )

    table = format_table(headers, table_rows, alignments)
    return "\n".join([header, "", table, "", _SBA_FOOTER])


def _format_lender_detail(data: Any) -> str:
    """Format a lender detail record with identity + quarterly history."""
    display_name = getattr(data, "display_name", None) or ""
    lender_id = getattr(data, "lender_id", None)
    city = getattr(data, "city", None) or ""
    state = getattr(data, "state", None) or ""
    first_seen = getattr(data, "first_seen_at", None)
    last_seen = getattr(data, "last_seen_at", None)

    label_w = 20
    lines = [
        f"SBA 7(a) Lender \u2014 {display_name}",
        "",
        f"{'Lender ID:':<{label_w}}{lender_id}",
        f"{'Display Name:':<{label_w}}{display_name}",
        f"{'City, State:':<{label_w}}{', '.join(part for part in (city, state) if part)}",
        f"{'First Seen:':<{label_w}}{first_seen or '—'}",
        f"{'Last Seen:':<{label_w}}{last_seen or '—'}",
        "",
        "## Quarterly History",
        "",
    ]

    history = getattr(data, "history", None) or []
    if not history:
        lines.append("No quarterly history on record.")
    else:
        headers = ["Period", "Loans", "Total Amount", "Avg Amount"]
        alignments = ["l", "r", "r", "r"]
        rows: list[list[str]] = []
        for q in history:
            year = getattr(q, "year", 0)
            quarter = getattr(q, "quarter", 0)
            period = getattr(q, "period", None) or _format_quarter_period(year, quarter)
            rows.append(
                [
                    period,
                    format_number(getattr(q, "loan_count", None), decimals=0),
                    _format_money(getattr(q, "total_amount", None)),
                    _format_money(getattr(q, "avg_amount", None)),
                ]
            )
        lines.append(format_table(headers, rows, alignments))

    lines.extend(["", _SBA_FOOTER])
    return "\n".join(lines)


def _format_bucket_table(buckets: list[Any], *, label_field: str) -> str:
    """Render a list of BucketCount or CategoryCount items as a 4-column table."""
    headers = [label_field, "Loans", "Total Amount", "% of Total"]
    alignments = ["l", "r", "r", "r"]
    rows: list[list[str]] = []
    for b in buckets:
        # BucketCount uses .label; CategoryCount uses .name
        label = getattr(b, "label", None) or getattr(b, "name", None) or ""
        rows.append(
            [
                str(label),
                format_number(getattr(b, "loan_count", None), decimals=0),
                _format_money(getattr(b, "total_amount", None)),
                _format_pct(getattr(b, "pct", None)),
            ]
        )
    return format_table(headers, rows, alignments)


def _format_characteristics(data: Any) -> str:
    """Format a CharacteristicsDistribution as six sub-section tables."""
    year = getattr(data, "year", 0)
    quarter = getattr(data, "quarter", 0)
    period = getattr(data, "period", None) or _format_quarter_period(year, quarter)
    total_loans = getattr(data, "total_loans", None)
    filter_scope = getattr(data, "filter_scope", None) or {}

    lines: list[str] = [
        f"SBA 7(a) Loan Characteristics \u2014 {period}",
        "",
        f"{'Period:':<20}{period}",
        f"{'Total Loans:':<20}{format_number(total_loans, decimals=0)}",
        f"{'Filter Scope:':<20}{filter_scope if filter_scope else '(none)'}",
    ]

    subsections: list[tuple[str, str, str]] = [
        ("loan_size_buckets", "Loan Size Distribution", "Label"),
        ("term_length_buckets", "Term Length Distribution", "Label"),
        ("interest_rate_histogram", "Interest Rate Histogram", "Label"),
        ("sub_programme_mix", "Sub-programme Mix", "Name"),
        ("business_type_mix", "Business Type Mix", "Name"),
        ("revolving_vs_term", "Revolving vs Term", "Name"),
    ]

    rendered_any = False
    for attr, title, label_field in subsections:
        items = getattr(data, attr, None) or []
        if not items:
            continue
        rendered_any = True
        lines.append("")
        lines.append(f"### {title}")
        lines.append("")
        lines.append(_format_bucket_table(items, label_field=label_field))

    if not rendered_any:
        lines.append("")
        lines.append("_(no distributional breakdowns available for this scope — try broadening the filter)_")

    lines.extend(["", _SBA_FOOTER])
    return "\n".join(lines)


def _format_outcomes(rows: list[Any]) -> str:
    """Format a list of VintageOutcomePoint items as a cohort table."""
    if not rows:
        return "No SBA vintage outcomes matched the specified filters."

    headers = [
        "Vintage Year",
        "Total Loans",
        "Charged Off",
        "Charge-off Rate",
        "Gross Charge-off Amount",
        "Avg Time to Charge-off (mo)",
        "Active Loans",
        "Maturity",
    ]
    alignments = ["r", "r", "r", "r", "r", "r", "r", "l"]
    table_rows: list[list[str]] = []
    for r in rows:
        avg_time = getattr(r, "avg_time_to_chargeoff_months", None)
        avg_time_str = f"{avg_time:.1f}" if avg_time is not None else "N/A"
        table_rows.append(
            [
                str(getattr(r, "vintage_year", "")),
                format_number(getattr(r, "loans_in_vintage", None), decimals=0),
                format_number(getattr(r, "charged_off_count", None), decimals=0),
                _format_pct(getattr(r, "charge_off_rate_pct", None)),
                _format_money(getattr(r, "gross_charge_off_amount", None)),
                avg_time_str,
                format_number(getattr(r, "active_loan_count", None), decimals=0),
                str(getattr(r, "vintage_maturity", "") or ""),
            ]
        )

    table = format_table(headers, table_rows, alignments)
    header = f"SBA 7(a) Vintage Outcomes ({len(rows)} cohorts)"
    return "\n".join([header, "", table, "", _SBA_FOOTER])


def _format_metric_list(rows: list[Any]) -> str:
    """Format a list of SbaMetricSummary items as a discovery table."""
    if not rows:
        return "No SBA metrics matched the specified filters."

    headers = ["Metric", "Display Name", "Category", "Unit", "Cadence"]
    alignments = ["l", "l", "l", "l", "l"]
    table_rows: list[list[str]] = []
    for m in rows:
        table_rows.append(
            [
                getattr(m, "canonical_name", None) or "",
                getattr(m, "display_name", None) or "",
                getattr(m, "category", None) or "",
                getattr(m, "unit", None) or "",
                getattr(m, "update_cadence", None) or "",
            ]
        )

    table = format_table(headers, table_rows, alignments)
    header = f"SBA 7(a) Metric Catalog ({len(rows)} metrics)"
    return "\n".join([header, "", table, "", _SBA_FOOTER])


def _format_metric_detail(data: Any) -> str:
    """Format a SbaMetricDetail record as key-value lines."""
    canonical = getattr(data, "canonical_name", None) or ""
    display = getattr(data, "display_name", None) or ""
    description = getattr(data, "description", None) or ""
    category = getattr(data, "category", None) or ""
    unit = getattr(data, "unit", None) or ""
    cadence = getattr(data, "update_cadence", None) or ""
    lag = getattr(data, "typical_lag_months", None)

    availability = getattr(data, "data_availability", None)
    if availability is None:
        availability_label = "unavailable"
    else:
        min_y = getattr(availability, "min", None)
        max_y = getattr(availability, "max", None)
        if min_y is None and max_y is None:
            availability_label = "unavailable"
        else:
            availability_label = f"{min_y}\u2013{max_y}"

    related = getattr(data, "related_endpoints", None) or []

    label_w = 22
    lines = [
        f"SBA 7(a) Metric \u2014 {display or canonical}",
        "",
        f"{'Canonical Name:':<{label_w}}{canonical}",
        f"{'Display Name:':<{label_w}}{display}",
        f"{'Description:':<{label_w}}{description}",
        f"{'Category:':<{label_w}}{category}",
        f"{'Unit:':<{label_w}}{unit}",
        f"{'Update Cadence:':<{label_w}}{cadence}",
        f"{'Typical Lag (months):':<{label_w}}{lag if lag is not None else 'N/A'}",
        f"{'Data availability:':<{label_w}}{availability_label}",
    ]
    if related:
        lines.append("")
        lines.append("Related endpoints:")
        for ep in related:
            lines.append(f"  - {ep}")
    lines.extend(["", _SBA_FOOTER])
    return "\n".join(lines)
