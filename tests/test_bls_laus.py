"""Tests for BLS LAUS unemployment MCP tools."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from thesma.errors import ThesmaError

from thesma_mcp.tools.bls_laus import (
    compare_county_unemployment,
    compare_state_unemployment,
    get_county_unemployment,
    get_state_unemployment,
)


def _make_county_obs(**kwargs: Any) -> MagicMock:
    """Build a mock LausCountyObservation with sensible defaults."""
    defaults: dict[str, Any] = {
        "county_fips": "06085",
        "county_name": "Santa Clara County",
        "state_fips": "06",
        "state_name": "California",
        "year": 2025,
        "month": 11,
        "period": "M11",
        "seasonal_adjustment": "not_seasonally_adjusted",
        "unemployment_rate": 4.2,
        "unemployment": 180000,
        "employment": 4100000,
        "labor_force": 4280000,
        "preliminary": True,
        "footnote_code": None,
    }
    defaults.update(kwargs)
    m = MagicMock()
    for k, v in defaults.items():
        setattr(m, k, v)
    return m


def _make_state_obs(**kwargs: Any) -> MagicMock:
    """Build a mock LausStateObservation with sensible defaults."""
    defaults: dict[str, Any] = {
        "state_fips": "06",
        "state_name": "California",
        "year": 2025,
        "month": 11,
        "period": "M11",
        "seasonal_adjustment": "seasonally_adjusted",
        "unemployment_rate": 5.3,
        "unemployment": 1000000,
        "employment": 18500000,
        "labor_force": 19500000,
        "employment_population_ratio": 60.5,
        "labor_force_participation_rate": 63.7,
        "civilian_noninstitutional_population": 30600000,
        "preliminary": True,
        "footnote_code": None,
    }
    defaults.update(kwargs)
    m = MagicMock()
    for k, v in defaults.items():
        setattr(m, k, v)
    return m


def _make_county_compare_item(**kwargs: Any) -> MagicMock:
    defaults: dict[str, Any] = {
        "county_fips": "06085",
        "county_name": "Santa Clara County",
        "unemployment_rate": 4.2,
        "unemployment": 180000,
        "employment": 4100000,
        "labor_force": 4280000,
    }
    defaults.update(kwargs)
    m = MagicMock()
    for k, v in defaults.items():
        setattr(m, k, v)
    return m


def _make_state_compare_item(**kwargs: Any) -> MagicMock:
    defaults: dict[str, Any] = {
        "state_fips": "06",
        "state_name": "California",
        "unemployment_rate": 5.3,
        "unemployment": 1000000,
        "employment": 18500000,
        "labor_force": 19500000,
        "employment_population_ratio": 60.5,
        "labor_force_participation_rate": 63.7,
        "civilian_noninstitutional_population": 30600000,
    }
    defaults.update(kwargs)
    m = MagicMock()
    for k, v in defaults.items():
        setattr(m, k, v)
    return m


def _make_compare_response(
    items: list[Any],
    *,
    year: int = 2025,
    month: int = 11,
    adjustment: str = "not_seasonally_adjusted",
    national_rate: float | None = 4.0,
    errors: list[Any] | None = None,
) -> MagicMock:
    resp = MagicMock()
    resp.data = items
    resp.year = year
    resp.month = month
    resp.seasonal_adjustment = adjustment
    resp.national_unemployment_rate = national_rate
    resp.errors = errors
    return resp


def _make_compare_error(fips: str, message: str) -> MagicMock:
    err = MagicMock()
    err.fips = fips
    err.message = message
    return err


def _make_paginated_response(items: list[Any], total: int | None = None) -> MagicMock:
    resp = MagicMock()
    resp.data = items
    resp.pagination = MagicMock()
    resp.pagination.total = total if total is not None else len(items)
    return resp


def _make_ctx() -> MagicMock:
    """Create a mock MCP context."""
    app = MagicMock()
    app.client = MagicMock()
    ctx = MagicMock()
    ctx.request_context.lifespan_context = app
    return ctx


def _app(ctx: MagicMock) -> Any:
    return ctx.request_context.lifespan_context


# --- get_county_unemployment ---


class TestGetCountyUnemployment:
    @pytest.mark.asyncio
    async def test_latest_default(self) -> None:
        """No dates returns latest observation via per_page=1."""
        ctx = _make_ctx()
        mock_call = AsyncMock(return_value=_make_paginated_response([_make_county_obs()]))
        _app(ctx).client.bls.county_unemployment = mock_call

        result = await get_county_unemployment("06085", ctx)

        assert "Santa Clara County" in result
        assert "California" in result
        assert "FIPS 06085" in result
        assert "4.2%" in result
        # Verify per_page=1 was passed and no date filters
        kwargs = mock_call.await_args.kwargs
        assert kwargs.get("per_page") == 1
        assert "from_date" not in kwargs
        assert "to_date" not in kwargs

    @pytest.mark.asyncio
    async def test_time_series(self) -> None:
        """Both dates returns a table including period strings."""
        ctx = _make_ctx()
        rows = [
            _make_county_obs(year=2025, month=11, period="M11"),
            _make_county_obs(year=2025, month=10, period="M10", unemployment_rate=4.0),
        ]
        mock_call = AsyncMock(return_value=_make_paginated_response(rows))
        _app(ctx).client.bls.county_unemployment = mock_call

        result = await get_county_unemployment("06085", ctx, from_date="2025-10", to_date="2025-11")

        assert "2025-11" in result
        assert "2025-10" in result
        kwargs = mock_call.await_args.kwargs
        assert kwargs["from_date"] == "2025-10"
        assert kwargs["to_date"] == "2025-11"

    @pytest.mark.asyncio
    async def test_annual_only(self) -> None:
        """annual_only=True forwards param and renders 'YYYY (annual)' for M13 rows."""
        ctx = _make_ctx()
        rows = [_make_county_obs(year=2024, month=13, period="M13", unemployment_rate=4.5)]
        mock_call = AsyncMock(return_value=_make_paginated_response(rows))
        _app(ctx).client.bls.county_unemployment = mock_call

        result = await get_county_unemployment("06085", ctx, from_date="2024-01", to_date="2024-12", annual_only=True)

        assert "2024 (annual)" in result
        kwargs = mock_call.await_args.kwargs
        assert kwargs["annual_only"] is True

    @pytest.mark.asyncio
    async def test_half_date_returns_error(self) -> None:
        ctx = _make_ctx()
        result = await get_county_unemployment("06085", ctx, from_date="2025-01")
        assert "Both from_date and to_date are required" in result

    @pytest.mark.asyncio
    async def test_not_found(self) -> None:
        ctx = _make_ctx()
        _app(ctx).client.bls.county_unemployment = AsyncMock(side_effect=ThesmaError("County FIPS 99999 not found"))
        result = await get_county_unemployment("99999", ctx)
        assert "99999" in result

    @pytest.mark.asyncio
    async def test_zero_pad_fips(self) -> None:
        """Input '6085' gets zfilled to '06085' before SDK call."""
        ctx = _make_ctx()
        mock_call = AsyncMock(return_value=_make_paginated_response([_make_county_obs()]))
        _app(ctx).client.bls.county_unemployment = mock_call
        await get_county_unemployment("6085", ctx)
        args = mock_call.await_args.args
        assert args[0] == "06085"

    @pytest.mark.asyncio
    async def test_empty_time_series(self) -> None:
        """Empty data list returns 'No LAUS data available' message."""
        ctx = _make_ctx()
        _app(ctx).client.bls.county_unemployment = AsyncMock(return_value=_make_paginated_response([]))
        result = await get_county_unemployment("06085", ctx, from_date="2025-10", to_date="2025-11")
        assert "No LAUS data available" in result
        assert "06085" in result

    @pytest.mark.asyncio
    async def test_empty_latest(self) -> None:
        """Empty data list on latest returns the no-data message."""
        ctx = _make_ctx()
        _app(ctx).client.bls.county_unemployment = AsyncMock(return_value=_make_paginated_response([]))
        result = await get_county_unemployment("06085", ctx)
        assert "No LAUS data available" in result


# --- compare_county_unemployment ---


class TestCompareCountyUnemployment:
    @pytest.mark.asyncio
    async def test_compare_default_period(self) -> None:
        ctx = _make_ctx()
        items = [
            _make_county_compare_item(county_fips="06085", county_name="Santa Clara County"),
            _make_county_compare_item(
                county_fips="48201",
                county_name="Harris County",
                unemployment_rate=3.9,
            ),
        ]
        mock_call = AsyncMock(return_value=_make_compare_response(items))
        _app(ctx).client.bls.county_unemployment_compare = mock_call

        result = await compare_county_unemployment("06085,48201", ctx)

        assert "Santa Clara County" in result
        assert "Harris County" in result
        # Asserts SDK called with list (not joined string), no year/month
        args = mock_call.await_args.args
        kwargs = mock_call.await_args.kwargs
        assert args[0] == ["06085", "48201"]
        assert kwargs.get("year") is None
        assert kwargs.get("month") is None

    @pytest.mark.asyncio
    async def test_compare_with_errors(self) -> None:
        ctx = _make_ctx()
        items = [
            _make_county_compare_item(county_fips="06085", county_name="Santa Clara County"),
            _make_county_compare_item(
                county_fips="48201",
                county_name="Harris County",
                unemployment_rate=3.9,
            ),
        ]
        errors = [_make_compare_error("99999", "FIPS not found")]
        _app(ctx).client.bls.county_unemployment_compare = AsyncMock(
            return_value=_make_compare_response(items, errors=errors)
        )
        result = await compare_county_unemployment("06085,48201,99999", ctx)
        assert "Errors:" in result
        assert "99999" in result
        assert "FIPS not found" in result

    @pytest.mark.asyncio
    async def test_compare_null_national_rate(self) -> None:
        ctx = _make_ctx()
        items = [_make_county_compare_item()]
        _app(ctx).client.bls.county_unemployment_compare = AsyncMock(
            return_value=_make_compare_response(items, national_rate=None)
        )
        result = await compare_county_unemployment("06085", ctx)
        assert "National unemployment rate: N/A" in result

    @pytest.mark.asyncio
    async def test_compare_half_period(self) -> None:
        ctx = _make_ctx()
        mock_call = AsyncMock()
        _app(ctx).client.bls.county_unemployment_compare = mock_call
        result = await compare_county_unemployment("06085", ctx, year=2024)
        assert "Both year and month must be provided together" in result
        mock_call.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_compare_empty_fips(self) -> None:
        ctx = _make_ctx()
        mock_call = AsyncMock()
        _app(ctx).client.bls.county_unemployment_compare = mock_call
        result = await compare_county_unemployment("", ctx)
        assert "requires at least one FIPS code" in result
        mock_call.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_compare_only_whitespace_fips(self) -> None:
        ctx = _make_ctx()
        mock_call = AsyncMock()
        _app(ctx).client.bls.county_unemployment_compare = mock_call
        result = await compare_county_unemployment("  ,  ", ctx)
        assert "requires at least one FIPS code" in result
        mock_call.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_compare_too_many_fips(self) -> None:
        ctx = _make_ctx()
        mock_call = AsyncMock()
        _app(ctx).client.bls.county_unemployment_compare = mock_call
        eleven = ",".join(f"0608{i}" for i in range(1, 12))  # 11 entries
        result = await compare_county_unemployment(eleven, ctx)
        assert "at most 10" in result
        mock_call.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_compare_whitespace_trim(self) -> None:
        ctx = _make_ctx()
        mock_call = AsyncMock(return_value=_make_compare_response([_make_county_compare_item()]))
        _app(ctx).client.bls.county_unemployment_compare = mock_call
        await compare_county_unemployment("06085, 48201 , 17031", ctx)
        args = mock_call.await_args.args
        assert args[0] == ["06085", "48201", "17031"]

    @pytest.mark.asyncio
    async def test_compare_annual_month(self) -> None:
        ctx = _make_ctx()
        items = [_make_county_compare_item()]
        _app(ctx).client.bls.county_unemployment_compare = AsyncMock(
            return_value=_make_compare_response(items, year=2024, month=13)
        )
        result = await compare_county_unemployment("06085", ctx)
        assert "2024 (annual)" in result


# --- get_state_unemployment ---


class TestGetStateUnemployment:
    @pytest.mark.asyncio
    async def test_state_latest(self) -> None:
        """Default adjustment 'sa', per_page=1."""
        ctx = _make_ctx()
        mock_call = AsyncMock(return_value=_make_paginated_response([_make_state_obs()]))
        _app(ctx).client.bls.state_unemployment = mock_call
        result = await get_state_unemployment("06", ctx)
        assert "California" in result
        assert "FIPS 06" in result
        assert "[SA]" in result
        kwargs = mock_call.await_args.kwargs
        assert kwargs["adjustment"] == "sa"
        assert kwargs["per_page"] == 1

    @pytest.mark.asyncio
    async def test_state_nsa_adjustment(self) -> None:
        ctx = _make_ctx()
        mock_call = AsyncMock(
            return_value=_make_paginated_response([_make_state_obs(seasonal_adjustment="not_seasonally_adjusted")])
        )
        _app(ctx).client.bls.state_unemployment = mock_call
        result = await get_state_unemployment("06", ctx, adjustment="nsa")
        assert "[NSA]" in result
        kwargs = mock_call.await_args.kwargs
        assert kwargs["adjustment"] == "nsa"

    @pytest.mark.asyncio
    async def test_state_invalid_adjustment(self) -> None:
        ctx = _make_ctx()
        mock_call = AsyncMock()
        _app(ctx).client.bls.state_unemployment = mock_call
        result = await get_state_unemployment("06", ctx, adjustment="partial")
        assert "adjustment must be" in result
        mock_call.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_state_time_series_with_lfpr(self) -> None:
        ctx = _make_ctx()
        rows = [
            _make_state_obs(year=2025, month=11, period="M11"),
            _make_state_obs(year=2025, month=10, period="M10"),
        ]
        _app(ctx).client.bls.state_unemployment = AsyncMock(return_value=_make_paginated_response(rows))
        result = await get_state_unemployment("06", ctx, from_date="2025-10", to_date="2025-11")
        assert "LFPR" in result
        assert "Emp/Pop" in result
        assert "63.7%" in result

    @pytest.mark.asyncio
    async def test_state_zero_pad_fips(self) -> None:
        ctx = _make_ctx()
        mock_call = AsyncMock(return_value=_make_paginated_response([_make_state_obs()]))
        _app(ctx).client.bls.state_unemployment = mock_call
        await get_state_unemployment("6", ctx)
        args = mock_call.await_args.args
        assert args[0] == "06"

    @pytest.mark.asyncio
    async def test_half_date_returns_error(self) -> None:
        ctx = _make_ctx()
        result = await get_state_unemployment("06", ctx, from_date="2025-01")
        assert "Both from_date and to_date are required" in result


# --- compare_state_unemployment ---


class TestCompareStateUnemployment:
    @pytest.mark.asyncio
    async def test_state_compare_default(self) -> None:
        ctx = _make_ctx()
        items = [
            _make_state_compare_item(state_fips="06", state_name="California"),
            _make_state_compare_item(state_fips="48", state_name="Texas", unemployment_rate=3.9),
        ]
        mock_call = AsyncMock(return_value=_make_compare_response(items, adjustment="seasonally_adjusted"))
        _app(ctx).client.bls.state_unemployment_compare = mock_call
        result = await compare_state_unemployment("06,48", ctx)
        assert "California" in result
        assert "Texas" in result
        assert "[SA]" in result
        args = mock_call.await_args.args
        kwargs = mock_call.await_args.kwargs
        assert args[0] == ["06", "48"]
        assert kwargs["adjustment"] == "sa"

    @pytest.mark.asyncio
    async def test_state_compare_adjustment(self) -> None:
        ctx = _make_ctx()
        items = [_make_state_compare_item()]
        mock_call = AsyncMock(return_value=_make_compare_response(items, adjustment="not_seasonally_adjusted"))
        _app(ctx).client.bls.state_unemployment_compare = mock_call
        result = await compare_state_unemployment("06", ctx, adjustment="nsa")
        assert "[NSA]" in result
        kwargs = mock_call.await_args.kwargs
        assert kwargs["adjustment"] == "nsa"

    @pytest.mark.asyncio
    async def test_state_compare_invalid_adjustment(self) -> None:
        ctx = _make_ctx()
        mock_call = AsyncMock()
        _app(ctx).client.bls.state_unemployment_compare = mock_call
        result = await compare_state_unemployment("06", ctx, adjustment="weekly")
        assert "adjustment must be" in result
        mock_call.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_state_compare_too_many_fips(self) -> None:
        ctx = _make_ctx()
        mock_call = AsyncMock()
        _app(ctx).client.bls.state_unemployment_compare = mock_call
        eleven = ",".join(f"{i:02d}" for i in range(1, 12))
        result = await compare_state_unemployment(eleven, ctx)
        assert "at most 10" in result
        mock_call.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_state_compare_empty_fips(self) -> None:
        ctx = _make_ctx()
        mock_call = AsyncMock()
        _app(ctx).client.bls.state_unemployment_compare = mock_call
        result = await compare_state_unemployment("", ctx)
        assert "requires at least one FIPS code" in result
        mock_call.assert_not_awaited()
