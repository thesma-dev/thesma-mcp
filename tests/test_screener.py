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


@pytest.mark.asyncio
async def test_screen_companies_passes_search() -> None:
    """search kwarg is forwarded to the underlying SDK screener call."""
    resp = _make_paginated_response(_default_companies())
    ctx = _make_ctx(resp)
    await screen_companies(ctx, search="AAPL")
    kwargs = ctx.request_context.lifespan_context.client.screener.screen.call_args.kwargs
    assert kwargs.get("search") == "AAPL"


def test_summary_header_search() -> None:
    """_build_summary_header renders the search term alongside other company filters."""
    header = _build_summary_header({"search": "AAPL"})
    assert 'search: "AAPL"' in header


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


class TestScreenerExchangeDomicileFilters:
    @pytest.mark.asyncio
    async def test_screen_exchange_single_param_sent(self) -> None:
        resp = _make_paginated_response(_default_companies())
        ctx = _make_ctx(resp)
        app = ctx.request_context.lifespan_context
        await screen_companies(ctx, exchange="nyse")
        assert app.client.screener.screen.call_args.kwargs.get("exchange") == "nyse"

    @pytest.mark.asyncio
    async def test_screen_exchange_multi_param_sent(self) -> None:
        resp = _make_paginated_response(_default_companies())
        ctx = _make_ctx(resp)
        app = ctx.request_context.lifespan_context
        await screen_companies(ctx, exchange="nyse,nasdaq")
        assert app.client.screener.screen.call_args.kwargs.get("exchange") == ["nyse", "nasdaq"]

    @pytest.mark.asyncio
    async def test_screen_domicile_param_sent(self) -> None:
        resp = _make_paginated_response(_default_companies())
        ctx = _make_ctx(resp)
        app = ctx.request_context.lifespan_context
        await screen_companies(ctx, domicile="us")
        assert app.client.screener.screen.call_args.kwargs.get("domicile") == "us"

    @pytest.mark.asyncio
    async def test_screen_exchange_and_domicile_combined(self) -> None:
        resp = _make_paginated_response(_default_companies())
        ctx = _make_ctx(resp)
        app = ctx.request_context.lifespan_context
        await screen_companies(ctx, tier="sp500", exchange="nyse", domicile="us")
        kwargs = app.client.screener.screen.call_args.kwargs
        assert kwargs.get("tier") == "sp500"
        assert kwargs.get("exchange") == "nyse"
        assert kwargs.get("domicile") == "us"

    @pytest.mark.asyncio
    async def test_screen_empty_exchange_not_forwarded(self) -> None:
        resp = _make_paginated_response(_default_companies())
        ctx = _make_ctx(resp)
        app = ctx.request_context.lifespan_context
        await screen_companies(ctx, exchange="")
        assert app.client.screener.screen.call_args.kwargs.get("exchange") is None

    @pytest.mark.asyncio
    async def test_screen_summary_header_includes_exchange_and_domicile(self) -> None:
        companies = [_make_screener_item(ratios={"gross_margin": 45.6})]
        resp = _make_paginated_response(companies)
        ctx = _make_ctx(resp)
        result = await screen_companies(ctx, exchange="nyse", domicile="us")
        assert "exchange: nyse" in result
        assert "domicile: us" in result

    @pytest.mark.asyncio
    async def test_screen_summary_header_multi_exchange(self) -> None:
        companies = [_make_screener_item(ratios={"gross_margin": 45.6})]
        resp = _make_paginated_response(companies)
        ctx = _make_ctx(resp)
        result = await screen_companies(ctx, exchange="nyse,nasdaq")
        assert "exchange in nyse, nasdaq" in result

    @pytest.mark.asyncio
    async def test_screen_table_renders_exchange_domicile_columns(self) -> None:
        item = _make_screener_item(ratios={"gross_margin": 45.6})
        item.exchange = "NYSE"
        item.domicile = "us"
        resp = _make_paginated_response([item])
        ctx = _make_ctx(resp)
        result = await screen_companies(ctx)
        assert "Exchange" in result
        assert "Domicile" in result
        assert "NYSE" in result
        assert "us" in result

    @pytest.mark.asyncio
    async def test_screen_table_renders_null_exchange_domicile_columns(self) -> None:
        item = _make_screener_item(ratios={"gross_margin": 45.6})
        item.exchange = None
        item.domicile = None
        resp = _make_paginated_response([item])
        ctx = _make_ctx(resp)
        result = await screen_companies(ctx)
        assert "Exchange" in result
        assert "Domicile" in result
        assert "—" in result

    @pytest.mark.asyncio
    async def test_screen_exchange_domicile_columns_always_render(self) -> None:
        """Columns render for every result, not only when the new filters are active."""
        item = _make_screener_item(ratios={"gross_margin": 45.6})
        item.exchange = "NYSE"
        item.domicile = "us"
        resp = _make_paginated_response([item])
        ctx = _make_ctx(resp)
        result = await screen_companies(ctx)  # no filters at all
        assert "Exchange" in result
        assert "Domicile" in result

    @pytest.mark.asyncio
    async def test_screen_preserves_jolts_columns_when_exchange_filter_active(self) -> None:
        """Regression: the new Exchange/Domicile columns must not displace the JOLTS column group."""
        item = _make_screener_item(
            ratios={"gross_margin": 45.6},
            labor_context={
                "industry_quits_rate": 2.5,
                "industry_openings_rate": 5.0,
                "labour_market_tightness": 1.8,
            },
        )
        item.exchange = "NYSE"
        item.domicile = "us"
        resp = _make_paginated_response([item])
        ctx = _make_ctx(resp)
        result = await screen_companies(ctx, exchange="nyse", min_industry_quits_rate=2.0)
        assert "Exchange" in result
        assert "Domicile" in result
        assert "Quits Rate" in result
        assert "Openings Rate" in result

    @pytest.mark.asyncio
    async def test_screen_preserves_laus_columns_when_domicile_filter_active(self) -> None:
        """Regression: the new Exchange/Domicile columns must not displace the LAUS column group."""
        item = _make_screener_item(
            ratios={"gross_margin": 45.6},
            labor_context={
                "local_market": {
                    "county_name": "Alameda County",
                    "unemployment_rate": 4.2,
                    "labor_force": 800_000,
                }
            },
        )
        item.exchange = "NYSE"
        item.domicile = "us"
        resp = _make_paginated_response([item])
        ctx = _make_ctx(resp)
        result = await screen_companies(ctx, domicile="us", min_local_unemployment_rate=4.0)
        assert "Exchange" in result
        assert "Domicile" in result
        assert "County" in result
        assert "Unemp Rate" in result
        assert "Alameda County" in result


