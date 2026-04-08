"""Tests for company discovery tools."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from thesma.errors import ThesmaError

from thesma_mcp.tools.companies import _format_labor_context, get_company, search_companies


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
