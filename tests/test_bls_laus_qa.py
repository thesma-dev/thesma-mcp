"""QA tests for BLS LAUS unemployment MCP tools (MCP-18).

Written from spec without looking at the dev implementation.
"""

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

# --- Test helpers ---


def _make_county_obs(**kwargs: Any) -> MagicMock:
    """Create a mock LausCountyObservation with default fields."""
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
        "footnote_code": None,
        "preliminary": True,
    }
    defaults.update(kwargs)
    m = MagicMock()
    for k, v in defaults.items():
        setattr(m, k, v)
    return m


def _make_state_obs(**kwargs: Any) -> MagicMock:
    """Create a mock LausStateObservation with default fields.

    seasonal_adjustment uses the plain-string form per the spec helper instructions.
    """
    defaults: dict[str, Any] = {
        "state_fips": "06",
        "state_name": "California",
        "year": 2025,
        "month": 11,
        "period": "M11",
        "seasonal_adjustment": "seasonally_adjusted",
        "unemployment_rate": 5.1,
        "unemployment": 990000,
        "employment": 18500000,
        "labor_force": 19490000,
        "employment_population_ratio": 60.4,
        "labor_force_participation_rate": 63.7,
        "civilian_noninstitutional_population": 30600000,
        "footnote_code": None,
        "preliminary": True,
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
        "unemployment_rate": 5.1,
        "unemployment": 990000,
        "employment": 18500000,
        "labor_force": 19490000,
        "employment_population_ratio": 60.4,
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
    year: int = 2025,
    month: int = 11,
    adjustment: str = "not_seasonally_adjusted",
    national_rate: float | None = 4.0,
    errors: list[Any] | None = None,
) -> MagicMock:
    """Build a mock LausCountyComparisonResponse / LausStateComparisonResponse envelope."""
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
        """No dates: SDK called with per_page=1; output contains county+state names."""
        ctx = _make_ctx()
        mock_call = AsyncMock(return_value=_make_paginated_response([_make_county_obs()]))
        _app(ctx).client.bls.county_unemployment = mock_call
        result = await get_county_unemployment("06085", ctx)

        assert "Santa Clara County" in result
        assert "California" in result
        assert "06085" in result
        # SDK called with per_page=1, no date filters
        kwargs = mock_call.call_args.kwargs
        assert kwargs.get("per_page") == 1
        assert "from_date" not in kwargs or kwargs.get("from_date") is None
        assert "to_date" not in kwargs or kwargs.get("to_date") is None

    @pytest.mark.asyncio
    async def test_time_series(self) -> None:
        """With both dates: SDK called with date range; output is a table with M11 periods."""
        ctx = _make_ctx()
        rows = [
            _make_county_obs(year=2025, month=11, period="M11", unemployment_rate=4.2),
            _make_county_obs(year=2025, month=10, period="M10", unemployment_rate=4.1),
        ]
        mock_call = AsyncMock(return_value=_make_paginated_response(rows))
        _app(ctx).client.bls.county_unemployment = mock_call
        result = await get_county_unemployment("06085", ctx, from_date="2025-10", to_date="2025-11")

        kwargs = mock_call.call_args.kwargs
        assert kwargs.get("from_date") == "2025-10"
        assert kwargs.get("to_date") == "2025-11"
        # Period column should appear in some form (header-rendered as YYYY-MM)
        assert "2025-11" in result or "M11" in result
        assert "2025-10" in result or "M10" in result

    @pytest.mark.asyncio
    async def test_annual_only(self) -> None:
        """annual_only=True: SDK called with annual_only; M13 row renders as 'YYYY (annual)'."""
        ctx = _make_ctx()
        rows = [
            _make_county_obs(year=2024, month=13, period="M13", unemployment_rate=4.0),
        ]
        mock_call = AsyncMock(return_value=_make_paginated_response(rows))
        _app(ctx).client.bls.county_unemployment = mock_call
        result = await get_county_unemployment("06085", ctx, from_date="2024-01", to_date="2024-12", annual_only=True)

        assert mock_call.call_args.kwargs.get("annual_only") is True
        assert "2024 (annual)" in result

    @pytest.mark.asyncio
    async def test_half_date_returns_error(self) -> None:
        """Only from_date provided: returns error string and does not call SDK."""
        ctx = _make_ctx()
        mock_call = AsyncMock()
        _app(ctx).client.bls.county_unemployment = mock_call
        result = await get_county_unemployment("06085", ctx, from_date="2025-01")
        assert "Both from_date and to_date are required" in result
        mock_call.assert_not_called()

    @pytest.mark.asyncio
    async def test_not_found(self) -> None:
        """ThesmaError from SDK is propagated as the return string."""
        ctx = _make_ctx()
        msg = "County FIPS 99999 not found"
        _app(ctx).client.bls.county_unemployment = AsyncMock(side_effect=ThesmaError(msg))
        result = await get_county_unemployment("99999", ctx)
        assert "99999" in result

    @pytest.mark.asyncio
    async def test_zero_pad_fips(self) -> None:
        """Input '6085' is zero-filled to '06085' before SDK call."""
        ctx = _make_ctx()
        mock_call = AsyncMock(return_value=_make_paginated_response([_make_county_obs()]))
        _app(ctx).client.bls.county_unemployment = mock_call
        await get_county_unemployment("6085", ctx)
        args = mock_call.call_args.args
        assert args[0] == "06085"

    @pytest.mark.asyncio
    async def test_empty_time_series(self) -> None:
        """SDK returns empty list for time series → 'No LAUS data available' message."""
        ctx = _make_ctx()
        _app(ctx).client.bls.county_unemployment = AsyncMock(return_value=_make_paginated_response([]))
        result = await get_county_unemployment("06085", ctx, from_date="2025-01", to_date="2025-12")
        assert "No LAUS data" in result
        assert "06085" in result

    @pytest.mark.asyncio
    async def test_empty_latest(self) -> None:
        """SDK returns empty list for latest call → 'No LAUS data available' message."""
        ctx = _make_ctx()
        _app(ctx).client.bls.county_unemployment = AsyncMock(return_value=_make_paginated_response([]))
        result = await get_county_unemployment("06085", ctx)
        assert "No LAUS data" in result


