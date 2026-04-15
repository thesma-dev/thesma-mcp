"""QA tests for screener LAUS filter wiring (MCP-18).

Written from spec without looking at the dev implementation.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from thesma_mcp.tools.screener import screen_companies


def _make_screener_item(
    cik: str = "0000320193",
    ticker: str = "AAPL",
    name: str = "Apple Inc.",
    ratios: dict[str, float | None] | None = None,
    bls: dict[str, Any] | None = None,
    labor_context: Any = None,
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


def _make_paginated_response(items: list[Any], total: int | None = None) -> MagicMock:
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


# --- Param forwarding ---


@pytest.mark.asyncio
async def test_min_local_unemployment_rate_param_sent() -> None:
    """min_local_unemployment_rate is forwarded to the SDK call."""
    resp = _make_paginated_response([_make_screener_item(ratios={"gross_margin": 45.6})])
    ctx = _make_ctx(resp)
    await screen_companies(ctx, min_local_unemployment_rate=5.0)
    sdk = ctx.request_context.lifespan_context.client.screener.screen
    assert sdk.call_args.kwargs.get("min_local_unemployment_rate") == 5.0


@pytest.mark.asyncio
async def test_max_local_unemployment_rate_param_sent() -> None:
    """max_local_unemployment_rate is forwarded to the SDK call."""
    resp = _make_paginated_response([_make_screener_item(ratios={"gross_margin": 45.6})])
    ctx = _make_ctx(resp)
    await screen_companies(ctx, max_local_unemployment_rate=8.0)
    sdk = ctx.request_context.lifespan_context.client.screener.screen
    assert sdk.call_args.kwargs.get("max_local_unemployment_rate") == 8.0


@pytest.mark.asyncio
async def test_local_unemployment_trend_param_sent() -> None:
    """local_unemployment_trend is forwarded to the SDK call."""
    resp = _make_paginated_response([_make_screener_item(ratios={"gross_margin": 45.6})])
    ctx = _make_ctx(resp)
    await screen_companies(ctx, local_unemployment_trend="rising")
    sdk = ctx.request_context.lifespan_context.client.screener.screen
    assert sdk.call_args.kwargs.get("local_unemployment_trend") == "rising"


@pytest.mark.asyncio
async def test_min_local_labor_force_param_sent() -> None:
    """min_local_labor_force is forwarded to the SDK call."""
    resp = _make_paginated_response([_make_screener_item(ratios={"gross_margin": 45.6})])
    ctx = _make_ctx(resp)
    await screen_companies(ctx, min_local_labor_force=500000)
    sdk = ctx.request_context.lifespan_context.client.screener.screen
    assert sdk.call_args.kwargs.get("min_local_labor_force") == 500000


# --- Column rendering ---


@pytest.mark.asyncio
async def test_laus_columns_in_table_nested_shape() -> None:
    """LAUS columns rendered when filter active; reads nested labor_context.local_market shape."""
    local_market = SimpleNamespace(
        county_name="Alameda County",
        unemployment_rate=4.2,
        labor_force=800000,
    )
    labor_context = SimpleNamespace(local_market=local_market)
    companies = [
        _make_screener_item(
            ratios={"gross_margin": 45.6},
            labor_context=labor_context,
        ),
    ]
    resp = _make_paginated_response(companies)
    ctx = _make_ctx(resp)
    result = await screen_companies(ctx, min_local_unemployment_rate=4.0)
    assert "Unemp Rate" in result
    assert "Labor Force" in result
    assert "County" in result
    assert "4.2%" in result
    assert "Alameda County" in result


@pytest.mark.asyncio
async def test_laus_columns_in_table_flat_shape() -> None:
    """LAUS columns rendered when labor_context is a flat dict (alternate access path)."""
    labor_context = {
        "local_market": {
            "county_name": "Harris County",
            "unemployment_rate": 5.4,
            "labor_force": 2400000,
        }
    }
    companies = [
        _make_screener_item(
            ratios={"gross_margin": 45.6},
            labor_context=labor_context,
        ),
    ]
    resp = _make_paginated_response(companies)
    ctx = _make_ctx(resp)
    result = await screen_companies(ctx, min_local_unemployment_rate=4.0)
    assert "Unemp Rate" in result
    assert "5.4%" in result
    assert "Harris County" in result


@pytest.mark.asyncio
async def test_laus_filter_in_summary_header() -> None:
    """LAUS filter is described in summary header line."""
    resp = _make_paginated_response([_make_screener_item(ratios={"gross_margin": 45.6})])
    ctx = _make_ctx(resp)
    result = await screen_companies(ctx, min_local_unemployment_rate=5.0)
    assert "local unemployment rate >= 5.0%" in result


@pytest.mark.asyncio
async def test_laus_trend_in_summary_header() -> None:
    """local_unemployment_trend appears in the summary header."""
    resp = _make_paginated_response([_make_screener_item(ratios={"gross_margin": 45.6})])
    ctx = _make_ctx(resp)
    result = await screen_companies(ctx, local_unemployment_trend="rising")
    assert "local unemployment trend: rising" in result
