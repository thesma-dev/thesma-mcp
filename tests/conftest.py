"""Shared test fixtures — mock API client, sample responses."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from thesma_mcp.resolver import TickerResolver

BASE_URL = "https://api.thesma.dev"


@pytest.fixture()
def mock_api() -> respx.MockRouter:
    """Create a respx mock router for the Thesma API."""
    with respx.mock(base_url=BASE_URL, assert_all_called=False) as router:
        yield router


@pytest.fixture()
def client(mock_api: respx.MockRouter) -> Any:
    """Create an AsyncThesmaClient with a test API key."""
    from thesma.client import AsyncThesmaClient

    return AsyncThesmaClient(api_key="th_test_key123456789012345678901234")


@pytest.fixture()
def resolver(client: Any) -> TickerResolver:
    """Create a TickerResolver backed by the mock client."""
    return TickerResolver(client)


# --- Sample API responses ---


def company_response(cik: str = "0000320193", ticker: str = "AAPL", name: str = "Apple Inc.") -> dict[str, Any]:
    """Sample single company response."""
    return {"data": {"cik": cik, "ticker": ticker, "name": name}}


def company_list_response(
    companies: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Sample company list response."""
    if companies is None:
        companies = [
            {
                "cik": "0000320193",
                "ticker": "AAPL",
                "name": "Apple Inc.",
                "company_tier": "sp500",
            }
        ]
    return {
        "data": companies,
        "pagination": {"page": 1, "per_page": 25, "total": len(companies)},
    }


def error_response(status: int, code: str, message: str) -> dict[str, Any]:
    """Sample error response."""
    return {"error": {"status": status, "code": code, "message": message}}


def mock_error(status: int, code: str, message: str) -> httpx.Response:
    """Create a mock error response."""
    return httpx.Response(
        status_code=status,
        json=error_response(status, code, message),
    )
