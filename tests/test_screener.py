"""Tests for the screen_companies MCP tool."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from thesma_mcp.tools.screener import _build_summary_header, screen_companies


def _make_screener_item(
    cik: str = "0000320193",
    ticker: str = "AAPL",
    name: str = "Apple Inc.",
    ratios: dict[str, float | None] | None = None,
    bls: dict[str, Any] | None = None,
    labor_context: dict[str, Any] | None = None,
) -> SimpleNamespace:
    """Create a mock ScreenerResultItem."""
    ratios_data = ratios or {}
    return SimpleNamespace(
        cik=cik,
        ticker=ticker,
        name=name,
        ratios=SimpleNamespace(**ratios_data),
        bls=bls,
        labor_context=labor_context,
    )


def _make_paginated_response(items: list[MagicMock], total: int | None = None) -> MagicMock:
    resp = MagicMock()
    resp.data = items
    resp.pagination = MagicMock()
    resp.pagination.total = total if total is not None else len(items)
    return resp


def _make_ctx(response: MagicMock) -> MagicMock:
    """Create a mock MCP context."""
    app = MagicMock()
    app.client = MagicMock()
    app.client.screener.screen = AsyncMock(return_value=response)
    app.resolver = AsyncMock()
    ctx = MagicMock()
    ctx.request_context.lifespan_context = app
    return ctx


def _default_companies() -> list[MagicMock]:
    return [
        _make_screener_item(
            "0000320193",
            "AAPL",
            "Apple Inc.",
            ratios={"gross_margin": 45.6, "operating_margin": 30.2, "net_margin": 25.3, "revenue_growth_yoy": 8.1},
        ),
        _make_screener_item(
            "0000789019",
            "MSFT",
            "Microsoft Corporation",
            ratios={"gross_margin": 69.4, "operating_margin": 44.1, "net_margin": 35.6, "revenue_growth_yoy": 15.7},
        ),
    ]


@pytest.mark.asyncio
async def test_screen_no_filters() -> None:
    """screen_companies with no filters returns formatted table."""
    resp = _make_paginated_response(_default_companies())
    ctx = _make_ctx(resp)
    result = await screen_companies(ctx)

    assert "AAPL" in result
    assert "MSFT" in result
    assert "Apple Inc." in result
    assert "All screened companies" in result


@pytest.mark.asyncio
async def test_screen_tier_filter() -> None:
    """screen_companies with tier filter includes it in API call."""
    resp = _make_paginated_response(_default_companies())
    ctx = _make_ctx(resp)
    result = await screen_companies(ctx, tier="sp500")

    assert "S&P 500" in result


@pytest.mark.asyncio
async def test_screen_sort_and_order() -> None:
    """screen_companies with sort and order includes both."""
    resp = _make_paginated_response(_default_companies())
    ctx = _make_ctx(resp)
    result = await screen_companies(ctx, sort="gross_margin", order="asc")

    assert "ascending" in result


@pytest.mark.asyncio
async def test_screen_no_matches() -> None:
    """screen_companies with no matches returns helpful message."""
    resp = _make_paginated_response([], total=0)
    ctx = _make_ctx(resp)
    result = await screen_companies(ctx, min_gross_margin=99.0)

    assert "No companies matched" in result
    assert "broadening" in result


@pytest.mark.asyncio
async def test_screen_summary_header() -> None:
    """screen_companies summary header describes applied filters."""
    resp = _make_paginated_response(_default_companies())
    ctx = _make_ctx(resp)
    result = await screen_companies(ctx, tier="sp500", min_gross_margin=40.0, min_revenue_growth=10.0)

    assert "S&P 500" in result
    assert "gross margin >= 40.0%" in result
    assert "revenue growth >= 10.0%" in result


def test_summary_header_no_filters() -> None:
    """Summary header with no filters returns generic label."""
    assert _build_summary_header({}) == "All screened companies"


def test_summary_header_multiple_filters() -> None:
    """Summary header with multiple filters joins them with 'and'."""
    header = _build_summary_header({"tier": "russell1000", "min_net_margin": 20})
    assert "Russell 1000" in header
    assert "net margin >= 20%" in header


# --- BLS filter tests ---


@pytest.mark.asyncio
async def test_screen_companies_bls_columns_shown() -> None:
    """screen_companies with BLS filter shows BLS columns in output."""
    companies = [
        _make_screener_item(
            "0000320193",
            "AAPL",
            "Apple Inc.",
            ratios={"gross_margin": 45.6, "net_margin": 25.3},
            bls={
                "industry": "Electronic Computers",
                "hiring_trend": "accelerating",
                "employment_growth": 3.2,
                "comp_ratio": 12.5,
            },
        ),
    ]
    resp = _make_paginated_response(companies)
    ctx = _make_ctx(resp)
    result = await screen_companies(ctx, min_industry_employment_growth=1.0)

    assert "Industry" in result
    assert "Hiring Trend" in result
    assert "Emp Growth" in result
    assert "Comp Ratio" in result
    assert "accelerating" in result


@pytest.mark.asyncio
async def test_screen_companies_bls_filter_in_summary() -> None:
    """screen_companies with BLS filter mentions it in summary header."""
    companies = [_make_screener_item(ratios={"gross_margin": 45.6})]
    resp = _make_paginated_response(companies)
    ctx = _make_ctx(resp)
    result = await screen_companies(ctx, industry_hiring_trend="declining")

    assert "hiring trend: declining" in result


# --- JOLTS filter tests ---


@pytest.mark.asyncio
async def test_screen_jolts_columns_in_table() -> None:
    """JOLTS filter activates Quits Rate column in output."""
    companies = [
        _make_screener_item(
            ratios={"gross_margin": 45.6},
            labor_context={"industry_quits_rate": 2.5, "industry_openings_rate": 4.8, "labour_market_tightness": 1.92},
        ),
    ]
    resp = _make_paginated_response(companies)
    ctx = _make_ctx(resp)
    result = await screen_companies(ctx, min_industry_quits_rate=2.0)
    assert "Quits Rate" in result


@pytest.mark.asyncio
async def test_screen_jolts_filter_in_summary_header() -> None:
    """JOLTS filter is described in summary header."""
    companies = [_make_screener_item(ratios={"gross_margin": 45.6})]
    resp = _make_paginated_response(companies)
    ctx = _make_ctx(resp)
    result = await screen_companies(ctx, min_industry_quits_rate=2.0)
    assert "industry quits rate >= 2.0%" in result


# --- LAUS filter tests ---


class TestScreenerLausFilters:
    @pytest.mark.asyncio
    async def test_local_unemployment_rate_param_sent(self) -> None:
        """min_local_unemployment_rate forwards through to the SDK call."""
        companies = [_make_screener_item(ratios={"gross_margin": 45.6})]
        resp = _make_paginated_response(companies)
        ctx = _make_ctx(resp)
        await screen_companies(ctx, min_local_unemployment_rate=5.0)
        kwargs = ctx.request_context.lifespan_context.client.screener.screen.await_args.kwargs
        assert kwargs["min_local_unemployment_rate"] == 5.0

    @pytest.mark.asyncio
    async def test_local_labor_force_param_sent(self) -> None:
        companies = [_make_screener_item(ratios={"gross_margin": 45.6})]
        resp = _make_paginated_response(companies)
        ctx = _make_ctx(resp)
        await screen_companies(ctx, min_local_labor_force=500000)
        kwargs = ctx.request_context.lifespan_context.client.screener.screen.await_args.kwargs
        assert kwargs["min_local_labor_force"] == 500000

    @pytest.mark.asyncio
    async def test_local_unemployment_trend_param_sent(self) -> None:
        companies = [_make_screener_item(ratios={"gross_margin": 45.6})]
        resp = _make_paginated_response(companies)
        ctx = _make_ctx(resp)
        await screen_companies(ctx, local_unemployment_trend="rising")
        kwargs = ctx.request_context.lifespan_context.client.screener.screen.await_args.kwargs
        assert kwargs["local_unemployment_trend"] == "rising"

    @pytest.mark.asyncio
    async def test_max_local_unemployment_rate_param_sent(self) -> None:
        companies = [_make_screener_item(ratios={"gross_margin": 45.6})]
        resp = _make_paginated_response(companies)
        ctx = _make_ctx(resp)
        await screen_companies(ctx, max_local_unemployment_rate=8.0)
        kwargs = ctx.request_context.lifespan_context.client.screener.screen.await_args.kwargs
        assert kwargs["max_local_unemployment_rate"] == 8.0

    @pytest.mark.asyncio
    async def test_laus_columns_in_table_nested(self) -> None:
        """LAUS columns render when labor_context is nested with .local_market."""
        companies = [
            _make_screener_item(
                ratios={"gross_margin": 45.6},
                labor_context={
                    "local_market": {
                        "county_name": "Alameda County",
                        "unemployment_rate": 4.2,
                        "labor_force": 800000,
                    }
                },
            ),
        ]
        resp = _make_paginated_response(companies)
        ctx = _make_ctx(resp)
        result = await screen_companies(ctx, min_local_unemployment_rate=4.0)
        assert "Unemp Rate" in result
        assert "Labor Force" in result
        assert "4.2%" in result
        assert "Alameda County" in result

    @pytest.mark.asyncio
    async def test_laus_columns_in_table_flat(self) -> None:
        """LAUS columns also render when labor_context is flat (legacy shape)."""
        companies = [
            _make_screener_item(
                ratios={"gross_margin": 45.6},
                labor_context={
                    "county_name": "Alameda County",
                    "unemployment_rate": 4.2,
                    "labor_force": 800000,
                },
            ),
        ]
        resp = _make_paginated_response(companies)
        ctx = _make_ctx(resp)
        result = await screen_companies(ctx, min_local_unemployment_rate=4.0)
        assert "Unemp Rate" in result
        assert "4.2%" in result
        assert "Alameda County" in result

    @pytest.mark.asyncio
    async def test_laus_filter_in_summary_header(self) -> None:
        companies = [_make_screener_item(ratios={"gross_margin": 45.6})]
        resp = _make_paginated_response(companies)
        ctx = _make_ctx(resp)
        result = await screen_companies(ctx, min_local_unemployment_rate=5.0)
        assert "local unemployment rate >= 5.0%" in result

    @pytest.mark.asyncio
    async def test_laus_trend_in_summary_header(self) -> None:
        companies = [_make_screener_item(ratios={"gross_margin": 45.6})]
        resp = _make_paginated_response(companies)
        ctx = _make_ctx(resp)
        result = await screen_companies(ctx, local_unemployment_trend="rising")
        assert "local unemployment trend: rising" in result
