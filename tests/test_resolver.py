"""Tests for the ticker-to-CIK resolver."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

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


async def test_resolve_with_custom_client(resolver: TickerResolver) -> None:
    """When a custom client is provided, it is used instead of the default client."""
    mock_response = MagicMock()
    mock_company = MagicMock()
    mock_company.cik = "0000320193"
    mock_response.data = [mock_company]

    custom_client = MagicMock()
    custom_client.companies.list = AsyncMock(return_value=mock_response)

    result = await resolver.resolve("AAPL", client=custom_client)

    assert result == "0000320193"
    custom_client.companies.list.assert_awaited_once_with(ticker="AAPL")


async def test_resolve_caches_across_clients(resolver: TickerResolver) -> None:
    """Cache is shared across clients — second call with different client uses cached value."""
    mock_response = MagicMock()
    mock_company = MagicMock()
    mock_company.cik = "0000320193"
    mock_response.data = [mock_company]

    client_a = MagicMock()
    client_a.companies.list = AsyncMock(return_value=mock_response)

    client_b = MagicMock()
    client_b.companies.list = AsyncMock(return_value=mock_response)

    # First call populates cache via client_a
    result1 = await resolver.resolve("AAPL", client=client_a)
    assert result1 == "0000320193"
    client_a.companies.list.assert_awaited_once()

    # Second call should use cache — client_b should NOT be called
    result2 = await resolver.resolve("AAPL", client=client_b)
    assert result2 == "0000320193"
    client_b.companies.list.assert_not_awaited()
