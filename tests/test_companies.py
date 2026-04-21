"""Tests for company discovery tools."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from thesma.errors import ThesmaError

from thesma_mcp.tools.companies import (
    _format_labor_context,
    _parse_exchange,
    _render_exchange,
    get_company,
    search_companies,
)


def _make_paginated_response(items: list[dict[str, Any]], total: int | None = None) -> Any:
    """Create a mock PaginatedResponse-like object."""
    mock = MagicMock()
    data_items = []
    for item in items:
        m = MagicMock()
        for k, v in item.items():
            if k == "company_tier":
                # Make it behave like an enum
                tier_mock = MagicMock()
                tier_mock.value = v
                setattr(m, k, tier_mock)
            else:
                setattr(m, k, v)
        data_items.append(m)
    mock.data = data_items
    pag = MagicMock()
    pag.total = total if total is not None else len(items)
    mock.pagination = pag
    return mock


def _make_data_response(data: dict[str, Any]) -> Any:
    """Create a mock DataResponse-like object for get_company."""
    from types import SimpleNamespace

    # Use SimpleNamespace to avoid MagicMock auto-creating attributes
    ns_data: dict[str, Any] = {}
    for k, v in data.items():
        if k == "company_tier":
            tier_mock = MagicMock()
            tier_mock.value = v
            ns_data[k] = tier_mock
        elif k == "labor_context" and isinstance(v, dict):
            ns_data[k] = v
        else:
            ns_data[k] = v
    # Ensure labor_context defaults to None if not provided
    ns_data.setdefault("labor_context", None)
    ns_data.setdefault("model_extra", {})
    data_obj = SimpleNamespace(**ns_data)
    return SimpleNamespace(data=data_obj)


@pytest.fixture()
def mock_ctx() -> MagicMock:
    """Create a mock Context with AppContext."""
    ctx = MagicMock()
    app = MagicMock()
    app.client = MagicMock()
    app.resolver = AsyncMock()
    ctx.request_context.lifespan_context = app
    return ctx


def _app(ctx: MagicMock) -> Any:
    return ctx.request_context.lifespan_context


class TestSearchCompanies:
    async def test_name_query_returns_table(self, mock_ctx: MagicMock) -> None:
        """search_companies with name query returns formatted table."""
        app = _app(mock_ctx)
        # Ticker match returns nothing
        empty_resp = _make_paginated_response([])
        name_resp = _make_paginated_response(
            [
                {"cik": "0000320193", "ticker": "AAPL", "name": "Apple Inc.", "company_tier": "sp500"},
                {
                    "cik": "0001418121",
                    "ticker": "APLE",
                    "name": "Apple Hospitality REIT",
                    "company_tier": "russell1000",
                },
            ]
        )
        app.client.companies.list = AsyncMock(side_effect=[empty_resp, name_resp])
        result = await search_companies("apple", mock_ctx)
        assert "Apple Inc." in result
        assert "AAPL" in result
        assert "S&P 500" in result
        assert "Russell 1000" in result

    async def test_exact_ticker_match_first(self, mock_ctx: MagicMock) -> None:
        """search_companies tries exact ticker match first."""
        app = _app(mock_ctx)
        resp = _make_paginated_response(
            [{"cik": "0000320193", "ticker": "AAPL", "name": "Apple Inc.", "company_tier": "sp500"}]
        )
        app.client.companies.list = AsyncMock(return_value=resp)
        result = await search_companies("AAPL", mock_ctx)
        assert "Apple Inc." in result
        # Should only call once (ticker match succeeded)
        app.client.companies.list.assert_called_once()

    async def test_no_results(self, mock_ctx: MagicMock) -> None:
        """search_companies with no results returns helpful message."""
        app = _app(mock_ctx)
        empty = _make_paginated_response([])
        app.client.companies.list = AsyncMock(return_value=empty)
        result = await search_companies("xyznonexistent", mock_ctx)
        assert "No companies found" in result

    async def test_ticker_match_error_falls_back(self, mock_ctx: MagicMock) -> None:
        """search_companies falls back to name search when ticker match fails."""
        app = _app(mock_ctx)
        name_resp = _make_paginated_response(
            [{"cik": "0000320193", "ticker": "AAPL", "name": "Apple Inc.", "company_tier": "sp500"}]
        )
        app.client.companies.list = AsyncMock(side_effect=[ThesmaError("Not found"), name_resp])
        result = await search_companies("apple", mock_ctx)
        assert "Apple Inc." in result


class TestGetCompany:
    async def test_resolves_ticker_and_returns_details(self, mock_ctx: MagicMock) -> None:
        """get_company resolves ticker and returns formatted details."""
        app = _app(mock_ctx)
        app.resolver.resolve = AsyncMock(return_value="0000320193")
        app.client.companies.get = AsyncMock(
            return_value=_make_data_response(
                {
                    "cik": "0000320193",
                    "ticker": "AAPL",
                    "name": "Apple Inc.",
                    "sic_code": "3571",
                    "sic_description": "Electronic Computers",
                    "company_tier": "sp500",
                    "fiscal_year_end": "September (0930)",
                }
            )
        )
        result = await get_company("AAPL", mock_ctx)
        assert "Apple Inc. (AAPL)" in result
        assert "0000320193" in result
        assert "3571" in result
        assert "Electronic Computers" in result
        assert "S&P 500" in result
        assert "September (0930)" in result

    async def test_unknown_ticker(self, mock_ctx: MagicMock) -> None:
        """get_company with unknown ticker returns error message."""
        app = _app(mock_ctx)
        app.resolver.resolve = AsyncMock(
            side_effect=ThesmaError("No company found for ticker 'ZZZZ'. Try searching with search_companies.")
        )
        result = await get_company("ZZZZ", mock_ctx)
        assert "No company found" in result

    async def test_get_company_includes_labor_context(self, mock_ctx: MagicMock) -> None:
        """get_company with full labor_context renders all 3 sub-sections."""
        app = _app(mock_ctx)
        app.resolver.resolve = AsyncMock(return_value="0000320193")
        app.client.companies.get = AsyncMock(
            return_value=_make_data_response(
                {
                    "cik": "0000320193",
                    "ticker": "AAPL",
                    "name": "Apple Inc.",
                    "sic_code": "3571",
                    "sic_description": "Electronic Computers",
                    "company_tier": "sp500",
                    "fiscal_year_end": "September (0930)",
                    "labor_context": {
                        "industry": {
                            "naics_code": "334111",
                            "naics_description": "Electronic Computer Manufacturing",
                            "total_employment_thousands": 1234.5,
                            "employment_yoy_pct": 2.3,
                            "avg_hourly_earnings": 32.50,
                            "earnings_yoy_pct": 4.1,
                        },
                        "local_market": {
                            "county_fips": "06085",
                            "county_name": "Santa Clara County, CA",
                            "industry_employment": 45200,
                            "industry_wage_yoy_pct": 3.5,
                            "avg_weekly_wage": 1890,
                        },
                        "compensation_benchmark": {
                            "soc_code": "11-1011",
                            "soc_title": "Chief Executives",
                            "market_median_annual_wage": 206420,
                            "market_mean_annual_wage": 230540,
                            "market_75th_percentile": 239660,
                            "market_90th_percentile": 312890,
                            "comp_to_market_ratio": 145.2,
                            "reference_year": 2024,
                        },
                    },
                }
            )
        )
        result = await get_company("AAPL", mock_ctx)

        assert "## Labor Market Context" in result
        assert "Industry (NAICS 334111" in result
        assert "Local Market (Santa Clara County, CA)" in result
        assert "CEO Compensation Benchmark" in result
        assert "\u25b2 2.3%" in result
        assert "145.2x" in result
        assert "$32.50" in result

    async def test_get_company_null_labor_context(self, mock_ctx: MagicMock) -> None:
        """get_company with null labor_context omits the section entirely."""
        app = _app(mock_ctx)
        app.resolver.resolve = AsyncMock(return_value="0000320193")
        app.client.companies.get = AsyncMock(
            return_value=_make_data_response(
                {
                    "cik": "0000320193",
                    "ticker": "AAPL",
                    "name": "Apple Inc.",
                    "labor_context": None,
                }
            )
        )
        result = await get_company("AAPL", mock_ctx)

        assert "Labor Market Context" not in result
        assert "Apple Inc. (AAPL)" in result


class TestFormatLaborContext:
    def test_yoy_indicators(self) -> None:
        """_format_labor_context renders correct arrow indicators."""
        result = _format_labor_context(
            {
                "industry": {
                    "naics_code": "5112",
                    "naics_description": "Software Publishers",
                    "total_employment_thousands": 500.0,
                    "employment_yoy_pct": 2.3,
                    "avg_hourly_earnings": 45.00,
                    "earnings_yoy_pct": -1.5,
                },
            }
        )
        assert "\u25b2 2.3%" in result
        assert "\u25bc 1.5%" in result

    def test_null_yoy(self) -> None:
        """_format_labor_context with null YoY omits arrow indicator."""
        result = _format_labor_context(
            {
                "industry": {
                    "naics_code": "5112",
                    "naics_description": "Software Publishers",
                    "total_employment_thousands": 500.0,
                    "employment_yoy_pct": None,
                    "avg_hourly_earnings": 45.00,
                    "earnings_yoy_pct": None,
                },
            }
        )
        assert "\u25b2" not in result
        assert "\u25bc" not in result
        assert "500.0" in result


class TestSearchCompaniesExchangeDomicile:
    async def test_search_with_exchange_single(self, mock_ctx: MagicMock) -> None:
        app = _app(mock_ctx)
        empty = _make_paginated_response([])
        results = _make_paginated_response(
            [{"cik": "0000320193", "ticker": "AAPL", "name": "Apple Inc.", "company_tier": "sp500"}]
        )
        app.client.companies.list = AsyncMock(side_effect=[empty, results])
        await search_companies("apple", mock_ctx, exchange="nyse")
        # Second call is the name-search branch — assert it carried the filter.
        kwargs = app.client.companies.list.call_args_list[1].kwargs
        assert kwargs.get("exchange") == "nyse"

    async def test_search_with_exchange_multi_comma(self, mock_ctx: MagicMock) -> None:
        app = _app(mock_ctx)
        empty = _make_paginated_response([])
        results = _make_paginated_response(
            [{"cik": "0000320193", "ticker": "AAPL", "name": "Apple Inc.", "company_tier": "sp500"}]
        )
        app.client.companies.list = AsyncMock(side_effect=[empty, results])
        await search_companies("apple", mock_ctx, exchange="nyse, nasdaq")
        kwargs = app.client.companies.list.call_args_list[1].kwargs
        assert kwargs.get("exchange") == ["nyse", "nasdaq"]

    async def test_search_with_exchange_empty_string(self, mock_ctx: MagicMock) -> None:
        app = _app(mock_ctx)
        empty = _make_paginated_response([])
        results = _make_paginated_response(
            [{"cik": "0000320193", "ticker": "AAPL", "name": "Apple Inc.", "company_tier": "sp500"}]
        )
        app.client.companies.list = AsyncMock(side_effect=[empty, results])
        await search_companies("apple", mock_ctx, exchange="")
        kwargs = app.client.companies.list.call_args_list[1].kwargs
        assert kwargs.get("exchange") is None

    async def test_search_with_exchange_whitespace_only(self, mock_ctx: MagicMock) -> None:
        app = _app(mock_ctx)
        empty = _make_paginated_response([])
        results = _make_paginated_response(
            [{"cik": "0000320193", "ticker": "AAPL", "name": "Apple Inc.", "company_tier": "sp500"}]
        )
        app.client.companies.list = AsyncMock(side_effect=[empty, results])
        await search_companies("apple", mock_ctx, exchange="  ,  ")
        kwargs = app.client.companies.list.call_args_list[1].kwargs
        assert kwargs.get("exchange") is None

    async def test_search_with_domicile(self, mock_ctx: MagicMock) -> None:
        app = _app(mock_ctx)
        empty = _make_paginated_response([])
        results = _make_paginated_response(
            [{"cik": "0000320193", "ticker": "AAPL", "name": "Apple Inc.", "company_tier": "sp500"}]
        )
        app.client.companies.list = AsyncMock(side_effect=[empty, results])
        await search_companies("apple", mock_ctx, domicile="us")
        kwargs = app.client.companies.list.call_args_list[1].kwargs
        assert kwargs.get("domicile") == "us"

    async def test_search_table_renders_exchange_domicile(self, mock_ctx: MagicMock) -> None:
        from thesma._generated.models import Domicile, Exchange

        app = _app(mock_ctx)
        empty = _make_paginated_response([])
        results = _make_paginated_response(
            [
                {
                    "cik": "0000320193",
                    "ticker": "AAPL",
                    "name": "Apple Inc.",
                    "company_tier": "sp500",
                    "exchange": Exchange.NASDAQ,
                    "domicile": Domicile.us,
                }
            ]
        )
        app.client.companies.list = AsyncMock(side_effect=[empty, results])
        result = await search_companies("apple", mock_ctx)
        assert "Exchange" in result
        assert "Domicile" in result
        assert "NASDAQ" in result
        assert "Exchange.NASDAQ" not in result  # enum repr must not leak
        assert "us" in result

    async def test_search_table_renders_none_as_dash(self, mock_ctx: MagicMock) -> None:
        app = _app(mock_ctx)
        empty = _make_paginated_response([])
        results = _make_paginated_response(
            [
                {
                    "cik": "0000320193",
                    "ticker": "AAPL",
                    "name": "Apple Inc.",
                    "company_tier": "sp500",
                    "exchange": None,
                    "domicile": None,
                }
            ]
        )
        app.client.companies.list = AsyncMock(side_effect=[empty, results])
        result = await search_companies("apple", mock_ctx)
        assert "—" in result

    async def test_search_invalid_exchange_propagates_badrequest(self, mock_ctx: MagicMock) -> None:
        app = _app(mock_ctx)
        # Ticker branch fails first, then name-search raises BadRequestError.
        app.client.companies.list = AsyncMock(side_effect=[ThesmaError("pass"), ThesmaError("Invalid exchange 'amex'")])
        result = await search_companies("apple", mock_ctx, exchange="amex")
        assert "Invalid exchange" in result


class TestSearchCompaniesTaxonomyCurrency:
    async def test_search_companies_passes_taxonomy_both_branches(self, mock_ctx: MagicMock) -> None:
        """taxonomy filter must apply on BOTH the ticker-exact branch AND the name-search fallback."""
        app = _app(mock_ctx)
        empty = _make_paginated_response([])
        results = _make_paginated_response(
            [{"cik": "0001639920", "ticker": "SPOT", "name": "Spotify Technology S.A.", "company_tier": "russell1000"}]
        )
        app.client.companies.list = AsyncMock(side_effect=[empty, results])
        await search_companies("spotify", mock_ctx, taxonomy="ifrs-full")
        # Ticker branch (call_args_list[0]) must carry the filter.
        assert app.client.companies.list.call_args_list[0].kwargs.get("taxonomy") == "ifrs-full"
        # Name-search branch (call_args_list[1]) must also carry it.
        assert app.client.companies.list.call_args_list[1].kwargs.get("taxonomy") == "ifrs-full"

    async def test_search_companies_passes_currency_both_branches(self, mock_ctx: MagicMock) -> None:
        """currency filter must apply on BOTH branches."""
        app = _app(mock_ctx)
        empty = _make_paginated_response([])
        results = _make_paginated_response(
            [{"cik": "0001639920", "ticker": "SPOT", "name": "Spotify Technology S.A.", "company_tier": "russell1000"}]
        )
        app.client.companies.list = AsyncMock(side_effect=[empty, results])
        await search_companies("spotify", mock_ctx, currency="EUR")
        assert app.client.companies.list.call_args_list[0].kwargs.get("currency") == "EUR"
        assert app.client.companies.list.call_args_list[1].kwargs.get("currency") == "EUR"

    async def test_search_companies_taxonomy_and_currency_combined_both_branches(self, mock_ctx: MagicMock) -> None:
        """Combined filters must not cross-contaminate between branches.

        Regression guard: if taxonomy were dropped from the ticker branch, a
        US-GAAP ticker matching the query would surface despite an IFRS-only
        filter request — a silent false positive.
        """
        app = _app(mock_ctx)
        empty = _make_paginated_response([])
        results = _make_paginated_response(
            [{"cik": "0000320193", "ticker": "AAPL", "name": "Apple Inc.", "company_tier": "sp500"}]
        )
        app.client.companies.list = AsyncMock(side_effect=[empty, results])
        await search_companies("apple", mock_ctx, taxonomy="us-gaap", currency="USD")
        first = app.client.companies.list.call_args_list[0].kwargs
        second = app.client.companies.list.call_args_list[1].kwargs
        assert first.get("taxonomy") == "us-gaap"
        assert first.get("currency") == "USD"
        assert second.get("taxonomy") == "us-gaap"
        assert second.get("currency") == "USD"

    async def test_search_companies_omits_taxonomy_and_currency_when_none(self, mock_ctx: MagicMock) -> None:
        """Without filter kwargs, both branches forward None (no silent coercion)."""
        app = _app(mock_ctx)
        empty = _make_paginated_response([])
        results = _make_paginated_response(
            [{"cik": "0000320193", "ticker": "AAPL", "name": "Apple Inc.", "company_tier": "sp500"}]
        )
        app.client.companies.list = AsyncMock(side_effect=[empty, results])
        await search_companies("apple", mock_ctx)
        first = app.client.companies.list.call_args_list[0].kwargs
        second = app.client.companies.list.call_args_list[1].kwargs
        assert first.get("taxonomy") is None
        assert first.get("currency") is None
        assert second.get("taxonomy") is None
        assert second.get("currency") is None

    async def test_search_companies_ticker_branch_short_circuits_with_taxonomy(self, mock_ctx: MagicMock) -> None:
        """When the ticker branch hits, the name-search branch does not fire —
        but the filter still applies to the ticker branch.
        """
        app = _app(mock_ctx)
        hit = _make_paginated_response(
            [{"cik": "0000320193", "ticker": "AAPL", "name": "Apple Inc.", "company_tier": "sp500"}]
        )
        empty = _make_paginated_response([])
        # The second element is inert — short-circuit means the name-search
        # branch never fires. Including it is defensive in case a regression
        # introduces an unexpected second call.
        app.client.companies.list = AsyncMock(side_effect=[hit, empty])
        await search_companies("AAPL", mock_ctx, taxonomy="us-gaap")
        assert app.client.companies.list.call_args_list[0].kwargs.get("taxonomy") == "us-gaap"
        assert len(app.client.companies.list.call_args_list) == 1


class TestGetCompanyExchangeDomicile:
    async def test_get_company_renders_exchange_domicile(self, mock_ctx: MagicMock) -> None:
        app = _app(mock_ctx)
        app.resolver.resolve = AsyncMock(return_value="0000320193")
        app.client.companies.get = AsyncMock(
            return_value=_make_data_response(
                {
                    "name": "Apple Inc.",
                    "cik": "0000320193",
                    "ticker": "AAPL",
                    "sic_code": "3571",
                    "sic_description": "Electronic Computers",
                    "company_tier": "sp500",
                    "fiscal_year_end": "0930",
                    "exchange": "NASDAQ",
                    "domicile": "us",
                }
            )
        )
        result = await get_company("AAPL", mock_ctx)
        assert "Exchange:" in result
        assert "NASDAQ" in result
        assert "Domicile:" in result
        assert "us" in result

    async def test_get_company_null_exchange_domicile(self, mock_ctx: MagicMock) -> None:
        app = _app(mock_ctx)
        app.resolver.resolve = AsyncMock(return_value="0000320193")
        app.client.companies.get = AsyncMock(
            return_value=_make_data_response(
                {
                    "name": "Apple Inc.",
                    "cik": "0000320193",
                    "ticker": "AAPL",
                    "sic_code": "3571",
                    "sic_description": "Electronic Computers",
                    "company_tier": "sp500",
                    "fiscal_year_end": "0930",
                    "exchange": None,
                    "domicile": None,
                }
            )
        )
        result = await get_company("AAPL", mock_ctx)
        assert "Exchange:" in result
        assert "Domicile:" in result
        assert "—" in result


class TestParseExchangeHelper:
    def test_none_returns_none(self) -> None:
        assert _parse_exchange(None) is None

    def test_empty_string_returns_none(self) -> None:
        assert _parse_exchange("") is None

    def test_whitespace_only_returns_none(self) -> None:
        assert _parse_exchange("  ,  ") is None

    def test_single_item_returns_string(self) -> None:
        assert _parse_exchange("nyse") == "nyse"

    def test_multi_item_returns_list(self) -> None:
        assert _parse_exchange("nyse,nasdaq") == ["nyse", "nasdaq"]

    def test_strips_whitespace(self) -> None:
        assert _parse_exchange(" nyse , nasdaq ") == ["nyse", "nasdaq"]


class TestRenderExchangeHelper:
    def test_none_renders_dash(self) -> None:
        assert _render_exchange(None) == "—"

    def test_plain_string_passes_through(self) -> None:
        assert _render_exchange("NYSE") == "NYSE"

    def test_enum_member_renders_value(self) -> None:
        from thesma._generated.models import Exchange

        assert _render_exchange(Exchange.NYSE) == "NYSE"


# ---------------------------------------------------------------------------
# Lending context tests (MCP-21)
# ---------------------------------------------------------------------------


def _make_lending_response(
    *,
    labor_context: Any = "omit",
    lending_context: Any = "omit",
) -> Any:
    """Build a get_company response with optional labor/lending context."""
    from types import SimpleNamespace

    base = {
        "name": "Apple Inc.",
        "cik": "0000320193",
        "ticker": "AAPL",
        "sic_code": "3571",
        "sic_description": "Electronic Computers",
        "fiscal_year_end": "0930",
        "exchange": "NASDAQ",
        "domicile": "us",
    }
    tier_mock = MagicMock()
    tier_mock.value = "sp500"
    base["company_tier"] = tier_mock

    if labor_context != "omit":
        base["labor_context"] = labor_context
    else:
        base["labor_context"] = None
    if lending_context != "omit":
        base["lending_context"] = lending_context
    base.setdefault("model_extra", {})
    return SimpleNamespace(data=SimpleNamespace(**base))


def _populated_local_market_dict() -> dict[str, Any]:
    return {
        "county_fips": "06085",
        "county_name": "Santa Clara County",
        "county_fips_confidence": "high",
        "quarterly_loan_count": 312,
        "quarterly_total_amount": 64_000_000,
        "avg_loan_size": 205_000,
        "quarterly_yoy_change_pct": 7.1,
        "charge_off_rate_trailing_4q": 1.4,
        "top_industry_naics": "722511",
        "top_industry_name": "Restaurants",
        "data_period": "2025-Q3",
        "source": "SBA",
    }


def _populated_industry_lending_dict() -> dict[str, Any]:
    return {
        "naics_code": "3571",
        "naics_description": "Electronic Computers",
        "naics_match_level": "6-digit",
        "national_quarterly_loan_count": 1240,
        "national_quarterly_total_amount": 320_000_000,
        "national_avg_loan_size": 258_000,
        "national_yoy_change_pct": 5.4,
        "national_charge_off_rate_trailing_4q": 1.7,
        "data_period": "2025-Q3",
        "source": "SBA",
    }


class TestGetCompanyLendingContext:
    async def test_get_company_with_populated_lending_context(self, mock_ctx: MagicMock) -> None:
        app = _app(mock_ctx)
        app.resolver.resolve = AsyncMock(return_value="0000320193")
        app.client.companies.get = AsyncMock(
            return_value=_make_lending_response(
                lending_context={
                    "local_market": _populated_local_market_dict(),
                    "industry_lending": _populated_industry_lending_dict(),
                }
            )
        )
        result = await get_company("AAPL", mock_ctx)
        assert "## Lending Market Context" in result
        assert "**Local Market" in result
        assert "**Industry Lending" in result
        assert "06085" in result
        assert "3571" in result

    async def test_get_company_with_null_children(self, mock_ctx: MagicMock) -> None:
        app = _app(mock_ctx)
        app.resolver.resolve = AsyncMock(return_value="0000320193")
        app.client.companies.get = AsyncMock(
            return_value=_make_lending_response(lending_context={"local_market": None, "industry_lending": None})
        )
        result = await get_company("AAPL", mock_ctx)
        assert "## Lending Market Context" in result
        assert "no lending context available" in result
        assert "**Local Market" not in result
        assert "**Industry Lending" not in result

    async def test_get_company_with_partial_local_only(self, mock_ctx: MagicMock) -> None:
        app = _app(mock_ctx)
        app.resolver.resolve = AsyncMock(return_value="0000320193")
        app.client.companies.get = AsyncMock(
            return_value=_make_lending_response(
                lending_context={"local_market": _populated_local_market_dict(), "industry_lending": None}
            )
        )
        result = await get_company("AAPL", mock_ctx)
        assert "**Local Market" in result
        assert "**Industry Lending" not in result

    async def test_get_company_omitted_lending_context_key(self, mock_ctx: MagicMock) -> None:
        app = _app(mock_ctx)
        app.resolver.resolve = AsyncMock(return_value="0000320193")
        app.client.companies.get = AsyncMock(return_value=_make_lending_response())  # both omitted
        result = await get_company("AAPL", mock_ctx)
        assert "## Lending Market Context" not in result

    async def test_get_company_empty_dict_lending_context(self, mock_ctx: MagicMock) -> None:
        app = _app(mock_ctx)
        app.resolver.resolve = AsyncMock(return_value="0000320193")
        app.client.companies.get = AsyncMock(return_value=_make_lending_response(lending_context={}))
        result = await get_company("AAPL", mock_ctx)
        assert "## Lending Market Context" not in result

    async def test_get_company_null_county_fips_with_confidence_unknown(self, mock_ctx: MagicMock) -> None:
        app = _app(mock_ctx)
        app.resolver.resolve = AsyncMock(return_value="0000320193")
        local = _populated_local_market_dict()
        local["county_fips"] = None
        local["county_name"] = None
        local["county_fips_confidence"] = "unknown"
        app.client.companies.get = AsyncMock(
            return_value=_make_lending_response(lending_context={"local_market": local, "industry_lending": None})
        )
        result = await get_company("AAPL", mock_ctx)
        assert "**Local Market (county unknown, FIPS \u2014)**" in result
        assert "Match Confidence: unknown" in result

    async def test_get_company_county_fips_confidence_unknown(self, mock_ctx: MagicMock) -> None:
        app = _app(mock_ctx)
        app.resolver.resolve = AsyncMock(return_value="0000320193")
        local = _populated_local_market_dict()
        local["county_fips_confidence"] = "unknown"
        app.client.companies.get = AsyncMock(
            return_value=_make_lending_response(lending_context={"local_market": local, "industry_lending": None})
        )
        result = await get_company("AAPL", mock_ctx)
        assert "Match Confidence: unknown" in result

    async def test_get_company_labor_and_lending_both_present(self, mock_ctx: MagicMock) -> None:
        app = _app(mock_ctx)
        app.resolver.resolve = AsyncMock(return_value="0000320193")
        app.client.companies.get = AsyncMock(
            return_value=_make_lending_response(
                labor_context={
                    "industry": {"naics_code": "3571", "naics_description": "Electronic Computers"},
                },
                lending_context={"local_market": _populated_local_market_dict(), "industry_lending": None},
            )
        )
        result = await get_company("AAPL", mock_ctx)
        assert "## Labor Market Context" in result
        assert "## Lending Market Context" in result

    async def test_get_company_labor_present_lending_absent(self, mock_ctx: MagicMock) -> None:
        app = _app(mock_ctx)
        app.resolver.resolve = AsyncMock(return_value="0000320193")
        app.client.companies.get = AsyncMock(
            return_value=_make_lending_response(
                labor_context={
                    "industry": {"naics_code": "3571", "naics_description": "Electronic Computers"},
                },
            )
        )
        result = await get_company("AAPL", mock_ctx)
        assert "## Labor Market Context" in result
        assert "## Lending Market Context" not in result

    async def test_get_company_lending_present_labor_absent(self, mock_ctx: MagicMock) -> None:
        app = _app(mock_ctx)
        app.resolver.resolve = AsyncMock(return_value="0000320193")
        app.client.companies.get = AsyncMock(
            return_value=_make_lending_response(
                lending_context={"local_market": _populated_local_market_dict(), "industry_lending": None}
            )
        )
        result = await get_company("AAPL", mock_ctx)
        assert "## Lending Market Context" in result
        assert "## Labor Market Context" not in result

    async def test_get_company_labor_context_output_format_unchanged(self, mock_ctx: MagicMock) -> None:
        """Regression: labor section markup is unchanged after include= expansion."""
        app = _app(mock_ctx)
        app.resolver.resolve = AsyncMock(return_value="0000320193")
        app.client.companies.get = AsyncMock(
            return_value=_make_lending_response(
                labor_context={
                    "industry": {
                        "naics_code": "3571",
                        "naics_description": "Electronic Computers",
                        "total_employment_thousands": 220.5,
                        "employment_yoy_pct": 2.4,
                    },
                    "local_market": {"county_name": "Santa Clara County"},
                    "compensation_benchmark": {
                        "soc_code": "11-1011",
                        "soc_title": "Chief Executives",
                        "market_median_annual_wage": 250_000,
                        "comp_to_market_ratio": 5.0,
                    },
                },
            )
        )
        result = await get_company("AAPL", mock_ctx)
        assert "**Industry (NAICS 3571" in result
        assert "**Local Market (Santa Clara County)**" in result
        assert "**CEO Compensation Benchmark**" in result

    async def test_get_company_forwards_include_both(self, mock_ctx: MagicMock) -> None:
        app = _app(mock_ctx)
        app.resolver.resolve = AsyncMock(return_value="0000320193")
        get_mock = AsyncMock(return_value=_make_lending_response())
        app.client.companies.get = get_mock
        await get_company("AAPL", mock_ctx)
        kwargs = get_mock.await_args.kwargs
        assert kwargs.get("include") == "labor_context,lending_context"
