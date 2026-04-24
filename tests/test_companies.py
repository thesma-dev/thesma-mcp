"""Tests for company discovery tools."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from thesma.errors import ThesmaError

from thesma_mcp.tools.companies import (
    _format_data_freshness_model_or_dict,
    _format_labor_context,
    _format_labor_context_model,
    _format_summary_model_or_dict,
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


# --- MCP-24: SDK-28 LaborContext.summary + data_freshness blocks ---


class TestLaborContextDerivedSignalsBlock:
    """Tests for `_format_summary_model_or_dict` — the new `**Derived Signals**` block
    appended to labor_context rendering by MCP-24.
    """

    def test_renders_all_four_fields_from_dict(self) -> None:
        lines = _format_summary_model_or_dict(
            {
                "industry_hiring_trend": "accelerating",
                "local_unemployment_trend": "improving",
                "comp_to_market_ratio": 1.12,
                "labour_market_tightness": 1.30,
            }
        )
        assert lines is not None
        rendered = "\n".join(lines)
        assert "**Derived Signals**" in rendered
        assert "Industry Hiring Trend: accelerating" in rendered
        assert "Local Unemployment Trend: improving" in rendered
        assert "Comp-to-Market Ratio: 1.1x" in rendered
        assert "Labour Market Tightness: 1.30 (tight)" in rendered

    def test_renders_from_model_path(self) -> None:
        """Model-path (Pydantic-typed labor_context.summary) renders identically."""
        from types import SimpleNamespace

        summary = SimpleNamespace(
            industry_hiring_trend="declining",
            local_unemployment_trend=None,
            comp_to_market_ratio=0.85,
            labour_market_tightness=0.70,
        )
        lines = _format_summary_model_or_dict(summary)
        assert lines is not None
        rendered = "\n".join(lines)
        assert "Industry Hiring Trend: declining" in rendered
        assert "Comp-to-Market Ratio: 0.8x" in rendered
        assert "Labour Market Tightness: 0.70 (loose)" in rendered
        # Null local_unemployment_trend is suppressed entirely
        assert "Local Unemployment Trend" not in rendered

    def test_suppresses_block_when_all_null(self) -> None:
        """All-null summary returns None so the caller can skip the header."""
        lines = _format_summary_model_or_dict(
            {
                "industry_hiring_trend": None,
                "local_unemployment_trend": None,
                "comp_to_market_ratio": None,
                "labour_market_tightness": None,
            }
        )
        assert lines is None

    def test_labour_market_tightness_bucket_balanced_no_suffix(self) -> None:
        """Tightness in the 1.0 ± 0.05 dead band gets no `(tight)` / `(loose)` suffix."""
        lines = _format_summary_model_or_dict({"labour_market_tightness": 1.00})
        assert lines is not None
        rendered = "\n".join(lines)
        assert "Labour Market Tightness: 1.00" in rendered
        assert "(tight)" not in rendered
        assert "(loose)" not in rendered

    def test_empty_string_hiring_trend_still_renders(self) -> None:
        """Classification label of "" should render, not be silently suppressed."""
        lines = _format_summary_model_or_dict({"industry_hiring_trend": ""})
        assert lines is not None
        rendered = "\n".join(lines)
        # The empty-string value produces a "Industry Hiring Trend: " line —
        # the operator sees the shape rather than a silent suppression.
        assert "Industry Hiring Trend:" in rendered


class TestDataFreshnessBlock:
    """Tests for `_format_data_freshness_model_or_dict`."""

    def test_renders_all_six_periods(self) -> None:
        lines = _format_data_freshness_model_or_dict(
            {
                "ces_period": "2025-11",
                "qcew_period": "2025-Q2",
                "jolts_period": "2025-10",
                "laus_period": "2025-11",
                "oews_period": "2024",
                "sec_exec_comp_snapshot_date": "2025-03-15",
            }
        )
        assert lines is not None
        rendered = "\n".join(lines)
        assert "**Data Freshness**" in rendered
        assert "CES: 2025-11" in rendered
        assert "QCEW: 2025-Q2" in rendered
        assert "JOLTS: 2025-10" in rendered
        assert "LAUS: 2025-11" in rendered
        assert "OEWS: 2024" in rendered
        assert "SEC Exec Comp Snapshot: 2025-03-15" in rendered

    def test_renders_partial(self) -> None:
        lines = _format_data_freshness_model_or_dict(
            {
                "ces_period": "2025-11",
                "qcew_period": None,
                "jolts_period": None,
                "laus_period": None,
                "oews_period": None,
                "sec_exec_comp_snapshot_date": None,
            }
        )
        assert lines is not None
        rendered = "\n".join(lines)
        assert "CES: 2025-11" in rendered
        assert "QCEW" not in rendered
        assert "JOLTS" not in rendered

    def test_suppresses_block_when_all_null(self) -> None:
        lines = _format_data_freshness_model_or_dict(
            {
                "ces_period": None,
                "qcew_period": None,
                "jolts_period": None,
                "laus_period": None,
                "oews_period": None,
                "sec_exec_comp_snapshot_date": None,
            }
        )
        assert lines is None


class TestLaborContextAppendsSummaryAndFreshness:
    """Integration: `_format_labor_context` (dict) and `_format_labor_context_model`
    (model) both append the new blocks at the bottom of the labor_context section.
    """

    def test_dict_path_appends_both_blocks(self) -> None:
        rendered = _format_labor_context(
            {
                "industry": {"naics_code": "5112", "naics_description": "Software"},
                "summary": {
                    "industry_hiring_trend": "stable",
                    "comp_to_market_ratio": 1.12,
                },
                "data_freshness": {
                    "ces_period": "2025-11",
                    "oews_period": "2024",
                },
            }
        )
        # Existing industry block still renders first; new blocks append below.
        assert rendered.index("## Labor Market Context") < rendered.index("**Derived Signals**")
        assert rendered.index("**Derived Signals**") < rendered.index("**Data Freshness**")
        assert "CES: 2025-11" in rendered

    def test_comp_to_market_ratio_appears_in_both_blocks(self) -> None:
        """Intentional duplication per MCP-24 Architecture Decision #7: comp_to_market_ratio
        renders once in CEO Compensation Benchmark (alongside wage percentiles) AND once in
        Derived Signals (alongside other classification labels).
        """
        rendered = _format_labor_context(
            {
                "compensation_benchmark": {
                    "soc_code": "11-1011",
                    "soc_title": "Chief Executives",
                    "market_median_annual_wage": 250000,
                    "comp_to_market_ratio": 1.12,
                },
                "summary": {"comp_to_market_ratio": 1.12},
            }
        )
        # Derived Signals form
        assert "Comp-to-Market Ratio: 1.1x" in rendered
        # CEO Compensation Benchmark form (distinct label)
        assert "Company CEO Comp-to-Market: 1.1x" in rendered

    def test_model_path_appends_both_blocks(self) -> None:
        from types import SimpleNamespace

        labor_ctx = SimpleNamespace(
            industry=SimpleNamespace(
                naics_code="5112",
                naics_description="Software",
                total_employment_thousands=None,
                employment_yoy_pct=None,
                avg_hourly_earnings=None,
                earnings_yoy_pct=None,
            ),
            local_market=None,
            compensation_benchmark=None,
            summary=SimpleNamespace(
                industry_hiring_trend="accelerating",
                local_unemployment_trend=None,
                comp_to_market_ratio=None,
                labour_market_tightness=None,
            ),
            data_freshness=SimpleNamespace(
                ces_period="2025-11",
                qcew_period=None,
                jolts_period=None,
                laus_period=None,
                oews_period=None,
                sec_exec_comp_snapshot_date=None,
            ),
        )
        rendered = _format_labor_context_model(labor_ctx)
        assert "**Derived Signals**" in rendered
        assert "**Data Freshness**" in rendered
        assert "CES: 2025-11" in rendered

    def test_missing_summary_and_freshness_does_not_crash(self) -> None:
        """Backwards-compat: labor_context without the new sub-objects renders unchanged."""
        rendered = _format_labor_context(
            {
                "industry": {
                    "naics_code": "5112",
                    "naics_description": "Software",
                    "total_employment_thousands": 500.0,
                    "employment_yoy_pct": 2.3,
                },
            }
        )
        assert "**Derived Signals**" not in rendered
        assert "**Data Freshness**" not in rendered
        # Existing industry rendering is preserved.
        assert "500.0" in rendered


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


# --- MCP-27: include composition primitive (all 9 values, events enabled via T-215) ---


def _make_composed_response(extras: dict[str, Any]) -> Any:
    """Build a DataResponse-like object where inline expander payloads live in model_extra."""
    from types import SimpleNamespace

    data = SimpleNamespace(
        cik="0000320193",
        ticker="AAPL",
        name="Apple Inc.",
        sic_code="3571",
        sic_description="Electronic Computers",
        company_tier=SimpleNamespace(value="sp500"),
        fiscal_year_end="September (0930)",
        exchange=None,
        domicile=None,
        model_extra=extras,
    )
    return SimpleNamespace(data=data)


class TestGetCompanyIncludeValidation:
    async def test_unknown_include_value_returns_error(self, mock_ctx: MagicMock) -> None:
        app = _app(mock_ctx)
        app.resolver.resolve = AsyncMock(return_value="0000320193")
        result = await get_company("AAPL", mock_ctx, include="bogus")
        assert "Unknown include value(s): bogus" in result

    async def test_events_alone_renders_events_section(self, mock_ctx: MagicMock) -> None:
        """events slot as direct attribute on SimpleNamespace (NOT model_extra) —
        exercises the `getattr(data, "events", None)` path that
        `_resolve_slot_value` hits on real SDK responses since SDK-33 declared
        `EnrichedCompanyData.events: Any | None` as a typed field.
        """
        from types import SimpleNamespace

        app = _app(mock_ctx)
        app.resolver.resolve = AsyncMock(return_value="0000320193")
        data = SimpleNamespace(
            cik="0000320193",
            ticker="AAPL",
            name="Apple Inc.",
            sic_code="3571",
            sic_description="Electronic Computers",
            company_tier=SimpleNamespace(value="sp500"),
            fiscal_year_end="September (0930)",
            exchange=None,
            domicile=None,
            events=[
                {
                    "filing_accession": "0000320193-25-000012",
                    "filed_at": "2025-12-01T16:00:00+00:00",
                    "category": "earnings",
                    "items": [{"code": "2.02", "description": "Results of Operations and Financial Condition"}],
                }
            ],
            model_extra={},
        )
        app.client.companies.get = AsyncMock(return_value=SimpleNamespace(data=data))
        result = await get_company("AAPL", mock_ctx, include="events")
        assert "## Recent 8-K Events" in result
        assert "2025-12-01" in result
        assert "earnings" in result
        assert "2.02" in result

    async def test_events_in_combination_renders_all_sections(self, mock_ctx: MagicMock) -> None:
        """Combined payload (events as direct attribute + financials + ratios
        via model_extra). Asserts all three section headers render.
        """
        from types import SimpleNamespace

        app = _app(mock_ctx)
        app.resolver.resolve = AsyncMock(return_value="0000320193")
        data = SimpleNamespace(
            cik="0000320193",
            ticker="AAPL",
            name="Apple Inc.",
            sic_code="3571",
            sic_description="Electronic Computers",
            company_tier=SimpleNamespace(value="sp500"),
            fiscal_year_end="September (0930)",
            exchange=None,
            domicile=None,
            events=[
                {
                    "filing_accession": "0000320193-25-000012",
                    "filed_at": "2025-12-01T16:00:00+00:00",
                    "category": "earnings",
                    "items": [{"code": "2.02", "description": "Results of Operations and Financial Condition"}],
                }
            ],
            model_extra={
                "financials": {"line_items": {"revenue": 391_035_000_000}, "currency": "USD"},
                "ratios": {"gross_margin": 46.2},
            },
        )
        app.client.companies.get = AsyncMock(return_value=SimpleNamespace(data=data))
        result = await get_company("AAPL", mock_ctx, include="financials,events,ratios")
        assert "## Recent 8-K Events" in result
        assert "## Financials" in result
        assert "## Ratios" in result

    async def test_unknown_include_lists_events_as_valid_value(self, mock_ctx: MagicMock) -> None:
        """The `- {"events"}` exclusion was removed from the accepted_list, so
        the unknown-value error now lists `events` as a valid include value.
        """
        app = _app(mock_ctx)
        app.resolver.resolve = AsyncMock(return_value="0000320193")
        result = await get_company("AAPL", mock_ctx, include="bogus")
        assert "Unknown include value(s): bogus" in result
        assert "events" in result

    async def test_empty_include_returns_error(self, mock_ctx: MagicMock) -> None:
        app = _app(mock_ctx)
        app.resolver.resolve = AsyncMock(return_value="0000320193")
        result = await get_company("AAPL", mock_ctx, include=",,")
        assert "Unknown include value(s)" in result


class TestGetCompanyIncludeForwarding:
    async def test_default_include_preserves_legacy_behaviour(self, mock_ctx: MagicMock) -> None:
        """Backwards-compat: include=None forwards labor_context,lending_context."""
        app = _app(mock_ctx)
        app.resolver.resolve = AsyncMock(return_value="0000320193")
        mock_get = AsyncMock(return_value=_make_composed_response({}))
        app.client.companies.get = mock_get
        await get_company("AAPL", mock_ctx)
        assert mock_get.call_args.kwargs.get("include") == "labor_context,lending_context"

    async def test_include_forwarded_verbatim(self, mock_ctx: MagicMock) -> None:
        app = _app(mock_ctx)
        app.resolver.resolve = AsyncMock(return_value="0000320193")
        mock_get = AsyncMock(return_value=_make_composed_response({}))
        app.client.companies.get = mock_get
        await get_company("AAPL", mock_ctx, include="financials,ratios")
        assert mock_get.call_args.kwargs.get("include") == "financials,ratios"


class TestGetCompanyRendersInCanonicalOrder:
    async def test_sections_rendered_in_canonical_order_regardless_of_input(self, mock_ctx: MagicMock) -> None:
        """User passes board,financials,labor_context — output renders in
        canonical (labor → financials → board) order.
        """
        app = _app(mock_ctx)
        app.resolver.resolve = AsyncMock(return_value="0000320193")
        extras = {
            "labor_context": {"industry": {"naics_code": "334111"}},
            "financials": {"line_items": {"revenue": 391_035_000_000}, "currency": "USD"},
            "board": {"members": [{"name": "Arthur Levinson", "is_independent": True, "committees": []}]},
        }
        app.client.companies.get = AsyncMock(return_value=_make_composed_response(extras))
        result = await get_company("AAPL", mock_ctx, include="board,financials,labor_context")
        idx_labor = result.index("## Labor Market Context")
        idx_fin = result.index("## Financials")
        idx_board = result.index("## Board of Directors")
        assert idx_labor < idx_fin < idx_board


class TestGetCompanyPerExpanderTeasers:
    async def test_financials_teaser(self, mock_ctx: MagicMock) -> None:
        app = _app(mock_ctx)
        app.resolver.resolve = AsyncMock(return_value="0000320193")
        extras = {
            "financials": {
                "line_items": {
                    "revenue": 391_035_000_000,
                    "gross_profit": 173_535_000_000,
                    "net_income": 96_995_000_000,
                    "eps_diluted": 6.08,
                },
                "currency": "USD",
            }
        }
        app.client.companies.get = AsyncMock(return_value=_make_composed_response(extras))
        result = await get_company("AAPL", mock_ctx, include="financials")
        assert "## Financials" in result
        assert "Revenue:" in result
        assert "Gross Profit:" in result
        assert "Net Income:" in result
        assert "Currency: USD" in result

    async def test_ratios_teaser(self, mock_ctx: MagicMock) -> None:
        app = _app(mock_ctx)
        app.resolver.resolve = AsyncMock(return_value="0000320193")
        extras = {
            "ratios": {
                "gross_margin": 46.2,
                "operating_margin": 31.5,
                "net_margin": 26.4,
                "return_on_equity": 1.65,
                "debt_to_equity": 1.87,
                "current_ratio": 0.95,
            }
        }
        app.client.companies.get = AsyncMock(return_value=_make_composed_response(extras))
        result = await get_company("AAPL", mock_ctx, include="ratios")
        assert "## Ratios" in result
        assert "Gross Margin" in result
        assert "Debt-to-Equity" in result

    async def test_insider_trades_teaser(self, mock_ctx: MagicMock) -> None:
        app = _app(mock_ctx)
        app.resolver.resolve = AsyncMock(return_value="0000320193")
        extras = {
            "insider_trades": [
                {
                    "person": {"name": "Kress Colette"},
                    "transaction_date": "2026-03-20",
                    "type": "sale",
                    "total_value": 13_120_000.00,
                }
            ]
        }
        app.client.companies.get = AsyncMock(return_value=_make_composed_response(extras))
        result = await get_company("AAPL", mock_ctx, include="insider_trades")
        assert "## Insider Trades" in result
        assert "Kress Colette" in result
        assert "2026-03-20" in result

    async def test_holders_teaser_surfaces_report_quarter(self, mock_ctx: MagicMock) -> None:
        app = _app(mock_ctx)
        app.resolver.resolve = AsyncMock(return_value="0000320193")
        extras = {
            "holders": [
                {
                    "fund_name": "Vanguard Group Inc",
                    "shares": 1_200_000_000,
                    "market_value": 180_000_000_000,
                    "report_quarter": "2025-Q3",
                }
            ]
        }
        app.client.companies.get = AsyncMock(return_value=_make_composed_response(extras))
        result = await get_company("AAPL", mock_ctx, include="holders")
        assert "## Institutional Holders" in result
        assert "as of 2025-Q3" in result
        assert "Vanguard" in result

    async def test_compensation_teaser(self, mock_ctx: MagicMock) -> None:
        app = _app(mock_ctx)
        app.resolver.resolve = AsyncMock(return_value="0000320193")
        extras = {
            "compensation": {
                "executives": [
                    {"name": "Tim Cook", "title": "CEO", "compensation": {"total": 63_200_000}},
                    {"name": "Luca Maestri", "title": "CFO", "compensation": {"total": 25_000_000}},
                ],
                "pay_ratio": {"ratio": 1447},
            }
        }
        app.client.companies.get = AsyncMock(return_value=_make_composed_response(extras))
        result = await get_company("AAPL", mock_ctx, include="compensation")
        assert "## Executive Compensation" in result
        assert "Tim Cook" in result
        assert "1447" in result

    async def test_board_teaser(self, mock_ctx: MagicMock) -> None:
        app = _app(mock_ctx)
        app.resolver.resolve = AsyncMock(return_value="0000320193")
        extras = {
            "board": {
                "members": [
                    {
                        "name": "Arthur Levinson",
                        "is_independent": True,
                        "committees": ["Compensation"],
                    }
                ]
            }
        }
        app.client.companies.get = AsyncMock(return_value=_make_composed_response(extras))
        result = await get_company("AAPL", mock_ctx, include="board")
        assert "## Board of Directors" in result
        assert "Arthur Levinson" in result

    async def test_empty_insider_trades_list_renders_note(self, mock_ctx: MagicMock) -> None:
        app = _app(mock_ctx)
        app.resolver.resolve = AsyncMock(return_value="0000320193")
        app.client.companies.get = AsyncMock(return_value=_make_composed_response({"insider_trades": []}))
        result = await get_company("AAPL", mock_ctx, include="insider_trades")
        assert "## Insider Trades" in result
        assert "no recent insider trades" in result


class TestGetCompanyPartialFailure:
    async def test_error_slot_renders_warning(self, mock_ctx: MagicMock) -> None:
        app = _app(mock_ctx)
        app.resolver.resolve = AsyncMock(return_value="0000320193")
        extras = {"holders": {"error": {"code": "upstream_timeout", "message": "holders did not complete within 3.0s"}}}
        app.client.companies.get = AsyncMock(return_value=_make_composed_response(extras))
        result = await get_company("AAPL", mock_ctx, include="holders")
        assert "## Institutional Holders" in result
        assert "⚠" in result
        assert "upstream_timeout" in result
        assert "did not complete" in result

    async def test_mixed_success_and_error(self, mock_ctx: MagicMock) -> None:
        app = _app(mock_ctx)
        app.resolver.resolve = AsyncMock(return_value="0000320193")
        extras = {
            "financials": {"line_items": {"revenue": 391_035_000_000}, "currency": "USD"},
            "holders": {"error": {"code": "upstream_timeout", "message": "timeout"}},
        }
        app.client.companies.get = AsyncMock(return_value=_make_composed_response(extras))
        result = await get_company("AAPL", mock_ctx, include="financials,holders")
        # Both sections present — no short-circuit on first failure
        assert "## Financials" in result
        assert "Revenue:" in result
        assert "## Institutional Holders" in result
        assert "⚠" in result

    async def test_string_valued_error_falls_through_safely(self, mock_ctx: MagicMock) -> None:
        """Degenerate API response: error is a string, not a dict. The inner
        isinstance guard prevents _format_expander_error from crashing on
        error.get("code") and falls through to the inline-payload path.
        """
        app = _app(mock_ctx)
        app.resolver.resolve = AsyncMock(return_value="0000320193")
        extras = {"holders": {"error": "unexpected string shape"}}
        app.client.companies.get = AsyncMock(return_value=_make_composed_response(extras))
        result = await get_company("AAPL", mock_ctx, include="holders")
        # Should not crash; _render_expander's holders path handles the dict
        # (even though the shape is unexpected — the teaser formatter's
        # `isinstance(slot, list)` guard kicks in).
        assert "## Institutional Holders" in result


def _make_events_response(events_slot: Any, extras: dict[str, Any] | None = None) -> Any:
    """Build a DataResponse-like object with `events` as a direct attribute.

    This exercises the `getattr(data, "events", None)` path (not the
    model_extra fallback) — matches the shape SDK-33+ returns for events.
    """
    from types import SimpleNamespace

    return SimpleNamespace(
        data=SimpleNamespace(
            cik="0000320193",
            ticker="AAPL",
            name="Apple Inc.",
            sic_code="3571",
            sic_description="Electronic Computers",
            company_tier=SimpleNamespace(value="sp500"),
            fiscal_year_end="September (0930)",
            exchange=None,
            domicile=None,
            events=events_slot,
            model_extra=extras or {},
        )
    )


class TestGetCompanyEventsTeaser:
    async def test_events_empty_list_renders_placeholder(self, mock_ctx: MagicMock) -> None:
        """data.events = [] renders section header + placeholder — guards
        against `[]` accidentally dropping the section entirely.
        """
        app = _app(mock_ctx)
        app.resolver.resolve = AsyncMock(return_value="0000320193")
        app.client.companies.get = AsyncMock(return_value=_make_events_response([]))
        result = await get_company("AAPL", mock_ctx, include="events")
        assert "## Recent 8-K Events" in result
        assert "No recent 8-K filings." in result

    async def test_events_expander_error_renders_correct_title(self, mock_ctx: MagicMock) -> None:
        """Partial-failure shape: events slot is {"error": {...}}. Title must
        render as "## Recent 8-K Events" (from the titles dict), NOT "## events"
        (the fallback). Catches regression where the titles dict isn't updated.
        """
        app = _app(mock_ctx)
        app.resolver.resolve = AsyncMock(return_value="0000320193")
        error_slot = {
            "error": {
                "code": "upstream_timeout",
                "message": "events did not complete within 3.0s",
            }
        }
        app.client.companies.get = AsyncMock(return_value=_make_events_response(error_slot))
        result = await get_company("AAPL", mock_ctx, include="events")
        assert "## Recent 8-K Events" in result
        assert "## events" not in result  # fallback would render this
        assert "upstream_timeout" in result

    async def test_events_row_with_null_filed_at_does_not_crash(self, mock_ctx: MagicMock) -> None:
        """Defensive guard: filed_at=None must not raise; renders 'unknown date'
        placeholder and the rest of the section still renders cleanly.
        """
        app = _app(mock_ctx)
        app.resolver.resolve = AsyncMock(return_value="0000320193")
        events = [
            {
                "filing_accession": "0000320193-25-000099",
                "filed_at": None,
                "category": "earnings",
                "items": [{"code": "2.02", "description": "Results of Operations"}],
            }
        ]
        app.client.companies.get = AsyncMock(return_value=_make_events_response(events))
        result = await get_company("AAPL", mock_ctx, include="events")
        assert "## Recent 8-K Events" in result
        assert "unknown date" in result
        assert "earnings" in result
        assert "2.02" in result

    async def test_events_row_with_empty_items_does_not_crash(self, mock_ctx: MagicMock) -> None:
        """Defensive guard: items=[] must not raise IndexError. Row renders
        with just date + category (no code+description fragment per the
        renderer's deterministic choice).
        """
        app = _app(mock_ctx)
        app.resolver.resolve = AsyncMock(return_value="0000320193")
        events = [
            {
                "filing_accession": "0000320193-25-000100",
                "filed_at": "2025-12-01T16:00:00+00:00",
                "category": "earnings",
                "items": [],
            }
        ]
        app.client.companies.get = AsyncMock(return_value=_make_events_response(events))
        result = await get_company("AAPL", mock_ctx, include="events")
        assert "## Recent 8-K Events" in result
        assert "2025-12-01" in result
        assert "earnings" in result

    async def test_events_canonical_order_between_holders_and_compensation(self, mock_ctx: MagicMock) -> None:
        """Seed all 9 expander slots; scramble the requested order; assert
        canonical render order: idx_holders < idx_events < idx_compensation.
        Guards INCLUDE_RENDER_ORDER insertion position.
        """
        from types import SimpleNamespace

        app = _app(mock_ctx)
        app.resolver.resolve = AsyncMock(return_value="0000320193")
        events = [
            {
                "filing_accession": "0000320193-25-000012",
                "filed_at": "2025-12-01T16:00:00+00:00",
                "category": "earnings",
                "items": [{"code": "2.02", "description": "Results"}],
            }
        ]
        extras = {
            "labor_context": {"industry": {"naics_code": "334111"}},
            "lending_context": {"local_market": {"county_name": "Santa Clara County", "county_fips": "06085"}},
            "financials": {"line_items": {"revenue": 391_035_000_000}, "currency": "USD"},
            "ratios": {"gross_margin": 46.2},
            "insider_trades": [
                {
                    "person": {"name": "Jane Doe"},
                    "transaction_date": "2025-11-01",
                    "type": "sale",
                    "total_value": 1_000_000,
                }
            ],
            "holders": [
                {
                    "fund_name": "Vanguard",
                    "shares": 1_000_000,
                    "market_value": 150_000_000,
                    "report_quarter": "2025-Q3",
                }
            ],
            "compensation": {
                "executives": [{"name": "Tim Cook", "title": "CEO", "compensation": {"total": 63_200_000}}]
            },
            "board": {"members": [{"name": "Arthur Levinson", "is_independent": True, "committees": []}]},
        }
        data = SimpleNamespace(
            cik="0000320193",
            ticker="AAPL",
            name="Apple Inc.",
            sic_code="3571",
            sic_description="Electronic Computers",
            company_tier=SimpleNamespace(value="sp500"),
            fiscal_year_end="September (0930)",
            exchange=None,
            domicile=None,
            events=events,
            model_extra=extras,
        )
        app.client.companies.get = AsyncMock(return_value=SimpleNamespace(data=data))
        # Deliberately scrambled input order.
        result = await get_company(
            "AAPL",
            mock_ctx,
            include="board,events,holders,labor_context,lending_context,financials,ratios,insider_trades,compensation",
        )
        idx_holders = result.index("## Institutional Holders")
        idx_events = result.index("## Recent 8-K Events")
        idx_compensation = result.index("## Executive Compensation")
        assert idx_holders < idx_events < idx_compensation
