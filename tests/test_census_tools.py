"""Tests for Census Bureau MCP tools (MCP-17)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from thesma.errors import ThesmaError

from thesma_mcp.tools.census_geographies import (
    explore_census_geographies,
    get_census_place,
    search_census_places,
)
from thesma_mcp.tools.census_metrics import (
    compare_census_metric,
    explore_census_metrics,
    get_census_metric_detail,
)
from thesma_mcp.tools.census_places import (
    get_census_place_breakdown,
    get_census_place_metric_series,
    get_census_place_metrics,
)


def _make_paginated_response(items: list[MagicMock], total: int | None = None) -> MagicMock:
    resp = MagicMock()
    resp.data = items
    resp.pagination = MagicMock()
    resp.pagination.total = total if total is not None else len(items)
    return resp


def _make_data_response(data: Any) -> MagicMock:
    resp = MagicMock()
    resp.data = data
    return resp


def _make_ctx() -> MagicMock:
    app = MagicMock()
    app.client = MagicMock()
    ctx = MagicMock()
    ctx.request_context.lifespan_context = app
    return ctx


def _app(ctx: MagicMock) -> Any:
    return ctx.request_context.lifespan_context


def _make_metric_summary(
    canonical_name: str,
    display_name: str,
    category: str | None,
    unit: str | None = "USD",
    acs5: int | None = 2023,
    acs1: int | None = 2022,
) -> MagicMock:
    m = MagicMock()
    m.canonical_name = canonical_name
    m.display_name = display_name
    m.category = category
    m.unit = unit
    m.is_computed = False
    m.notes = None
    latest_year = MagicMock()
    latest_year.acs5 = acs5
    latest_year.acs1 = acs1
    m.latest_year = latest_year
    return m


def _make_place_summary(
    fips: str, name: str, parent_fips: str | None = None, population: int | None = None
) -> MagicMock:
    m = MagicMock()
    m.fips = fips
    m.name = name
    m.level = "county"
    m.parent_fips = parent_fips
    m.population = population
    return m


def _make_metric_value(
    canonical_name: str,
    display_name: str,
    category: str | None,
    value: float | None,
    moe: float | None = None,
    unit: str | None = None,
    suppressed: bool = False,
) -> MagicMock:
    m = MagicMock()
    m.canonical_name = canonical_name
    m.display_name = display_name
    m.category = category
    m.value = value
    m.moe = moe
    m.unit = unit
    m.suppressed = suppressed
    return m


def _make_comparison_place(
    fips: str, name: str, value: float | None, moe: float | None = None, suppressed: bool = False
) -> MagicMock:
    m = MagicMock()
    m.fips = fips
    m.name = name
    m.value = value
    m.moe = moe
    m.suppressed = suppressed
    return m


# --- explore_census_metrics ---


@pytest.mark.asyncio
async def test_explore_census_metrics() -> None:
    """explore_census_metrics returns all metrics and the Census source footer."""
    ctx = _make_ctx()
    items = [
        _make_metric_summary("median_household_income", "Median Household Income", "economy"),
        _make_metric_summary("total_population", "Total Population", "demographics", unit="count"),
        _make_metric_summary("median_home_value", "Median Home Value", "housing"),
    ]
    _app(ctx).client.census.metrics = AsyncMock(return_value=_make_data_response(items))

    result = await explore_census_metrics(ctx)

    assert "median_household_income" in result
    assert "total_population" in result
    assert "median_home_value" in result
    assert "Source: US Census Bureau." in result


@pytest.mark.asyncio
async def test_explore_census_metrics_query_filter() -> None:
    """Query filter keeps only matching rows."""
    ctx = _make_ctx()
    items = [
        _make_metric_summary("median_household_income", "Median Household Income", "economy"),
        _make_metric_summary("per_capita_income", "Per Capita Income", "economy"),
        _make_metric_summary("total_population", "Total Population", "demographics"),
        _make_metric_summary("median_home_value", "Median Home Value", "housing"),
        _make_metric_summary("poverty_rate", "Poverty Rate", "economy"),
    ]
    _app(ctx).client.census.metrics = AsyncMock(return_value=_make_data_response(items))

    result = await explore_census_metrics(ctx, query="income")

    assert "median_household_income" in result
    assert "per_capita_income" in result
    assert "total_population" not in result
    assert "median_home_value" not in result
    assert "poverty_rate" not in result


@pytest.mark.asyncio
async def test_explore_census_metrics_none_category_guard() -> None:
    """Category filter safely handles rows with category=None."""
    ctx = _make_ctx()
    items = [
        _make_metric_summary("total_population", "Total Population", "demographics"),
        _make_metric_summary("broken_metric", "Broken Metric", None),
    ]
    _app(ctx).client.census.metrics = AsyncMock(return_value=_make_data_response(items))

    result = await explore_census_metrics(ctx, category="demographics")

    assert "total_population" in result
    assert "broken_metric" not in result


@pytest.mark.asyncio
async def test_explore_census_metrics_truncates_at_50() -> None:
    """explore_census_metrics truncates results to 50 and reports the total."""
    ctx = _make_ctx()
    items = [_make_metric_summary(f"metric_{i}", f"Metric {i}", "economy") for i in range(100)]
    _app(ctx).client.census.metrics = AsyncMock(return_value=_make_data_response(items))

    result = await explore_census_metrics(ctx)

    assert "Showing 50 of 100" in result


# --- get_census_metric_detail ---


@pytest.mark.asyncio
async def test_get_census_metric_detail() -> None:
    """get_census_metric_detail renders latest_year and source variables correctly."""
    ctx = _make_ctx()
    data = MagicMock()
    data.canonical_name = "median_household_income"
    data.display_name = "Median Household Income"
    data.category = "economy"
    data.unit = "USD"
    data.is_computed = False
    data.moe_formula_type = "direct"
    data.notes = None
    latest_year = MagicMock()
    latest_year.acs5 = 2023
    latest_year.acs1 = None
    data.latest_year = latest_year
    sv = MagicMock()
    sv.variable_code = "B19013_001E"
    sv.role = "numerator"
    sv.dataset = "acs5"
    sv.valid_from = 2012
    sv.valid_to = None
    data.source_variables = [sv]
    _app(ctx).client.census.metric = AsyncMock(return_value=_make_data_response(data))

    result = await get_census_metric_detail("median_household_income", ctx)

    assert "2023 (acs5)" in result
    assert "B19013_001E" in result
    assert "role: numerator" in result
    assert "2012-present" in result
    assert "Source: US Census Bureau." in result


# --- compare_census_metric ---


@pytest.mark.asyncio
async def test_compare_census_metric() -> None:
    """compare_census_metric renders header with metric display_name and both places."""
    ctx = _make_ctx()
    data = MagicMock()
    metric_info = MagicMock()
    metric_info.display_name = "Population"
    metric_info.unit = None
    data.metric = metric_info
    data.year = 2023
    data.dataset = "acs5"
    data.survey_years = None
    data.places = [
        _make_comparison_place("06", "California", 39500000),
        _make_comparison_place("36", "New York", 19500000),
    ]
    mock_compare = AsyncMock(return_value=_make_data_response(data))
    _app(ctx).client.census.compare = mock_compare

    result = await compare_census_metric("population", ["06", "36"], ctx)

    assert "Population" in result
    assert "California" in result
    assert "New York" in result
    mock_compare.assert_called_once_with("population", fips=["06", "36"], dataset=None, year=None)


@pytest.mark.asyncio
async def test_compare_census_metric_rejects_single_fips() -> None:
    """compare_census_metric rejects < 2 FIPS without calling the SDK."""
    ctx = _make_ctx()
    mock_compare = AsyncMock()
    _app(ctx).client.census.compare = mock_compare

    result = await compare_census_metric("population", ["06"], ctx)

    mock_compare.assert_not_called()
    assert "requires at least 2" in result


@pytest.mark.asyncio
async def test_compare_census_metric_rejects_over_25() -> None:
    """compare_census_metric rejects > 25 FIPS without calling the SDK."""
    ctx = _make_ctx()
    mock_compare = AsyncMock()
    _app(ctx).client.census.compare = mock_compare

    fips = [str(i).zfill(2) for i in range(26)]
    result = await compare_census_metric("population", fips, ctx)

    mock_compare.assert_not_called()
    assert "at most 25" in result


@pytest.mark.asyncio
async def test_compare_census_metric_dedupes_fips() -> None:
    """compare_census_metric dedupes the FIPS list before calling the SDK."""
    ctx = _make_ctx()
    data = MagicMock()
    metric_info = MagicMock()
    metric_info.display_name = "Population"
    metric_info.unit = None
    data.metric = metric_info
    data.year = 2023
    data.dataset = "acs5"
    data.survey_years = None
    data.places = [
        _make_comparison_place("06", "California", 39500000),
        _make_comparison_place("36", "New York", 19500000),
    ]
    mock_compare = AsyncMock(return_value=_make_data_response(data))
    _app(ctx).client.census.compare = mock_compare

    await compare_census_metric("population", ["06", "06", "36"], ctx)

    mock_compare.assert_called_once_with("population", fips=["06", "36"], dataset=None, year=None)


@pytest.mark.asyncio
async def test_compare_census_metric_handles_suppressed() -> None:
    """Suppressed rows render (suppressed) and are NOT dropped."""
    ctx = _make_ctx()
    data = MagicMock()
    metric_info = MagicMock()
    metric_info.display_name = "Population"
    metric_info.unit = None
    data.metric = metric_info
    data.year = 2023
    data.dataset = "acs5"
    data.survey_years = None
    data.places = [
        _make_comparison_place("06", "California", 39500000),
        _make_comparison_place("99", "Tiny Place", None, suppressed=True),
    ]
    _app(ctx).client.census.compare = AsyncMock(return_value=_make_data_response(data))

    result = await compare_census_metric("population", ["06", "99"], ctx)

    assert "(suppressed)" in result
    assert "Tiny Place" in result


# --- explore_census_geographies ---


@pytest.mark.asyncio
async def test_explore_census_geographies() -> None:
    """explore_census_geographies renders level/count table and a hint line."""
    ctx = _make_ctx()
    items = []
    for level, count in [("state", 52), ("county", 3220), ("place", 29500)]:
        m = MagicMock()
        m.level = level
        m.count = count
        items.append(m)
    _app(ctx).client.census.geographies = AsyncMock(return_value=_make_data_response(items))

    result = await explore_census_geographies(ctx)

    assert "state" in result
    assert "county" in result
    assert "Use search_census_places" in result
    assert "Source: US Census Bureau." in result


# --- search_census_places ---


@pytest.mark.asyncio
async def test_search_census_places_with_filter() -> None:
    """search_census_places filters by query on the returned page."""
    ctx = _make_ctx()
    items = [
        _make_place_summary("06037", "Los Angeles County", "06", 9800000),
        _make_place_summary("06059", "Orange County", "06", 3200000),
        _make_place_summary("06073", "San Diego County", "06", 3300000),
        _make_place_summary("36061", "New York County", "36", 1600000),
        _make_place_summary("12086", "Miami-Dade County", "12", 2700000),
    ]
    _app(ctx).client.census.geography = AsyncMock(return_value=_make_paginated_response(items))

    result = await search_census_places("county", ctx, query="angeles")

    assert "Los Angeles County" in result
    assert "Orange County" not in result
    assert "Miami-Dade County" not in result
    assert "total across all pages" not in result


@pytest.mark.asyncio
async def test_search_census_places_empty() -> None:
    """search_census_places returns a human-readable empty message."""
    ctx = _make_ctx()
    _app(ctx).client.census.geography = AsyncMock(return_value=_make_paginated_response([]))

    result = await search_census_places("county", ctx)

    assert "No places" in result


# --- get_census_place ---


@pytest.mark.asyncio
async def test_get_census_place() -> None:
    """get_census_place renders population, coordinates and children_levels."""
    ctx = _make_ctx()
    data = MagicMock()
    data.fips = "06037"
    data.name = "Los Angeles County"
    data.level = "county"
    data.parent_fips = "06"
    data.parent_name = "California"
    data.population = 9800000
    data.area_sq_mi = 4751.0
    data.lat = 34.05
    data.lon = -118.24
    data.children_levels = ["tract", "blockgroup"]
    _app(ctx).client.census.geography_places = AsyncMock(return_value=_make_data_response(data))

    result = await get_census_place("county", "06037", ctx)

    assert "Los Angeles County" in result
    assert "34.05" in result
    assert "-118.24" in result
    # population via format_number (decimals=0 rounds 9.8M to 10M)
    assert "10M" in result
    assert "Child levels: tract, blockgroup" in result


# --- get_census_place_metrics ---


@pytest.mark.asyncio
async def test_get_census_place_metrics_grouped_by_category() -> None:
    """get_census_place_metrics groups by category, None falls through to Other."""
    ctx = _make_ctx()
    data = MagicMock()
    data.fips = "06037"
    data.name = "Los Angeles County"
    data.level = "county"
    data.year = 2023
    data.dataset = "acs5"
    data.survey_years = None
    data.metrics = [
        _make_metric_value("total_population", "Total Population", "demographics", 9800000.0),
        _make_metric_value(
            "median_household_income",
            "Median Household Income",
            "economy",
            83000.0,
            unit="USD",
        ),
        _make_metric_value("weird_metric", "Weird Metric", None, 42.0),
        _make_metric_value("median_home_value", "Median Home Value", "housing", 800000.0, unit="USD"),
    ]
    _app(ctx).client.census.place = AsyncMock(return_value=_make_data_response(data))

    result = await get_census_place_metrics("06037", ctx)

    assert "### demographics" in result
    assert "### economy" in result
    assert "### housing" in result
    assert "### Other" in result
    # Ensure Other is last by checking positions
    idx_demo = result.index("### demographics")
    idx_econ = result.index("### economy")
    idx_hous = result.index("### housing")
    idx_other = result.index("### Other")
    assert idx_demo < idx_econ < idx_hous < idx_other
    assert "Weird Metric" in result


# --- get_census_place_metric_series ---


@pytest.mark.asyncio
async def test_get_census_place_metric_series() -> None:
    """get_census_place_metric_series renders header, USD-formatted values, and suppressed rows."""
    ctx = _make_ctx()
    data = MagicMock()
    metric_info = MagicMock()
    metric_info.display_name = "Median Household Income"
    metric_info.unit = "USD"
    data.metric = metric_info
    data.name = "Los Angeles County"
    data.fips = "06037"
    data.dataset = "acs5"
    p1 = MagicMock()
    p1.year = 2021
    p1.value = 76000
    p1.moe = 500
    p1.suppressed = False
    p1.survey_years = None
    p2 = MagicMock()
    p2.year = 2022
    p2.value = None
    p2.moe = None
    p2.suppressed = True
    p2.survey_years = None
    data.series = [p1, p2]
    _app(ctx).client.census.place_metric = AsyncMock(return_value=_make_data_response(data))

    result = await get_census_place_metric_series("06037", "median_household_income", ctx)

    assert "Median Household Income" in result
    assert "Los Angeles County" in result
    assert "2021" in result
    assert "2022" in result
    assert "(suppressed)" in result
    # format_currency with decimals=0 produces '$76.0K'
    assert "$76" in result


# --- get_census_place_breakdown ---


@pytest.mark.asyncio
async def test_get_census_place_breakdown() -> None:
    """get_census_place_breakdown renders parent name, child_level, and all rows."""
    ctx = _make_ctx()
    data = MagicMock()
    parent = MagicMock()
    parent.fips = "06"
    parent.name = "California"
    parent.level = "state"
    data.parent = parent
    metric_info = MagicMock()
    metric_info.display_name = "Population"
    metric_info.unit = None
    data.metric = metric_info
    data.child_level = "county"
    data.year = 2023
    data.dataset = "acs5"
    data.survey_years = None
    data.places = [
        _make_comparison_place("06037", "Los Angeles County", 9800000),
        _make_comparison_place("06059", "Orange County", 3200000),
        _make_comparison_place("06073", "San Diego County", 3300000),
    ]
    _app(ctx).client.census.breakdown = AsyncMock(return_value=_make_data_response(data))

    result = await get_census_place_breakdown("06", "population", ctx)

    assert "California" in result
    assert "county" in result
    assert "Los Angeles County" in result
    assert "Orange County" in result
    assert "San Diego County" in result


# --- error handling ---


@pytest.mark.asyncio
async def test_census_error_handling() -> None:
    """ThesmaError from the SDK is caught and returned as a string."""
    ctx = _make_ctx()
    _app(ctx).client.census.metric = AsyncMock(side_effect=ThesmaError("metric not found"))

    result = await get_census_metric_detail("nonexistent", ctx)

    assert result == "metric not found"
