"""Tests for SEC filing search tool."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from thesma_mcp.tools.filings import search_filings


def _make_filing(
    filed_at: str = "2024-11-01",
    filing_type: str = "10-K",
    period_of_report: str | None = "2024-09-28",
    accession_number: str = "0000320193-24-000123",
) -> MagicMock:
    """Create a mock FilingListItem."""
    m = MagicMock()
    m.filed_at = datetime.fromisoformat(f"{filed_at}T00:00:00+00:00")
    m.filing_type = filing_type
    m.period_of_report = date.fromisoformat(period_of_report) if period_of_report else None
    m.accession_number = accession_number
    return m


def _make_paginated_response(items: list[MagicMock], total: int | None = None) -> MagicMock:
    resp = MagicMock()
    resp.data = items
    resp.pagination = MagicMock()
    resp.pagination.total = total if total is not None else len(items)
    return resp


def _make_data_response(data: dict[str, Any]) -> MagicMock:
    resp = MagicMock()
    resp.data = MagicMock()
    for k, v in data.items():
        setattr(resp.data, k, v)
    return resp


def _make_ctx(
    resolve_cik: str = "0000320193",
    filings_response: MagicMock | None = None,
) -> MagicMock:
    ctx = MagicMock()
    app = MagicMock()
    app.resolver = AsyncMock()
    app.resolver.resolve = AsyncMock(return_value=resolve_cik)
    app.client = MagicMock()
    if filings_response:
        app.client.filings.list_all = AsyncMock(return_value=filings_response)
    else:
        app.client.filings.list_all = AsyncMock(return_value=_make_paginated_response([], total=0))
    # Mock companies.get for title lookup
    app.client.companies.get = AsyncMock(
        return_value=_make_data_response(
            {
                "name": "Apple Inc.",
                "ticker": "AAPL",
                "cik": "0000320193",
            }
        )
    )
    ctx.request_context.lifespan_context = app
    return ctx


SAMPLE_FILINGS_RESP = _make_paginated_response(
    [
        _make_filing("2024-11-01", "10-K", "2024-09-28", "0000320193-24-000123"),
        _make_filing("2024-08-02", "10-Q", "2024-06-29", "0000320193-24-000089"),
    ],
    total=234,
)


class TestSearchFilings:
    async def test_with_ticker(self) -> None:
        """search_filings with ticker resolves and passes CIK."""
        ctx = _make_ctx(filings_response=SAMPLE_FILINGS_RESP)
        result = await search_filings(ctx, ticker="AAPL")
        assert "Apple Inc. (AAPL)" in result
        assert "10-K" in result
        assert "0000320193-24-000123" in result

    async def test_formats_correctly(self) -> None:
        """search_filings formats dates and accession numbers correctly."""
        ctx = _make_ctx(filings_response=SAMPLE_FILINGS_RESP)
        result = await search_filings(ctx, ticker="AAPL")
        assert "2024-11-01" in result
        assert "2024-09-28" in result
        assert "0000320193-24-000123" in result
        assert "Showing 2 of 234 filings" in result
        assert "Source: SEC EDGAR filing index." in result

    async def test_no_results(self) -> None:
        """search_filings with no results returns helpful message."""
        ctx = _make_ctx()
        result = await search_filings(ctx, ticker="AAPL")
        assert "No filings found" in result
