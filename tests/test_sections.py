"""Tests for the search_filing_sections MCP tool."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from thesma_mcp.tools.sections import search_filing_sections


def _make_result(
    chunk_text: str = "The company faces risks related to supply chain disruption.",
    similarity_score: float = 0.92,
    word_count: int = 150,
    accession_number: str = "0000320193-24-000081",
    cik: str = "0000320193",
    company_name: str = "Apple Inc.",
    filing_type: str = "10-K",
    filed_at: str = "2024-11-01",
    section_type: str = "item_1a",
) -> MagicMock:
    m = MagicMock()
    m.chunk_text = chunk_text
    m.similarity_score = similarity_score
    m.word_count = word_count
    m.accession_number = accession_number
    m.cik = cik
    m.company_name = company_name
    m.filing_type = filing_type
    m.filed_at = datetime.fromisoformat(f"{filed_at}T00:00:00+00:00")
    m.section_type = section_type
    return m


def _make_response(results: list[MagicMock], has_more: bool = False) -> MagicMock:
    resp = MagicMock()
    resp.data = results
    resp.pagination = MagicMock()
    resp.pagination.has_more = has_more
    # SearchPagination has no `total`; ensure formatter never references it.
    del resp.pagination.total
    return resp


def _make_ctx() -> MagicMock:
    app = MagicMock()
    app.client = MagicMock()
    # Default companies.get response — the Option B path resolves ticker→CIK via
    # client.companies.get(identifier=ticker) post-MCP-36, then forwards data.cik
    # as cik= to sections.search.
    company_resp = MagicMock()
    company_data = MagicMock()
    company_data.cik = "0000320193"
    company_resp.data = company_data
    app.client.companies = MagicMock()
    app.client.companies.get = AsyncMock(return_value=company_resp)
    app.client.sections = MagicMock()
    app.client.sections.search = AsyncMock()
    ctx = MagicMock()
    ctx.request_context.lifespan_context = app
    # get_client() inspects ctx.request_context.request — None means "use default client"
    ctx.request_context.request = None
    return ctx


@pytest.mark.asyncio
async def test_search_filing_sections_basic() -> None:
    """Basic call returns formatted results."""
    ctx = _make_ctx()
    ctx.request_context.lifespan_context.client.sections.search = AsyncMock(
        return_value=_make_response([_make_result()])
    )

    result = await search_filing_sections(ctx, query="supply chain risk")

    assert "Apple Inc." in result
    assert "10-K" in result
    assert "item_1a" in result
    assert "score 0.92" in result
    assert "supply chain disruption" in result


@pytest.mark.asyncio
async def test_search_filing_sections_with_ticker_resolves_cik() -> None:
    """Ticker is resolved to canonical CIK via companies.get (Option B) and forwarded as cik=."""
    ctx = _make_ctx()
    sdk_mock = AsyncMock(return_value=_make_response([_make_result()]))
    ctx.request_context.lifespan_context.client.sections.search = sdk_mock

    await search_filing_sections(ctx, query="risk", ticker="AAPL")

    companies_get_mock = ctx.request_context.lifespan_context.client.companies.get
    companies_get_mock.assert_called_once()
    assert companies_get_mock.call_args.args[0] == "AAPL"
    kwargs = sdk_mock.call_args.kwargs
    assert kwargs["cik"] == "0000320193"


@pytest.mark.asyncio
async def test_search_filing_sections_forwards_all_filters() -> None:
    """All five filter kwargs reach the SDK call unchanged."""
    ctx = _make_ctx()
    sdk_mock = AsyncMock(return_value=_make_response([_make_result()]))
    ctx.request_context.lifespan_context.client.sections.search = sdk_mock

    await search_filing_sections(
        ctx,
        query="climate change",
        ticker="AAPL",
        filing_type="10-K",
        section_type="item_1a",
        year=2024,
        min_similarity=0.7,
    )

    kwargs = sdk_mock.call_args.kwargs
    assert kwargs["query"] == "climate change"
    assert kwargs["cik"] == "0000320193"
    assert kwargs["filing_type"] == "10-K"
    assert kwargs["section_type"] == "item_1a"
    assert kwargs["year"] == 2024
    assert kwargs["min_similarity"] == 0.7


@pytest.mark.asyncio
async def test_search_filing_sections_empty_string_filters_normalized() -> None:
    """Empty / whitespace strings on ticker/filing_type/section_type become None."""
    ctx = _make_ctx()
    sdk_mock = AsyncMock(return_value=_make_response([_make_result()]))
    ctx.request_context.lifespan_context.client.sections.search = sdk_mock

    await search_filing_sections(ctx, query="risk", ticker="", filing_type="  ", section_type="")

    kwargs = sdk_mock.call_args.kwargs
    assert kwargs["cik"] is None
    assert kwargs["filing_type"] is None
    assert kwargs["section_type"] is None
    ctx.request_context.lifespan_context.client.companies.get.assert_not_called()


@pytest.mark.asyncio
async def test_search_filing_sections_query_too_short() -> None:
    """Query <3 non-whitespace chars returns a clean error without hitting the SDK."""
    ctx = _make_ctx()
    sdk_mock = AsyncMock()
    ctx.request_context.lifespan_context.client.sections.search = sdk_mock

    result = await search_filing_sections(ctx, query="ab")

    assert "too short" in result.lower()
    sdk_mock.assert_not_called()


@pytest.mark.asyncio
async def test_search_filing_sections_query_whitespace_only() -> None:
    """Whitespace-only query is rejected (api would also reject; MCP pre-validates)."""
    ctx = _make_ctx()
    sdk_mock = AsyncMock()
    ctx.request_context.lifespan_context.client.sections.search = sdk_mock

    result = await search_filing_sections(ctx, query="   ")

    assert "too short" in result.lower()
    sdk_mock.assert_not_called()


@pytest.mark.asyncio
async def test_search_filing_sections_limit_capped() -> None:
    """limit > 50 is clamped to 50 before the SDK call."""
    ctx = _make_ctx()
    sdk_mock = AsyncMock(return_value=_make_response([_make_result()]))
    ctx.request_context.lifespan_context.client.sections.search = sdk_mock

    await search_filing_sections(ctx, query="risk", limit=200)

    assert sdk_mock.call_args.kwargs["per_page"] == 50


@pytest.mark.asyncio
async def test_search_filing_sections_limit_floor() -> None:
    """limit <= 0 is clamped up to 1."""
    ctx = _make_ctx()
    sdk_mock = AsyncMock(return_value=_make_response([_make_result()]))
    ctx.request_context.lifespan_context.client.sections.search = sdk_mock

    await search_filing_sections(ctx, query="risk", limit=0)

    assert sdk_mock.call_args.kwargs["per_page"] == 1


@pytest.mark.asyncio
async def test_search_filing_sections_no_results() -> None:
    """Empty result set yields a helpful 'no matches' message."""
    ctx = _make_ctx()
    ctx.request_context.lifespan_context.client.sections.search = AsyncMock(return_value=_make_response([]))

    result = await search_filing_sections(ctx, query="zzz nonsense query", ticker="AAPL", year=2024)

    assert "no matches" in result.lower()
    assert "ticker=AAPL" in result
    assert "year=2024" in result


@pytest.mark.asyncio
async def test_search_filing_sections_has_more_footer() -> None:
    """has_more=True surfaces a 'more available' hint in the footer."""
    ctx = _make_ctx()
    ctx.request_context.lifespan_context.client.sections.search = AsyncMock(
        return_value=_make_response([_make_result()], has_more=True)
    )

    result = await search_filing_sections(ctx, query="risk")

    assert "more available" in result.lower()


@pytest.mark.asyncio
async def test_search_filing_sections_thesma_error_surfaces() -> None:
    """SDK ThesmaError (e.g. 422 from out-of-bounds min_similarity) is returned as text."""
    from thesma.errors import ThesmaError

    ctx = _make_ctx()
    ctx.request_context.lifespan_context.client.sections.search = AsyncMock(
        side_effect=ThesmaError("min_similarity must be between 0.0 and 1.0")
    )

    result = await search_filing_sections(ctx, query="risk", min_similarity=2.0)

    assert "min_similarity" in result


@pytest.mark.asyncio
async def test_search_filing_sections_companies_get_error_surfaces() -> None:
    """companies.get failure (unknown ticker) returns the ThesmaError message; sections.search is not called."""
    from thesma.errors import ThesmaError

    ctx = _make_ctx()
    ctx.request_context.lifespan_context.client.companies.get = AsyncMock(
        side_effect=ThesmaError("Company 'ZZZZ' not found.")
    )
    sdk_mock = AsyncMock()
    ctx.request_context.lifespan_context.client.sections.search = sdk_mock

    result = await search_filing_sections(ctx, query="risk", ticker="ZZZZ")

    assert "ZZZZ" in result
    sdk_mock.assert_not_called()
