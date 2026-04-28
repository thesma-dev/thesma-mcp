"""Tests for executive compensation and board governance tools."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

from thesma.errors import ThesmaError

from thesma_mcp.tools.compensation import get_board_members, get_executive_compensation


def _make_comp_detail(**kwargs: Any) -> MagicMock:
    """Create a mock CompensationDetail."""
    m = MagicMock()
    for field in ("salary", "bonus", "stock_awards", "option_awards", "non_equity_incentive", "other", "total"):
        setattr(m, field, kwargs.get(field))
    return m


def _make_data_response(data: dict[str, Any]) -> Any:
    """Create a mock DataResponse-like object."""
    mock = MagicMock()
    data_mock = MagicMock()
    # Set company
    company = data.get("company", {})
    company_mock = MagicMock()
    for k, v in company.items():
        setattr(company_mock, k, v)
    data_mock.company = company_mock
    data_mock.fiscal_year = data.get("fiscal_year", 2024)
    data_mock.filing_accession = data.get("filing_accession", "0000320193-24-000456")

    # Set executives
    execs = data.get("executives", [])
    exec_mocks = []
    for e in execs:
        em = MagicMock()
        em.name = e["name"]
        em.title = e.get("title", "")
        em.compensation = _make_comp_detail(**e.get("compensation", {}))
        exec_mocks.append(em)
    data_mock.executives = exec_mocks

    # Set pay_ratio
    pr = data.get("pay_ratio")
    if pr:
        pr_mock = MagicMock()
        for k, v in pr.items():
            setattr(pr_mock, k, v)
        data_mock.pay_ratio = pr_mock
    else:
        data_mock.pay_ratio = None

    # Set members (for board)
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


def _make_ctx(
    resolve_cik: str = "0000320193",
    single_response: Any = None,
) -> MagicMock:
    ctx = MagicMock()
    app = MagicMock()
    app.resolver = AsyncMock()
    app.resolver.resolve = AsyncMock(return_value=resolve_cik)
    app.client = MagicMock()
    if single_response:
        app.client.compensation.get = AsyncMock(return_value=single_response)
        app.client.compensation.board = AsyncMock(return_value=single_response)
    else:
        empty = _make_data_response({"company": {"name": "", "ticker": ""}, "executives": [], "members": []})
        app.client.compensation.get = AsyncMock(return_value=empty)
        app.client.compensation.board = AsyncMock(return_value=empty)
    ctx.request_context.lifespan_context = app
    return ctx


SAMPLE_EXEC_COMP = _make_data_response(
    {
        "company": {"cik": "0000320193", "ticker": "AAPL", "name": "Apple Inc."},
        "fiscal_year": 2024,
        "filing_accession": "0000320193-24-000456",
        "executives": [
            {
                "name": "Timothy D. Cook",
                "title": "CEO",
                "compensation": {"salary": 3_000_000, "stock_awards": 58_000_000, "total": 74_600_000},
            },
            {
                "name": "Luca Maestri",
                "title": "SVP, CFO",
                "compensation": {"salary": 1_000_000, "stock_awards": 21_000_000, "total": 27_200_000},
            },
        ],
        "pay_ratio": {
            "ratio": 287,
            "ceo_compensation": 74_600_000,
            "median_employee_compensation": 260_000,
            "fiscal_year": 2024,
            "confidence": "high",
        },
    }
)

SAMPLE_BOARD = _make_data_response(
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
        "executives": [],
    }
)


class TestGetExecutiveCompensation:
    async def test_returns_formatted_table(self) -> None:
        """get_executive_compensation returns formatted table."""
        ctx = _make_ctx(single_response=SAMPLE_EXEC_COMP)
        result = await get_executive_compensation("AAPL", ctx)
        assert "Apple Inc. (AAPL)" in result
        assert "Timothy D. Cook" in result
        assert "CEO" in result
        assert "$3.0M" in result  # salary
        assert "$74.6M" in result  # total

    async def test_includes_pay_ratio(self) -> None:
        """get_executive_compensation includes pay ratio when available."""
        ctx = _make_ctx(single_response=SAMPLE_EXEC_COMP)
        result = await get_executive_compensation("AAPL", ctx)
        assert "287:1" in result
        assert "$74.6M" in result
        assert "$260.0K" in result

    async def test_no_data(self) -> None:
        """get_executive_compensation with no data returns helpful message."""
        empty = _make_data_response(
            {
                "company": {"cik": "0000320193", "ticker": "AAPL", "name": "Apple Inc."},
                "executives": [],
            }
        )
        ctx = _make_ctx(single_response=empty)
        result = await get_executive_compensation("AAPL", ctx)
        assert "No executive compensation data" in result

    async def test_api_error(self) -> None:
        """get_executive_compensation passes through API error."""
        ctx = _make_ctx()
        ctx.request_context.lifespan_context.client.compensation.get = AsyncMock(
            side_effect=ThesmaError("Company not found")
        )
        result = await get_executive_compensation("ZZZZ", ctx)
        assert "Company not found" in result


class TestGetBoardMembers:
    async def test_returns_formatted_table(self) -> None:
        """get_board_members returns formatted table with committees."""
        ctx = _make_ctx(single_response=SAMPLE_BOARD)
        result = await get_board_members("AAPL", ctx)
        assert "Apple Inc. (AAPL)" in result
        assert "Board of Directors" in result
        assert "Timothy D. Cook" in result
        assert "James Bell" in result

    async def test_shows_chair_designation(self) -> None:
        """get_board_members shows chair designation."""
        ctx = _make_ctx(single_response=SAMPLE_BOARD)
        result = await get_board_members("AAPL", ctx)
        assert "Audit (Chair)" in result
        assert "Compensation (Chair)" in result

    async def test_counts_independent_directors(self) -> None:
        """get_board_members counts independent directors."""
        ctx = _make_ctx(single_response=SAMPLE_BOARD)
        result = await get_board_members("AAPL", ctx)
        assert "2 of 3 directors are independent" in result

    async def test_no_data(self) -> None:
        """get_board_members with no data returns helpful message."""
        empty = _make_data_response(
            {
                "company": {"cik": "0000320193", "ticker": "AAPL", "name": "Apple Inc."},
                "members": [],
                "executives": [],
            }
        )
        ctx = _make_ctx(single_response=empty)
        result = await get_board_members("AAPL", ctx)
        assert "No board data" in result
