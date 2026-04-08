"""QA tests for MCP-12: SDK migration.

Written COLD from the MCP-12 spec (Section 3) without looking at dev implementation.
Verifies that tools correctly access nested SDK Pydantic model structures after migration
from raw dict access to thesma.AsyncThesmaClient.

Mock objects use MagicMock with attribute access to match how the dev code
accesses SDK response objects (e.g. result.data.company.name).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from thesma_mcp.tools.compensation import get_board_members, get_executive_compensation
from thesma_mcp.tools.financials import get_financial_metric, get_financials
from thesma_mcp.tools.ratios import get_ratio_history, get_ratios

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_ctx() -> MagicMock:
    """Create a mock MCP Context whose lifespan_context behaves like post-migration AppContext.

    After migration the AppContext holds:
      - client: AsyncThesmaClient  (mocked per-test via SDK resource methods)
      - resolver: TickerResolver   (mocked to return a fixed CIK)
    """
    ctx = MagicMock()
    app = MagicMock()
    # The resolver exposes an async .resolve() that returns a CIK string.
    app.resolver = AsyncMock()
    app.resolver.resolve = AsyncMock(return_value="0000320193")
    # The client is an AsyncThesmaClient.  Resource methods are wired per-test.
    app.client = MagicMock()
    ctx.request_context.lifespan_context = app
    return ctx


def _app(ctx: MagicMock) -> Any:
    """Shorthand to reach the AppContext from a mock Context."""
    return ctx.request_context.lifespan_context


# ---------------------------------------------------------------------------
# Mock response builders — produce objects with attribute access matching
# the SDK Pydantic models that the dev code navigates.
# ---------------------------------------------------------------------------


def _make_sdk_response(data: dict[str, Any]) -> Any:
    """Create a mock SDK DataResponse-like object for financials/ratios.

    Handles nested company/metadata as attribute-access objects, line_items as
    a plain dict (accessed via .get()), ratios as an attribute-access object
    (accessed via getattr()), and series as a list of attribute-access objects.
    """
    mock = MagicMock()
    mock.data = MagicMock()
    for k, v in data.items():
        if isinstance(v, dict) and k in ("company", "metadata"):
            sub = MagicMock()
            for sk, sv in v.items():
                setattr(sub, sk, sv)
            setattr(mock.data, k, sub)
        elif isinstance(v, dict) and k == "ratios":
            sub = MagicMock()
            for sk, sv in v.items():
                setattr(sub, sk, sv)
            mock.data.ratios = sub
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


def _make_comp_detail(**kwargs: Any) -> MagicMock:
    """Create a mock CompensationDetail with the expected fields."""
    m = MagicMock()
    for field in ("salary", "bonus", "stock_awards", "option_awards", "non_equity_incentive", "other", "total"):
        setattr(m, field, kwargs.get(field))
    return m


def _make_comp_response(data: dict[str, Any]) -> Any:
    """Create a mock DataResponse for compensation (executives + pay_ratio)."""
    mock = MagicMock()
    data_mock = MagicMock()

    # Company sub-object
    company = data.get("company", {})
    company_mock = MagicMock()
    for k, v in company.items():
        setattr(company_mock, k, v)
    data_mock.company = company_mock
    data_mock.fiscal_year = data.get("fiscal_year", 2024)
    data_mock.filing_accession = data.get("filing_accession", "0000320193-24-000456")

    # Executives
    execs = data.get("executives", [])
    exec_mocks = []
    for e in execs:
        em = MagicMock()
        em.name = e["name"]
        em.title = e.get("title", "")
        em.compensation = _make_comp_detail(**e.get("compensation", {}))
        exec_mocks.append(em)
    data_mock.executives = exec_mocks

    # Pay ratio
    pr = data.get("pay_ratio")
    if pr:
        pr_mock = MagicMock()
        for k, v in pr.items():
            setattr(pr_mock, k, v)
        data_mock.pay_ratio = pr_mock
    else:
        data_mock.pay_ratio = None

    mock.data = data_mock
    return mock


def _make_board_response(data: dict[str, Any]) -> Any:
    """Create a mock DataResponse for board members."""
    mock = MagicMock()
    data_mock = MagicMock()

    # Company sub-object
    company = data.get("company", {})
    company_mock = MagicMock()
    for k, v in company.items():
        setattr(company_mock, k, v)
    data_mock.company = company_mock
    data_mock.fiscal_year = data.get("fiscal_year", 2024)
    data_mock.filing_accession = data.get("filing_accession", "0000320193-24-000456")

    # Members
    members = data.get("members", [])
    member_mocks = []
    for m in members:
        mm = MagicMock()
        mm.name = m["name"]
        mm.age = m.get("age")
        mm.tenure_years = m.get("tenure_years")
        mm.is_independent = m.get("is_independent")
        mm.committees = m.get("committees", [])
        # committee_details
        cd = m.get("committee_details", [])
        cd_mocks = []
        for c in cd:
            cm = MagicMock()
            cm.name = c["name"]
            cm.is_chair = c.get("is_chair", False)
            cd_mocks.append(cm)
        mm.committee_details = cd_mocks if cd_mocks else None
        member_mocks.append(mm)
    data_mock.members = member_mocks

    mock.data = data_mock
    return mock


# ---------------------------------------------------------------------------
# Shared SDK-shaped mock response objects (Section 3 fixture shapes)
# ---------------------------------------------------------------------------

SDK_FINANCIALS_INCOME = _make_sdk_response(
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
        "metadata": {
            "source": "ixbrl",
            "data_completeness": 12,
            "expected_fields": 15,
            "source_tags": {},
        },
    }
)

SDK_FINANCIALS_BALANCE_SHEET = _make_sdk_response(
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
        "metadata": {
            "source": "ixbrl",
            "data_completeness": 5,
            "expected_fields": 17,
            "source_tags": {},
        },
    }
)

SDK_RATIOS = _make_sdk_response(
    {
        "company": {"cik": "0000320193", "ticker": "AAPL", "name": "Apple Inc."},
        "period": "annual",
        "fiscal_year": 2024,
        "fiscal_quarter": None,
        "ratios": {
            "gross_margin": 46.2,
            "operating_margin": 31.5,
            "net_margin": 24.0,
            "return_on_equity": 157.4,
            "return_on_assets": 30.3,
            "debt_to_equity": 4.56,
            "current_ratio": 0.99,
            "interest_coverage": 35.2,
            "revenue_growth_yoy": 2.0,
            "net_income_growth_yoy": -3.4,
            "eps_growth_yoy": -2.1,
        },
    }
)

SDK_TIME_SERIES = _make_sdk_response(
    {
        "company": {"cik": "0000320193", "ticker": "AAPL", "name": "Apple Inc."},
        "metric": "revenue",
        "period": "annual",
        "currency": "USD",
        "series": [
            {"fiscal_year": 2024, "fiscal_quarter": None, "value": 391_035_000_000, "filing_accession": "acc-2024"},
            {"fiscal_year": 2023, "fiscal_quarter": None, "value": 383_285_000_000, "filing_accession": "acc-2023"},
            {"fiscal_year": 2022, "fiscal_quarter": None, "value": 394_328_000_000, "filing_accession": "acc-2022"},
        ],
    }
)

SDK_RATIO_TIME_SERIES = _make_sdk_response(
    {
        "company": {"cik": "0000320193", "ticker": "AAPL", "name": "Apple Inc."},
        "ratio": "gross_margin",
        "period": "annual",
        "series": [
            {"fiscal_year": 2024, "fiscal_quarter": None, "value": 46.2},
            {"fiscal_year": 2023, "fiscal_quarter": None, "value": 44.1},
            {"fiscal_year": 2022, "fiscal_quarter": None, "value": 43.3},
        ],
    }
)

SDK_COMPENSATION = _make_comp_response(
    {
        "company": {"cik": "0000320193", "ticker": "AAPL", "name": "Apple Inc."},
        "fiscal_year": 2024,
        "filing_accession": "0000320193-24-000456",
        "executives": [
            {
                "name": "Timothy D. Cook",
                "title": "CEO",
                "compensation": {
                    "salary": 3_000_000,
                    "bonus": None,
                    "stock_awards": 58_000_000,
                    "option_awards": None,
                    "non_equity_incentive": None,
                    "other": None,
                    "total": 74_600_000,
                },
            },
            {
                "name": "Luca Maestri",
                "title": "SVP, CFO",
                "compensation": {
                    "salary": 1_000_000,
                    "bonus": None,
                    "stock_awards": 21_000_000,
                    "option_awards": None,
                    "non_equity_incentive": None,
                    "other": None,
                    "total": 27_200_000,
                },
            },
        ],
        "pay_ratio": {
            "ratio": 287.0,
            "ceo_compensation": 74_600_000,
            "median_employee_compensation": 260_000,
            "fiscal_year": 2024,
            "confidence": "high",
        },
    }
)

SDK_BOARD = _make_board_response(
    {
        "company": {"cik": "0000320193", "ticker": "AAPL", "name": "Apple Inc."},
        "fiscal_year": 2024,
        "filing_accession": "0000320193-24-000456",
        "members": [
            {
                "name": "Timothy D. Cook",
                "age": 63,
                "tenure_years": 13,
                "is_independent": False,
                "committees": [],
                "committee_details": [],
            },
            {
                "name": "James Bell",
                "age": 75,
                "tenure_years": 8,
                "is_independent": True,
                "committees": ["Audit"],
                "committee_details": [{"name": "Audit", "is_chair": True}],
            },
            {
                "name": "Andrea Jung",
                "age": 65,
                "tenure_years": 16,
                "is_independent": True,
                "committees": ["Compensation", "Nominating"],
                "committee_details": [
                    {"name": "Compensation", "is_chair": True},
                    {"name": "Nominating", "is_chair": False},
                ],
            },
        ],
    }
)


# --- COR regression data (the company that triggered MCP-12) ---

SDK_FINANCIALS_COR = _make_sdk_response(
    {
        "company": {"cik": "0001140859", "ticker": "COR", "name": "Cencora, Inc."},
        "statement": "income",
        "period": "annual",
        "fiscal_year": 2024,
        "fiscal_quarter": None,
        "fiscal_year_end": None,
        "filing_accession": "0001140859-24-000055",
        "currency": "USD",
        "line_items": {
            "revenue": 271_456_000_000,
            "cost_of_revenue": 259_892_000_000,
            "gross_profit": 11_564_000_000,
            "operating_income": 3_250_000_000,
            "net_income": 2_100_000_000,
            "eps_diluted": 10.67,
        },
        "metadata": {
            "source": "ixbrl",
            "data_completeness": 6,
            "expected_fields": 15,
            "source_tags": {},
        },
    }
)

SDK_RATIOS_AAPL = SDK_RATIOS  # reuse


# ===========================================================================
# 1. Financials: line items come from nested data.line_items
# ===========================================================================


class TestFinancialsSDKNesting:
    """Verify get_financials reads from data.line_items, not flat data dict keys."""

    async def test_income_statement_returns_revenue(self, mock_ctx: MagicMock) -> None:
        """Revenue comes from data.line_items['revenue'], not data['revenue']."""
        _app(mock_ctx).client.financials = MagicMock()
        _app(mock_ctx).client.financials.get = AsyncMock(return_value=SDK_FINANCIALS_INCOME)
        result = await get_financials("AAPL", mock_ctx)
        assert "$391.0B" in result

    async def test_income_statement_returns_net_income(self, mock_ctx: MagicMock) -> None:
        """Net income comes from data.line_items['net_income']."""
        _app(mock_ctx).client.financials = MagicMock()
        _app(mock_ctx).client.financials.get = AsyncMock(return_value=SDK_FINANCIALS_INCOME)
        result = await get_financials("AAPL", mock_ctx)
        assert "Net Income" in result
        assert "$93.7B" in result

    async def test_income_statement_returns_eps(self, mock_ctx: MagicMock) -> None:
        """EPS comes from data.line_items['eps_diluted']."""
        _app(mock_ctx).client.financials = MagicMock()
        _app(mock_ctx).client.financials.get = AsyncMock(return_value=SDK_FINANCIALS_INCOME)
        result = await get_financials("AAPL", mock_ctx)
        assert "$6.08" in result

    async def test_income_statement_includes_margins(self, mock_ctx: MagicMock) -> None:
        """Gross margin is calculated from line_items revenue and gross_profit."""
        _app(mock_ctx).client.financials = MagicMock()
        _app(mock_ctx).client.financials.get = AsyncMock(return_value=SDK_FINANCIALS_INCOME)
        result = await get_financials("AAPL", mock_ctx)
        assert "(46.2%)" in result  # gross margin inline

    async def test_balance_sheet_omits_null_line_items(self, mock_ctx: MagicMock) -> None:
        """Null entries in data.line_items are omitted from output."""
        _app(mock_ctx).client.financials = MagicMock()
        _app(mock_ctx).client.financials.get = AsyncMock(return_value=SDK_FINANCIALS_BALANCE_SHEET)
        result = await get_financials("AAPL", mock_ctx, statement="balance-sheet")
        assert "Total Assets" in result
        assert "Inventory" not in result
        assert "Goodwill" not in result

    async def test_financials_includes_currency(self, mock_ctx: MagicMock) -> None:
        """Currency string is present in the output."""
        _app(mock_ctx).client.financials = MagicMock()
        _app(mock_ctx).client.financials.get = AsyncMock(return_value=SDK_FINANCIALS_INCOME)
        result = await get_financials("AAPL", mock_ctx)
        assert "Currency: USD" in result

    async def test_financials_shows_fiscal_year(self, mock_ctx: MagicMock) -> None:
        """Fiscal year from nested model appears in the output."""
        _app(mock_ctx).client.financials = MagicMock()
        _app(mock_ctx).client.financials.get = AsyncMock(return_value=SDK_FINANCIALS_INCOME)
        result = await get_financials("AAPL", mock_ctx)
        assert "FY 2024" in result


# ===========================================================================
# 2. Ratios: values come from data.ratios.gross_margin etc.
# ===========================================================================


class TestRatiosSDKNesting:
    """Verify get_ratios reads from data.ratios nested object, not flat data dict keys."""

    async def test_returns_gross_margin(self, mock_ctx: MagicMock) -> None:
        """Gross margin from data.ratios.gross_margin appears in output."""
        _app(mock_ctx).client.ratios = MagicMock()
        _app(mock_ctx).client.ratios.get = AsyncMock(return_value=SDK_RATIOS)
        result = await get_ratios("AAPL", mock_ctx)
        assert "46.2%" in result

    async def test_returns_operating_margin(self, mock_ctx: MagicMock) -> None:
        """Operating margin from data.ratios.operating_margin."""
        _app(mock_ctx).client.ratios = MagicMock()
        _app(mock_ctx).client.ratios.get = AsyncMock(return_value=SDK_RATIOS)
        result = await get_ratios("AAPL", mock_ctx)
        assert "31.5%" in result

    async def test_returns_debt_to_equity_as_multiplier(self, mock_ctx: MagicMock) -> None:
        """Debt to equity from data.ratios.debt_to_equity is formatted as multiplier."""
        _app(mock_ctx).client.ratios = MagicMock()
        _app(mock_ctx).client.ratios.get = AsyncMock(return_value=SDK_RATIOS)
        result = await get_ratios("AAPL", mock_ctx)
        assert "4.56x" in result

    async def test_returns_negative_growth(self, mock_ctx: MagicMock) -> None:
        """Negative YoY growth from data.ratios.net_income_growth_yoy."""
        _app(mock_ctx).client.ratios = MagicMock()
        _app(mock_ctx).client.ratios.get = AsyncMock(return_value=SDK_RATIOS)
        result = await get_ratios("AAPL", mock_ctx)
        assert "-3.4%" in result

    async def test_grouped_by_category(self, mock_ctx: MagicMock) -> None:
        """Ratios are grouped into Profitability, Returns, Leverage, Growth."""
        _app(mock_ctx).client.ratios = MagicMock()
        _app(mock_ctx).client.ratios.get = AsyncMock(return_value=SDK_RATIOS)
        result = await get_ratios("AAPL", mock_ctx)
        assert "Profitability" in result
        assert "Returns" in result
        assert "Leverage" in result
        assert "Growth (YoY)" in result

    async def test_skips_null_ratios(self, mock_ctx: MagicMock) -> None:
        """Ratios that are null in data.ratios are omitted."""
        sparse_ratios = _make_sdk_response(
            {
                "company": {"cik": "0000320193", "ticker": "TEST", "name": "Test Corp"},
                "period": "annual",
                "fiscal_year": 2024,
                "fiscal_quarter": None,
                "ratios": {
                    "gross_margin": 40.0,
                    "operating_margin": None,
                    "net_margin": None,
                    "return_on_equity": None,
                    "return_on_assets": None,
                    "debt_to_equity": None,
                    "current_ratio": None,
                    "interest_coverage": None,
                    "revenue_growth_yoy": None,
                    "net_income_growth_yoy": None,
                    "eps_growth_yoy": None,
                },
            }
        )
        _app(mock_ctx).client.ratios = MagicMock()
        _app(mock_ctx).client.ratios.get = AsyncMock(return_value=sparse_ratios)
        result = await get_ratios("TEST", mock_ctx)
        assert "Gross Margin" in result
        assert "Operating Margin" not in result
        assert "Returns" not in result


# ===========================================================================
# 3. Financial metric time series: data.series[i].value
# ===========================================================================


class TestFinancialMetricTimeSeries:
    """Verify get_financial_metric reads from data.series[i].value, not flat data list."""

    async def test_returns_time_series_values(self, mock_ctx: MagicMock) -> None:
        """Values from data.series[i].value appear in output."""
        _app(mock_ctx).client.financials = MagicMock()
        _app(mock_ctx).client.financials.time_series = AsyncMock(return_value=SDK_TIME_SERIES)
        result = await get_financial_metric("AAPL", "revenue", mock_ctx)
        assert "$391.0B" in result
        assert "$383.3B" in result
        assert "$394.3B" in result

    async def test_reports_data_point_count(self, mock_ctx: MagicMock) -> None:
        """Output includes the count of data points."""
        _app(mock_ctx).client.financials = MagicMock()
        _app(mock_ctx).client.financials.time_series = AsyncMock(return_value=SDK_TIME_SERIES)
        result = await get_financial_metric("AAPL", "revenue", mock_ctx)
        assert "3 data points" in result

    async def test_reports_year_range(self, mock_ctx: MagicMock) -> None:
        """Output includes the year range from series."""
        _app(mock_ctx).client.financials = MagicMock()
        _app(mock_ctx).client.financials.time_series = AsyncMock(return_value=SDK_TIME_SERIES)
        result = await get_financial_metric("AAPL", "revenue", mock_ctx)
        assert "2022" in result
        assert "2024" in result

    async def test_metric_label_in_header(self, mock_ctx: MagicMock) -> None:
        """The metric name appears in the header."""
        _app(mock_ctx).client.financials = MagicMock()
        _app(mock_ctx).client.financials.time_series = AsyncMock(return_value=SDK_TIME_SERIES)
        result = await get_financial_metric("AAPL", "revenue", mock_ctx)
        assert "Revenue" in result
        assert "Annual" in result


class TestRatioTimeSeries:
    """Verify get_ratio_history reads from data.series[i].value (ratio time series)."""

    async def test_returns_ratio_time_series_values(self, mock_ctx: MagicMock) -> None:
        """Values from data.series[i].value appear in ratio history output."""
        _app(mock_ctx).client.ratios = MagicMock()
        _app(mock_ctx).client.ratios.time_series = AsyncMock(return_value=SDK_RATIO_TIME_SERIES)
        result = await get_ratio_history("AAPL", "gross_margin", mock_ctx)
        assert "46.2%" in result
        assert "44.1%" in result
        assert "43.3%" in result

    async def test_reports_data_point_count(self, mock_ctx: MagicMock) -> None:
        """Output includes the count of data points."""
        _app(mock_ctx).client.ratios = MagicMock()
        _app(mock_ctx).client.ratios.time_series = AsyncMock(return_value=SDK_RATIO_TIME_SERIES)
        result = await get_ratio_history("AAPL", "gross_margin", mock_ctx)
        assert "3 data points" in result

    async def test_shows_company_name(self, mock_ctx: MagicMock) -> None:
        """Company name from data.company.name, not ticker fallback."""
        _app(mock_ctx).client.ratios = MagicMock()
        _app(mock_ctx).client.ratios.time_series = AsyncMock(return_value=SDK_RATIO_TIME_SERIES)
        result = await get_ratio_history("AAPL", "gross_margin", mock_ctx)
        assert "Apple Inc." in result


# ===========================================================================
# 4. Company name from data.company.name, not fallback ticker
# ===========================================================================


class TestCompanyNameFromNestedModel:
    """Verify company name in output comes from data.company.name, not ticker fallback."""

    async def test_financials_shows_company_name(self, mock_ctx: MagicMock) -> None:
        """get_financials header uses data.company.name = 'Apple Inc.', not 'AAPL'."""
        _app(mock_ctx).client.financials = MagicMock()
        _app(mock_ctx).client.financials.get = AsyncMock(return_value=SDK_FINANCIALS_INCOME)
        result = await get_financials("AAPL", mock_ctx)
        assert "Apple Inc." in result
        assert "Apple Inc. (AAPL)" in result

    async def test_ratios_shows_company_name(self, mock_ctx: MagicMock) -> None:
        """get_ratios header uses data.company.name."""
        _app(mock_ctx).client.ratios = MagicMock()
        _app(mock_ctx).client.ratios.get = AsyncMock(return_value=SDK_RATIOS)
        result = await get_ratios("AAPL", mock_ctx)
        assert "Apple Inc. (AAPL)" in result

    async def test_financial_metric_shows_company_name(self, mock_ctx: MagicMock) -> None:
        """get_financial_metric header uses data.company.name."""
        _app(mock_ctx).client.financials = MagicMock()
        _app(mock_ctx).client.financials.time_series = AsyncMock(return_value=SDK_TIME_SERIES)
        result = await get_financial_metric("AAPL", "revenue", mock_ctx)
        assert "Apple Inc. (AAPL)" in result

    async def test_compensation_shows_company_name(self, mock_ctx: MagicMock) -> None:
        """get_executive_compensation header uses data.company.name."""
        _app(mock_ctx).client.compensation = MagicMock()
        _app(mock_ctx).client.compensation.get = AsyncMock(return_value=SDK_COMPENSATION)
        result = await get_executive_compensation("AAPL", mock_ctx)
        assert "Apple Inc. (AAPL)" in result

    async def test_board_shows_company_name(self, mock_ctx: MagicMock) -> None:
        """get_board_members header uses data.company.name."""
        _app(mock_ctx).client.compensation = MagicMock()
        _app(mock_ctx).client.compensation.board = AsyncMock(return_value=SDK_BOARD)
        result = await get_board_members("AAPL", mock_ctx)
        assert "Apple Inc. (AAPL)" in result

    async def test_company_name_is_not_ticker_fallback(self, mock_ctx: MagicMock) -> None:
        """When data.company.name = 'Cencora, Inc.', output shows that, not 'COR'."""
        _app(mock_ctx).resolver.resolve = AsyncMock(return_value="0001140859")
        _app(mock_ctx).client.financials = MagicMock()
        _app(mock_ctx).client.financials.get = AsyncMock(return_value=SDK_FINANCIALS_COR)
        result = await get_financials("COR", mock_ctx)
        assert "Cencora, Inc." in result
        # The ticker-only fallback pattern should NOT appear as the company name
        # (Before migration, COR would show "COR" instead of "Cencora, Inc.")


# ===========================================================================
# 5. Compensation: data.executives[i].compensation.salary nesting
# ===========================================================================


class TestCompensationSDKNesting:
    """Verify compensation reads nested executives[i].compensation.salary etc."""

    async def test_shows_executive_names(self, mock_ctx: MagicMock) -> None:
        """Executive names from data.executives[i].name."""
        _app(mock_ctx).client.compensation = MagicMock()
        _app(mock_ctx).client.compensation.get = AsyncMock(return_value=SDK_COMPENSATION)
        result = await get_executive_compensation("AAPL", mock_ctx)
        assert "Timothy D. Cook" in result
        assert "Luca Maestri" in result

    async def test_shows_salary_from_nested_compensation(self, mock_ctx: MagicMock) -> None:
        """Salary from data.executives[i].compensation.salary, not data.executives[i].salary."""
        _app(mock_ctx).client.compensation = MagicMock()
        _app(mock_ctx).client.compensation.get = AsyncMock(return_value=SDK_COMPENSATION)
        result = await get_executive_compensation("AAPL", mock_ctx)
        assert "$3.0M" in result  # Cook salary
        assert "$1.0M" in result  # Maestri salary

    async def test_shows_total_from_nested_compensation(self, mock_ctx: MagicMock) -> None:
        """Total from data.executives[i].compensation.total."""
        _app(mock_ctx).client.compensation = MagicMock()
        _app(mock_ctx).client.compensation.get = AsyncMock(return_value=SDK_COMPENSATION)
        result = await get_executive_compensation("AAPL", mock_ctx)
        assert "$74.6M" in result  # Cook total

    async def test_shows_stock_awards(self, mock_ctx: MagicMock) -> None:
        """Stock awards from data.executives[i].compensation.stock_awards."""
        _app(mock_ctx).client.compensation = MagicMock()
        _app(mock_ctx).client.compensation.get = AsyncMock(return_value=SDK_COMPENSATION)
        result = await get_executive_compensation("AAPL", mock_ctx)
        assert "Stock Awards" in result
        assert "$58.0M" in result

    async def test_skips_null_compensation_columns(self, mock_ctx: MagicMock) -> None:
        """Columns where all executives have None (bonus, option_awards) are omitted."""
        _app(mock_ctx).client.compensation = MagicMock()
        _app(mock_ctx).client.compensation.get = AsyncMock(return_value=SDK_COMPENSATION)
        result = await get_executive_compensation("AAPL", mock_ctx)
        assert "Bonus" not in result
        assert "Option Awards" not in result

    async def test_shows_pay_ratio_from_nested_model(self, mock_ctx: MagicMock) -> None:
        """Pay ratio from data.pay_ratio.ratio, ceo_compensation, median_employee_compensation."""
        _app(mock_ctx).client.compensation = MagicMock()
        _app(mock_ctx).client.compensation.get = AsyncMock(return_value=SDK_COMPENSATION)
        result = await get_executive_compensation("AAPL", mock_ctx)
        assert "287" in result
        assert "$74.6M" in result
        assert "$260.0K" in result

    async def test_omits_pay_ratio_when_null(self, mock_ctx: MagicMock) -> None:
        """When data.pay_ratio is None, pay ratio section is omitted."""
        no_ratio = _make_comp_response(
            {
                "company": {"cik": "0000320193", "ticker": "AAPL", "name": "Apple Inc."},
                "fiscal_year": 2024,
                "filing_accession": "0000320193-24-000456",
                "executives": [
                    {
                        "name": "Timothy D. Cook",
                        "title": "CEO",
                        "compensation": {
                            "salary": 3_000_000,
                            "stock_awards": 58_000_000,
                            "total": 74_600_000,
                        },
                    },
                    {
                        "name": "Luca Maestri",
                        "title": "SVP, CFO",
                        "compensation": {
                            "salary": 1_000_000,
                            "stock_awards": 21_000_000,
                            "total": 27_200_000,
                        },
                    },
                ],
                "pay_ratio": None,
            }
        )
        _app(mock_ctx).client.compensation = MagicMock()
        _app(mock_ctx).client.compensation.get = AsyncMock(return_value=no_ratio)
        result = await get_executive_compensation("AAPL", mock_ctx)
        assert "Pay Ratio" not in result


# ===========================================================================
# 6. Board: data.company.name nesting + committee_details
# ===========================================================================


class TestBoardSDKNesting:
    """Verify board reads from nested data.company.name and data.members."""

    async def test_shows_board_members(self, mock_ctx: MagicMock) -> None:
        """Board member names from data.members[i].name."""
        _app(mock_ctx).client.compensation = MagicMock()
        _app(mock_ctx).client.compensation.board = AsyncMock(return_value=SDK_BOARD)
        result = await get_board_members("AAPL", mock_ctx)
        assert "Timothy D. Cook" in result
        assert "James Bell" in result
        assert "Andrea Jung" in result

    async def test_shows_company_name_from_nested_model(self, mock_ctx: MagicMock) -> None:
        """Company name from data.company.name in the board header."""
        _app(mock_ctx).client.compensation = MagicMock()
        _app(mock_ctx).client.compensation.board = AsyncMock(return_value=SDK_BOARD)
        result = await get_board_members("AAPL", mock_ctx)
        assert "Apple Inc. (AAPL)" in result
        assert "Board of Directors" in result

    async def test_shows_chair_designation(self, mock_ctx: MagicMock) -> None:
        """Chair designation from data.members[i].committee_details[j].is_chair."""
        _app(mock_ctx).client.compensation = MagicMock()
        _app(mock_ctx).client.compensation.board = AsyncMock(return_value=SDK_BOARD)
        result = await get_board_members("AAPL", mock_ctx)
        assert "Audit (Chair)" in result
        assert "Compensation (Chair)" in result

    async def test_counts_independent_directors(self, mock_ctx: MagicMock) -> None:
        """Independence count from data.members[i].is_independent."""
        _app(mock_ctx).client.compensation = MagicMock()
        _app(mock_ctx).client.compensation.board = AsyncMock(return_value=SDK_BOARD)
        result = await get_board_members("AAPL", mock_ctx)
        assert "2 of 3 directors are independent" in result

    async def test_shows_age_and_tenure(self, mock_ctx: MagicMock) -> None:
        """Age and tenure from data.members[i].age and .tenure_years."""
        _app(mock_ctx).client.compensation = MagicMock()
        _app(mock_ctx).client.compensation.board = AsyncMock(return_value=SDK_BOARD)
        result = await get_board_members("AAPL", mock_ctx)
        assert "63" in result  # Cook's age
        assert "13 yr" in result  # Cook's tenure


# ===========================================================================
# 7. Regression tests: COR financials and AAPL ratios
# ===========================================================================


class TestRegressionCOR:
    """Regression: get_financials('COR') must return populated financial data.

    This was the exact bug that triggered MCP-12 — COR returned empty results
    because the code accessed flat dict keys that don't exist in the nested API
    response structure.
    """

    async def test_cor_financials_returns_revenue(self, mock_ctx: MagicMock) -> None:
        """COR financials must return actual revenue, not empty output."""
        _app(mock_ctx).resolver.resolve = AsyncMock(return_value="0001140859")
        _app(mock_ctx).client.financials = MagicMock()
        _app(mock_ctx).client.financials.get = AsyncMock(return_value=SDK_FINANCIALS_COR)
        result = await get_financials("COR", mock_ctx)
        # Must contain financial data, not "No financial data"
        assert "No financial data" not in result
        assert "Revenue" in result
        assert "$271.5B" in result

    async def test_cor_financials_returns_net_income(self, mock_ctx: MagicMock) -> None:
        """COR financials must return net_income from line_items."""
        _app(mock_ctx).resolver.resolve = AsyncMock(return_value="0001140859")
        _app(mock_ctx).client.financials = MagicMock()
        _app(mock_ctx).client.financials.get = AsyncMock(return_value=SDK_FINANCIALS_COR)
        result = await get_financials("COR", mock_ctx)
        assert "Net Income" in result
        assert "$2.1B" in result

    async def test_cor_financials_returns_eps(self, mock_ctx: MagicMock) -> None:
        """COR financials must return EPS from line_items."""
        _app(mock_ctx).resolver.resolve = AsyncMock(return_value="0001140859")
        _app(mock_ctx).client.financials = MagicMock()
        _app(mock_ctx).client.financials.get = AsyncMock(return_value=SDK_FINANCIALS_COR)
        result = await get_financials("COR", mock_ctx)
        assert "$10.67" in result

    async def test_cor_shows_company_name(self, mock_ctx: MagicMock) -> None:
        """COR output shows 'Cencora, Inc.', not just 'COR'."""
        _app(mock_ctx).resolver.resolve = AsyncMock(return_value="0001140859")
        _app(mock_ctx).client.financials = MagicMock()
        _app(mock_ctx).client.financials.get = AsyncMock(return_value=SDK_FINANCIALS_COR)
        result = await get_financials("COR", mock_ctx)
        assert "Cencora, Inc." in result


class TestRegressionAAPLRatios:
    """Regression: get_ratios('AAPL') must return populated ratio values.

    Before migration, ratios returned empty because code read flat dict keys
    (data.get('gross_margin')) but the API nests under data.ratios.
    """

    async def test_aapl_ratios_returns_gross_margin(self, mock_ctx: MagicMock) -> None:
        """AAPL ratios must return gross_margin, not empty output."""
        _app(mock_ctx).client.ratios = MagicMock()
        _app(mock_ctx).client.ratios.get = AsyncMock(return_value=SDK_RATIOS_AAPL)
        result = await get_ratios("AAPL", mock_ctx)
        assert "No ratio data" not in result
        assert "46.2%" in result

    async def test_aapl_ratios_returns_roe(self, mock_ctx: MagicMock) -> None:
        """AAPL ratios must return return_on_equity."""
        _app(mock_ctx).client.ratios = MagicMock()
        _app(mock_ctx).client.ratios.get = AsyncMock(return_value=SDK_RATIOS_AAPL)
        result = await get_ratios("AAPL", mock_ctx)
        assert "157.4%" in result

    async def test_aapl_ratios_returns_current_ratio(self, mock_ctx: MagicMock) -> None:
        """AAPL ratios must return current_ratio as multiplier."""
        _app(mock_ctx).client.ratios = MagicMock()
        _app(mock_ctx).client.ratios.get = AsyncMock(return_value=SDK_RATIOS_AAPL)
        result = await get_ratios("AAPL", mock_ctx)
        assert "0.99x" in result

    async def test_aapl_ratios_shows_company_name(self, mock_ctx: MagicMock) -> None:
        """AAPL ratios header shows 'Apple Inc.' not 'AAPL'."""
        _app(mock_ctx).client.ratios = MagicMock()
        _app(mock_ctx).client.ratios.get = AsyncMock(return_value=SDK_RATIOS_AAPL)
        result = await get_ratios("AAPL", mock_ctx)
        assert "Apple Inc. (AAPL)" in result


class TestRegressionTimeSeriesMetric:
    """Regression: get_financial_metric must return time series with values.

    Before migration, data was a flat list with value at top level;
    after migration, data.series is the list with .value on each point.
    """

    async def test_revenue_time_series_has_values(self, mock_ctx: MagicMock) -> None:
        """Revenue time series must show actual dollar values."""
        _app(mock_ctx).client.financials = MagicMock()
        _app(mock_ctx).client.financials.time_series = AsyncMock(return_value=SDK_TIME_SERIES)
        result = await get_financial_metric("AAPL", "revenue", mock_ctx)
        assert "No data found" not in result
        assert "$391.0B" in result
        assert "3 data points" in result

    async def test_company_name_not_ticker_in_time_series(self, mock_ctx: MagicMock) -> None:
        """Time series header uses 'Apple Inc.', not the raw ticker string."""
        _app(mock_ctx).client.financials = MagicMock()
        _app(mock_ctx).client.financials.time_series = AsyncMock(return_value=SDK_TIME_SERIES)
        result = await get_financial_metric("AAPL", "revenue", mock_ctx)
        assert "Apple Inc." in result
