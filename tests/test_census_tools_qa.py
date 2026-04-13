"""QA tests for Census Bureau MCP tools (MCP-17).

Independent test suite written from the spec — does NOT look at dev implementation.
Spec: gov-data-docs/mcp/prompts/MCP-17-census-tools.md
"""

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

# --- Helpers (copied verbatim from test_bls_tools.py:74-84 pattern) ---


def _make_ctx() -> MagicMock:
    """Create a mock MCP context."""
    app = MagicMock()
    app.client = MagicMock()
    ctx = MagicMock()
    ctx.request_context.lifespan_context = app
    return ctx


def _app(ctx: MagicMock) -> Any:
    return ctx.request_context.lifespan_context


def _make_data_response(data: Any) -> MagicMock:
    resp = MagicMock()
    resp.data = data
    return resp


def _make_paginated_response(items: list[Any], total: int | None = None) -> MagicMock:
    resp = MagicMock()
    resp.data = items
    resp.pagination = MagicMock()
    resp.pagination.total = total if total is not None else len(items)
    return resp


def _make_latest_year(acs5: int | None = None, acs1: int | None = None) -> MagicMock:
    m = MagicMock()
    m.acs5 = acs5
    m.acs1 = acs1
    return m


def _make_metric_summary(
    canonical_name: str,
    display_name: str,
    category: str | None,
    unit: str = "",
    latest_year: MagicMock | None = None,
) -> MagicMock:
    m = MagicMock()
    m.canonical_name = canonical_name
    m.display_name = display_name
    m.category = category
    m.unit = unit
    m.is_computed = False
    m.notes = None
    m.latest_year = latest_year if latest_year is not None else _make_latest_year(2023, 2022)
    return m


def _make_source_variable(
    variable_code: str,
    role: str,
    dataset: str,
    valid_from: int,
    valid_to: int | None,
) -> MagicMock:
    m = MagicMock()
    m.variable_code = variable_code
    m.role = role
    m.dataset = dataset
    m.valid_from = valid_from
    m.valid_to = valid_to
    return m


def _make_metric_detail(
    canonical_name: str,
    display_name: str,
    category: str,
    unit: str,
    latest_year: MagicMock,
    source_variables: list[MagicMock],
    moe_formula_type: str | None = None,
    notes: str | None = None,
    is_computed: bool = False,
) -> MagicMock:
    m = MagicMock()
    m.canonical_name = canonical_name
    m.display_name = display_name
    m.category = category
    m.unit = unit
    m.is_computed = is_computed
    m.moe_formula_type = moe_formula_type
    m.notes = notes
    m.latest_year = latest_year
    m.source_variables = source_variables
    return m


def _make_comparison_place(
    fips: str,
    name: str,
    value: float | None,
    moe: float | None = None,
    suppressed: bool = False,
) -> MagicMock:
    m = MagicMock()
    m.fips = fips
    m.name = name
    m.value = value
    m.moe = moe
    m.suppressed = suppressed
    return m


def _make_metric_info(
    display_name: str, unit: str | None = None, canonical_name: str = "", category: str = ""
) -> MagicMock:
    m = MagicMock()
    m.display_name = display_name
    m.unit = unit
    m.canonical_name = canonical_name
    m.category = category
    return m


def _make_comparison_data(
    metric: MagicMock,
    year: int,
    dataset: str,
    places: list[MagicMock],
) -> MagicMock:
    m = MagicMock()
    m.metric = metric
    m.year = year
    m.dataset = dataset
    m.survey_years = None
    m.places = places
    return m


def _make_geography_level(level: str, count: int) -> MagicMock:
    m = MagicMock()
    m.level = level
    m.count = count
    return m


def _make_place_summary(
    fips: str,
    name: str,
    level: str = "county",
    parent_fips: str | None = None,
    population: int | None = None,
) -> MagicMock:
    m = MagicMock()
    m.fips = fips
    m.name = name
    m.level = level
    m.parent_fips = parent_fips
    m.population = population
    return m


def _make_place_detail(
    fips: str,
    name: str,
    level: str,
    parent_fips: str | None = None,
    parent_name: str | None = None,
    population: int | None = None,
    area_sq_mi: float | None = None,
    lat: float | None = None,
    lon: float | None = None,
    children_levels: list[str] | None = None,
) -> MagicMock:
    m = MagicMock()
    m.fips = fips
    m.name = name
    m.level = level
    m.parent_fips = parent_fips
    m.parent_name = parent_name
    m.population = population
    m.area_sq_mi = area_sq_mi
    m.lat = lat
    m.lon = lon
    m.children_levels = children_levels if children_levels is not None else []
    return m


