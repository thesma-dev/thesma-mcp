"""Tests for institutional holdings tools."""

from __future__ import annotations

from datetime import UTC, datetime, timezone
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
    report_quarter: str = "2025-Q3",
    filed_at: datetime | None = None,
) -> MagicMock:
    m = MagicMock()
    m.fund_name = fund_name
    m.shares = shares
    m.market_value = market_value
    disc = MagicMock()
    disc.value = discretion
    m.discretion = disc
    # SDK-29 added required report_quarter + filed_at fields post-Wave-1.
    m.report_quarter = report_quarter
    m.filed_at = filed_at if filed_at is not None else datetime(2025, 11, 14, 16, 30, tzinfo=UTC)
    return m


def _make_fund_holding(
    held_company_name: str = "Apple Inc.",
    held_company_ticker: str = "AAPL",
    shares: float = 400_000_000,
    market_value: float = 91_600_000_000,
    report_quarter: str = "2025-Q3",
    filed_at: datetime | None = None,
) -> MagicMock:
    m = MagicMock()
    m.held_company_name = held_company_name
    m.held_company_ticker = held_company_ticker
    m.shares = shares
    m.market_value = market_value
    m.report_quarter = report_quarter
    m.filed_at = filed_at if filed_at is not None else datetime(2025, 11, 14, 16, 30, tzinfo=UTC)
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
    app.client.holdings.funds = AsyncMock(return_value=_make_paginated_response([]))
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
        ctx.request_context.lifespan_context.client.holdings.funds = AsyncMock(return_value=resp)

        result = await search_funds("berkshire", ctx)
        assert "BERKSHIRE HATHAWAY" in result
        assert "0001067983" in result
        assert "Found 2 funds" in result

    async def test_no_results(self) -> None:
        """search_funds with no results returns helpful message."""
        ctx = _make_ctx()
        resp = _make_paginated_response([])
        ctx.request_context.lifespan_context.client.holdings.funds = AsyncMock(return_value=resp)

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

    # --- MCP-24: SDK-29 temporal surfacing ---

    async def test_surfaces_report_quarter_from_row(self) -> None:
        """report_quarter + filed_at are read from the row, not the user input."""
        ctx = _make_ctx()
        holders = [_make_holder()]  # default report_quarter="2025-Q3"
        resp = _make_paginated_response(holders, total=1)
        ctx.request_context.lifespan_context.client.holdings.holders = AsyncMock(return_value=resp)

        result = await get_institutional_holders("AAPL", ctx)
        assert "Holdings as of 2025-Q3" in result
        assert "most recent filing submitted 2025-11-14" in result

    async def test_row_quarter_wins_over_user_input(self) -> None:
        """Row's report_quarter wins over the user's quarter kwarg (row is authoritative)."""
        ctx = _make_ctx()
        holders = [_make_holder(report_quarter="2025-Q3")]
        resp = _make_paginated_response(holders, total=1)
        ctx.request_context.lifespan_context.client.holdings.holders = AsyncMock(return_value=resp)

        result = await get_institutional_holders("AAPL", ctx, quarter="2024-Q4")
        assert "Holdings as of 2025-Q3" in result
        assert "2024-Q4" not in result

    async def test_most_recent_filed_at_max_reduction(self) -> None:
        """Footer filed_at picks the MAX across all rows (not first-row)."""
        ctx = _make_ctx()
        holders = [
            _make_holder(filed_at=datetime(2025, 11, 7, 0, 0, tzinfo=UTC)),
            _make_holder(filed_at=datetime(2025, 11, 14, 16, 30, tzinfo=UTC)),
            _make_holder(filed_at=datetime(2025, 11, 1, 0, 0, tzinfo=UTC)),
        ]
        resp = _make_paginated_response(holders, total=3)
        ctx.request_context.lifespan_context.client.holdings.holders = AsyncMock(return_value=resp)

        result = await get_institutional_holders("AAPL", ctx)
        assert "most recent filing submitted 2025-11-14" in result

    async def test_filed_at_normalizes_non_utc_offset(self) -> None:
        """Non-UTC aware datetime is converted to UTC before `.date()` is taken."""
        from datetime import timedelta

        ctx = _make_ctx()
        # 2025-11-14 23:30 at UTC-05:00 is already 2025-11-15 04:30 UTC.
        pacific_offset = timezone(timedelta(hours=-5))
        holders = [_make_holder(filed_at=datetime(2025, 11, 14, 23, 30, tzinfo=pacific_offset))]
        resp = _make_paginated_response(holders, total=1)
        ctx.request_context.lifespan_context.client.holdings.holders = AsyncMock(return_value=resp)

        result = await get_institutional_holders("AAPL", ctx)
        # Should be 2025-11-15 (UTC day), not 2025-11-14 (local day).
        assert "most recent filing submitted 2025-11-15" in result


