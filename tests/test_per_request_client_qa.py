"""QA tests for MCP-13: per-request client migration.

These tests verify the per-request client pattern works end-to-end
for representative tools across all categories (SEC, BLS, Holdings).
Written from the spec without looking at dev implementation.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from thesma_mcp.server import AppContext

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_paginated_response(items: list[Any], total: int | None = None) -> MagicMock:
    """Create a mock PaginatedResponse-like object."""
    resp = MagicMock()
    resp.data = items
    resp.pagination = MagicMock()
    resp.pagination.total = total if total is not None else len(items)
    return resp


def _make_data_response(data: Any) -> MagicMock:
    """Create a mock DataResponse-like object."""
    resp = MagicMock()
    resp.data = data
    return resp


def _make_mock_client() -> MagicMock:
    """Create a mock AsyncThesmaClient with all sub-resources."""
    client = MagicMock()
    # SEC resources
    client.companies = MagicMock()
    client.companies.list = AsyncMock()
    client.companies.get = AsyncMock()
    client.screener = MagicMock()
    client.screener.screen = AsyncMock()
    # Holdings resources
    client.holdings = MagicMock()
    client.holdings.funds = AsyncMock()
    client.holdings.holders = AsyncMock()
    client.holdings.fund_holdings = AsyncMock()
    client.holdings.holder_changes = AsyncMock()
    client.holdings.fund_changes = AsyncMock()
    # BLS resources
    client.bls = MagicMock()
    client.bls.county_employment = AsyncMock()
    client.bls.county_wages = AsyncMock()
    return client


def _make_ctx_with_mock_client(mock_client: MagicMock) -> MagicMock:
    """Create a mock MCP context where get_client returns mock_client.

    The app.client is set to a DIFFERENT mock so we can verify tools
    use the per-request client (from get_client), not app.client.
    """
    ctx = MagicMock()
    app = MagicMock(spec=AppContext)
    # app.client is a different mock — tools should NOT use it
    app.client = MagicMock()
    app.resolver = MagicMock()
    app.resolver.resolve = AsyncMock(return_value="0000320193")
    ctx.request_context.lifespan_context = app
    return ctx


# ---------------------------------------------------------------------------
# SEC tool with resolver: get_company
# ---------------------------------------------------------------------------


class TestGetCompanyPerRequestClient:
    """Verify get_company uses per-request client from get_client(ctx)."""

    async def test_uses_per_request_client(self) -> None:
        """get_company should use per-request client for the companies.get call, not app.client."""
        mock_client = _make_mock_client()
        ctx = _make_ctx_with_mock_client(mock_client)
        app = ctx.request_context.lifespan_context

        # Set up the mock client to return company data
        company_data = SimpleNamespace(
            cik="0000320193",
            ticker="AAPL",
            name="Apple Inc.",
            sic_code="3571",
            sic_description="Electronic Computers",
            company_tier=MagicMock(value="sp500"),
            fiscal_year_end="September (0930)",
            labor_context=None,
            model_extra={},
        )
        mock_client.companies.get = AsyncMock(return_value=_make_data_response(company_data))

        with patch("thesma_mcp.tools.companies.get_client", return_value=mock_client):
            from thesma_mcp.tools.companies import get_company

            result = await get_company("AAPL", ctx)

        # The per-request mock client should have been used for the API call.
        # Post-MCP-36 the tool calls companies.get(ticker) directly — the api
        # resolves ticker to canonical CIK server-side via the path-param identifier.
        mock_client.companies.get.assert_called_once()
        assert mock_client.companies.get.call_args.args[0] == "AAPL"
        # The app.client should NOT have been used for companies.get
        app.client.companies.get.assert_not_called()

        # Should return formatted output
        assert "Apple Inc." in result


# ---------------------------------------------------------------------------
# SEC tool without resolver: screen_companies
# ---------------------------------------------------------------------------


class TestScreenCompaniesPerRequestClient:
    """Verify screen_companies uses per-request client from get_client(ctx)."""

    async def test_uses_per_request_client(self) -> None:
        """screen_companies should use per-request client for screener call."""
        mock_client = _make_mock_client()
        ctx = _make_ctx_with_mock_client(mock_client)
        app = ctx.request_context.lifespan_context

        # Set up screener response
        item = SimpleNamespace(
            cik="0000320193",
            ticker="AAPL",
            name="Apple Inc.",
            ratios=SimpleNamespace(gross_margin=45.6, net_margin=25.3, revenue_growth_yoy=8.1),
            bls=None,
            labor_context=None,
        )
        mock_client.screener.screen = AsyncMock(return_value=_make_paginated_response([item]))

        with patch("thesma_mcp.tools.screener.get_client", return_value=mock_client):
            from thesma_mcp.tools.screener import screen_companies

            result = await screen_companies(ctx)

        # Per-request client's screener should have been called
        mock_client.screener.screen.assert_called_once()
        # app.client.screener should NOT have been called
        app.client.screener.screen.assert_not_called()
        assert "AAPL" in result


# ---------------------------------------------------------------------------
# BLS tool: get_county_employment
# ---------------------------------------------------------------------------


class TestGetCountyEmploymentPerRequestClient:
    """Verify get_county_employment uses per-request client from get_client(ctx)."""

    async def test_uses_per_request_client(self) -> None:
        """get_county_employment should use per-request client for BLS call."""
        mock_client = _make_mock_client()
        ctx = _make_ctx_with_mock_client(mock_client)
        app = ctx.request_context.lifespan_context

        # Set up BLS county employment response
        emp_data = MagicMock()
        emp_data.year = 2024
        emp_data.quarter = 1
        emp_data.month1_employment = 345000
        emp_data.month2_employment = 347000
        emp_data.month3_employment = 350000
        emp_data.employment_yoy_pct = 2.5
        emp_data.establishment_count = 12500
        mock_client.bls.county_employment = AsyncMock(return_value=_make_paginated_response([emp_data]))

        with patch("thesma_mcp.tools.bls_counties.get_client", return_value=mock_client):
            from thesma_mcp.tools.bls_counties import get_county_employment

            result = await get_county_employment("12086", ctx)

        # Per-request client's BLS resource should have been called
        mock_client.bls.county_employment.assert_called_once()
        # app.client.bls should NOT have been called
        app.client.bls.county_employment.assert_not_called()
        assert "FIPS 12086" in result


# ---------------------------------------------------------------------------
# Holdings tool with _resolve_fund_cik: get_fund_holdings
# ---------------------------------------------------------------------------


class TestGetFundHoldingsPerRequestClient:
    """Verify get_fund_holdings uses per-request client for fund resolution and holdings."""

    async def test_uses_per_request_client_for_fund_resolution(self) -> None:
        """get_fund_holdings should use per-request client for fund search (resolution)."""
        mock_client = _make_mock_client()
        ctx = _make_ctx_with_mock_client(mock_client)
        app = ctx.request_context.lifespan_context

        # Set up fund search response (for _resolve_fund_cik)
        fund = MagicMock()
        fund.cik = "0001067983"
        fund.name = "BERKSHIRE HATHAWAY INC"
        mock_client.holdings.funds = AsyncMock(return_value=_make_paginated_response([fund]))

        # Set up fund holdings response
        holding = MagicMock()
        holding.held_company_name = "Apple Inc."
        holding.held_company_ticker = "AAPL"
        holding.shares = 400_000_000
        holding.market_value = 91_600_000_000
        mock_client.holdings.fund_holdings = AsyncMock(return_value=_make_paginated_response([holding], total=42))

        with patch("thesma_mcp.tools.holdings.get_client", return_value=mock_client):
            from thesma_mcp.tools.holdings import get_fund_holdings

            result = await get_fund_holdings("Berkshire Hathaway", ctx)

        # Per-request client's holdings.funds should have been called for fund resolution
        mock_client.holdings.funds.assert_called_once()
        # Per-request client's holdings.fund_holdings should have been called
        mock_client.holdings.fund_holdings.assert_called_once()
        # app.client should NOT have been used for either call
        app.client.holdings.funds.assert_not_called()
        app.client.holdings.fund_holdings.assert_not_called()
        assert "BERKSHIRE HATHAWAY" in result
        assert "AAPL" in result
