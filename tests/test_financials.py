"""Tests for financial statement tools."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from thesma_mcp.tools.financials import get_financial_metric, get_financials


def _make_sdk_response(data: dict[str, Any]) -> Any:
    """Create a mock SDK DataResponse-like object."""
    mock = MagicMock()
    mock.data = MagicMock()
    for k, v in data.items():
        if isinstance(v, dict) and k in ("company", "metadata"):
            sub = MagicMock()
            for sk, sv in v.items():
                setattr(sub, sk, sv)
            setattr(mock.data, k, sub)
        elif isinstance(v, list) and k == "series":
            items = []
            for item_dict in v:
                item = MagicMock()
                for ik, iv in item_dict.items():
                    setattr(item, ik, iv)
                items.append(item)
            mock.data.series = items
        else:
            setattr(mock.data, k, v)
    return mock


@pytest.fixture()
def mock_ctx() -> MagicMock:
    """Create a mock Context with AppContext."""
    ctx = MagicMock()
    app = MagicMock()
    app.client = MagicMock()
    app.resolver = AsyncMock(return_value="0000320193")
    app.resolver.resolve = AsyncMock(return_value="0000320193")
    ctx.request_context.lifespan_context = app
    return ctx


def _app(ctx: MagicMock) -> Any:
    return ctx.request_context.lifespan_context


SAMPLE_INCOME = _make_sdk_response(
    {
        "company": {"cik": "0000320193", "ticker": "AAPL", "name": "Apple Inc."},
        "statement": "income",
        "period": "annual",
        "fiscal_year": 2024,
        "fiscal_quarter": None,
        "fiscal_year_end": None,
        "filing_accession": "0000320193-24-000123",
        "currency": "USD",
        "line_items": {
            "revenue": 391_035_000_000,
            "cost_of_revenue": 210_400_000_000,
            "gross_profit": 180_635_000_000,
            "operating_expenses": 57_500_000_000,
            "research_and_development": 29_900_000_000,
            "selling_general_admin": 27_600_000_000,
            "operating_income": 123_135_000_000,
            "interest_expense": 3_500_000_000,
            "pre_tax_income": 123_500_000_000,
            "income_tax_expense": 29_700_000_000,
            "net_income": 93_736_000_000,
            "eps_diluted": 6.08,
        },
        "metadata": {"source": "ixbrl", "data_completeness": 10, "expected_fields": 15, "source_tags": {}},
    }
)

SAMPLE_BALANCE_SHEET = _make_sdk_response(
    {
        "company": {"cik": "0000320193", "ticker": "AAPL", "name": "Apple Inc."},
        "statement": "balance-sheet",
        "period": "annual",
        "fiscal_year": 2024,
        "fiscal_quarter": None,
        "fiscal_year_end": None,
        "filing_accession": "0000320193-24-000123",
        "currency": "USD",
        "line_items": {
            "total_assets": 352_583_000_000,
            "current_assets": 133_293_000_000,
            "cash_and_equivalents": 29_943_000_000,
            "total_liabilities": 290_437_000_000,
            "total_equity": 62_146_000_000,
            "inventory": None,
            "goodwill": None,
        },
        "metadata": {"source": "ixbrl"},
    }
)

SAMPLE_CASH_FLOW = _make_sdk_response(
    {
        "company": {"cik": "0000320193", "ticker": "AAPL", "name": "Apple Inc."},
        "statement": "cash-flow",
        "period": "annual",
        "fiscal_year": 2024,
        "fiscal_quarter": None,
        "fiscal_year_end": None,
        "filing_accession": "0000320193-24-000123",
        "currency": "USD",
        "line_items": {
            "operating_cash_flow": 110_543_000_000,
            "investing_cash_flow": -7_077_000_000,
            "financing_cash_flow": -103_466_000_000,
            "capital_expenditures": -10_959_000_000,
            "dividends_paid": -15_025_000_000,
            "share_repurchases": -77_550_000_000,
            "net_change_in_cash": None,
        },
        "metadata": {"source": "ixbrl"},
    }
)


class TestGetFinancials:
    async def test_income_statement_with_margins(self, mock_ctx: MagicMock) -> None:
        """get_financials returns formatted income statement with margins."""
        _app(mock_ctx).client.financials.get = AsyncMock(return_value=SAMPLE_INCOME)
        result = await get_financials("AAPL", mock_ctx)
        assert "Income Statement" in result
        assert "FY 2024" in result
        assert "$391.0B" in result  # revenue
        assert "$6.08" in result  # EPS
        assert "(46.2%)" in result  # gross margin shown inline
        assert "Currency: USD" in result

    async def test_balance_sheet_omits_null(self, mock_ctx: MagicMock) -> None:
        """get_financials for balance sheet omits null fields."""
        _app(mock_ctx).client.financials.get = AsyncMock(return_value=SAMPLE_BALANCE_SHEET)
        result = await get_financials("AAPL", mock_ctx, statement="balance-sheet")
        assert "Balance Sheet" in result
        assert "Total Assets" in result
        assert "Inventory" not in result  # null, should be omitted
        assert "Goodwill" not in result  # null, should be omitted

    async def test_cash_flow(self, mock_ctx: MagicMock) -> None:
        """get_financials for cash flow formats correctly."""
        _app(mock_ctx).client.financials.get = AsyncMock(return_value=SAMPLE_CASH_FLOW)
        result = await get_financials("AAPL", mock_ctx, statement="cash-flow")
        assert "Cash Flow" in result
        assert "Operating Cash Flow" in result
        assert "Net Change in Cash" not in result  # null

    async def test_quarterly_no_quarter_error(self, mock_ctx: MagicMock) -> None:
        """get_financials with quarterly period but no quarter returns helpful error."""
        result = await get_financials("AAPL", mock_ctx, period="quarterly")
        assert "Quarter (1-4) is required" in result

    async def test_annual_with_quarter_error(self, mock_ctx: MagicMock) -> None:
        """get_financials rejects quarter when period is annual."""
        result = await get_financials("AAPL", mock_ctx, period="annual", quarter=2)
        assert "Quarter should not be specified" in result

    async def test_no_data(self, mock_ctx: MagicMock) -> None:
        """get_financials for company with no financial data returns helpful message."""
        empty = _make_sdk_response(
            {
                "company": {"cik": "0000320193", "ticker": "AAPL", "name": "Apple Inc."},
                "statement": "income",
                "period": "annual",
                "fiscal_year": 2024,
                "fiscal_quarter": None,
                "fiscal_year_end": None,
                "filing_accession": "0000320193-24-000123",
                "currency": "USD",
                "line_items": {},
                "metadata": {"source": "ixbrl"},
            }
        )
        _app(mock_ctx).client.financials.get = AsyncMock(return_value=empty)
        result = await get_financials("AAPL", mock_ctx)
        assert "No financial data" in result

    async def test_includes_currency(self, mock_ctx: MagicMock) -> None:
        """get_financials includes currency in response."""
        _app(mock_ctx).client.financials.get = AsyncMock(return_value=SAMPLE_INCOME)
        result = await get_financials("AAPL", mock_ctx)
        assert "Currency: USD" in result


class TestGetFinancialMetric:
    async def test_returns_time_series(self, mock_ctx: MagicMock) -> None:
        """get_financial_metric returns formatted time series."""
        resp = _make_sdk_response(
            {
                "company": {"cik": "0000320193", "ticker": "AAPL", "name": "Apple Inc."},
                "metric": "revenue",
                "period": "annual",
                "currency": "USD",
                "series": [
                    {"fiscal_year": 2024, "value": 391_035_000_000, "filing_accession": "a1"},
                    {"fiscal_year": 2023, "value": 383_285_000_000, "filing_accession": "a2"},
                    {"fiscal_year": 2022, "value": 394_328_000_000, "filing_accession": "a3"},
                ],
            }
        )
        _app(mock_ctx).client.financials.time_series = AsyncMock(return_value=resp)
        result = await get_financial_metric("AAPL", "revenue", mock_ctx)
        assert "Revenue" in result
        assert "Annual" in result
        assert "$391.0B" in result
        assert "3 data points" in result

    async def test_no_data(self, mock_ctx: MagicMock) -> None:
        """get_financial_metric with no data returns helpful message."""
        resp = _make_sdk_response(
            {
                "company": {"cik": "0000320193", "ticker": "AAPL", "name": "Apple Inc."},
                "metric": "revenue",
                "period": "annual",
                "currency": "USD",
                "series": [],
            }
        )
        _app(mock_ctx).client.financials.time_series = AsyncMock(return_value=resp)
        result = await get_financial_metric("AAPL", "revenue", mock_ctx)
        assert "No data found" in result

    async def test_invalid_metric(self, mock_ctx: MagicMock) -> None:
        """get_financial_metric with invalid metric name returns helpful error."""
        result = await get_financial_metric("AAPL", "invalid_metric", mock_ctx)
        assert "Invalid metric" in result
        assert "revenue" in result  # should list valid metrics

    async def test_company_name_from_sdk(self, mock_ctx: MagicMock) -> None:
        """get_financial_metric uses company name from SDK response, not ticker fallback."""
        _app(mock_ctx).client.financials.get = AsyncMock(return_value=SAMPLE_INCOME)
        result = await get_financials("AAPL", mock_ctx)
        assert "Apple Inc." in result


# IFRS-06: dynamic currency from SDK response — replaces the hardcoded
# "Currency: USD" literal so IFRS filers (EUR/JPY/etc.) render correctly.
SAMPLE_IFRS_EUR = _make_sdk_response(
    {
        "company": {"cik": "0001639920", "ticker": "SPOT", "name": "Spotify Technology"},
        "statement": "income",
        "period": "annual",
        "fiscal_year": 2024,
        "fiscal_quarter": None,
        "fiscal_year_end": None,
        "filing_accession": "0001639920-25-000010",
        "currency": "EUR",
        "line_items": {
            "revenue": 15_600_000_000,
            "gross_profit": 4_600_000_000,
            "operating_income": 1_400_000_000,
            "net_income": 1_140_000_000,
            "eps_diluted": 5.48,
        },
        "metadata": {"source": "ixbrl"},
    }
)


class TestGetFinancialsIFRSCurrency:
    async def test_ifrs_filer_shows_eur_not_usd(self, mock_ctx: MagicMock) -> None:
        """IFRS-06: a filer reporting in EUR renders 'Currency: EUR'."""
        _app(mock_ctx).client.financials.get = AsyncMock(return_value=SAMPLE_IFRS_EUR)
        result = await get_financials("SPOT", mock_ctx)
        assert "Currency: EUR" in result
        assert "Currency: USD" not in result

    async def test_null_currency_falls_back_to_usd_with_warning(self, mock_ctx: MagicMock, caplog) -> None:
        """IFRS-06: fallback MUST be loud — missing currency emits WARNING."""
        import logging

        null_resp = _make_sdk_response(
            {
                "company": {"cik": "0000320193", "ticker": "AAPL", "name": "Apple Inc."},
                "statement": "income",
                "period": "annual",
                "fiscal_year": 2024,
                "fiscal_quarter": None,
                "fiscal_year_end": None,
                "filing_accession": "0000320193-24-000123",
                "currency": None,
                "line_items": {"revenue": 391_035_000_000, "net_income": 93_736_000_000},
                "metadata": {"source": "ixbrl"},
            }
        )
        _app(mock_ctx).client.financials.get = AsyncMock(return_value=null_resp)

        with caplog.at_level(logging.WARNING, logger="thesma_mcp.tools.financials"):
            result = await get_financials("AAPL", mock_ctx)
        assert "Currency: USD" in result
        # Warning must fire — silent fallback reproduces the bug invisibly.
        assert any("currency field absent" in rec.message for rec in caplog.records)


class TestGetFinancialMetricIFRSCurrency:
    async def test_metric_ifrs_filer_shows_eur(self, mock_ctx: MagicMock) -> None:
        """IFRS-06: time-series output reads currency from SDK response."""
        resp = _make_sdk_response(
            {
                "company": {"cik": "0001639920", "ticker": "SPOT", "name": "Spotify"},
                "metric": "revenue",
                "period": "annual",
                "currency": "EUR",
                "series": [
                    {"fiscal_year": 2024, "value": 15_600_000_000, "filing_accession": "a1"},
                    {"fiscal_year": 2023, "value": 13_250_000_000, "filing_accession": "a2"},
                ],
            }
        )
        _app(mock_ctx).client.financials.time_series = AsyncMock(return_value=resp)
        result = await get_financial_metric("SPOT", "revenue", mock_ctx)
        assert "Currency: EUR" in result
        assert "Currency: USD" not in result

    async def test_metric_null_currency_falls_back_to_usd_with_warning(self, mock_ctx: MagicMock, caplog) -> None:
        import logging

        resp = _make_sdk_response(
            {
                "company": {"cik": "0000320193", "ticker": "AAPL", "name": "Apple Inc."},
                "metric": "revenue",
                "period": "annual",
                "currency": None,
                "series": [
                    {"fiscal_year": 2024, "value": 391_035_000_000, "filing_accession": "a1"},
                ],
            }
        )
        _app(mock_ctx).client.financials.time_series = AsyncMock(return_value=resp)

        with caplog.at_level(logging.WARNING, logger="thesma_mcp.tools.financials"):
            result = await get_financial_metric("AAPL", "revenue", mock_ctx)
        assert "Currency: USD" in result
        assert any("currency field absent" in rec.message for rec in caplog.records)
