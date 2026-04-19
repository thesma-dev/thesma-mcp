"""Tests for SBA 7(a) lending MCP tools."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from thesma.errors import ThesmaError

from thesma_mcp.tools.sba import (
    explore_sba_metrics,
    get_county_lending,
    get_industry_lending,
    get_lender,
    get_lenders,
    get_lending_characteristics,
    get_lending_outcomes,
    get_sba_metric_detail,
    get_state_lending,
)

# --- Mock factories ---


def _make_county_lending_point(**kwargs: Any) -> MagicMock:
    defaults: dict[str, Any] = {
        "year": 2025,
        "quarter": 3,
        "period": "2025-Q3",
        "county_fips": "06037",
        "loan_count": 512,
        "total_amount": 98_000_000,
        "avg_amount": 191_000,
        "median_amount": 150_000,
        "guaranteed_amount": 73_000_000,
        "avg_guarantee_pct": 74.5,
        "jobs_supported": 3200,
        "charge_off_count": 12,
        "charge_off_rate": 2.1,
        "charge_off_amount": 1_400_000,
        "naics_code": None,
        "naics_match_level": None,
        "source": "SBA",
    }
    defaults.update(kwargs)
    m = MagicMock()
    for k, v in defaults.items():
        setattr(m, k, v)
    return m


def _make_state_lending_point(**kwargs: Any) -> MagicMock:
    defaults: dict[str, Any] = {
        "year": 2025,
        "quarter": 3,
        "period": "2025-Q3",
        "state_fips": "06",
        "loan_count": 4200,
        "total_amount": 780_000_000,
        "avg_amount": 185_000,
        "median_amount": 140_000,
        "guaranteed_amount": 580_000_000,
        "avg_guarantee_pct": 74.4,
        "jobs_supported": 26000,
        "charge_off_count": 95,
        "charge_off_rate": 1.8,
        "charge_off_amount": 12_500_000,
        "source": "SBA",
    }
    defaults.update(kwargs)
    m = MagicMock()
    for k, v in defaults.items():
        setattr(m, k, v)
    return m


def _make_industry_lending_point(**kwargs: Any) -> MagicMock:
    defaults: dict[str, Any] = {
        "year": 2025,
        "quarter": 3,
        "period": "2025-Q3",
        "naics_code": "541211",
        "naics_match_level": "6-digit",
        "geo": "national",
        "state_fips": None,
        "county_fips": None,
        "loan_count": 620,
        "total_amount": 118_000_000,
        "avg_amount": 190_000,
        "avg_guarantee_pct": 74.5,
        "jobs_supported": 4100,
        "charge_off_rate": 1.9,
    }
    defaults.update(kwargs)
    m = MagicMock()
    for k, v in defaults.items():
        setattr(m, k, v)
    return m


def _make_lender_summary(**kwargs: Any) -> MagicMock:
    defaults: dict[str, Any] = {
        "lender_id": 1,
        "display_name": "Live Oak Banking Company",
        "city": "Wilmington",
        "state": "NC",
        "loan_count": 3200,
        "total_amount": 2_100_000_000,
        "avg_amount": 656_000,
        "market_share_pct": 9.4,
        "source": "SBA",
    }
    defaults.update(kwargs)
    m = MagicMock()
    for k, v in defaults.items():
        setattr(m, k, v)
    return m


def _make_lender_quarter_point(**kwargs: Any) -> MagicMock:
    defaults: dict[str, Any] = {
        "year": 2025,
        "quarter": 3,
        "period": "2025-Q3",
        "loan_count": 410,
        "total_amount": 275_000_000,
        "avg_amount": 671_000,
        "source": "SBA",
    }
    defaults.update(kwargs)
    m = MagicMock()
    for k, v in defaults.items():
        setattr(m, k, v)
    return m


def _make_lender_detail(history: list[Any] | None = None, **kwargs: Any) -> MagicMock:
    defaults: dict[str, Any] = {
        "lender_id": 1,
        "display_name": "Live Oak Banking Company",
        "city": "Wilmington",
        "state": "NC",
        "source": "SBA",
        "first_seen_at": "2010-Q1",
        "last_seen_at": "2025-Q3",
        "history": history if history is not None else [_make_lender_quarter_point()],
    }
    defaults.update(kwargs)
    m = MagicMock()
    for k, v in defaults.items():
        setattr(m, k, v)
    return m


def _make_bucket(label: str, loan_count: int = 100, total_amount: float = 10_000_000, pct: float = 10.0) -> MagicMock:
    m = MagicMock()
    m.label = label
    m.name = label
    m.loan_count = loan_count
    m.total_amount = total_amount
    m.pct = pct
    return m


def _make_characteristics(
    *,
    total_loans: int = 28341,
    year: int = 2025,
    quarter: int = 3,
    loan_size_buckets: list[Any] | None = None,
    term_length_buckets: list[Any] | None = None,
    interest_rate_histogram: list[Any] | None = None,
    sub_programme_mix: list[Any] | None = None,
    business_type_mix: list[Any] | None = None,
    revolving_vs_term: list[Any] | None = None,
) -> MagicMock:
    m = MagicMock()
    m.year = year
    m.quarter = quarter
    m.period = f"{year}-Q{quarter}"
    m.total_loans = total_loans
    m.filter_scope = {}
    m.loan_size_buckets = loan_size_buckets if loan_size_buckets is not None else [_make_bucket("<100K")]
    m.term_length_buckets = term_length_buckets if term_length_buckets is not None else [_make_bucket("<5y")]
    m.interest_rate_histogram = (
        interest_rate_histogram if interest_rate_histogram is not None else [_make_bucket("<5%")]
    )
    m.sub_programme_mix = sub_programme_mix if sub_programme_mix is not None else [_make_bucket("Standard")]
    m.business_type_mix = business_type_mix if business_type_mix is not None else [_make_bucket("Corporation")]
    m.revolving_vs_term = revolving_vs_term if revolving_vs_term is not None else [_make_bucket("Term")]
    return m


def _make_vintage_point(**kwargs: Any) -> MagicMock:
    defaults: dict[str, Any] = {
        "vintage_year": 2018,
        "loans_in_vintage": 54000,
        "charged_off_count": 3800,
        "charge_off_rate_pct": 7.0,
        "gross_charge_off_amount": 420_000_000,
        "avg_time_to_chargeoff_months": 38.5,
        "active_loan_count": 18000,
        "vintage_maturity": "mature",
    }
    defaults.update(kwargs)
    m = MagicMock()
    for k, v in defaults.items():
        setattr(m, k, v)
    return m


def _make_metric_summary(**kwargs: Any) -> MagicMock:
    defaults: dict[str, Any] = {
        "canonical_name": "loan_count_4q",
        "display_name": "Trailing 4Q Loan Count",
        "description": "Rolling four-quarter sum of SBA 7(a) loan count.",
        "category": "volume",
        "unit": "loans",
        "update_cadence": "quarterly",
        "typical_lag_months": 3,
    }
    defaults.update(kwargs)
    m = MagicMock()
    for k, v in defaults.items():
        setattr(m, k, v)
    return m


def _make_year_range(min_year: int | None = 2010, max_year: int | None = 2025) -> MagicMock:
    m = MagicMock()
    m.min = min_year
    m.max = max_year
    return m


def _make_metric_detail(
    *,
    data_availability: Any = "default",
    related_endpoints: list[str] | None = None,
    **kwargs: Any,
) -> MagicMock:
    summary = _make_metric_summary(**kwargs)
    summary.data_availability = _make_year_range() if data_availability == "default" else data_availability
    summary.related_endpoints = related_endpoints if related_endpoints is not None else ["/v1/sba/county-lending"]
    return summary


def _make_paginated(items: list[Any]) -> MagicMock:
    resp = MagicMock()
    resp.data = items
    resp.pagination = MagicMock()
    resp.pagination.total = len(items)
    return resp


def _make_data_response(data: Any) -> MagicMock:
    resp = MagicMock()
    resp.data = data
    return resp


def _make_ctx() -> MagicMock:
    app = MagicMock()
    app.client = MagicMock()
    ctx = MagicMock()
    ctx.request_context.lifespan_context = app
    return ctx


def _app(ctx: MagicMock) -> Any:
    return ctx.request_context.lifespan_context


# --- TestGetCountyLending ---


class TestGetCountyLending:
    @pytest.mark.asyncio
    async def test_latest_observation(self) -> None:
        ctx = _make_ctx()
        mock = AsyncMock(return_value=_make_paginated([_make_county_lending_point()]))
        _app(ctx).client.sba.county_lending = mock

        result = await get_county_lending("06037", ctx)

        assert "06037" in result
        assert "2025-Q3" in result
        assert "Source: US Small Business Administration, 7(a) Loan Program" in result
        kwargs = mock.await_args.kwargs
        assert kwargs.get("per_page") == 1
        assert "from_period" not in kwargs or kwargs.get("from_period") is None

    @pytest.mark.asyncio
    async def test_time_series(self) -> None:
        ctx = _make_ctx()
        rows = [
            _make_county_lending_point(year=2024, quarter=q, period=f"2024-Q{q}", loan_count=400 + q)
            for q in range(1, 5)
        ] + [
            _make_county_lending_point(year=2025, quarter=q, period=f"2025-Q{q}", loan_count=500 + q)
            for q in range(1, 4)
        ]
        mock = AsyncMock(return_value=_make_paginated(rows))
        _app(ctx).client.sba.county_lending = mock

        result = await get_county_lending("06037", ctx, from_period="2024-Q1", to_period="2025-Q3")

        assert "2024-Q1" in result
        assert "2025-Q3" in result
        kwargs = mock.await_args.kwargs
        assert kwargs["from_period"] == "2024-Q1"
        assert kwargs["to_period"] == "2025-Q3"

    @pytest.mark.asyncio
    async def test_only_from_period_rejected(self) -> None:
        ctx = _make_ctx()
        mock = AsyncMock()
        _app(ctx).client.sba.county_lending = mock

        result = await get_county_lending("06037", ctx, from_period="2024-Q1")

        assert "Both from_period and to_period are required" in result
        mock.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_bad_period_format_rejected(self) -> None:
        ctx = _make_ctx()
        mock = AsyncMock()
        _app(ctx).client.sba.county_lending = mock

        result = await get_county_lending("06037", ctx, from_period="2024-03", to_period="2025-03")

        assert "Invalid from_period format" in result
        assert "'2024-03'" in result
        mock.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_fips_zfilled(self) -> None:
        ctx = _make_ctx()
        mock = AsyncMock(return_value=_make_paginated([_make_county_lending_point()]))
        _app(ctx).client.sba.county_lending = mock

        await get_county_lending("6037", ctx)

        args, _ = mock.await_args
        assert args[0] == "06037"

    @pytest.mark.asyncio
    async def test_industry_filter_forwarded(self) -> None:
        ctx = _make_ctx()
        mock = AsyncMock(return_value=_make_paginated([_make_county_lending_point()]))
        _app(ctx).client.sba.county_lending = mock

        await get_county_lending("06037", ctx, industry="722511")

        kwargs = mock.await_args.kwargs
        assert kwargs["industry"] == "722511"

    @pytest.mark.asyncio
    async def test_thesma_error_propagates(self) -> None:
        ctx = _make_ctx()
        _app(ctx).client.sba.county_lending = AsyncMock(side_effect=ThesmaError("not found"))

        result = await get_county_lending("06037", ctx)

        assert result == "not found"


# --- TestGetStateLending ---


class TestGetStateLending:
    @pytest.mark.asyncio
    async def test_latest_observation(self) -> None:
        ctx = _make_ctx()
        mock = AsyncMock(return_value=_make_paginated([_make_state_lending_point()]))
        _app(ctx).client.sba.state_lending = mock

        result = await get_state_lending("06", ctx)

        assert "State FIPS 06" in result
        assert "2025-Q3" in result
        kwargs = mock.await_args.kwargs
        assert kwargs.get("per_page") == 1

    @pytest.mark.asyncio
    async def test_state_fips_zfilled(self) -> None:
        ctx = _make_ctx()
        mock = AsyncMock(return_value=_make_paginated([_make_state_lending_point()]))
        _app(ctx).client.sba.state_lending = mock

        await get_state_lending("6", ctx)

        args, _ = mock.await_args
        assert args[0] == "06"


# --- TestGetIndustryLending ---


class TestGetIndustryLending:
    @pytest.mark.asyncio
    async def test_geo_national_default(self) -> None:
        ctx = _make_ctx()
        mock = AsyncMock(return_value=_make_paginated([_make_industry_lending_point()]))
        _app(ctx).client.sba.industry_lending = mock

        await get_industry_lending("541211", ctx)

        kwargs = mock.await_args.kwargs
        assert kwargs["geo"] is None

    @pytest.mark.asyncio
    async def test_geo_state_with_state_param(self) -> None:
        ctx = _make_ctx()
        mock = AsyncMock(return_value=_make_paginated([_make_industry_lending_point(state_fips="06", geo="state")]))
        _app(ctx).client.sba.industry_lending = mock

        await get_industry_lending("541211", ctx, geo="state", state="06")

        kwargs = mock.await_args.kwargs
        assert kwargs["geo"] == "state"
        assert kwargs["state"] == "06"

    @pytest.mark.asyncio
    async def test_geo_county_with_county_param(self) -> None:
        ctx = _make_ctx()
        mock = AsyncMock(
            return_value=_make_paginated([_make_industry_lending_point(county_fips="06037", geo="county")])
        )
        _app(ctx).client.sba.industry_lending = mock

        await get_industry_lending("541211", ctx, geo="county", county="06037")

        kwargs = mock.await_args.kwargs
        assert kwargs["geo"] == "county"
        assert kwargs["county"] == "06037"

    @pytest.mark.asyncio
    async def test_bad_geo_propagates_api_error(self) -> None:
        ctx = _make_ctx()
        _app(ctx).client.sba.industry_lending = AsyncMock(side_effect=ThesmaError("Invalid geo 'bogus'"))

        result = await get_industry_lending("541211", ctx, geo="bogus")

        assert result == "Invalid geo 'bogus'"


# --- TestGetLenders ---


class TestGetLenders:
    @pytest.mark.asyncio
    async def test_default_sort(self) -> None:
        ctx = _make_ctx()
        mock = AsyncMock(return_value=_make_paginated([_make_lender_summary()]))
        _app(ctx).client.sba.lenders = mock

        await get_lenders(ctx)

        kwargs = mock.await_args.kwargs
        assert kwargs["sort"] == "loan_count"

    @pytest.mark.asyncio
    async def test_custom_sort_forwarded(self) -> None:
        ctx = _make_ctx()
        mock = AsyncMock(return_value=_make_paginated([_make_lender_summary()]))
        _app(ctx).client.sba.lenders = mock

        await get_lenders(ctx, sort="total_amount")

        kwargs = mock.await_args.kwargs
        assert kwargs["sort"] == "total_amount"

    @pytest.mark.asyncio
    async def test_limit_capped_at_50(self) -> None:
        ctx = _make_ctx()
        mock = AsyncMock(return_value=_make_paginated([_make_lender_summary()]))
        _app(ctx).client.sba.lenders = mock

        await get_lenders(ctx, limit=200)

        kwargs = mock.await_args.kwargs
        assert kwargs["per_page"] == 50

    @pytest.mark.asyncio
    async def test_output_table_has_market_share(self) -> None:
        ctx = _make_ctx()
        mock = AsyncMock(return_value=_make_paginated([_make_lender_summary(market_share_pct=5.4)]))
        _app(ctx).client.sba.lenders = mock

        result = await get_lenders(ctx)

        assert "5.40%" in result


# --- TestGetLender ---


class TestGetLender:
    @pytest.mark.asyncio
    async def test_basic(self) -> None:
        ctx = _make_ctx()
        detail = _make_lender_detail()
        mock = AsyncMock(return_value=_make_data_response(detail))
        _app(ctx).client.sba.lender = mock

        result = await get_lender(42, ctx)

        args, _ = mock.await_args
        assert args[0] == 42
        assert "Live Oak" in result
        assert "## Quarterly History" in result

    @pytest.mark.asyncio
    async def test_empty_history(self) -> None:
        ctx = _make_ctx()
        detail = _make_lender_detail(history=[])
        mock = AsyncMock(return_value=_make_data_response(detail))
        _app(ctx).client.sba.lender = mock

        result = await get_lender(42, ctx)

        assert "No quarterly history on record." in result

    @pytest.mark.asyncio
    async def test_missing_history_attr(self) -> None:
        ctx = _make_ctx()
        # Build a MagicMock and explicitly set history=None via delattr-ish approach
        detail = MagicMock(spec=["lender_id", "display_name", "city", "state", "first_seen_at", "last_seen_at"])
        detail.lender_id = 42
        detail.display_name = "Test Bank"
        detail.city = "Nowhere"
        detail.state = "NV"
        detail.first_seen_at = "2020-Q1"
        detail.last_seen_at = "2025-Q3"
        mock = AsyncMock(return_value=_make_data_response(detail))
        _app(ctx).client.sba.lender = mock

        result = await get_lender(42, ctx)

        assert "No quarterly history on record." in result

    @pytest.mark.asyncio
    async def test_period_filter_forwarded(self) -> None:
        ctx = _make_ctx()
        mock = AsyncMock(return_value=_make_data_response(_make_lender_detail()))
        _app(ctx).client.sba.lender = mock

        await get_lender(42, ctx, from_period="2024-Q1", to_period="2024-Q4")

        kwargs = mock.await_args.kwargs
        assert kwargs["from_period"] == "2024-Q1"
        assert kwargs["to_period"] == "2024-Q4"

    @pytest.mark.asyncio
    async def test_only_from_period_rejected_on_lender(self) -> None:
        ctx = _make_ctx()
        mock = AsyncMock()
        _app(ctx).client.sba.lender = mock

        result = await get_lender(42, ctx, from_period="2024-Q1")

        assert "Both from_period and to_period are required" in result
        mock.assert_not_awaited()


# --- TestGetLendingCharacteristics ---


class TestGetLendingCharacteristics:
    @pytest.mark.asyncio
    async def test_basic(self) -> None:
        ctx = _make_ctx()
        mock = AsyncMock(return_value=_make_data_response(_make_characteristics()))
        _app(ctx).client.sba.lending_characteristics = mock

        result = await get_lending_characteristics(ctx, year=2025, quarter=3)

        assert "### Loan Size Distribution" in result
        assert "### Term Length Distribution" in result
        assert "### Interest Rate Histogram" in result
        assert "### Sub-programme Mix" in result
        assert "### Business Type Mix" in result
        assert "### Revolving vs Term" in result

    @pytest.mark.asyncio
    async def test_skips_empty_subsections(self) -> None:
        ctx = _make_ctx()
        mock = AsyncMock(
            return_value=_make_data_response(
                _make_characteristics(
                    loan_size_buckets=[_make_bucket("<100K")],
                    term_length_buckets=[],
                )
            )
        )
        _app(ctx).client.sba.lending_characteristics = mock

        result = await get_lending_characteristics(ctx, year=2025, quarter=3)

        assert "### Loan Size Distribution" in result
        assert "### Term Length Distribution" not in result

    @pytest.mark.asyncio
    async def test_all_six_subsections_empty_fallback(self) -> None:
        ctx = _make_ctx()
        mock = AsyncMock(
            return_value=_make_data_response(
                _make_characteristics(
                    total_loans=28341,
                    loan_size_buckets=[],
                    term_length_buckets=[],
                    interest_rate_histogram=[],
                    sub_programme_mix=[],
                    business_type_mix=[],
                    revolving_vs_term=[],
                )
            )
        )
        _app(ctx).client.sba.lending_characteristics = mock

        result = await get_lending_characteristics(ctx, year=2025, quarter=3)

        assert "no distributional breakdowns available" in result
        assert "### Loan Size Distribution" not in result
        assert "### Term Length Distribution" not in result

    @pytest.mark.asyncio
    async def test_missing_year_propagates_api_400(self) -> None:
        ctx = _make_ctx()
        _app(ctx).client.sba.lending_characteristics = AsyncMock(side_effect=ThesmaError("year required"))

        result = await get_lending_characteristics(ctx, quarter=3)

        assert result == "year required"


# --- TestGetLendingOutcomes ---


class TestGetLendingOutcomes:
    @pytest.mark.asyncio
    async def test_basic(self) -> None:
        ctx = _make_ctx()
        mock = AsyncMock(return_value=_make_paginated([_make_vintage_point()]))
        _app(ctx).client.sba.lending_outcomes = mock

        result = await get_lending_outcomes(ctx, vintage_from=2018)

        assert "Vintage Outcomes" in result
        assert "mature" in result

    @pytest.mark.asyncio
    async def test_vintage_range_forwarded(self) -> None:
        ctx = _make_ctx()
        mock = AsyncMock(return_value=_make_paginated([_make_vintage_point()]))
        _app(ctx).client.sba.lending_outcomes = mock

        await get_lending_outcomes(ctx, vintage_from=2015, vintage_to=2020)

        kwargs = mock.await_args.kwargs
        assert kwargs["vintage_from"] == 2015
        assert kwargs["vintage_to"] == 2020

    @pytest.mark.asyncio
    async def test_missing_vintage_from_propagates_api_400(self) -> None:
        ctx = _make_ctx()
        _app(ctx).client.sba.lending_outcomes = AsyncMock(side_effect=ThesmaError("vintage_from required"))

        result = await get_lending_outcomes(ctx)

        assert result == "vintage_from required"


# --- TestExploreSbaMetrics ---


class TestExploreSbaMetrics:
    @pytest.mark.asyncio
    async def test_basic_list(self) -> None:
        ctx = _make_ctx()
        mock = AsyncMock(
            return_value=_make_paginated(
                [
                    _make_metric_summary(canonical_name="loan_count_4q"),
                    _make_metric_summary(canonical_name="total_amount_4q", display_name="Trailing 4Q Total Amount"),
                    _make_metric_summary(
                        canonical_name="charge_off_rate_4q", display_name="Trailing 4Q Charge-off Rate"
                    ),
                ]
            )
        )
        _app(ctx).client.sba.metrics = mock

        result = await explore_sba_metrics(ctx)

        assert "loan_count_4q" in result
        assert "total_amount_4q" in result
        assert "charge_off_rate_4q" in result

    @pytest.mark.asyncio
    async def test_category_filter_forwarded(self) -> None:
        ctx = _make_ctx()
        mock = AsyncMock(return_value=_make_paginated([_make_metric_summary()]))
        _app(ctx).client.sba.metrics = mock

        await explore_sba_metrics(ctx, category="volume")

        kwargs = mock.await_args.kwargs
        assert kwargs["category"] == "volume"

    @pytest.mark.asyncio
    async def test_query_param_maps_to_search(self) -> None:
        ctx = _make_ctx()
        mock = AsyncMock(return_value=_make_paginated([_make_metric_summary()]))
        _app(ctx).client.sba.metrics = mock

        await explore_sba_metrics(ctx, query="loan")

        kwargs = mock.await_args.kwargs
        assert kwargs["search"] == "loan"


# --- TestGetSbaMetricDetail ---


class TestGetSbaMetricDetail:
    @pytest.mark.asyncio
    async def test_basic(self) -> None:
        ctx = _make_ctx()
        mock = AsyncMock(return_value=_make_data_response(_make_metric_detail()))
        _app(ctx).client.sba.metric = mock

        result = await get_sba_metric_detail("loan_count_4q", ctx)

        assert "2010\u20132025" in result

    @pytest.mark.asyncio
    async def test_unavailable_data_availability(self) -> None:
        ctx = _make_ctx()
        mock = AsyncMock(return_value=_make_data_response(_make_metric_detail(data_availability=None)))
        _app(ctx).client.sba.metric = mock

        result = await get_sba_metric_detail("loan_count_4q", ctx)

        assert "unavailable" in result

    @pytest.mark.asyncio
    async def test_unknown_metric_propagates_404(self) -> None:
        ctx = _make_ctx()
        _app(ctx).client.sba.metric = AsyncMock(side_effect=ThesmaError("not found"))

        result = await get_sba_metric_detail("bogus_metric", ctx)

        assert result == "not found"
