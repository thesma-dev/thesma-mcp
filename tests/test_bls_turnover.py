"""Tests for JOLTS turnover MCP tools and screener JOLTS filters."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from thesma_mcp.client import ThesmaAPIError
from thesma_mcp.tools.bls_turnover import get_industry_turnover, get_regional_turnover, get_state_turnover
from thesma_mcp.tools.screener import screen_companies


def _make_ctx(client_response: Any = None, *, side_effect: Any = None) -> MagicMock:
    """Create a mock MCP context with a mock client."""
    mock_client = AsyncMock()
    if side_effect is not None:
        mock_client.get = AsyncMock(side_effect=side_effect)
    else:
        mock_client.get = AsyncMock(return_value=client_response)

    app = MagicMock()
    app.client = mock_client

    ctx = MagicMock()
    ctx.request_context.lifespan_context = app
    return ctx


# --- Sample API responses ---


def _industry_latest_response() -> dict[str, Any]:
    return {
        "data": {
            "year": 2025,
            "month": 10,
            "period": "2025-10",
            "naics_code": "511210",
            "jolts_industry_code": "510000",
            "jolts_industry_name": "Information",
            "naics_match_level": "jolts_industry",
            "adjustment": "sa",
            "job_openings": {"level": 296.0, "rate": 4.8},
            "hires": {"level": 150.0, "rate": 2.5},
            "quits": {"level": 120.0, "rate": 2.0},
            "layoffs_and_discharges": {"level": 80.0, "rate": 1.3},
            "total_separations": {"level": 210.0, "rate": 3.5},
            "other_separations": {"level": 10.0, "rate": 0.2},
            "source": "JOLTS",
        }
    }


def _industry_time_series_response() -> dict[str, Any]:
    return {
        "data": [
            {
                "year": 2025,
                "month": 10,
                "period": "2025-10",
                "naics_code": "511210",
                "jolts_industry_code": "510000",
                "jolts_industry_name": "Information",
                "adjustment": "sa",
                "job_openings": {"level": 296.0, "rate": 4.8},
                "hires": {"level": 150.0, "rate": 2.5},
                "quits": {"level": 120.0, "rate": 2.0},
                "layoffs_and_discharges": {"level": 80.0, "rate": 1.3},
                "total_separations": {"level": 210.0, "rate": 3.5},
                "other_separations": {"level": 10.0, "rate": 0.2},
            },
            {
                "year": 2025,
                "month": 9,
                "period": "2025-09",
                "naics_code": "511210",
                "jolts_industry_code": "510000",
                "jolts_industry_name": "Information",
                "adjustment": "sa",
                "job_openings": {"level": 290.0, "rate": 4.7},
                "hires": {"level": 145.0, "rate": 2.4},
                "quits": {"level": 115.0, "rate": 1.9},
                "layoffs_and_discharges": {"level": 78.0, "rate": 1.3},
                "total_separations": {"level": 205.0, "rate": 3.4},
                "other_separations": {"level": 12.0, "rate": 0.2},
            },
        ],
        "pagination": {"page": 1, "per_page": 25, "total": 2},
    }


def _state_turnover_response() -> dict[str, Any]:
    return {
        "data": [
            {
                "year": 2025,
                "month": 10,
                "period": "2025-10",
                "state_code": "06",
                "adjustment": "sa",
                "job_openings": {"level": 1200.0, "rate": 5.2},
                "hires": {"level": 800.0, "rate": 3.5},
                "quits": {"level": 600.0, "rate": 2.6},
                "layoffs_and_discharges": {"level": 400.0, "rate": 1.7},
                "total_separations": {"level": 1050.0, "rate": 4.6},
            }
        ],
        "pagination": {"page": 1, "per_page": 1, "total": 1},
    }


def _regional_turnover_response(region: str = "northeast") -> dict[str, Any]:
    return {
        "data": [
            {
                "year": 2025,
                "month": 10,
                "period": "2025-10",
                "region": region,
                "adjustment": "sa",
                "job_openings": {"level": 800.0, "rate": 4.5},
                "hires": {"level": 500.0, "rate": 2.8},
                "quits": {"level": 400.0, "rate": 2.2},
                "layoffs_and_discharges": {"level": 250.0, "rate": 1.4},
                "total_separations": {"level": 700.0, "rate": 3.9},
            }
        ],
        "pagination": {"page": 1, "per_page": 1, "total": 1},
    }


def _screener_jolts_response() -> dict[str, Any]:
    return {
        "data": [
            {
                "cik": "0000320193",
                "ticker": "AAPL",
                "name": "Apple Inc.",
                "ratios": {
                    "gross_margin": 45.6,
                    "net_margin": 25.3,
                    "revenue_growth_yoy": 8.1,
                },
                "labor_context": {
                    "industry_quits_rate": 2.5,
                    "industry_openings_rate": 4.8,
                    "labour_market_tightness": 1.92,
                },
            },
        ],
        "pagination": {"page": 1, "per_page": 20, "total": 1},
    }


# --- Industry turnover tests ---


class TestGetIndustryTurnover:
    @pytest.mark.asyncio
    async def test_latest_default(self) -> None:
        """Call without dates requests /turnover/latest and returns key-value output."""
        ctx = _make_ctx(_industry_latest_response())
        result = await get_industry_turnover("511210", ctx)

        call_args = ctx.request_context.lifespan_context.client.get.call_args
        assert "/turnover/latest" in call_args[0][0]

        assert "NAICS 511210" in result
        assert "510000" in result
        assert "Information" in result
        assert "Openings" in result

    @pytest.mark.asyncio
    async def test_time_series(self) -> None:
        """Call with dates requests time series endpoint with from/to params."""
        ctx = _make_ctx(_industry_time_series_response())
        result = await get_industry_turnover("511210", ctx, from_date="2025-09", to_date="2025-10")

        call_args = ctx.request_context.lifespan_context.client.get.call_args
        path = call_args[0][0]
        params = call_args.kwargs.get("params", {})
        assert "/turnover" in path
        assert "/latest" not in path
        assert params.get("from") == "2025-09"
        assert params.get("to") == "2025-10"

        assert "2025-10" in result
        assert "2025-09" in result

    @pytest.mark.asyncio
    async def test_agricultural_404(self) -> None:
        """Agricultural NAICS returns descriptive error from API."""
        msg = "No JOLTS data available for NAICS 111 \u2014 agricultural industries are excluded from the JOLTS survey"
        ctx = _make_ctx(side_effect=ThesmaAPIError(msg))
        result = await get_industry_turnover("111", ctx)
        assert "agricultural" in result.lower() or "JOLTS" in result

    @pytest.mark.asyncio
    async def test_adjustment_param(self) -> None:
        """Adjustment parameter is passed through to API."""
        ctx = _make_ctx(_industry_latest_response())
        await get_industry_turnover("511210", ctx, adjustment="nsa")

        call_args = ctx.request_context.lifespan_context.client.get.call_args
        params = call_args.kwargs.get("params", {})
        assert params.get("adjustment") == "nsa"

    @pytest.mark.asyncio
    async def test_measures_param(self) -> None:
        """Measures parameter is passed through to API."""
        ctx = _make_ctx(_industry_latest_response())
        await get_industry_turnover("511210", ctx, measures="job_openings,hires")

        call_args = ctx.request_context.lifespan_context.client.get.call_args
        params = call_args.kwargs.get("params", {})
        assert params.get("measures") == "job_openings,hires"

    @pytest.mark.asyncio
    async def test_empty_data(self) -> None:
        """Empty response returns clear 'no data' message."""
        ctx = _make_ctx({"data": {}})
        result = await get_industry_turnover("511210", ctx)
        assert "No JOLTS" in result

    @pytest.mark.asyncio
    async def test_half_date_returns_error(self) -> None:
        """Only from_date without to_date returns error message."""
        ctx = _make_ctx({})
        result = await get_industry_turnover("511210", ctx, from_date="2025-01")
        assert "Both from_date and to_date are required" in result


# --- State turnover tests ---


class TestGetStateTurnover:
    @pytest.mark.asyncio
    async def test_state_latest(self) -> None:
        """Latest call sends per_page=1 and formats as key-value pairs."""
        ctx = _make_ctx(_state_turnover_response())
        result = await get_state_turnover("06", ctx)

        call_args = ctx.request_context.lifespan_context.client.get.call_args
        params = call_args.kwargs.get("params", {})
        assert params.get("per_page") == 1

        assert "FIPS 06" in result

    @pytest.mark.asyncio
    async def test_state_time_series(self) -> None:
        """Time series call with dates returns table."""
        response: dict[str, Any] = {
            "data": [
                {
                    "year": 2025,
                    "month": 10,
                    "period": "2025-10",
                    "state_code": "06",
                    "adjustment": "sa",
                    "job_openings": {"level": 1200.0, "rate": 5.2},
                    "hires": {"level": 800.0, "rate": 3.5},
                    "quits": {"level": 600.0, "rate": 2.6},
                    "layoffs_and_discharges": {"level": 400.0, "rate": 1.7},
                    "total_separations": {"level": 1050.0, "rate": 4.6},
                },
                {
                    "year": 2025,
                    "month": 9,
                    "period": "2025-09",
                    "state_code": "06",
                    "adjustment": "sa",
                    "job_openings": {"level": 1180.0, "rate": 5.1},
                    "hires": {"level": 790.0, "rate": 3.4},
                    "quits": {"level": 590.0, "rate": 2.5},
                    "layoffs_and_discharges": {"level": 395.0, "rate": 1.7},
                    "total_separations": {"level": 1040.0, "rate": 4.5},
                },
            ],
            "pagination": {"page": 1, "per_page": 25, "total": 2},
        }
        ctx = _make_ctx(response)
        result = await get_state_turnover("06", ctx, from_date="2025-09", to_date="2025-10")
        assert "2025-10" in result
        assert "2025-09" in result

    @pytest.mark.asyncio
    async def test_fips_00_rejected(self) -> None:
        """FIPS 00 returns a helpful message about using national endpoint."""
        ctx = _make_ctx(side_effect=ThesmaAPIError("Use /v1/us/bls/industries/{naics}/turnover for national data"))
        result = await get_state_turnover("00", ctx)
        assert "national" in result.lower()

    @pytest.mark.asyncio
    async def test_no_other_separations_in_output(self) -> None:
        """State output does not include other_separations."""
        ctx = _make_ctx(_state_turnover_response())
        result = await get_state_turnover("06", ctx)
        assert "Other Sep" not in result
        assert "other_separations" not in result


# --- Regional turnover tests ---


class TestGetRegionalTurnover:
    @pytest.mark.asyncio
    async def test_regional_basic(self) -> None:
        """Basic regional call returns formatted output."""
        ctx = _make_ctx(_regional_turnover_response())
        result = await get_regional_turnover("northeast", ctx)
        assert "Northeast" in result

    @pytest.mark.asyncio
    async def test_all_four_regions(self) -> None:
        """All four Census regions return valid output."""
        for region in ("northeast", "south", "midwest", "west"):
            ctx = _make_ctx(_regional_turnover_response(region))
            result = await get_regional_turnover(region, ctx)
            assert region.title() in result

    @pytest.mark.asyncio
    async def test_unknown_region(self) -> None:
        """Unknown region returns error message."""
        ctx = _make_ctx(
            side_effect=ThesmaAPIError("Unknown region: 'pacific'. Valid regions: northeast, south, midwest, west.")
        )
        result = await get_regional_turnover("pacific", ctx)
        assert "pacific" in result.lower()


# --- Screener JOLTS filter tests ---


class TestScreenerJoltsFilters:
    @pytest.mark.asyncio
    async def test_jolts_filter_params_sent(self) -> None:
        """JOLTS filter params are passed to the API."""
        ctx = _make_ctx(_screener_jolts_response())
        await screen_companies(ctx, min_industry_quits_rate=2.0)

        call_args = ctx.request_context.lifespan_context.client.get.call_args
        params = call_args.kwargs.get("params", {})
        assert params.get("min_industry_quits_rate") == 2.0

    @pytest.mark.asyncio
    async def test_jolts_columns_in_table(self) -> None:
        """JOLTS filter activates Quits Rate column in output."""
        ctx = _make_ctx(_screener_jolts_response())
        result = await screen_companies(ctx, min_industry_quits_rate=2.0)
        assert "Quits Rate" in result

    @pytest.mark.asyncio
    async def test_jolts_filter_in_summary_header(self) -> None:
        """JOLTS filter is described in summary header."""
        ctx = _make_ctx(_screener_jolts_response())
        result = await screen_companies(ctx, min_industry_quits_rate=2.0)
        assert "industry quits rate >= 2.0%" in result
