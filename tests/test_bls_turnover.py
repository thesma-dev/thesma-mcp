"""Tests for JOLTS turnover MCP tools."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from thesma.errors import ThesmaError

from thesma_mcp.tools.bls_turnover import get_industry_turnover, get_regional_turnover, get_state_turnover


def _make_measure(level: float | None = None, rate: float | None = None) -> MagicMock:
    """Create a mock JoltsMeasureValue."""
    from thesma._generated.models import JoltsMeasureValue

    return JoltsMeasureValue(level=level, rate=rate)


def _make_turnover_point(**kwargs: Any) -> MagicMock:
    """Create a mock turnover point."""
    m = MagicMock()
    for k, v in kwargs.items():
        setattr(m, k, v)
    return m


def _make_paginated_response(items: list[Any], total: int | None = None) -> MagicMock:
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
    """Create a mock MCP context."""
    app = MagicMock()
    app.client = MagicMock()
    ctx = MagicMock()
    ctx.request_context.lifespan_context = app
    return ctx


def _app(ctx: MagicMock) -> Any:
    return ctx.request_context.lifespan_context


def _industry_latest_data() -> MagicMock:
    return _make_turnover_point(
        year=2025,
        month=10,
        period="2025-10",
        naics_code="511210",
        jolts_industry_code="510000",
        jolts_industry_name="Information",
        naics_match_level="jolts_industry",
        adjustment="sa",
        job_openings=_make_measure(296.0, 4.8),
        hires=_make_measure(150.0, 2.5),
        quits=_make_measure(120.0, 2.0),
        layoffs_and_discharges=_make_measure(80.0, 1.3),
        total_separations=_make_measure(210.0, 3.5),
        other_separations=_make_measure(10.0, 0.2),
        source="JOLTS",
    )


def _industry_time_series_data() -> list[MagicMock]:
    return [
        _make_turnover_point(
            year=2025,
            month=10,
            period="2025-10",
            naics_code="511210",
            jolts_industry_code="510000",
            jolts_industry_name="Information",
            adjustment="sa",
            job_openings=_make_measure(296.0, 4.8),
            hires=_make_measure(150.0, 2.5),
            quits=_make_measure(120.0, 2.0),
            layoffs_and_discharges=_make_measure(80.0, 1.3),
            total_separations=_make_measure(210.0, 3.5),
            other_separations=_make_measure(10.0, 0.2),
        ),
        _make_turnover_point(
            year=2025,
            month=9,
            period="2025-09",
            naics_code="511210",
            jolts_industry_code="510000",
            jolts_industry_name="Information",
            adjustment="sa",
            job_openings=_make_measure(290.0, 4.7),
            hires=_make_measure(145.0, 2.4),
            quits=_make_measure(115.0, 1.9),
            layoffs_and_discharges=_make_measure(78.0, 1.3),
            total_separations=_make_measure(205.0, 3.4),
            other_separations=_make_measure(12.0, 0.2),
        ),
    ]


def _state_turnover_data() -> list[MagicMock]:
    return [
        _make_turnover_point(
            year=2025,
            month=10,
            period="2025-10",
            state_code="06",
            adjustment="sa",
            job_openings=_make_measure(1200.0, 5.2),
            hires=_make_measure(800.0, 3.5),
            quits=_make_measure(600.0, 2.6),
            layoffs_and_discharges=_make_measure(400.0, 1.7),
            total_separations=_make_measure(1050.0, 4.6),
        ),
    ]


def _regional_turnover_data(region: str = "northeast") -> list[MagicMock]:
    return [
        _make_turnover_point(
            year=2025,
            month=10,
            period="2025-10",
            region=region,
            adjustment="sa",
            job_openings=_make_measure(800.0, 4.5),
            hires=_make_measure(500.0, 2.8),
            quits=_make_measure(400.0, 2.2),
            layoffs_and_discharges=_make_measure(250.0, 1.4),
            total_separations=_make_measure(700.0, 3.9),
        ),
    ]


# --- Industry turnover tests ---


class TestGetIndustryTurnover:
    @pytest.mark.asyncio
    async def test_latest_default(self) -> None:
        """Call without dates requests turnover_latest."""
        ctx = _make_ctx()
        _app(ctx).client.bls.turnover_latest = AsyncMock(return_value=_make_data_response(_industry_latest_data()))
        result = await get_industry_turnover("511210", ctx)

        assert "NAICS 511210" in result
        assert "510000" in result
        assert "Information" in result
        assert "Openings" in result

    @pytest.mark.asyncio
    async def test_time_series(self) -> None:
        """Call with dates returns time series."""
        ctx = _make_ctx()
        _app(ctx).client.bls.turnover = AsyncMock(return_value=_make_paginated_response(_industry_time_series_data()))
        result = await get_industry_turnover("511210", ctx, from_date="2025-09", to_date="2025-10")

        assert "2025-10" in result
        assert "2025-09" in result

    @pytest.mark.asyncio
    async def test_agricultural_404(self) -> None:
        """Agricultural NAICS returns descriptive error from API."""
        ctx = _make_ctx()
        msg = "No JOLTS data available for NAICS 111"
        _app(ctx).client.bls.turnover_latest = AsyncMock(side_effect=ThesmaError(msg))
        result = await get_industry_turnover("111", ctx)
        assert "JOLTS" in result

    @pytest.mark.asyncio
    async def test_half_date_returns_error(self) -> None:
        """Only from_date without to_date returns error message."""
        ctx = _make_ctx()
        result = await get_industry_turnover("511210", ctx, from_date="2025-01")
        assert "Both from_date and to_date are required" in result


# --- State turnover tests ---


class TestGetStateTurnover:
    @pytest.mark.asyncio
    async def test_state_latest(self) -> None:
        """Latest call with per_page=1."""
        ctx = _make_ctx()
        _app(ctx).client.bls.state_turnover = AsyncMock(return_value=_make_paginated_response(_state_turnover_data()))
        result = await get_state_turnover("06", ctx)

        assert "FIPS 06" in result

    @pytest.mark.asyncio
    async def test_state_time_series(self) -> None:
        """Time series call with dates returns table."""
        ctx = _make_ctx()
        data = _state_turnover_data() + [
            _make_turnover_point(
                year=2025,
                month=9,
                period="2025-09",
                state_code="06",
                adjustment="sa",
                job_openings=_make_measure(1180.0, 5.1),
                hires=_make_measure(790.0, 3.4),
                quits=_make_measure(590.0, 2.5),
                layoffs_and_discharges=_make_measure(395.0, 1.7),
                total_separations=_make_measure(1040.0, 4.5),
            ),
        ]
        _app(ctx).client.bls.state_turnover = AsyncMock(return_value=_make_paginated_response(data))
        result = await get_state_turnover("06", ctx, from_date="2025-09", to_date="2025-10")
        assert "2025-10" in result
        assert "2025-09" in result

    @pytest.mark.asyncio
    async def test_no_other_separations_in_output(self) -> None:
        """State output does not include other_separations."""
        ctx = _make_ctx()
        _app(ctx).client.bls.state_turnover = AsyncMock(return_value=_make_paginated_response(_state_turnover_data()))
        result = await get_state_turnover("06", ctx)
        assert "Other Sep" not in result
        assert "other_separations" not in result


# --- Regional turnover tests ---


class TestGetRegionalTurnover:
    @pytest.mark.asyncio
    async def test_regional_basic(self) -> None:
        """Basic regional call returns formatted output."""
        ctx = _make_ctx()
        _app(ctx).client.bls.regional_turnover = AsyncMock(
            return_value=_make_paginated_response(_regional_turnover_data())
        )
        result = await get_regional_turnover("northeast", ctx)
        assert "Northeast" in result

    @pytest.mark.asyncio
    async def test_all_four_regions(self) -> None:
        """All four Census regions return valid output."""
        for region in ("northeast", "south", "midwest", "west"):
            ctx = _make_ctx()
            _app(ctx).client.bls.regional_turnover = AsyncMock(
                return_value=_make_paginated_response(_regional_turnover_data(region))
            )
            result = await get_regional_turnover(region, ctx)
            assert region.title() in result

    @pytest.mark.asyncio
    async def test_unknown_region(self) -> None:
        """Unknown region returns error message."""
        ctx = _make_ctx()
        _app(ctx).client.bls.regional_turnover = AsyncMock(
            side_effect=ThesmaError("Unknown region: 'pacific'. Valid regions: northeast, south, midwest, west.")
        )
        result = await get_regional_turnover("pacific", ctx)
        assert "pacific" in result.lower()