# --- compare_county_unemployment ---


class TestCompareCountyUnemployment:
    @pytest.mark.asyncio
    async def test_compare_default_period(self) -> None:
        """Two FIPS, no year/month: SDK called with list+None,None; output has both counties."""
        ctx = _make_ctx()
        items = [
            _make_county_compare_item(county_fips="06085", county_name="Santa Clara County"),
            _make_county_compare_item(county_fips="48201", county_name="Harris County"),
        ]
        mock_call = AsyncMock(return_value=_make_compare_response(items))
        _app(ctx).client.bls.county_unemployment_compare = mock_call
        result = await compare_county_unemployment("06085,48201", ctx)

        # The SDK is called with list of FIPS as the first positional or keyword arg
        call_args = mock_call.call_args
        first_arg = call_args.args[0] if call_args.args else call_args.kwargs.get("fips")
        assert first_arg == ["06085", "48201"]
        assert call_args.kwargs.get("year") is None
        assert call_args.kwargs.get("month") is None

        assert "Santa Clara County" in result
        assert "Harris County" in result

    @pytest.mark.asyncio
    async def test_compare_with_errors(self) -> None:
        """Partial errors: response has hits + LausComparisonError; Errors section rendered."""
        ctx = _make_ctx()
        items = [
            _make_county_compare_item(county_fips="06085", county_name="Santa Clara County"),
            _make_county_compare_item(county_fips="48201", county_name="Harris County"),
        ]
        errors = [_make_compare_error("99999", "FIPS 99999 not found")]
        _app(ctx).client.bls.county_unemployment_compare = AsyncMock(
            return_value=_make_compare_response(items, errors=errors)
        )
        result = await compare_county_unemployment("06085,48201,99999", ctx)
        assert "Errors:" in result
        assert "99999" in result
        assert "not found" in result
        # Hits still rendered
        assert "Santa Clara County" in result

    @pytest.mark.asyncio
    async def test_compare_null_national_rate(self) -> None:
        """national_unemployment_rate=None renders as 'N/A' in header."""
        ctx = _make_ctx()
        items = [_make_county_compare_item()]
        _app(ctx).client.bls.county_unemployment_compare = AsyncMock(
            return_value=_make_compare_response(items, national_rate=None)
        )
        result = await compare_county_unemployment("06085", ctx)
        assert "National unemployment rate: N/A" in result

    @pytest.mark.asyncio
    async def test_compare_half_period(self) -> None:
        """Only year provided → error returned, no SDK call."""
        ctx = _make_ctx()
        mock_call = AsyncMock()
        _app(ctx).client.bls.county_unemployment_compare = mock_call
        result = await compare_county_unemployment("06085,48201", ctx, year=2024)
        assert "year and month" in result
        mock_call.assert_not_called()

    @pytest.mark.asyncio
    async def test_compare_half_period_only_month(self) -> None:
        """Only month provided → error returned, no SDK call."""
        ctx = _make_ctx()
        mock_call = AsyncMock()
        _app(ctx).client.bls.county_unemployment_compare = mock_call
        result = await compare_county_unemployment("06085,48201", ctx, month=11)
        assert "year and month" in result
        mock_call.assert_not_called()

    @pytest.mark.asyncio
    async def test_compare_empty_fips(self) -> None:
        """Empty fips string → error returned, no SDK call."""
        ctx = _make_ctx()
        mock_call = AsyncMock()
        _app(ctx).client.bls.county_unemployment_compare = mock_call
        result = await compare_county_unemployment("", ctx)
        assert "at least one FIPS" in result
        mock_call.assert_not_called()

    @pytest.mark.asyncio
    async def test_compare_whitespace_only_fips(self) -> None:
        """Whitespace-only/empty entries → error returned, no SDK call."""
        ctx = _make_ctx()
        mock_call = AsyncMock()
        _app(ctx).client.bls.county_unemployment_compare = mock_call
        result = await compare_county_unemployment("  ,  ", ctx)
        assert "at least one FIPS" in result
        mock_call.assert_not_called()

    @pytest.mark.asyncio
    async def test_compare_too_many_fips(self) -> None:
        """11 FIPS codes → error returned, no SDK call."""
        ctx = _make_ctx()
        mock_call = AsyncMock()
        _app(ctx).client.bls.county_unemployment_compare = mock_call
        fips = ",".join(f"0608{i}" for i in range(11))
        result = await compare_county_unemployment(fips, ctx)
        assert "at most 10" in result
        mock_call.assert_not_called()

    @pytest.mark.asyncio
    async def test_compare_whitespace_trim(self) -> None:
        """Whitespace around FIPS codes is trimmed before SDK call."""
        ctx = _make_ctx()
        items = [_make_county_compare_item()]
        mock_call = AsyncMock(return_value=_make_compare_response(items))
        _app(ctx).client.bls.county_unemployment_compare = mock_call
        await compare_county_unemployment("06085, 48201 , 17031", ctx)
        call_args = mock_call.call_args
        first_arg = call_args.args[0] if call_args.args else call_args.kwargs.get("fips")
        assert first_arg == ["06085", "48201", "17031"]

    @pytest.mark.asyncio
    async def test_compare_annual_month(self) -> None:
        """Response with month=13 renders as 'YYYY (annual)' in header."""
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
        """No dates: SDK called with per_page=1, default adjustment 'sa'."""
        ctx = _make_ctx()
        mock_call = AsyncMock(return_value=_make_paginated_response([_make_state_obs()]))
        _app(ctx).client.bls.state_unemployment = mock_call
        result = await get_state_unemployment("06", ctx)
        kwargs = mock_call.call_args.kwargs
        assert kwargs.get("per_page") == 1
        assert kwargs.get("adjustment") == "sa"
        assert "California" in result
        assert "06" in result

    @pytest.mark.asyncio
    async def test_state_nsa_adjustment(self) -> None:
        """adjustment='nsa' is forwarded to the SDK."""
        ctx = _make_ctx()
        mock_call = AsyncMock(
            return_value=_make_paginated_response([_make_state_obs(seasonal_adjustment="not_seasonally_adjusted")])
        )
        _app(ctx).client.bls.state_unemployment = mock_call
        await get_state_unemployment("06", ctx, adjustment="nsa")
        assert mock_call.call_args.kwargs.get("adjustment") == "nsa"

    @pytest.mark.asyncio
    async def test_state_invalid_adjustment(self) -> None:
        """adjustment='partial' → error returned, no SDK call."""
        ctx = _make_ctx()
        mock_call = AsyncMock()
        _app(ctx).client.bls.state_unemployment = mock_call
        result = await get_state_unemployment("06", ctx, adjustment="partial")
        assert "adjustment" in result
        assert "sa" in result and "nsa" in result
        mock_call.assert_not_called()

    @pytest.mark.asyncio
    async def test_state_time_series_with_lfpr(self) -> None:
        """Time series table includes LFPR and Emp/Pop columns."""
        ctx = _make_ctx()
        rows = [
            _make_state_obs(year=2025, month=11, period="M11", labor_force_participation_rate=63.7),
            _make_state_obs(year=2025, month=10, period="M10", labor_force_participation_rate=63.5),
        ]
        _app(ctx).client.bls.state_unemployment = AsyncMock(return_value=_make_paginated_response(rows))
        result = await get_state_unemployment("06", ctx, from_date="2025-10", to_date="2025-11")
        assert "LFPR" in result
        assert "Emp/Pop" in result
        assert "63.7%" in result

    @pytest.mark.asyncio
    async def test_state_zero_pad_fips(self) -> None:
        """Input '6' is zero-filled to '06' before SDK call."""
        ctx = _make_ctx()
        mock_call = AsyncMock(return_value=_make_paginated_response([_make_state_obs()]))
        _app(ctx).client.bls.state_unemployment = mock_call
        await get_state_unemployment("6", ctx)
        args = mock_call.call_args.args
        assert args[0] == "06"

    @pytest.mark.asyncio
    async def test_half_date_returns_error(self) -> None:
        """Only to_date provided: returns error string and does not call SDK."""
        ctx = _make_ctx()
        mock_call = AsyncMock()
        _app(ctx).client.bls.state_unemployment = mock_call
        result = await get_state_unemployment("06", ctx, to_date="2025-11")
        assert "Both from_date and to_date are required" in result
        mock_call.assert_not_called()


