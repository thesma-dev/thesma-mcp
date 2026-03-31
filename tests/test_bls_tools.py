"""Tests for BLS standalone tools (MCP-08)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from thesma_mcp.tools.bls_counties import get_county_employment, get_county_wages
from thesma_mcp.tools.bls_industries import get_industry_detail, get_industry_employment, search_industries
from thesma_mcp.tools.bls_metrics import explore_bls_metrics
from thesma_mcp.tools.bls_occupations import get_occupation_wages, search_occupations


def _make_ctx(response: dict[str, Any]) -> MagicMock:
    """Create a mock MCP context returning the given response."""
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=response)

    app = MagicMock()
    app.client = mock_client

    ctx = MagicMock()
    ctx.request_context.lifespan_context = app
    return ctx


def _app(ctx: MagicMock) -> Any:
    return ctx.request_context.lifespan_context


# --- Industries ---


@pytest.mark.asyncio
async def test_search_industries() -> None:
    """search_industries returns formatted table with NAICS codes and titles."""
    ctx = _make_ctx(
        {
            "data": [
                {"naics_code": "5112", "title": "Software Publishers", "level": 4},
                {"naics_code": "5111", "title": "Newspaper Publishers", "level": 4},
            ],
            "pagination": {"page": 1, "per_page": 25, "total": 2},
        }
    )
    result = await search_industries(ctx, query="publishers")

    assert "5112" in result
    assert "Software Publishers" in result
    assert "5111" in result
    assert "Newspaper Publishers" in result
    assert "NAICS" in result
    assert "publishers" in result


@pytest.mark.asyncio
async def test_search_industries_with_level() -> None:
    """search_industries with level param forwards it to the API."""
    ctx = _make_ctx(
        {
            "data": [{"naics_code": "51", "title": "Information", "level": 2}],
            "pagination": {"page": 1, "per_page": 25, "total": 1},
        }
    )
    await search_industries(ctx, level=2)

    call_args = _app(ctx).client.get.call_args
    params = call_args.kwargs.get("params", call_args[1].get("params", {}))
    assert params.get("level") == 2


@pytest.mark.asyncio
async def test_get_industry_detail() -> None:
    """get_industry_detail returns key-value detail with children table."""
    ctx = _make_ctx(
        {
            "data": {
                "naics_code": "5112",
                "title": "Software Publishers",
                "level": 4,
                "parent_naics": "511",
                "has_ces_data": True,
                "has_qcew_data": True,
                "has_oews_data": False,
                "children": [
                    {"naics_code": "51121", "title": "Software Publishers (5-digit)", "level": 5},
                ],
            }
        }
    )
    result = await get_industry_detail("5112", ctx)

    assert "Software Publishers (NAICS 5112)" in result
    assert "CES Data:" in result
    assert "Yes" in result
    assert "Child Industries:" in result
    assert "51121" in result


@pytest.mark.asyncio
async def test_get_industry_employment_latest() -> None:
    """get_industry_employment without date range returns latest with YoY."""
    ctx = _make_ctx(
        {
            "data": {
                "period": "2024-06",
                "all_employees_thousands": 1895.3,
                "employment_yoy_pct": 2.1,
                "avg_hourly_earnings": 45.50,
                "earnings_yoy_pct": 3.8,
                "avg_weekly_hours": 38.2,
            }
        }
    )
    result = await get_industry_employment("5112", ctx)

    assert "NAICS 5112" in result
    assert "2024-06" in result
    assert "+2.1%" in result
    assert "$45.50" in result
    assert "CES" in result


@pytest.mark.asyncio
async def test_get_industry_employment_series() -> None:
    """get_industry_employment with date range returns table format."""
    ctx = _make_ctx(
        {
            "data": [
                {
                    "period": "2024-01",
                    "all_employees_thousands": 1880.0,
                    "employment_yoy_pct": 1.8,
                    "avg_hourly_earnings": 44.20,
                },
                {
                    "period": "2024-06",
                    "all_employees_thousands": 1895.3,
                    "employment_yoy_pct": 2.1,
                    "avg_hourly_earnings": 45.50,
                },
            ],
            "pagination": {"page": 1, "per_page": 25, "total": 2},
        }
    )
    result = await get_industry_employment("5112", ctx, from_date="2024-01", to_date="2024-06")

    assert "2 observations" in result
    assert "2024-01" in result
    assert "2024-06" in result
    assert "Period" in result  # table header


# --- Counties ---


@pytest.mark.asyncio
async def test_get_county_employment() -> None:
    """get_county_employment returns table with employment columns."""
    ctx = _make_ctx(
        {
            "data": [
                {
                    "year": 2024,
                    "quarter": 1,
                    "month1_employment": 345000,
                    "month2_employment": 347000,
                    "month3_employment": 350000,
                    "employment_yoy_pct": 2.5,
                    "establishment_count": 12500,
                }
            ],
            "pagination": {"page": 1, "per_page": 25, "total": 1},
        }
    )
    result = await get_county_employment("12086", ctx)

    assert "FIPS 12086" in result
    assert "2024" in result
    assert "Month 1" in result  # table header
    assert "QCEW" in result

    # Verify FIPS in API path
    call_args = _app(ctx).client.get.call_args
    assert "/v1/us/bls/counties/12086/employment" in call_args[0][0]


@pytest.mark.asyncio
async def test_get_county_wages() -> None:
    """get_county_wages returns key-value format with location quotients."""
    ctx = _make_ctx(
        {
            "data": {
                "area_fips": "12086",
                "ownership": "Private",
                "industry_code": "10",
                "avg_weekly_wage": 1250,
                "total_quarterly_wages": 45000000000,
                "wage_yoy_pct": 3.2,
                "location_quotient_employment": 1.15,
                "location_quotient_wages": 0.98,
                "location_quotient_establishments": 1.05,
            }
        }
    )
    result = await get_county_wages("12086", ctx)

    assert "FIPS 12086" in result
    assert "$1K" in result or "$1,250" in result  # format_currency
    assert "3.2%" in result
    assert "1.15" in result
    assert "Location quotient > 1.0" in result


# --- Occupations ---


@pytest.mark.asyncio
async def test_search_occupations() -> None:
    """search_occupations returns table with SOC codes."""
    ctx = _make_ctx(
        {
            "data": [
                {"soc_code": "15-1252", "title": "Software Developers", "major_group": "Computer and Mathematical"},
                {
                    "soc_code": "15-1253",
                    "title": "Software Quality Assurance Analysts",
                    "major_group": "Computer and Mathematical",
                },
            ],
            "pagination": {"page": 1, "per_page": 25, "total": 2},
        }
    )
    result = await search_occupations(ctx, query="software")

    assert "15-1252" in result
    assert "Software Developers" in result
    assert "SOC" in result
    assert "software" in result


@pytest.mark.asyncio
async def test_get_occupation_wages() -> None:
    """get_occupation_wages returns wage data with percentiles formatted as currency."""
    ctx = _make_ctx(
        {
            "data": [
                {
                    "soc_code": "15-1252",
                    "area_name": "National",
                    "mean_annual_wage": 132270,
                    "mean_hourly_wage": 63.59,
                    "median_annual_wage": 127260,
                    "median_hourly_wage": 61.18,
                    "pct10_hourly": 35.50,
                    "pct25_hourly": 48.20,
                    "pct75_hourly": 78.90,
                    "pct90_hourly": 98.30,
                }
            ],
            "pagination": {"page": 1, "per_page": 25, "total": 1},
        }
    )
    result = await get_occupation_wages("15-1252", ctx)

    assert "SOC 15-1252" in result
    assert "National" in result
    assert "$132" in result  # format_currency truncates to K
    assert "$63.59" in result
    assert "Percentiles" in result
    assert "$35.50" in result  # pct10
    assert "OEWS" in result


# --- Metrics ---


@pytest.mark.asyncio
async def test_explore_bls_metrics() -> None:
    """explore_bls_metrics returns filtered table of metrics."""
    ctx = _make_ctx(
        {
            "data": [
                {
                    "canonical_name": "all_employees_thousands",
                    "display_name": "All Employees (Thousands)",
                    "category": "employment",
                    "source_dataset": "ces",
                },
                {
                    "canonical_name": "avg_hourly_earnings",
                    "display_name": "Average Hourly Earnings",
                    "category": "wages",
                    "source_dataset": "ces",
                },
            ],
            "pagination": {"page": 1, "per_page": 25, "total": 2},
        }
    )
    result = await explore_bls_metrics(ctx, category="employment")

    assert "all_employees_thousands" in result
    assert "employment" in result
    assert "ces" in result
    assert "Metric" in result  # table header


# --- Edge cases ---


@pytest.mark.asyncio
async def test_fips_zero_padding() -> None:
    """get_county_employment zero-pads 4-digit FIPS to 5 digits."""
    ctx = _make_ctx(
        {
            "data": [
                {
                    "year": 2024,
                    "quarter": 1,
                    "month1_employment": 1000,
                    "month2_employment": 1100,
                    "month3_employment": 1200,
                    "employment_yoy_pct": 1.0,
                    "establishment_count": 50,
                }
            ],
            "pagination": {"page": 1, "per_page": 25, "total": 1},
        }
    )
    await get_county_employment("1234", ctx)

    call_args = _app(ctx).client.get.call_args
    assert "/v1/us/bls/counties/01234/employment" in call_args[0][0]


@pytest.mark.asyncio
async def test_soc_normalization() -> None:
    """get_occupation_wages inserts hyphen in SOC code without one."""
    ctx = _make_ctx(
        {
            "data": [
                {
                    "soc_code": "15-1252",
                    "area_name": "National",
                    "mean_annual_wage": 132270,
                    "mean_hourly_wage": 63.59,
                    "median_annual_wage": 127260,
                    "median_hourly_wage": 61.18,
                }
            ],
            "pagination": {"page": 1, "per_page": 25, "total": 1},
        }
    )
    await get_occupation_wages("151252", ctx)

    call_args = _app(ctx).client.get.call_args
    assert "/v1/us/bls/occupations/15-1252/wages" in call_args[0][0]


@pytest.mark.asyncio
async def test_empty_results() -> None:
    """search_industries with empty data returns human-readable message."""
    ctx = _make_ctx(
        {
            "data": [],
            "pagination": {"page": 1, "per_page": 25, "total": 0, "total_pages": 0},
        }
    )
    result = await search_industries(ctx, query="xyznonexistent")

    assert "No industries found" in result
    assert "xyznonexistent" in result
