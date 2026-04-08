"""Tests for the get_events MCP tool."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from thesma_mcp.tools.events import get_events


def _make_event(
    filed_at: str = "2024-10-31",
    category: str = "earnings",
    company_name: str = "Apple Inc.",
    company_ticker: str = "AAPL",
    description: str = "Results of Operations (Item 2.02)",
) -> MagicMock:
    """Create a mock EventListItem."""
    m = MagicMock()
    m.filed_at = datetime.fromisoformat(f"{filed_at}T00:00:00+00:00")
    m.category = category
    m.company_name = company_name
    m.company_ticker = company_ticker
    # Create mock items
    item = MagicMock()
    item.description = description
    item.model_extra = {"description": description}
    m.items = [item]
    return m


def _make_paginated_response(events: list[MagicMock], total: int | None = None) -> MagicMock:
    """Create a mock PaginatedResponse."""
    resp = MagicMock()
    resp.data = events
    resp.pagination = MagicMock()
    resp.pagination.total = total if total is not None else len(events)
    return resp


def _make_ctx() -> MagicMock:
    """Create a mock MCP context."""
    app = MagicMock()
    app.client = MagicMock()
    app.resolver = AsyncMock()
    app.resolver.resolve = AsyncMock(return_value="0000320193")
    ctx = MagicMock()
    ctx.request_context.lifespan_context = app
    return ctx


@pytest.mark.asyncio
async def test_events_with_ticker() -> None:
    """get_events with ticker scopes to company endpoint."""
    ctx = _make_ctx()
    events = [_make_event(), _make_event(category="governance", company_ticker="AAPL")]
    resp = _make_paginated_response(events, total=2)
    ctx.request_context.lifespan_context.client.events.list = AsyncMock(return_value=resp)

    result = await get_events(ctx, ticker="AAPL")

    assert "Apple Inc. (AAPL)" in result
    resolve_mock = ctx.request_context.lifespan_context.resolver.resolve
    resolve_mock.assert_called_once()
    assert resolve_mock.call_args[0][0] == "AAPL"


@pytest.mark.asyncio
async def test_events_without_ticker() -> None:
    """get_events without ticker uses all-events endpoint."""
    ctx = _make_ctx()
    events = [
        _make_event(),
        _make_event(category="governance", company_name="Microsoft Corporation", company_ticker="MSFT"),
    ]
    resp = _make_paginated_response(events, total=2)
    ctx.request_context.lifespan_context.client.events.list_all = AsyncMock(return_value=resp)

    result = await get_events(ctx)

    assert "Recent" in result


@pytest.mark.asyncio
async def test_events_empty_ticker() -> None:
    """get_events with empty string ticker uses all-events endpoint."""
    ctx = _make_ctx()
    events = [_make_event()]
    resp = _make_paginated_response(events)
    ctx.request_context.lifespan_context.client.events.list_all = AsyncMock(return_value=resp)

    await get_events(ctx, ticker="  ")
    ctx.request_context.lifespan_context.client.events.list_all.assert_called_once()


@pytest.mark.asyncio
async def test_events_invalid_category() -> None:
    """get_events with invalid category returns error listing valid categories."""
    ctx = _make_ctx()
    result = await get_events(ctx, category="invalid_cat")

    assert "Invalid category 'invalid_cat'" in result
    assert "Valid categories:" in result
    assert "earnings" in result


@pytest.mark.asyncio
async def test_events_invalid_date() -> None:
    """get_events with invalid date format returns helpful error."""
    ctx = _make_ctx()
    result = await get_events(ctx, from_date="last week")

    assert "Invalid date format 'last week'" in result
    assert "YYYY-MM-DD" in result


@pytest.mark.asyncio
async def test_events_no_results() -> None:
    """get_events with no results returns helpful message."""
    ctx = _make_ctx()
    resp = _make_paginated_response([], total=0)
    ctx.request_context.lifespan_context.client.events.list_all = AsyncMock(return_value=resp)

    result = await get_events(ctx, category="distress")
    assert "No events found" in result