# --- compare_state_unemployment ---


class TestCompareStateUnemployment:
    @pytest.mark.asyncio
    async def test_state_compare_default(self) -> None:
        """Two state FIPS, no year/month: SDK called with list+None,None+sa default."""
        ctx = _make_ctx()
        items = [
            _make_state_compare_item(state_fips="06", state_name="California"),
            _make_state_compare_item(state_fips="48", state_name="Texas"),
        ]
        mock_call = AsyncMock(return_value=_make_compare_response(items, adjustment="seasonally_adjusted"))
        _app(ctx).client.bls.state_unemployment_compare = mock_call
        result = await compare_state_unemployment("06,48", ctx)
        call_args = mock_call.call_args
        first_arg = call_args.args[0] if call_args.args else call_args.kwargs.get("fips")
        assert first_arg == ["06", "48"]
        assert call_args.kwargs.get("year") is None
        assert call_args.kwargs.get("month") is None
        assert call_args.kwargs.get("adjustment") == "sa"
        assert "California" in result
        assert "Texas" in result

    @pytest.mark.asyncio
    async def test_state_compare_adjustment(self) -> None:
        """adjustment='nsa' is forwarded to the SDK."""
        ctx = _make_ctx()
        items = [_make_state_compare_item()]
        mock_call = AsyncMock(return_value=_make_compare_response(items, adjustment="not_seasonally_adjusted"))
        _app(ctx).client.bls.state_unemployment_compare = mock_call
        await compare_state_unemployment("06,48", ctx, adjustment="nsa")
        assert mock_call.call_args.kwargs.get("adjustment") == "nsa"

    @pytest.mark.asyncio
    async def test_state_compare_invalid_adjustment(self) -> None:
        """Invalid adjustment → error returned, no SDK call."""
        ctx = _make_ctx()
        mock_call = AsyncMock()
        _app(ctx).client.bls.state_unemployment_compare = mock_call
        result = await compare_state_unemployment("06,48", ctx, adjustment="bogus")
        assert "adjustment" in result
        mock_call.assert_not_called()

    @pytest.mark.asyncio
    async def test_state_compare_too_many_fips(self) -> None:
        """11 FIPS codes → error returned, no SDK call."""
        ctx = _make_ctx()
        mock_call = AsyncMock()
        _app(ctx).client.bls.state_unemployment_compare = mock_call
        fips = ",".join(f"{i:02d}" for i in range(11))
        result = await compare_state_unemployment(fips, ctx)
        assert "at most 10" in result
        mock_call.assert_not_called()

    @pytest.mark.asyncio
    async def test_state_compare_empty_fips(self) -> None:
        """Empty fips string → error returned, no SDK call."""
        ctx = _make_ctx()
        mock_call = AsyncMock()
        _app(ctx).client.bls.state_unemployment_compare = mock_call
        result = await compare_state_unemployment("", ctx)
        assert "at least one FIPS" in result
        mock_call.assert_not_called()
