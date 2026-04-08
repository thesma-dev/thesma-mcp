"""Tests for the ticker-to-CIK resolver."""

from __future__ import annotations

import httpx
import pytest
import respx
from thesma.errors import ThesmaError

from thesma_mcp.resolver import TickerResolver

from .conftest import company_list_response


async def test_cik_passthrough(resolver: TickerResolver) -> None:
    """CIK input (10-digit zero-padded) passes through unchanged."""
    result = await resolver.resolve("0000320193")
    assert result == "0000320193"


async def test_ticker_resolves(resolver: TickerResolver, mock_api: respx.MockRouter) -> None:
    """Ticker input resolves via API call."""
    mock_api.get("/v1/us/sec/companies").mock(return_value=httpx.Response(200, json=company_list_response()))
    result = await resolver.resolve("AAPL")
    assert result == "0000320193"


async def test_ticker_cached(resolver: TickerResolver, mock_api: respx.MockRouter) -> None:
    """Resolved tickers are cached — second call doesn't hit API."""
    route = mock_api.get("/v1/us/sec/companies").mock(return_value=httpx.Response(200, json=company_list_response()))
    await resolver.resolve("AAPL")
    await resolver.resolve("AAPL")

    assert route.call_count == 1


async def test_cache_case_insensitive(resolver: TickerResolver, mock_api: respx.MockRouter) -> None:
    """Cache is case-insensitive — AAPL and aapl share an entry."""
    route = mock_api.get("/v1/us/sec/companies").mock(return_value=httpx.Response(200, json=company_list_response()))
    await resolver.resolve("AAPL")
    result = await resolver.resolve("aapl")

    assert result == "0000320193"
    assert route.call_count == 1


async def test_unknown_ticker(resolver: TickerResolver, mock_api: respx.MockRouter) -> None:
    """Unknown ticker raises descriptive error."""
    mock_api.get("/v1/us/sec/companies").mock(
        return_value=httpx.Response(200, json={"data": [], "pagination": {"page": 1, "per_page": 25, "total": 0}})
    )
    with pytest.raises(ThesmaError, match="No company found for ticker 'ZZZZ'"):
        await resolver.resolve("ZZZZ")