class TestGetFundHoldings:
    async def test_resolves_fund_name(self) -> None:
        """get_fund_holdings resolves fund name to CIK via search."""
        ctx = _make_ctx()
        # Fund search response
        fund_resp = _make_paginated_response([_make_fund()])
        ctx.request_context.lifespan_context.client.holdings.funds = AsyncMock(return_value=fund_resp)
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
        ctx.request_context.lifespan_context.client.holdings.funds = AsyncMock(return_value=resp)

        result = await get_fund_holdings("NonexistentFund", ctx)
        assert "No fund found" in result

    async def test_empty_portfolio(self) -> None:
        """get_fund_holdings with empty portfolio returns helpful message."""
        ctx = _make_ctx()
        fund_resp = _make_paginated_response([_make_fund()])
        ctx.request_context.lifespan_context.client.holdings.funds = AsyncMock(return_value=fund_resp)
        ctx.request_context.lifespan_context.client.holdings.fund_holdings = AsyncMock(
            return_value=_make_paginated_response([])
        )

        result = await get_fund_holdings("Berkshire", ctx)
        assert "No holdings found" in result

    async def test_surfaces_report_quarter_and_filed_at(self) -> None:
        """get_fund_holdings mirrors the MCP-24 temporal surfacing pattern."""
        ctx = _make_ctx()
        fund_resp = _make_paginated_response([_make_fund()])
        ctx.request_context.lifespan_context.client.holdings.funds = AsyncMock(return_value=fund_resp)
        holdings = [_make_fund_holding()]
        holdings_resp = _make_paginated_response(holdings, total=42)
        ctx.request_context.lifespan_context.client.holdings.fund_holdings = AsyncMock(return_value=holdings_resp)

        result = await get_fund_holdings("Berkshire Hathaway", ctx)
        assert "Holdings as of 2025-Q3" in result
        assert "most recent filing submitted 2025-11-14" in result


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
        ctx.request_context.lifespan_context.client.holdings.funds = AsyncMock(return_value=fund_resp)
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

    async def test_unchanged_by_mcp24(self) -> None:
        """MCP-24 scope boundary: holding_changes does NOT get the temporal-surfacing
        treatment. CompanyPositionChange / FundPositionChange are derived delta rows,
        not raw 13F rows — they lack report_quarter / filed_at on the SDK side.
        """
        ctx = _make_ctx()
        changes = [_make_company_position_change()]
        resp = _make_paginated_response(changes, total=1)
        ctx.request_context.lifespan_context.client.holdings.holder_changes = AsyncMock(return_value=resp)

        result = await get_holding_changes(ctx, ticker="AAPL")
        # Existing "Position Changes, <quarter>" title format is preserved; the new
        # "Holdings as of ..." / "most recent filing submitted ..." lines are NOT
        # rendered on the holding-changes code path.
        assert "Position Changes, 2024-Q3" in result
        assert "Holdings as of" not in result
        assert "most recent filing submitted" not in result

    async def test_no_changes(self) -> None:
        """get_holding_changes with no changes returns helpful message."""
        ctx = _make_ctx()
        resp = _make_paginated_response([])
        ctx.request_context.lifespan_context.client.holdings.holder_changes = AsyncMock(return_value=resp)

        result = await get_holding_changes(ctx, ticker="AAPL")
        assert "No position changes" in result
