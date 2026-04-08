"""Tests for institutional holdings tools."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

from thesma_mcp.tools.holdings import (
    get_fund_holdings,
    get_holding_changes,
    get_institutional_holders,
    search_funds,
)


def _make_paginated_response(items: list[MagicMock], total: int | None = None) -> MagicMock:
    resp = MagicMock()
    resp.data = items
    resp.pagination = MagicMock()
    resp.pagination.total = total if total is not None else len(items)
    return resp


def _make_fund(cik: str = "0001067983", name: str = "BERKSHIRE HATHAWAY INC") -> MagicMock:
    m = MagicMock()
    m.cik = cik
    m.name = name
    return m


def _make_holder(
    fund_name: str = "VANGUARD GROUP INC",
    shares: float = 1_250_300_000,
    market_value: float = 286_300_000_000,
    discretion: str = "shared",
) -> MagicMock:
    m = MagicMock()
    m.fund_name = fund_name
    m.shares = shares
    m.market_value = market_value
    disc = MagicMock()
    disc.value = discretion
    m.discretion = disc
    return m


def _make_fund_holding(
    held_company_name: str = "Apple Inc.",
    held_company_ticker: str = "AAPL",
    shares: float = 400_000_000,
    market_value: float = 91_600_000_000,
) -> MagicMock:
    m = MagicMock()
    m.held_company_name = held_company_name
    m.held_company_ticker = held_company_ticker
    m.shares = shares
    m.market_value = market_value
    return m


def _make_company_position_change(
    fund_name: str = "BRIDGEWATER ASSOCIATES",
    change_type: str = "new",
    share_delta: float | None = 2_500_000,
    pct_change: float | None = None,
    current_market_value: float | None = 572_500_000,
    quarter: str = "2024-Q3",
) -> MagicMock:
    m = MagicMock()
    m.fund_name = fund_name
    ct = MagicMock()
    ct.value = change_type
    m.change_type = ct
    m.share_delta = share_delta
    m.pct_change = pct_change
    m.current_market_value = current_market_value
    m.quarter = quarter
    return m


def _make_fund_position_change(
    held_company_name: str = "Sirius XM Holdings",
    held_company_ticker: str = "SIRI",
    change_type: str = "new",
    share_delta: float | None = 105_200_000,
    pct_change: float | None = None,
    current_market_value: float | None = 310_300_000,
    quarter: str = "2024-Q3",
) -> MagicMock:
    m = MagicMock()
    m.held_company_name = held_company_name
    m.held_company_ticker = held_company_ticker
    ct = MagicMock()
    ct.value = change_type
    m.change_type = ct
    m.share_delta = share_delta
    m.pct_change = pct_change
    m.current_market_value = current_market_value
    m.quarter = quarter
    return m


def _make_data_response(data: dict[str, Any]) -> MagicMock:
    resp = MagicMock()
    resp.data = MagicMock()
    for k, v in data.items():
        setattr(resp.data, k, v)
    return resp


def _make_ctx(
    resolve_cik: str = "0000320193",
) -> MagicMock:
    ctx = MagicMock()
    app = MagicMock()
    app.resolver = AsyncMock()
    app.resolver.resolve = AsyncMock(return_value=resolve_cik)
    app.client = MagicMock()
    # Default: fund search returns empty
    app.client.request = AsyncMock(return_value=_make_paginated_response([]))
    # Default: companies.get for holders title
    app.client.companies.get = AsyncMock(
        return_value=_make_data_response(
            {
                "name": "Apple Inc.",
                "ticker": "AAPL",
            }
        )
    )
    ctx.request_context.lifespan_context = app
    return ctx


class TestSearchFunds:
    async def test_returns_fund_list(self) -> None:
        """search_funds returns formatted fund list."""
        ctx = _make_ctx()
        funds = [_make_fund(), _make_fund("0001234567", "BERKSHIRE CAPITAL HOLDINGS LLC")]
        resp = _make_paginated_response(funds, total=2)
        ctx.request_context.lifespan_context.client.request = AsyncMock(return_value=resp)

        result = await search_funds("berkshire", ctx)
        assert "BERKSHIRE HATHAWAY" in result
        assert "0001067983" in result
        assert "Found 2 funds" in result

    async def test_no_results(self) -> None:
        """search_funds with no results returns helpful message."""
        ctx = _make_ctx()
        resp = _make_paginated_response([])
        ctx.request_context.lifespan_context.client.request = AsyncMock(return_value=resp)

        result = await search_funds("xyznonexistent", ctx)
        assert "No funds found" in result


class TestGetInstitutionalHolders:
    async def test_returns_formatted_table(self) -> None:
        """get_institutional_holders resolves ticker and returns formatted table."""
        ctx = _make_ctx()
        holders = [_make_holder()]
        resp = _make_paginated_response(holders, total=4521)
        ctx.request_context.lifespan_context.client.holdings.holders = AsyncMock(return_value=resp)

        result = await get_institutional_holders("AAPL", ctx)
        assert "Apple Inc. (AAPL)" in result
        assert "VANGUARD GROUP" in result
        assert "Shared" in result
        assert "4,521" in result

    async def test_no_holders(self) -> None:
        """get_institutional_holders with no holders returns helpful message."""
        ctx = _make_ctx()
        resp = _make_paginated_response([])
        ctx.request_context.lifespan_context.client.holdings.holders = AsyncMock(return_value=resp)

        result = await get_institutional_holders("AAPL", ctx)
        assert "No institutional holders" in result


class TestGetFundHoldings:
    async def test_resolves_fund_name(self) -> None:
        """get_fund_holdings resolves fund name to CIK via search."""
        ctx = _make_ctx()
        # Fund search response
        fund_resp = _make_paginated_response([_make_fund()])
        ctx.request_context.lifespan_context.client.request = AsyncMock(return_value=fund_resp)
        # Holdings response
        holdings = [_make_fund_holding()]
        holdings_resp = _make_paginated_response(holdings, total=42)
        ctx.request_context.lifespan_context.client.holdings.fund_holdings = AsyncMock(return_value=holdings_resp)

        result = await get_fund_holdings("Berkshire Hathaway", ctx)
        assert "BERKSHIRE HATHAWAY" in result
        assert "AAPL" in result
        assert "Apple Inc." in result

    async def test_fund_name_not_found(self) -> None:
        """get_fund_holdings with fund name returning no search results returns error."""
        ctx = _make_ctx()
        resp = _make_paginated_response([])
        ctx.request_context.lifespan_context.client.request = AsyncMock(return_value=resp)

        result = await get_fund_holdings("NonexistentFund", ctx)
        assert "No fund found" in result

    async def test_empty_portfolio(self) -> None:
        """get_fund_holdings with empty portfolio returns helpful message."""
        ctx = _make_ctx()
        fund_resp = _make_paginated_response([_make_fund()])
        ctx.request_context.lifespan_context.client.request = AsyncMock(return_value=fund_resp)
        ctx.request_context.lifespan_context.client.holdings.fund_holdings = AsyncMock(
            return_value=_make_paginated_response([])
        )

        result = await get_fund_holdings("Berkshire", ctx)
        assert "No holdings found" in result


class TestGetHoldingChanges:
    async def test_by_ticker(self) -> None:
        """get_holding_changes with ticker uses holder_changes."""
        ctx = _make_ctx()
        changes = [_make_company_position_change()]
        resp = _make_paginated_response(changes, total=312)
        ctx.request_context.lifespan_context.client.holdings.holder_changes = AsyncMock(return_value=resp)

        result = await get_holding_changes(ctx, ticker="AAPL")
        assert "BRIDGEWATER" in result
        assert "New" in result

    async def test_by_fund_name(self) -> None:
        """get_holding_changes with fund_name uses fund_changes."""
        ctx = _make_ctx()
        fund_resp = _make_paginated_response([_make_fund()])
        ctx.request_context.lifespan_context.client.request = AsyncMock(return_value=fund_resp)
        changes = [_make_fund_position_change()]
        resp = _make_paginated_response(changes, total=10)
        ctx.request_context.lifespan_context.client.holdings.fund_changes = AsyncMock(return_value=resp)

        result = await get_holding_changes(ctx, fund_name="Berkshire Hathaway")
        assert "BERKSHIRE HATHAWAY" in result
        assert "SIRI" in result
        assert "New" in result

    async def test_neither_provided(self) -> None:
        """get_holding_changes with neither ticker nor fund_name returns error."""
        ctx = _make_ctx()
        result = await get_holding_changes(ctx)
        assert "Provide exactly one" in result

    async def test_both_provided(self) -> None:
        """get_holding_changes with both ticker and fund_name returns error."""
        ctx = _make_ctx()
        result = await get_holding_changes(ctx, ticker="AAPL", fund_name="Berkshire")
        assert "Provide exactly one" in result

    async def test_no_changes(self) -> None:
        """get_holding_changes with no changes returns helpful message."""
        ctx = _make_ctx()
        resp = _make_paginated_response([])
        ctx.request_context.lifespan_context.client.holdings.holder_changes = AsyncMock(return_value=resp)

        result = await get_holding_changes(ctx, ticker="AAPL")
        assert "No position changes" in result
