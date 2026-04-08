"""Tests for BLS standalone tools (MCP-08)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from thesma_mcp.tools.bls_counties import get_county_employment, get_county_wages
from thesma_mcp.tools.bls_industries import get_industry_detail, get_industry_employment, search_industries
from thesma_mcp.tools.bls_metrics import explore_bls_metrics
from thesma_mcp.tools.bls_occupations import get_occupation_wages, search_occupations


def _make_paginated_response(items: list[MagicMock], total: int | None = None) -> MagicMock:
    resp = MagicMock()
    resp.data = items
    resp.pagination = MagicMock()
    resp.pagination.total = total if total is not None else len(items)
    return resp


def _make_data_response(data: MagicMock) -> MagicMock:
    resp = MagicMock()
    resp.data = data
    return resp


def _make_industry_summary(naics: str, title: str, level: int) -> MagicMock:
    m = MagicMock()
    m.naics_code = naics
    m.title = title
    m.level = level
    return m


def _make_employment_point(**kwargs: Any) -> MagicMock:
    m = MagicMock()
    for k, v in kwargs.items():
        setattr(m, k, v)
    return m


def _make_county_employment(**kwargs: Any) -> MagicMock:
    m = MagicMock()
    for k, v in kwargs.items():
        setattr(m, k, v)
    return m


def _make_occupation_summary(soc: str, title: str, major_group: str) -> MagicMock:
    m = MagicMock()
    m.soc_code = soc
    m.title = title
    m.major_group = major_group
    return m


def _make_occupation_wages(**kwargs: Any) -> MagicMock:
    m = MagicMock()
    for k, v in kwargs.items():
        setattr(m, k, v)
    return m


def _make_metric_summary(**kwargs: Any) -> MagicMock:
    m = MagicMock()
    for k, v in kwargs.items():
        setattr(m, k, v)
    return m


def _make_ctx() -> MagicMock:
    """Create a mock MCP context."""
    app = MagicMock()
    app.client = MagicMock()
    ctx = MagicMock()
    ctx.request_context.lifespan_context = app
    return ctx


def _app(ctx: MagicMock) -> Any:
    return ctx.request_context.lifespan_context


# --- Industries ---


@pytest.mark.asyncio
async def test_search_industries() -> None:
    """search_industries returns formatted table with NAICS codes and titles."""
    ctx = _make_ctx()
    items = [
        _make_industry_summary("5112", "Software Publishers", 4),
        _make_industry_summary("5111", "Newspaper Publishers", 4),
    ]
    resp = _make_paginated_response(items)
    _app(ctx).client.bls.industries = AsyncMock(return_value=resp)

    result = await search_industries(ctx, query="publishers")

    assert "5112" in result
    assert "Software Publishers" in result
    assert "NAICS" in result
    assert "publishers" in result


@pytest.mark.asyncio
async def test_get_industry_detail() -> None:
    """get_industry_detail returns key-value detail with children table."""
    ctx = _make_ctx()
    data = MagicMock()
    data.naics_code = "5112"
    data.title = "Software Publishers"
    data.level = 4
    data.parent_naics = "511"
    data.has_ces_data = True
    data.has_qcew_data = True
    data.has_oews_data = False
    child = MagicMock()
    child.naics_code = "51121"
    child.title = "Software Publishers (5-digit)"
    child.level = 5
    data.children = [child]
    _app(ctx).client.bls.industry = AsyncMock(return_value=_make_data_response(data))

    result = await get_industry_detail("5112", ctx)

    assert "Software Publishers (NAICS 5112)" in result
    assert "CES Data:" in result
    assert "Yes" in result
    assert "Child Industries:" in result
    assert "51121" in result


@pytest.mark.asyncio
async def test_get_industry_employment_latest() -> None:
    """get_industry_employment without date range returns latest with YoY."""
    ctx = _make_ctx()
    data = MagicMock()
    data.period = "2024-06"
    data.all_employees_thousands = 1895.3
    data.employment_yoy_pct = 2.1
    data.avg_hourly_earnings = 45.50
    data.earnings_yoy_pct = 3.8
    data.avg_weekly_hours = 38.2
    _app(ctx).client.bls.employment_latest = AsyncMock(return_value=_make_data_response(data))

    result = await get_industry_employment("5112", ctx)

    assert "NAICS 5112" in result
    assert "2024-06" in result
    assert "+2.1%" in result
    assert "$45.50" in result
    assert "CES" in result


@pytest.mark.asyncio
async def test_get_industry_employment_series() -> None:
    """get_industry_employment with date range returns table format."""
    ctx = _make_ctx()
    items = [
        _make_employment_point(
            period="2024-01", all_employees_thousands=1880.0, employment_yoy_pct=1.8, avg_hourly_earnings=44.20
        ),
        _make_employment_point(
            period="2024-06", all_employees_thousands=1895.3, employment_yoy_pct=2.1, avg_hourly_earnings=45.50
        ),
    ]
    resp = _make_paginated_response(items)
    _app(ctx).client.bls.employment = AsyncMock(return_value=resp)

    result = await get_industry_employment("5112", ctx, from_date="2024-01", to_date="2024-06")

    assert "2 observations" in result
    assert "2024-01" in result
    assert "Period" in result


# --- Counties ---


@pytest.mark.asyncio
async def test_get_county_employment() -> None:
    """get_county_employment returns table with employment columns."""
    ctx = _make_ctx()
    items = [
        _make_county_employment(
            year=2024,
            quarter=1,
            month1_employment=345000,
            month2_employment=347000,
            month3_employment=350000,
            employment_yoy_pct=2.5,
            establishment_count=12500,
        ),
    ]
    resp = _make_paginated_response(items)
    _app(ctx).client.bls.county_employment = AsyncMock(return_value=resp)

    result = await get_county_employment("12086", ctx)

    assert "FIPS 12086" in result
    assert "2024" in result
    assert "Month 1" in result
    assert "QCEW" in result


@pytest.mark.asyncio
async def test_get_county_wages() -> None:
    """get_county_wages returns key-value format with location quotients."""
    ctx = _make_ctx()
    data = MagicMock()
    data.area_fips = "12086"
    data.ownership = "Private"
    data.industry_code = "10"
    data.avg_weekly_wage = 1250
    data.total_quarterly_wages = 45000000000
    data.wage_yoy_pct = 3.2
    data.location_quotient_employment = 1.15
    data.location_quotient_wages = 0.98
    data.location_quotient_establishments = 1.05
    _app(ctx).client.bls.county_wages = AsyncMock(return_value=_make_data_response(data))

    result = await get_county_wages("12086", ctx)

    assert "FIPS 12086" in result
    assert "3.2%" in result
    assert "1.15" in result
    assert "Location quotient > 1.0" in result


# --- Occupations ---


@pytest.mark.asyncio
async def test_search_occupations() -> None:
    """search_occupations returns table with SOC codes."""
    ctx = _make_ctx()
    items = [
        _make_occupation_summary("15-1252", "Software Developers", "Computer and Mathematical"),
        _make_occupation_summary("15-1253", "Software Quality Assurance Analysts", "Computer and Mathematical"),
    ]
    resp = _make_paginated_response(items)
    _app(ctx).client.bls.occupations = AsyncMock(return_value=resp)

    result = await search_occupations(ctx, query="software")

    assert "15-1252" in result
    assert "Software Developers" in result
    assert "SOC" in result
    assert "software" in result


@pytest.mark.asyncio
async def test_get_occupation_wages() -> None:
    """get_occupation_wages returns wage data with percentiles formatted as currency."""
    ctx = _make_ctx()
    items = [
        _make_occupation_wages(
            soc_code="15-1252",
            area_name="National",
            mean_annual_wage=132270,
            mean_hourly_wage=63.59,
            median_annual_wage=127260,
            median_hourly_wage=61.18,
            pct10_hourly=35.50,
            pct25_hourly=48.20,
            pct75_hourly=78.90,
            pct90_hourly=98.30,
        )
    ]
    resp = _make_paginated_response(items)
    _app(ctx).client.bls.occupation_wages = AsyncMock(return_value=resp)

    result = await get_occupation_wages("15-1252", ctx)

    assert "SOC 15-1252" in result
    assert "National" in result
    assert "$63.59" in result
    assert "Percentiles" in result
    assert "$35.50" in result
    assert "OEWS" in result


# --- Metrics ---


@pytest.mark.asyncio
async def test_explore_bls_metrics() -> None:
    """explore_bls_metrics returns filtered table of metrics."""
    ctx = _make_ctx()
    items = [
        _make_metric_summary(
            canonical_name="all_employees_thousands",
            display_name="All Employees (Thousands)",
            category="employment",
            source_dataset="ces",
        ),
        _make_metric_summary(
            canonical_name="avg_hourly_earnings",
            display_name="Average Hourly Earnings",
            category="wages",
            source_dataset="ces",
        ),
    ]
    resp = _make_paginated_response(items)
    _app(ctx).client.bls.metrics = AsyncMock(return_value=resp)

    result = await explore_bls_metrics(ctx, category="employment")

    assert "all_employees_thousands" in result
    assert "employment" in result
    assert "ces" in result
    assert "Metric" in result


# --- Edge cases ---


@pytest.mark.asyncio
async def test_fips_zero_padding() -> None:
    """get_county_employment zero-pads 4-digit FIPS to 5 digits."""
    ctx = _make_ctx()
    items = [
        _make_county_employment(
            year=2024,
            quarter=1,
            month1_employment=1000,
            month2_employment=1100,
            month3_employment=1200,
            employment_yoy_pct=1.0,
            establishment_count=50,
        )
    ]
    resp = _make_paginated_response(items)
    _app(ctx).client.bls.county_employment = AsyncMock(return_value=resp)

    await get_county_employment("1234", ctx)

    call_args = _app(ctx).client.bls.county_employment.call_args
    assert call_args[0][0] == "01234"


@pytest.mark.asyncio
async def test_soc_normalization() -> None:
    """get_occupation_wages inserts hyphen in SOC code without one."""
    ctx = _make_ctx()
    items = [
        _make_occupation_wages(
            soc_code="15-1252",
            area_name="National",
            mean_annual_wage=132270,
            mean_hourly_wage=63.59,
            median_annual_wage=127260,
            median_hourly_wage=61.18,
        )
    ]
    resp = _make_paginated_response(items)
    _app(ctx).client.bls.occupation_wages = AsyncMock(return_value=resp)

    await get_occupation_wages("151252", ctx)

    call_args = _app(ctx).client.bls.occupation_wages.call_args
    assert call_args[0][0] == "15-1252"


@pytest.mark.asyncio
async def test_empty_results() -> None:
    """search_industries with empty data returns human-readable message."""
    ctx = _make_ctx()
    resp = _make_paginated_response([])
    _app(ctx).client.bls.industries = AsyncMock(return_value=resp)

    result = await search_industries(ctx, query="xyznonexistent")

    assert "No industries found" in result
    assert "xyznonexistent" in result
