"""Tests for the get_insider_trades MCP tool."""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest

from thesma_mcp.tools.insider_trades import get_insider_trades


def _make_trade(
    transaction_date: str = "2024-04-01",
    person_name: str = "Jeffrey E. Williams",
    person_title: str = "COO",
    shares: float = 100000,
    price_per_share: float | None = 171.48,
    total_value: float | None = 17148000,
    company_name: str = "Apple Inc.",
    company_ticker: str = "AAPL",
    is_planned_trade: bool = False,
) -> MagicMock:
    """Create a mock InsiderTradeListItem."""
    m = MagicMock()
    m.transaction_date = date.fromisoformat(transaction_date)
    person = MagicMock()
    person.name = person_name
    person.title = person_title
    m.person = person
    m.shares = shares
    m.price_per_share = price_per_share
    m.total_value = total_value
    m.company_name = company_name
    m.company_ticker = company_ticker
    m.is_planned_trade = is_planned_trade
    return m


def _make_paginated_response(items: list[MagicMock], total: int | None = None) -> MagicMock:
    resp = MagicMock()
    resp.data = items
    resp.pagination = MagicMock()
    resp.pagination.total = total if total is not None else len(items)
    return resp


def _make_ctx() -> MagicMock:
    """Create a mock MCP context."""
    app = MagicMock()
    app.client = MagicMock()
    app.resolver = AsyncMock()
    app.resolver.resolve = AsyncMock(return_value="0000320193")
    ctx = MagicMock()
    ctx.request_context.lifespan_context = app
    return ctx


@pytest.mark.asyncio
async def test_trades_with_ticker() -> None:
    """get_insider_trades with ticker scopes to company endpoint."""
    ctx = _make_ctx()
    trades = [_make_trade(), _make_trade(person_name="Luca Maestri", person_title="SVP, CFO", is_planned_trade=True)]
    resp = _make_paginated_response(trades, total=2)
    ctx.request_context.lifespan_context.client.insider_trades.list = AsyncMock(return_value=resp)

    result = await get_insider_trades(ctx, ticker="AAPL")

    assert "Apple Inc. (AAPL)" in result
    resolve_mock = ctx.request_context.lifespan_context.resolver.resolve
    resolve_mock.assert_called_once()
    assert resolve_mock.call_args[0][0] == "AAPL"


@pytest.mark.asyncio
async def test_trades_without_ticker() -> None:
    """get_insider_trades without ticker uses all-trades endpoint."""
    ctx = _make_ctx()
    trades = [_make_trade(), _make_trade(is_planned_trade=True)]
    resp = _make_paginated_response(trades, total=2)
    ctx.request_context.lifespan_context.client.insider_trades.list_all = AsyncMock(return_value=resp)

    result = await get_insider_trades(ctx)

    assert "Recent" in result


@pytest.mark.asyncio
async def test_trades_empty_ticker() -> None:
    """get_insider_trades with empty string ticker uses all-trades endpoint."""
    ctx = _make_ctx()
    trades = [_make_trade()]
    resp = _make_paginated_response(trades)
    ctx.request_context.lifespan_context.client.insider_trades.list_all = AsyncMock(return_value=resp)

    await get_insider_trades(ctx, ticker="")
    ctx.request_context.lifespan_context.client.insider_trades.list_all.assert_called_once()


@pytest.mark.asyncio
async def test_trades_invalid_type() -> None:
    """get_insider_trades with invalid type returns error listing valid types."""
    ctx = _make_ctx()
    result = await get_insider_trades(ctx, type="short_sell")

    assert "Invalid type 'short_sell'" in result
    assert "Valid types:" in result
    assert "purchase" in result
    assert "sale" in result


@pytest.mark.asyncio
async def test_trades_invalid_date() -> None:
    """get_insider_trades with invalid date format returns helpful error."""
    ctx = _make_ctx()
    result = await get_insider_trades(ctx, from_date="yesterday")

    assert "Invalid date format 'yesterday'" in result
    assert "YYYY-MM-DD" in result


@pytest.mark.asyncio
async def test_trades_company_scoped_shows_detail() -> None:
    """get_insider_trades company-scoped shows per-share detail."""
    ctx = _make_ctx()
    trades = [_make_trade()]
    resp = _make_paginated_response(trades, total=1)
    ctx.request_context.lifespan_context.client.insider_trades.list = AsyncMock(return_value=resp)

    result = await get_insider_trades(ctx, ticker="AAPL")

    assert "Shares" in result
    assert "Price" in result
    assert "Value" in result
    assert "100,000" in result
    assert "$171.48" in result


@pytest.mark.asyncio
async def test_trades_all_companies_shows_value_and_planned() -> None:
    """get_insider_trades all-companies shows total value and planned flag."""
    ctx = _make_ctx()
    trades = [_make_trade(), _make_trade(is_planned_trade=True)]
    resp = _make_paginated_response(trades, total=2)
    ctx.request_context.lifespan_context.client.insider_trades.list_all = AsyncMock(return_value=resp)

    result = await get_insider_trades(ctx)

    assert "Planned?" in result
    assert "Yes" in result
    assert "No" in result


@pytest.mark.asyncio
async def test_trades_no_results() -> None:
    """get_insider_trades with no results returns helpful message."""
    ctx = _make_ctx()
    resp = _make_paginated_response([], total=0)
    ctx.request_context.lifespan_context.client.insider_trades.list_all = AsyncMock(return_value=resp)

    result = await get_insider_trades(ctx, type="grant")
    assert "No insider trades found" in result