def _make_metric_value(
    canonical_name: str,
    display_name: str,
    category: str | None,
    value: float | None,
    unit: str = "",
    moe: float | None = None,
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


def _make_place_metrics(
    fips: str,
    name: str,
    level: str,
    year: int,
    dataset: str,
    metrics: list[MagicMock],
) -> MagicMock:
    m = MagicMock()
    m.fips = fips
    m.name = name
    m.level = level
    m.year = year
    m.dataset = dataset
    m.survey_years = None
    m.metrics = metrics
    return m


def _make_time_series_point(
    year: int,
    value: float | None,
    moe: float | None = None,
    suppressed: bool = False,
) -> MagicMock:
    m = MagicMock()
    m.year = year
    m.value = value
    m.moe = moe
    m.suppressed = suppressed
    m.survey_years = None
    return m


def _make_time_series(
    fips: str,
    name: str,
    metric: MagicMock,
    dataset: str,
    series: list[MagicMock],
) -> MagicMock:
    m = MagicMock()
    m.fips = fips
    m.name = name
    m.metric = metric
    m.dataset = dataset
    m.series = series
    return m


def _make_parent_info(fips: str, name: str, level: str) -> MagicMock:
    m = MagicMock()
    m.fips = fips
    m.name = name
    m.level = level
    return m


def _make_breakdown_data(
    parent: MagicMock,
    metric: MagicMock,
    child_level: str,
    year: int,
    dataset: str,
    places: list[MagicMock],
) -> MagicMock:
    m = MagicMock()
    m.parent = parent
    m.metric = metric
    m.child_level = child_level
    m.year = year
    m.dataset = dataset
    m.survey_years = None
    m.places = places
    return m


# =============================================================================
# Tests — Metrics module
# =============================================================================


@pytest.mark.asyncio
async def test_explore_census_metrics() -> None:
    """Test 1: mock 3 MetricSummary rows with latest_year acs5=2023, acs1=2022."""
    ctx = _make_ctx()
    ly = _make_latest_year(2023, 2022)
    items = [
        _make_metric_summary("median_household_income", "Median Household Income", "economy", "USD", ly),
        _make_metric_summary("total_population", "Total Population", "demographics", "count", ly),
        _make_metric_summary("median_age", "Median Age", "demographics", "years", ly),
    ]
    _app(ctx).client.census.metrics = AsyncMock(return_value=_make_data_response(items))

    result = await explore_census_metrics(ctx)

    assert "median_household_income" in result
    assert "total_population" in result
    assert "median_age" in result
    assert "Source: US Census Bureau." in result


@pytest.mark.asyncio
async def test_explore_census_metrics_query_filter() -> None:
    """Test 2: query='income' returns only matching rows."""
    ctx = _make_ctx()
    ly = _make_latest_year(2023, 2022)
    items = [
        _make_metric_summary("median_household_income", "Median Household Income", "economy", "USD", ly),
        _make_metric_summary("per_capita_income", "Per Capita Income", "economy", "USD", ly),
        _make_metric_summary("total_population", "Total Population", "demographics", "count", ly),
        _make_metric_summary("median_age", "Median Age", "demographics", "years", ly),
        _make_metric_summary("unemployment_rate", "Unemployment Rate", "economy", "pct", ly),
    ]
    _app(ctx).client.census.metrics = AsyncMock(return_value=_make_data_response(items))

    result = await explore_census_metrics(ctx, query="income")

    assert "median_household_income" in result
    assert "per_capita_income" in result
    assert "total_population" not in result
    assert "median_age" not in result
    assert "unemployment_rate" not in result


@pytest.mark.asyncio
async def test_explore_census_metrics_none_category_guard() -> None:
    """Test 3: None category row must not crash, and must be excluded when filtering."""
    ctx = _make_ctx()
    ly = _make_latest_year(2023, 2022)
    items = [
        _make_metric_summary("total_population", "Total Population", "demographics", "count", ly),
        _make_metric_summary("mystery_metric", "Mystery Metric", None, "count", ly),
    ]
    _app(ctx).client.census.metrics = AsyncMock(return_value=_make_data_response(items))

    # Should not raise — proves (d.category or "").lower() guard
    result = await explore_census_metrics(ctx, category="demographics")

    assert "total_population" in result
    assert "mystery_metric" not in result


@pytest.mark.asyncio
async def test_explore_census_metrics_truncates_at_50() -> None:
    """Test 4: 100 metrics, no filter — output must contain 'Showing 50 of 100'."""
    ctx = _make_ctx()
    ly = _make_latest_year(2023, 2022)
    items = [
        _make_metric_summary(f"metric_{i:03d}", f"Metric {i:03d}", "demographics", "count", ly) for i in range(100)
    ]
    _app(ctx).client.census.metrics = AsyncMock(return_value=_make_data_response(items))

    result = await explore_census_metrics(ctx)

    assert "Showing 50 of 100" in result


@pytest.mark.asyncio
async def test_get_census_metric_detail() -> None:
    """Test 5: asserts '2023 (acs5)', 'B19013_001E', 'role: numerator', '2012-present'."""
    ctx = _make_ctx()
    ly = _make_latest_year(acs5=2023, acs1=None)
    sv = _make_source_variable("B19013_001E", "numerator", "acs5", 2012, None)
    data = _make_metric_detail(
        canonical_name="median_household_income",
        display_name="Median Household Income",
        category="economy",
        unit="USD",
        latest_year=ly,
        source_variables=[sv],
        moe_formula_type="direct",
        notes=None,
    )
    _app(ctx).client.census.metric = AsyncMock(return_value=_make_data_response(data))

    result = await get_census_metric_detail("median_household_income", ctx)

    assert "2023 (acs5)" in result
    assert "B19013_001E" in result
    assert "role: numerator" in result
    assert "2012-present" in result


@pytest.mark.asyncio
async def test_compare_census_metric() -> None:
    """Test 6: header uses data.metric.display_name (not str(data.metric))."""
    ctx = _make_ctx()
    metric_info = _make_metric_info(display_name="Population", unit=None)
    places = [
        _make_comparison_place("06", "California", 39_000_000, moe=None),
        _make_comparison_place("36", "New York", 19_000_000, moe=None),
    ]
    data = _make_comparison_data(metric=metric_info, year=2023, dataset="acs5", places=places)
    compare_mock = AsyncMock(return_value=_make_data_response(data))
    _app(ctx).client.census.compare = compare_mock

    result = await compare_census_metric("population", ["06", "36"], ctx)

    assert "Population" in result
    assert "California" in result
    assert "New York" in result
    # Must NOT contain a MagicMock repr leaking
    assert "MagicMock" not in result

    # Called with fips=["06","36"], dataset=None, year=None
    call_kwargs = compare_mock.call_args.kwargs
    assert call_kwargs.get("fips") == ["06", "36"]
    assert call_kwargs.get("dataset") is None
    assert call_kwargs.get("year") is None


@pytest.mark.asyncio
async def test_compare_census_metric_rejects_single_fips() -> None:
    """Test 7: single FIPS — SDK not called, guard message returned."""
    ctx = _make_ctx()
    compare_mock = AsyncMock()
    _app(ctx).client.census.compare = compare_mock

    result = await compare_census_metric("population", ["06"], ctx)

    compare_mock.assert_not_called()
    assert "requires at least 2" in result


@pytest.mark.asyncio
async def test_compare_census_metric_rejects_over_25() -> None:
    """Test 8: 26 FIPS — SDK not called, 'at most 25' message returned."""
    ctx = _make_ctx()
    compare_mock = AsyncMock()
    _app(ctx).client.census.compare = compare_mock

    fips = [str(i).zfill(2) for i in range(26)]
    result = await compare_census_metric("population", fips, ctx)

    compare_mock.assert_not_called()
    assert "at most 25" in result


@pytest.mark.asyncio
async def test_compare_census_metric_dedupes_fips() -> None:
    """Test 9: ['06','06','36'] deduped to ['06','36'] before SDK call (order preserved)."""
    ctx = _make_ctx()
    metric_info = _make_metric_info(display_name="Population", unit=None)
    places = [
        _make_comparison_place("06", "California", 39_000_000),
        _make_comparison_place("36", "New York", 19_000_000),
    ]
    data = _make_comparison_data(metric=metric_info, year=2023, dataset="acs5", places=places)
    compare_mock = AsyncMock(return_value=_make_data_response(data))
    _app(ctx).client.census.compare = compare_mock

    await compare_census_metric("population", ["06", "06", "36"], ctx)

    call_kwargs = compare_mock.call_args.kwargs
    assert call_kwargs.get("fips") == ["06", "36"]


@pytest.mark.asyncio
async def test_compare_census_metric_handles_suppressed() -> None:
    """Test 10: suppressed place renders '(suppressed)' and is NOT dropped."""
    ctx = _make_ctx()
    metric_info = _make_metric_info(display_name="Median Household Income", unit="USD")
    places = [
        _make_comparison_place("06", "California", 85_000, moe=500),
        _make_comparison_place("36", "New York", None, moe=None, suppressed=True),
    ]
    data = _make_comparison_data(metric=metric_info, year=2023, dataset="acs5", places=places)
    _app(ctx).client.census.compare = AsyncMock(return_value=_make_data_response(data))

    result = await compare_census_metric("median_household_income", ["06", "36"], ctx)

    assert "(suppressed)" in result
    assert "New York" in result
    assert "California" in result


# =============================================================================
# Tests — Geographies module
# =============================================================================


@pytest.mark.asyncio
async def test_explore_census_geographies() -> None:
    """Test 11: 3 GeographyLevel rows, table + hint line."""
    ctx = _make_ctx()
    items = [
        _make_geography_level("state", 52),
        _make_geography_level("county", 3221),
        _make_geography_level("place", 29573),
    ]
    _app(ctx).client.census.geographies = AsyncMock(return_value=_make_data_response(items))

    result = await explore_census_geographies(ctx)

    assert "state" in result
    assert "county" in result
    assert "place" in result
    assert "52" in result
    # format_number with decimals=0 abbreviates: 3221 -> "3K", 29573 -> "30K"
    assert "3K" in result
    assert "30K" in result
    assert "search_census_places" in result
    assert "Source: US Census Bureau." in result


@pytest.mark.asyncio
async def test_search_census_places_with_filter() -> None:
    """Test 12: query='angeles' returns only matching. Header does not claim 'total across all pages'."""
    ctx = _make_ctx()
    items = [
        _make_place_summary("06037", "Los Angeles County", "county", "06", 10_000_000),
        _make_place_summary("06073", "San Diego County", "county", "06", 3_300_000),
        _make_place_summary("06075", "San Francisco County", "county", "06", 870_000),
        _make_place_summary("06001", "Alameda County", "county", "06", 1_650_000),
        _make_place_summary("06085", "Santa Clara County", "county", "06", 1_930_000),
    ]
    _app(ctx).client.census.geography = AsyncMock(return_value=_make_data_response(items))

    result = await search_census_places("county", ctx, query="angeles")

    assert "Los Angeles County" in result
    assert "San Diego County" not in result
    assert "San Francisco County" not in result
    assert "total across all pages" not in result.lower()


@pytest.mark.asyncio
async def test_search_census_places_empty() -> None:
    """Test 13: empty data list — human-readable empty message (not empty table)."""
    ctx = _make_ctx()
    _app(ctx).client.census.geography = AsyncMock(return_value=_make_data_response([]))

    result = await search_census_places("county", ctx)

    # Human-readable message, not empty table
    assert "No" in result or "no " in result.lower()


@pytest.mark.asyncio
async def test_get_census_place() -> None:
    """Test 14: PlaceDetail with children_levels — assert coordinates, population, child levels."""
    ctx = _make_ctx()
    data = _make_place_detail(
        fips="06037",
        name="Los Angeles County",
        level="county",
        parent_fips="06",
        parent_name="California",
        population=10_014_009,
        area_sq_mi=4751.0,
        lat=34.05,
        lon=-118.24,
        children_levels=["tract", "blockgroup"],
    )
    _app(ctx).client.census.geography_places = AsyncMock(return_value=_make_data_response(data))

    result = await get_census_place("county", "06037", ctx)

    assert "Los Angeles County" in result
    # format_number with decimals=0 abbreviates: 10,014,009 -> "10M"
    assert "10M" in result
    assert "34.05" in result
    assert "-118.24" in result
    assert "Child levels: tract, blockgroup" in result


# =============================================================================
# Tests — Places module
# =============================================================================


@pytest.mark.asyncio
async def test_get_census_place_metrics_grouped_by_category() -> None:
    """Test 15: 4 metrics: demographics, economy, None→Other, housing. Sorted alpha, Other last."""
    ctx = _make_ctx()
    metrics = [
        _make_metric_value("total_population", "Total Population", "demographics", 10_000_000, unit="count"),
        _make_metric_value("median_household_income", "Median Household Income", "economy", 85_000, unit="USD"),
        _make_metric_value("mystery_metric", "Mystery Metric", None, 42, unit="count"),
        _make_metric_value("median_home_value", "Median Home Value", "housing", 750_000, unit="USD"),
    ]
    data = _make_place_metrics(
        fips="06037",
        name="Los Angeles County",
        level="county",
        year=2023,
        dataset="acs5",
        metrics=metrics,
    )
    _app(ctx).client.census.place = AsyncMock(return_value=_make_data_response(data))

    result = await get_census_place_metrics("06037", ctx)

    # All four sections present
    assert "demographics" in result
    assert "economy" in result
    assert "housing" in result
    assert "Other" in result

    # Order: demographics, economy, housing, Other (last)
    idx_demo = result.find("demographics")
    idx_econ = result.find("economy")
    idx_hous = result.find("housing")
    idx_other = result.find("Other")
    assert idx_demo < idx_econ < idx_hous < idx_other

    # None-category metric should appear under Other
    idx_mystery = result.find("Mystery Metric")
    assert idx_mystery > idx_other


@pytest.mark.asyncio
async def test_get_census_place_metric_series() -> None:
    """Test 16: TimeSeries with USD unit, suppressed row must render '(suppressed)', non-suppressed USD-formatted."""
    ctx = _make_ctx()
    metric_info = _make_metric_info(display_name="Median Household Income", unit="USD")
    series = [
        _make_time_series_point(year=2021, value=76000, moe=500, suppressed=False),
        _make_time_series_point(year=2022, value=None, moe=None, suppressed=True),
    ]
    data = _make_time_series(
        fips="06037",
        name="Los Angeles County",
        metric=metric_info,
        dataset="acs5",
        series=series,
    )
    _app(ctx).client.census.place_metric = AsyncMock(return_value=_make_data_response(data))

    result = await get_census_place_metric_series("06037", "median_household_income", ctx)

    assert "Median Household Income" in result
    assert "Los Angeles County" in result
    assert "2021" in result
    assert "2022" in result
    assert "(suppressed)" in result
    # USD format via format_currency(decimals=0) abbreviates: 76000 -> "$76K"
    assert "$76K" in result


@pytest.mark.asyncio
async def test_get_census_place_breakdown() -> None:
    """Test 17: BreakdownData with parent California, 3 child places — header has California and county."""
    ctx = _make_ctx()
    parent = _make_parent_info(fips="06", name="California", level="state")
    metric_info = _make_metric_info(display_name="Population", unit=None)
    places = [
        _make_comparison_place("06037", "Los Angeles County", 10_000_000),
        _make_comparison_place("06073", "San Diego County", 3_300_000),
        _make_comparison_place("06001", "Alameda County", 1_650_000),
    ]
    data = _make_breakdown_data(
        parent=parent,
        metric=metric_info,
        child_level="county",
        year=2023,
        dataset="acs5",
        places=places,
    )
    breakdown_mock = AsyncMock(return_value=_make_data_response(data))
    _app(ctx).client.census.breakdown = breakdown_mock

    result = await get_census_place_breakdown("06", "population", ctx)

    assert "California" in result
    assert "county" in result
    assert "Los Angeles County" in result
    assert "San Diego County" in result
    assert "Alameda County" in result

    # Verify dataset=None, year=None passthrough
    call_kwargs = breakdown_mock.call_args.kwargs
    assert call_kwargs.get("dataset") is None
    assert call_kwargs.get("year") is None


@pytest.mark.asyncio
async def test_census_error_handling() -> None:
    """Test 18: ThesmaError raised by SDK is caught and str(e) returned."""
    ctx = _make_ctx()
    _app(ctx).client.census.metric = AsyncMock(side_effect=ThesmaError("metric not found"))

    result = await get_census_metric_detail("nonexistent_metric", ctx)

    assert "metric not found" in result