# ---------------------------------------------------------------------------
# SBA filter / lending_context tests (MCP-21)
# ---------------------------------------------------------------------------


def _sba_lending_dict(**overrides: Any) -> dict[str, Any]:
    base = {
        "local_sba_loan_count_4q": 520,
        "local_sba_lending_growth_yoy": 8.4,
        "industry_sba_lending_growth_yoy": 6.1,
        "industry_sba_charge_off_rate": 1.9,
    }
    base.update(overrides)
    return base


def _make_sba_item(
    *,
    lending_context: Any = "default",
    data_freshness: Any = None,
    ratios: dict[str, float | None] | None = None,
) -> SimpleNamespace:
    """A ScreenerResultItem-shaped namespace with optional SBA enrichment."""
    ratios_data = ratios or {"gross_margin": 45.6}
    item = SimpleNamespace(
        cik="0000320193",
        ticker="AAPL",
        name="Apple Inc.",
        ratios=SimpleNamespace(**ratios_data),
        bls=None,
        labor_context=None,
        lending_context=_sba_lending_dict() if lending_context == "default" else lending_context,
        data_freshness=data_freshness,
    )
    return item


class TestScreenerSbaFilters:
    @pytest.mark.asyncio
    async def test_min_local_sba_loan_count_forwarded(self) -> None:
        resp = _make_paginated_response([_make_sba_item()])
        ctx = _make_ctx(resp)
        await screen_companies(ctx, min_local_sba_loan_count=100)
        kwargs = ctx.request_context.lifespan_context.client.screener.screen.await_args.kwargs
        assert kwargs["min_local_sba_loan_count"] == 100

    @pytest.mark.asyncio
    async def test_max_local_sba_loan_count_forwarded(self) -> None:
        resp = _make_paginated_response([_make_sba_item()])
        ctx = _make_ctx(resp)
        await screen_companies(ctx, max_local_sba_loan_count=1000)
        kwargs = ctx.request_context.lifespan_context.client.screener.screen.await_args.kwargs
        assert kwargs["max_local_sba_loan_count"] == 1000

    @pytest.mark.asyncio
    async def test_min_local_sba_lending_growth_forwarded(self) -> None:
        resp = _make_paginated_response([_make_sba_item()])
        ctx = _make_ctx(resp)
        await screen_companies(ctx, min_local_sba_lending_growth=5.0)
        kwargs = ctx.request_context.lifespan_context.client.screener.screen.await_args.kwargs
        assert kwargs["min_local_sba_lending_growth"] == 5.0

    @pytest.mark.asyncio
    async def test_max_local_sba_lending_growth_forwarded(self) -> None:
        resp = _make_paginated_response([_make_sba_item()])
        ctx = _make_ctx(resp)
        await screen_companies(ctx, max_local_sba_lending_growth=20.0)
        kwargs = ctx.request_context.lifespan_context.client.screener.screen.await_args.kwargs
        assert kwargs["max_local_sba_lending_growth"] == 20.0

    @pytest.mark.asyncio
    async def test_min_industry_sba_lending_growth_forwarded(self) -> None:
        resp = _make_paginated_response([_make_sba_item()])
        ctx = _make_ctx(resp)
        await screen_companies(ctx, min_industry_sba_lending_growth=3.5)
        kwargs = ctx.request_context.lifespan_context.client.screener.screen.await_args.kwargs
        assert kwargs["min_industry_sba_lending_growth"] == 3.5

    @pytest.mark.asyncio
    async def test_max_industry_sba_charge_off_rate_forwarded(self) -> None:
        resp = _make_paginated_response([_make_sba_item()])
        ctx = _make_ctx(resp)
        await screen_companies(ctx, max_industry_sba_charge_off_rate=10.0)
        kwargs = ctx.request_context.lifespan_context.client.screener.screen.await_args.kwargs
        assert kwargs["max_industry_sba_charge_off_rate"] == 10.0

    @pytest.mark.asyncio
    async def test_combined_sba_filters_forwarded(self) -> None:
        resp = _make_paginated_response([_make_sba_item()])
        ctx = _make_ctx(resp)
        result = await screen_companies(
            ctx,
            min_local_sba_loan_count=100,
            max_local_sba_loan_count=1000,
            min_local_sba_lending_growth=5.0,
            max_local_sba_lending_growth=20.0,
            min_industry_sba_lending_growth=3.5,
            max_industry_sba_charge_off_rate=10.0,
        )
        kwargs = ctx.request_context.lifespan_context.client.screener.screen.await_args.kwargs
        assert kwargs["min_local_sba_loan_count"] == 100
        assert kwargs["max_local_sba_loan_count"] == 1000
        assert kwargs["min_local_sba_lending_growth"] == 5.0
        assert kwargs["max_local_sba_lending_growth"] == 20.0
        assert kwargs["min_industry_sba_lending_growth"] == 3.5
        assert kwargs["max_industry_sba_charge_off_rate"] == 10.0
        assert "local SBA loan count" in result
        assert "local SBA lending growth" in result
        assert "industry SBA lending growth" in result
        assert "industry SBA charge-off rate" in result

    @pytest.mark.asyncio
    async def test_summary_header_includes_sba_filters(self) -> None:
        resp = _make_paginated_response([_make_sba_item()])
        ctx = _make_ctx(resp)
        result = await screen_companies(ctx, min_local_sba_loan_count=100, max_industry_sba_charge_off_rate=5.0)
        assert "local SBA loan count >= 100" in result
        assert "industry SBA charge-off rate <= 5.0%" in result

    @pytest.mark.asyncio
    async def test_sba_columns_render_when_sba_filter_active(self) -> None:
        resp = _make_paginated_response([_make_sba_item()])
        ctx = _make_ctx(resp)
        result = await screen_companies(ctx, min_local_sba_loan_count=100)
        assert "Local Loans (4Q)" in result
        assert "Local Growth" in result
        assert "Industry Growth" in result
        assert "Industry Charge-off" in result
        assert "520" in result
        assert "8.4%" in result
        assert "6.1%" in result
        assert "1.9%" in result

    @pytest.mark.asyncio
    async def test_sba_columns_render_when_include_lending_context(self) -> None:
        resp = _make_paginated_response([_make_sba_item()])
        ctx = _make_ctx(resp)
        result = await screen_companies(ctx, include="lending_context")
        assert "Local Loans (4Q)" in result
        assert "Industry Growth" in result

    @pytest.mark.asyncio
    async def test_sba_columns_render_when_include_combined(self) -> None:
        resp = _make_paginated_response([_make_sba_item()])
        ctx = _make_ctx(resp)
        result = await screen_companies(ctx, include="labor_context,lending_context")
        assert "Local Loans (4Q)" in result

    @pytest.mark.asyncio
    async def test_sba_columns_absent_when_no_sba_filter_no_include(self) -> None:
        resp = _make_paginated_response([_make_sba_item(lending_context=None)])
        ctx = _make_ctx(resp)
        result = await screen_companies(ctx)
        assert "Local Loans (4Q)" not in result
        assert "Industry Charge-off" not in result

    @pytest.mark.asyncio
    async def test_sba_null_lending_context_renders_na(self) -> None:
        resp = _make_paginated_response([_make_sba_item(lending_context=None)])
        ctx = _make_ctx(resp)
        result = await screen_companies(ctx, min_local_sba_loan_count=100)
        # Four N/A cells in the SBA block
        assert "Local Loans (4Q)" in result
        # Pull the data row substring (after the header separator "---")
        assert result.count("N/A") >= 4

    @pytest.mark.asyncio
    async def test_sba_partial_lending_context_renders_mixed(self) -> None:
        partial = {
            "local_sba_loan_count_4q": 520,
            "local_sba_lending_growth_yoy": None,
            "industry_sba_lending_growth_yoy": 6.1,
            "industry_sba_charge_off_rate": None,
        }
        resp = _make_paginated_response([_make_sba_item(lending_context=partial)])
        ctx = _make_ctx(resp)
        result = await screen_companies(ctx, min_local_sba_loan_count=100)
        assert "520" in result
        assert "6.1%" in result
        assert "N/A" in result

    @pytest.mark.asyncio
    async def test_sba_freshness_footer_line_present(self) -> None:
        resp = _make_paginated_response([_make_sba_item(data_freshness={"sba_period": "2025-Q4"})])
        ctx = _make_ctx(resp)
        result = await screen_companies(ctx, min_local_sba_loan_count=100)
        assert "SBA data as of 2025-Q4" in result

    @pytest.mark.asyncio
    async def test_sba_freshness_footer_absent_when_no_sba_active(self) -> None:
        resp = _make_paginated_response([_make_sba_item(data_freshness={"sba_period": "2025-Q4"})])
        ctx = _make_ctx(resp)
        result = await screen_companies(ctx)
        assert "SBA data as of" not in result

    @pytest.mark.asyncio
    async def test_include_param_forwarded(self) -> None:
        resp = _make_paginated_response([_make_sba_item()])
        ctx = _make_ctx(resp)
        await screen_companies(ctx, include="lending_context")
        kwargs = ctx.request_context.lifespan_context.client.screener.screen.await_args.kwargs
        assert kwargs["include"] == "lending_context"

    @pytest.mark.asyncio
    async def test_include_combined_param_forwarded(self) -> None:
        resp = _make_paginated_response([_make_sba_item()])
        ctx = _make_ctx(resp)
        await screen_companies(ctx, include="labor_context,lending_context")
        kwargs = ctx.request_context.lifespan_context.client.screener.screen.await_args.kwargs
        assert kwargs["include"] == "labor_context,lending_context"

    @pytest.mark.asyncio
    async def test_invalid_include_propagates_badrequest(self) -> None:
        from thesma.errors import ThesmaError

        resp = _make_paginated_response([_make_sba_item()])
        ctx = _make_ctx(resp)
        ctx.request_context.lifespan_context.client.screener.screen = AsyncMock(
            side_effect=ThesmaError("Invalid include 'bogus'")
        )
        result = await screen_companies(ctx, include="bogus")
        assert result == "Invalid include 'bogus'"

    @pytest.mark.asyncio
    async def test_lending_context_dict_shape_read(self) -> None:
        # Already covered by default — lending_context defaults to dict shape
        resp = _make_paginated_response([_make_sba_item()])
        ctx = _make_ctx(resp)
        result = await screen_companies(ctx, min_local_sba_loan_count=100)
        assert "520" in result

    @pytest.mark.asyncio
    async def test_lending_context_model_shape_read(self) -> None:
        # Build a SimpleNamespace simulating a typed Pydantic LendingContextSummary
        lc_model = SimpleNamespace(
            local_sba_loan_count_4q=520,
            local_sba_lending_growth_yoy=8.4,
            industry_sba_lending_growth_yoy=6.1,
            industry_sba_charge_off_rate=1.9,
        )
        resp = _make_paginated_response([_make_sba_item(lending_context=lc_model)])
        ctx = _make_ctx(resp)
        result = await screen_companies(ctx, min_local_sba_loan_count=100)
        assert "520" in result
        assert "8.4%" in result

    @pytest.mark.asyncio
    async def test_include_lending_context_alone_renders_columns_without_labor_context(self) -> None:
        item = _make_sba_item()
        item.labor_context = None
        resp = _make_paginated_response([item])
        ctx = _make_ctx(resp)
        result = await screen_companies(ctx, include="lending_context")
        assert "Local Loans (4Q)" in result
        # No JOLTS / LAUS / BLS column headers should appear
        assert "Quits Rate" not in result
        assert "Hiring Trend" not in result
        assert "Unemp Rate" not in result

    @pytest.mark.asyncio
    async def test_include_whitespace_and_duplicates_tolerated(self) -> None:
        resp = _make_paginated_response([_make_sba_item()])
        ctx = _make_ctx(resp)
        result = await screen_companies(ctx, include="labor_context, lending_context")
        assert "Local Loans (4Q)" in result

        resp2 = _make_paginated_response([_make_sba_item()])
        ctx2 = _make_ctx(resp2)
        result2 = await screen_companies(ctx2, include="lending_context,lending_context")
        assert "Local Loans (4Q)" in result2
        # Single column block (count of one of the unique header strings)
        assert result2.count("Local Loans (4Q)") == 1


