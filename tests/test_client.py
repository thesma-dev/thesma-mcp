"""Tests for SDK client integration — verifies AsyncThesmaClient usage patterns."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

BASE_URL = "https://api.thesma.dev"


async def test_successful_get(client: Any, mock_api: respx.MockRouter) -> None:
    """Successful GET returns parsed data via SDK client."""
    mock_api.get("/v1/us/sec/companies").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {
                        "cik": "0000320193",
                        "ticker": "AAPL",
                        "name": "Apple Inc.",
                        "company_tier": "sp500",
                        "detail_url": "https://api.thesma.dev/v1/us/sec/companies/0000320193",
                    }
                ],
                "pagination": {"page": 1, "per_page": 25, "total": 1},
            },
        )
    )
    result = await client.companies.list(ticker="AAPL")
    assert result.data[0].cik == "0000320193"


async def test_404_error(client: Any, mock_api: respx.MockRouter) -> None:
    """404 raises NotFoundError."""
    from thesma.errors import NotFoundError

    mock_api.get("/v1/us/sec/companies/0000000000").mock(
        return_value=httpx.Response(404, json={"detail": "Company not found"})
    )
    with pytest.raises(NotFoundError, match="Company not found"):
        await client.companies.get("0000000000")


async def test_401_error(client: Any, mock_api: respx.MockRouter) -> None:
    """401 raises AuthenticationError."""
    from thesma.errors import AuthenticationError

    mock_api.get("/v1/us/sec/companies").mock(return_value=httpx.Response(401, json={"detail": "Invalid API key"}))
    with pytest.raises(AuthenticationError, match="Invalid API key"):
        await client.companies.list()


async def test_429_error(client: Any, mock_api: respx.MockRouter) -> None:
    """429 raises RateLimitError."""
    from thesma.errors import RateLimitError

    mock_api.get("/v1/us/sec/companies").mock(
        return_value=httpx.Response(429, headers={"Retry-After": "30"}, json={"detail": "Rate limited"})
    )
    with pytest.raises(RateLimitError):
        await client.companies.list()
