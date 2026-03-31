"""Tests for the screen_companies MCP tool."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from thesma_mcp.tools.screener import _build_summary_header, screen_companies


def _make_ctx(client_response: dict[str, Any]) -> MagicMock:
    """Create a mock MCP context with a mock client returning the given response."""
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=client_response)

    mock_resolver = AsyncMock()

    app = MagicMock()
    app.client = mock_client
    app.resolver = mock_resolver

    ctx = MagicMock()
    ctx.request_context.lifespan_context = app
    return ctx


def _screener_response(
    companies: list[dict[str, Any]] | None = None,
    total: int | None = None,
) -> dict[str, Any]:
    """Build a sample screener API response."""
    if companies is None:
        companies = [
            {
                "cik": "0000320193",
                "ticker": "AAPL",
                "name": "Apple Inc.",
                "ratios": {
                    "gross_margin": 45.6,
                    "operating_margin": 30.2,
                    "net_margin": 25.3,
                    "revenue_growth_yoy": 8.1,
                    "return_on_equity": 150.0,
                },
            },
            {
                "cik": "0000789019",
                "ticker": "MSFT",
                "name": "Microsoft Corporation",
                "ratios": {
                    "gross_margin": 69.4,
                    "operating_margin": 44.1,
                    "net_margin": 35.6,
                    "revenue_growth_yoy": 15.7,
                    "return_on_equity": 38.0,
                },
            },
        ]
    if total is None:
        total = len(companies)
    return {
        "data": companies,
        "pagination": {"page": 1, "per_page": 20, "total": total},
    }


@pytest.mark.asyncio
async def test_screen_no_filters() -> None:
    """screen_companies with no filters returns formatted table."""
    ctx = _make_ctx(_screener_response())
    result = await screen_companies(ctx)

    assert "AAPL" in result
    assert "MSFT" in result
    assert "Apple Inc." in result
    assert "All screened companies" in result


@pytest.mark.asyncio
async def test_screen_margin_and_growth_filters() -> None:
    """screen_companies with margin + growth filters builds correct query params."""
    ctx = _make_ctx(_screener_response())
    await screen_companies(ctx, min_gross_margin=40.0, min_revenue_growth=10.0)

    ctx.request_context.lifespan_context.client.get.assert_called_once()
    call_args = ctx.request_context.lifespan_context.client.get.call_args
    assert call_args[0][0] == "/v1/us/sec/screener"
    params = call_args.kwargs.get("params", {})
    assert params.get("min_gross_margin") == 40.0
    assert params.get("min_revenue_growth") == 10.0


@pytest.mark.asyncio
async def test_screen_tier_filter() -> None:
    """screen_companies with tier filter includes it in API call."""
    ctx = _make_ctx(_screener_response())
    result = await screen_companies(ctx, tier="sp500")

    assert "S&P 500" in result
    call_args = ctx.request_context.lifespan_context.client.get.call_args
    params = call_args.kwargs.get("params", {})
    assert params.get("tier") == "sp500"


@pytest.mark.asyncio
async def test_screen_sic_filter() -> None:
    """screen_companies with sic filter passes it to API."""
    ctx = _make_ctx(_screener_response())
    result = await screen_companies(ctx, sic="3571")

    assert "SIC 3571" in result
    call_args = ctx.request_context.lifespan_context.client.get.call_args
    params = call_args.kwargs.get("params", {})
    assert params.get("sic") == "3571"


@pytest.mark.asyncio
async def test_screen_insider_buying() -> None:
    """screen_companies with insider buying signal passes has_insider_buying=true."""
    ctx = _make_ctx(_screener_response())
    await screen_companies(ctx, has_insider_buying=True)

    call_args = ctx.request_context.lifespan_context.client.get.call_args
    params = call_args.kwargs.get("params", {})
    assert params.get("has_insider_buying") == "true"


@pytest.mark.asyncio
async def test_screen_insider_buying_false_omitted() -> None:
    """screen_companies with has_insider_buying=False omits it from API params."""
    ctx = _make_ctx(_screener_response())
    await screen_companies(ctx, has_insider_buying=False)

    call_args = ctx.request_context.lifespan_context.client.get.call_args
    params = call_args.kwargs.get("params", {})
    assert "has_insider_buying" not in params


@pytest.mark.asyncio
async def test_screen_sort_and_order() -> None:
    """screen_companies with sort and order passes both to API."""
    ctx = _make_ctx(_screener_response())
    result = await screen_companies(ctx, sort="gross_margin", order="asc")

    call_args = ctx.request_context.lifespan_context.client.get.call_args
    params = call_args.kwargs.get("params", {})
    assert params.get("sort") == "gross_margin"
    assert params.get("order") == "asc"
    assert "ascending" in result


@pytest.mark.asyncio
async def test_screen_without_sort_omits_param() -> None:
    """screen_companies without sort omits sort param."""
    ctx = _make_ctx(_screener_response())
    await screen_companies(ctx)

    call_args = ctx.request_context.lifespan_context.client.get.call_args
    params = call_args.kwargs.get("params", {})
    assert "sort" not in params


@pytest.mark.asyncio
async def test_screen_summary_header() -> None:
    """screen_companies summary header describes applied filters."""
    ctx = _make_ctx(_screener_response())
    result = await screen_companies(ctx, tier="sp500", min_gross_margin=40.0, min_revenue_growth=10.0)

    assert "S&P 500" in result
    assert "gross margin >= 40.0%" in result
    assert "revenue growth >= 10.0%" in result


@pytest.mark.asyncio
async def test_screen_no_matches() -> None:
    """screen_companies with no matches returns helpful message."""
    ctx = _make_ctx(_screener_response(companies=[], total=0))
    result = await screen_companies(ctx, min_gross_margin=99.0)

    assert "No companies matched" in result
    assert "broadening" in result


@pytest.mark.asyncio
async def test_screen_caps_limit() -> None:
    """screen_companies caps limit at 50."""
    ctx = _make_ctx(_screener_response())
    await screen_companies(ctx, limit=100)

    call_args = ctx.request_context.lifespan_context.client.get.call_args
    params = call_args.kwargs.get("params", {})
    assert params.get("per_page") == 50


def test_summary_header_no_filters() -> None:
    """Summary header with no filters returns generic label."""
    assert _build_summary_header({}) == "All screened companies"


def test_summary_header_multiple_filters() -> None:
    """Summary header with multiple filters joins them with 'and'."""
    header = _build_summary_header({"tier": "russell1000", "min_net_margin": 20})
    assert "Russell 1000" in header
    assert "net margin >= 20%" in header


# --- BLS filter tests (MCP-09) ---


def _screener_response_with_bls(
    companies: list[dict[str, Any]] | None = None,
    total: int | None = None,
) -> dict[str, Any]:
    """Build a screener response with BLS data."""
    if companies is None:
        companies = [
            {
                "cik": "0000320193",
                "ticker": "AAPL",
                "name": "Apple Inc.",
                "ratios": {"gross_margin": 45.6, "net_margin": 25.3},
                "bls": {
                    "industry": "Electronic Computers",
                    "hiring_trend": "accelerating",
                    "employment_growth": 3.2,
                    "comp_ratio": 12.5,
                },
            },
            {
                "cik": "0000789019",
                "ticker": "MSFT",
                "name": "Microsoft Corporation",
                "ratios": {"gross_margin": 69.4, "net_margin": 35.6},
                "bls": {
                    "industry": "Software Publishers",
                    "hiring_trend": "stable",
                    "employment_growth": 1.8,
                    "comp_ratio": 8.3,
                },
            },
        ]
    if total is None:
        total = len(companies)
    return {
        "data": companies,
        "pagination": {"page": 1, "per_page": 20, "total": total},
    }


@pytest.mark.asyncio
async def test_screen_companies_bls_filters() -> None:
    """screen_companies with BLS filters forwards them to API."""
    ctx = _make_ctx(_screener_response_with_bls())
    await screen_companies(ctx, industry_hiring_trend="accelerating", min_comp_to_market_ratio=2.0)

    call_args = ctx.request_context.lifespan_context.client.get.call_args
    params = call_args.kwargs.get("params", {})
    assert params.get("industry_hiring_trend") == "accelerating"
    assert params.get("min_comp_to_market_ratio") == 2.0


@pytest.mark.asyncio
async def test_screen_companies_bls_columns_shown() -> None:
    """screen_companies with BLS filter shows BLS columns in output."""
    ctx = _make_ctx(_screener_response_with_bls())
    result = await screen_companies(ctx, min_industry_employment_growth=1.0)

    assert "Industry" in result
    assert "Hiring Trend" in result
    assert "Emp Growth" in result
    assert "Comp Ratio" in result
    assert "accelerating" in result


@pytest.mark.asyncio
async def test_screen_companies_no_bls_columns_without_filters() -> None:
    """screen_companies without BLS filters omits BLS columns."""
    ctx = _make_ctx(_screener_response())
    result = await screen_companies(ctx, min_gross_margin=40.0)

    assert "Hiring Trend" not in result
    assert "Emp Growth" not in result


@pytest.mark.asyncio
async def test_screen_companies_all_bls_filters() -> None:
    """screen_companies forwards all 6 BLS filter params."""
    ctx = _make_ctx(_screener_response_with_bls())
    await screen_companies(
        ctx,
        industry_hiring_trend="declining",
        min_industry_employment_growth=1.0,
        max_industry_employment_growth=5.0,
        min_industry_wage_growth=2.0,
        min_hq_county_wage_growth=1.5,
        min_comp_to_market_ratio=3.0,
    )

    call_args = ctx.request_context.lifespan_context.client.get.call_args
    params = call_args.kwargs.get("params", {})
    assert params.get("industry_hiring_trend") == "declining"
    assert params.get("min_industry_employment_growth") == 1.0
    assert params.get("max_industry_employment_growth") == 5.0
    assert params.get("min_industry_wage_growth") == 2.0
    assert params.get("min_hq_county_wage_growth") == 1.5
    assert params.get("min_comp_to_market_ratio") == 3.0


@pytest.mark.asyncio
async def test_screen_companies_bls_filter_in_summary() -> None:
    """screen_companies with BLS filter mentions it in summary header."""
    ctx = _make_ctx(_screener_response_with_bls())
    result = await screen_companies(ctx, industry_hiring_trend="declining")

    assert "hiring trend: declining" in result