class TestScreenerSbaRegression:
    @pytest.mark.asyncio
    async def test_laus_columns_still_render_when_sba_also_active(self) -> None:
        item = _make_sba_item()
        item.labor_context = {
            "local_market": {
                "county_name": "Santa Clara County",
                "unemployment_rate": 3.8,
                "labor_force": 1_080_000,
            }
        }
        item.exchange = "NASDAQ"
        item.domicile = "us"
        resp = _make_paginated_response([item])
        ctx = _make_ctx(resp)
        result = await screen_companies(ctx, min_local_unemployment_rate=2.0, min_local_sba_loan_count=100)
        assert "County" in result
        assert "Unemp Rate" in result
        assert "Labor Force" in result
        assert "Local Loans (4Q)" in result
        assert "Industry Charge-off" in result

    @pytest.mark.asyncio
    async def test_bls_labor_context_data_freshness_still_nested(self) -> None:
        item = _make_sba_item(data_freshness={"sba_period": "2025-Q4"})
        item.labor_context = SimpleNamespace(
            data_freshness=SimpleNamespace(ces_period="2025-11"),
            local_market=None,
        )
        resp = _make_paginated_response([item])
        ctx = _make_ctx(resp)
        result = await screen_companies(ctx, include="labor_context,lending_context")
        # SBA freshness footer present, no crash
        assert "SBA data as of 2025-Q4" in result
