"""Tests for the webhook MCP tools."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import BaseModel, ValidationError
from thesma._generated.models import Event
from thesma.errors import ThesmaError

from thesma_mcp.tools.webhooks import (
    create_webhook,
    delete_webhook,
    get_webhook,
    list_webhook_deliveries,
    list_webhook_event_types,
    list_webhooks,
    replay_webhook_delivery,
    rotate_webhook_secret,
    send_webhook_test,
    update_webhook,
)


def _make_event_type(
    event_type: str = "filing.created",
    description: str = "A new SEC filing has been parsed and stored.",
    category: str = "filings",
    payload_schema_url: str = "https://docs.thesma.dev/webhooks/payloads#filing-created",
) -> MagicMock:
    m = MagicMock()
    m.event_type = event_type
    m.description = description
    m.category = category
    m.payload_schema_url = payload_schema_url
    return m


def _make_webhook(
    id: str = "sub_abc123",
    url: str = "https://example.com/hook",
    events: list[MagicMock] | None = None,
    filing_types: list[str] | None = None,
    is_active: bool = True,
    description: str | None = None,
    last_delivery_at: datetime | None = None,
    success_rate_last_100: float | None = None,
    consecutive_failure_count: int = 0,
) -> MagicMock:
    m = MagicMock()
    m.id = id
    m.url = url
    m.events = events or [MagicMock(value="filing.created")]
    m.filing_types = filing_types
    m.is_active = is_active
    m.description = description
    m.consecutive_failure_count = consecutive_failure_count
    m.created_at = datetime(2026, 4, 27, 0, 0, 0, tzinfo=UTC)
    m.updated_at = datetime(2026, 4, 27, 0, 0, 0, tzinfo=UTC)
    m.last_delivery_at = last_delivery_at
    m.success_rate_last_100 = success_rate_last_100
    return m


def _make_create_response(
    secret: str = "wh_secret_3f5a8b1c2d4e6f7081234567890abcde",
) -> MagicMock:
    m = _make_webhook()
    m.secret = secret
    return m


def _make_data_response(data: object) -> MagicMock:
    resp = MagicMock()
    resp.data = data
    return resp


def _make_delivery(
    id: str = "del_xyz789",
    event_type: str = "filing.created",
    status: str = "delivered",
    attempt_count: int = 1,
    created_at: datetime | None = None,
    completed_at: datetime | None = None,
) -> MagicMock:
    """Mock a `WebhookDeliveryResponse`. Verified fields: id, event_type, status,
    attempt_count, created_at (required), completed_at (optional). NO `attempted_at`."""
    m = MagicMock()
    m.id = id
    m.event_type = event_type
    m.status = status
    m.attempt_count = attempt_count
    m.created_at = created_at or datetime(2026, 4, 27, 12, 0, 0, tzinfo=UTC)
    m.completed_at = completed_at
    return m


def _make_paginated_response(
    items: list[MagicMock],
    total: int | None = None,
    page: int = 1,
    per_page: int = 25,
    total_pages: int | None = None,
) -> MagicMock:
    resp = MagicMock()
    resp.data = items
    resp.pagination = MagicMock()
    resp.pagination.total = total if total is not None else len(items)
    resp.pagination.page = page
    resp.pagination.per_page = per_page
    resp.pagination.total_pages = total_pages if total_pages is not None else 1
    return resp


def _make_test_response(
    test_delivery_id: str = "del_test_001",
    queued_at: str = "2026-04-27T12:00:00Z",
) -> MagicMock:
    """Mock a `WebhookTestResponse` (models.py:3667+). Two fields only."""
    m = MagicMock()
    m.test_delivery_id = test_delivery_id
    m.queued_at = queued_at
    return m


def _make_replay_response(
    replay_delivery_id: str = "del_replay_001",
    queued_at: str = "2026-04-27T12:00:00Z",
) -> MagicMock:
    """Mock a `WebhookReplayResponse` (models.py:3598-3606). Two fields only."""
    m = MagicMock()
    m.replay_delivery_id = replay_delivery_id
    m.queued_at = queued_at
    return m


def _make_ctx() -> MagicMock:
    app = MagicMock()
    app.client = MagicMock()
    app.client.webhooks = MagicMock()
    ctx = MagicMock()
    ctx.request_context.lifespan_context = app
    # get_client() inspects ctx.request_context.request — None means "use default client".
    # Mirrors the pattern in tests/test_sections.py:_make_ctx (line 57). Without this
    # assignment, MagicMock auto-creates a truthy object on access and get_client may
    # take a different code path than the integration expects.
    ctx.request_context.request = None
    return ctx


def _make_validation_error() -> ValidationError:
    """Build a real Pydantic ValidationError that mimics what the SDK raises when
    the api ships a new event-type before the SDK regenerates."""

    class _M(BaseModel):
        e: Event

    try:
        _M(e="unknown.event")  # type: ignore[arg-type]
    except ValidationError as exc:
        return exc
    raise AssertionError("expected ValidationError to be raised")  # pragma: no cover


# --- list_webhook_event_types -------------------------------------------------


@pytest.mark.asyncio
async def test_list_event_types_basic() -> None:
    ctx = _make_ctx()
    items = [
        _make_event_type(),
        _make_event_type(event_type="board.changed", category="governance", description="Board changed."),
    ]
    ctx.request_context.lifespan_context.client.webhooks.list_event_types = AsyncMock(
        return_value=_make_data_response(items)
    )

    result = await list_webhook_event_types(ctx)

    assert "filing.created" in result
    assert "filings" in result
    assert "A new SEC filing has been parsed and stored." in result
    assert "board.changed" in result


# --- list_webhooks ------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_webhooks_empty() -> None:
    ctx = _make_ctx()
    ctx.request_context.lifespan_context.client.webhooks.list = AsyncMock(return_value=_make_data_response([]))

    result = await list_webhooks(ctx)

    assert "No webhook subscriptions" in result
    assert "create_webhook" in result


@pytest.mark.asyncio
async def test_list_webhooks_renders_rows() -> None:
    ctx = _make_ctx()
    items = [_make_webhook(), _make_webhook(id="sub_def456", url="https://example.org/hook2", is_active=False)]
    ctx.request_context.lifespan_context.client.webhooks.list = AsyncMock(return_value=_make_data_response(items))

    result = await list_webhooks(ctx)

    assert "sub_abc123" in result
    assert "https://example.com/hook" in result
    assert "Active" in result
    assert "Yes" in result
    assert "No" in result


# --- create_webhook -----------------------------------------------------------


@pytest.mark.asyncio
async def test_create_webhook_minimal() -> None:
    ctx = _make_ctx()
    sdk_mock = AsyncMock(return_value=_make_data_response(_make_create_response()))
    ctx.request_context.lifespan_context.client.webhooks.create = sdk_mock

    result = await create_webhook(ctx, url="https://example.com/hook", events=["filing.created"])

    kwargs = sdk_mock.call_args.kwargs
    assert kwargs["url"] == "https://example.com/hook"
    assert kwargs["events"] == ["filing.created"]
    assert kwargs["filing_types"] is None
    assert kwargs["description"] is None
    # Secret on its own line in the output.
    assert "wh_secret_3f5a8b1c2d4e6f7081234567890abcde" in result
    assert "store this NOW" in result


@pytest.mark.asyncio
async def test_create_webhook_full() -> None:
    ctx = _make_ctx()
    sdk_mock = AsyncMock(return_value=_make_data_response(_make_create_response()))
    ctx.request_context.lifespan_context.client.webhooks.create = sdk_mock

    await create_webhook(
        ctx,
        url="https://example.com/hook",
        events=["filing.created", "amendment.filed"],
        filing_types=["10-K", "8-K"],
        description="my hook",
    )

    kwargs = sdk_mock.call_args.kwargs
    assert kwargs["url"] == "https://example.com/hook"
    assert kwargs["events"] == ["filing.created", "amendment.filed"]
    assert kwargs["filing_types"] == ["10-K", "8-K"]
    assert kwargs["description"] == "my hook"


@pytest.mark.asyncio
async def test_create_webhook_empty_events_rejected() -> None:
    ctx = _make_ctx()
    sdk_mock = AsyncMock()
    ctx.request_context.lifespan_context.client.webhooks.create = sdk_mock

    result = await create_webhook(ctx, url="https://example.com/hook", events=[])

    assert "events is required" in result
    sdk_mock.assert_not_called()


@pytest.mark.asyncio
async def test_create_webhook_empty_string_description_normalized() -> None:
    ctx = _make_ctx()
    sdk_mock = AsyncMock(return_value=_make_data_response(_make_create_response()))
    ctx.request_context.lifespan_context.client.webhooks.create = sdk_mock

    await create_webhook(
        ctx,
        url="https://example.com/hook",
        events=["filing.created"],
        description="   ",
    )

    kwargs = sdk_mock.call_args.kwargs
    assert kwargs["description"] is None


@pytest.mark.asyncio
async def test_create_webhook_402_renders_upgrade_message() -> None:
    ctx = _make_ctx()
    ctx.request_context.lifespan_context.client.webhooks.create = AsyncMock(
        side_effect=ThesmaError("Plan tier insufficient", status_code=402)
    )

    result = await create_webhook(ctx, url="https://example.com/hook", events=["filing.created"])

    assert "Starter+" in result
    assert "thesma.dev/pricing" in result


@pytest.mark.asyncio
async def test_create_webhook_other_error_passthrough() -> None:
    ctx = _make_ctx()
    ctx.request_context.lifespan_context.client.webhooks.create = AsyncMock(
        side_effect=ThesmaError("Invalid url scheme", status_code=400)
    )

    result = await create_webhook(ctx, url="ftp://example.com", events=["filing.created"])

    assert "Invalid url scheme" in result
    assert "Starter+" not in result


# --- get_webhook --------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_webhook() -> None:
    ctx = _make_ctx()
    ctx.request_context.lifespan_context.client.webhooks.get = AsyncMock(
        return_value=_make_data_response(_make_webhook())
    )

    result = await get_webhook(ctx, subscription_id="sub_abc123")

    assert "sub_abc123" in result
    assert "https://example.com/hook" in result
    assert "filing.created" in result


# --- update_webhook -----------------------------------------------------------


@pytest.mark.asyncio
async def test_update_webhook_single_field() -> None:
    ctx = _make_ctx()
    sdk_mock = AsyncMock(return_value=_make_data_response(_make_webhook(is_active=False)))
    ctx.request_context.lifespan_context.client.webhooks.update = sdk_mock

    await update_webhook(ctx, subscription_id="sub_abc123", is_active=False)

    args, kwargs = sdk_mock.call_args
    assert args[0] == "sub_abc123"
    assert kwargs["is_active"] is False
    assert kwargs["url"] is None
    assert kwargs["events"] is None
    assert kwargs["filing_types"] is None
    assert kwargs["description"] is None


@pytest.mark.asyncio
async def test_update_webhook_no_fields_pre_validated() -> None:
    ctx = _make_ctx()
    sdk_mock = AsyncMock()
    ctx.request_context.lifespan_context.client.webhooks.update = sdk_mock

    result = await update_webhook(ctx, subscription_id="sub_abc123")

    assert "No update fields provided" in result
    sdk_mock.assert_not_called()


@pytest.mark.asyncio
async def test_update_webhook_empty_strings_normalized() -> None:
    ctx = _make_ctx()
    sdk_mock = AsyncMock(return_value=_make_data_response(_make_webhook()))
    ctx.request_context.lifespan_context.client.webhooks.update = sdk_mock

    # is_active=True keeps the call valid (so we can verify the empty-string
    # normalization rather than tripping the no-fields gate).
    await update_webhook(
        ctx,
        subscription_id="sub_abc123",
        url="",
        description="   ",
        is_active=True,
    )

    kwargs = sdk_mock.call_args.kwargs
    assert kwargs["url"] is None
    assert kwargs["description"] is None
    assert kwargs["is_active"] is True


@pytest.mark.asyncio
async def test_update_webhook_empty_lists_normalized() -> None:
    ctx = _make_ctx()
    sdk_mock = AsyncMock(return_value=_make_data_response(_make_webhook()))
    ctx.request_context.lifespan_context.client.webhooks.update = sdk_mock

    # is_active=True keeps the call valid (so we can verify the empty-list
    # normalization rather than tripping the no-fields gate).
    await update_webhook(
        ctx,
        subscription_id="sub_abc123",
        events=[],
        filing_types=[],
        is_active=True,
    )

    kwargs = sdk_mock.call_args.kwargs
    assert kwargs["events"] is None
    assert kwargs["filing_types"] is None
    assert kwargs["is_active"] is True


# --- delete_webhook -----------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_webhook_success() -> None:
    ctx = _make_ctx()
    ctx.request_context.lifespan_context.client.webhooks.delete = AsyncMock(return_value=None)

    result = await delete_webhook(ctx, subscription_id="sub_abc123")

    assert "sub_abc123" in result
    assert "deleted" in result.lower()


@pytest.mark.asyncio
async def test_delete_webhook_error_passthrough() -> None:
    ctx = _make_ctx()
    ctx.request_context.lifespan_context.client.webhooks.delete = AsyncMock(
        side_effect=ThesmaError("Subscription not found", status_code=404)
    )

    result = await delete_webhook(ctx, subscription_id="sub_missing")

    assert "Subscription not found" in result


# --- list_webhook_deliveries --------------------------------------------------


@pytest.mark.asyncio
async def test_list_webhook_deliveries_default_limit_and_page() -> None:
    ctx = _make_ctx()
    sdk_mock = AsyncMock(return_value=_make_paginated_response([_make_delivery()]))
    ctx.request_context.lifespan_context.client.webhooks.list_deliveries = sdk_mock

    await list_webhook_deliveries(ctx, subscription_id="sub_abc123")

    args, kwargs = sdk_mock.call_args
    assert args[0] == "sub_abc123"
    assert kwargs["per_page"] == 25
    assert kwargs["page"] == 1


@pytest.mark.asyncio
async def test_list_webhook_deliveries_explicit_page() -> None:
    ctx = _make_ctx()
    sdk_mock = AsyncMock(return_value=_make_paginated_response([_make_delivery()], page=2))
    ctx.request_context.lifespan_context.client.webhooks.list_deliveries = sdk_mock

    await list_webhook_deliveries(ctx, subscription_id="sub_abc123", page=2)

    kwargs = sdk_mock.call_args.kwargs
    assert kwargs["page"] == 2


@pytest.mark.asyncio
async def test_list_webhook_deliveries_limit_capped() -> None:
    ctx = _make_ctx()
    sdk_mock = AsyncMock(return_value=_make_paginated_response([_make_delivery()]))
    ctx.request_context.lifespan_context.client.webhooks.list_deliveries = sdk_mock

    await list_webhook_deliveries(ctx, subscription_id="sub_abc123", limit=200)

    kwargs = sdk_mock.call_args.kwargs
    assert kwargs["per_page"] == 50


@pytest.mark.asyncio
async def test_list_webhook_deliveries_renders_created_and_completed() -> None:
    ctx = _make_ctx()
    completed = datetime(2026, 4, 27, 12, 0, 5, tzinfo=UTC)
    items = [_make_delivery(completed_at=completed)]
    ctx.request_context.lifespan_context.client.webhooks.list_deliveries = AsyncMock(
        return_value=_make_paginated_response(items)
    )

    result = await list_webhook_deliveries(ctx, subscription_id="sub_abc123")

    assert "Queued At" in result
    assert "Completed At" in result
    assert "2026-04-27 12:00:00" in result
    assert "2026-04-27 12:00:05" in result
    assert "attempted_at" not in result.lower()


@pytest.mark.asyncio
async def test_list_webhook_deliveries_empty() -> None:
    ctx = _make_ctx()
    ctx.request_context.lifespan_context.client.webhooks.list_deliveries = AsyncMock(
        return_value=_make_paginated_response([])
    )

    result = await list_webhook_deliveries(ctx, subscription_id="sub_abc123", page=3)

    assert "No deliveries on page 3" in result
    assert "sub_abc123" in result


# --- rotate_webhook_secret ----------------------------------------------------


@pytest.mark.asyncio
async def test_rotate_webhook_secret() -> None:
    ctx = _make_ctx()
    rotated = MagicMock()
    rotated.id = "sub_abc123"
    rotated.secret = "wh_secret_NEWVALUE_0123456789abcdef"
    ctx.request_context.lifespan_context.client.webhooks.rotate_secret = AsyncMock(
        return_value=_make_data_response(rotated)
    )

    result = await rotate_webhook_secret(ctx, subscription_id="sub_abc123")

    assert "wh_secret_NEWVALUE_0123456789abcdef" in result
    assert "previous secret is invalidated" in result.lower()
    assert "store this NOW" in result


# --- send_webhook_test --------------------------------------------------------


@pytest.mark.asyncio
async def test_send_webhook_test_surfaces_delivery_id() -> None:
    ctx = _make_ctx()
    ctx.request_context.lifespan_context.client.webhooks.send_test = AsyncMock(
        return_value=_make_data_response(_make_test_response())
    )

    result = await send_webhook_test(ctx, subscription_id="sub_abc123")

    assert "del_test_001" in result
    assert "list_webhook_deliveries" in result


# --- replay_webhook_delivery --------------------------------------------------


@pytest.mark.asyncio
async def test_replay_webhook_delivery_happy_path_surfaces_delivery_id() -> None:
    ctx = _make_ctx()
    ctx.request_context.lifespan_context.client.webhooks.replay_delivery = AsyncMock(
        return_value=_make_data_response(_make_replay_response())
    )

    result = await replay_webhook_delivery(ctx, subscription_id="sub_abc123", delivery_id="del_old_001")

    assert "del_replay_001" in result
    assert "2026-04-27T12:00:00Z" in result


@pytest.mark.asyncio
async def test_replay_webhook_delivery_410_renders_retention_message() -> None:
    ctx = _make_ctx()
    ctx.request_context.lifespan_context.client.webhooks.replay_delivery = AsyncMock(
        side_effect=ThesmaError("Delivery aged out", status_code=410)
    )

    result = await replay_webhook_delivery(ctx, subscription_id="sub_abc123", delivery_id="del_old_001")

    assert "7-day retention window" in result
    assert "del_old_001" in result


# --- ValidationError handling on the four WebhookResponse-touching tools ------


@pytest.mark.asyncio
async def test_validation_error_on_unknown_event_renders_actionable_message() -> None:
    """list_webhooks, get_webhook, create_webhook, update_webhook all need the
    ValidationError catch wired so a stale SDK enum doesn't bubble a raw
    Pydantic traceback to the LLM."""
    expected_tokens = ("list_webhook_event_types", "regenerate")

    # list_webhooks
    ctx = _make_ctx()
    ctx.request_context.lifespan_context.client.webhooks.list = AsyncMock(side_effect=_make_validation_error())
    result = await list_webhooks(ctx)
    for token in expected_tokens:
        assert token in result, f"list_webhooks output missing {token!r}"
    assert "Traceback" not in result

    # get_webhook
    ctx = _make_ctx()
    ctx.request_context.lifespan_context.client.webhooks.get = AsyncMock(side_effect=_make_validation_error())
    result = await get_webhook(ctx, subscription_id="sub_abc123")
    for token in expected_tokens:
        assert token in result, f"get_webhook output missing {token!r}"
    assert "Traceback" not in result

    # create_webhook
    ctx = _make_ctx()
    ctx.request_context.lifespan_context.client.webhooks.create = AsyncMock(side_effect=_make_validation_error())
    result = await create_webhook(ctx, url="https://example.com/hook", events=["filing.created"])
    for token in expected_tokens:
        assert token in result, f"create_webhook output missing {token!r}"
    assert "Traceback" not in result

    # update_webhook
    ctx = _make_ctx()
    ctx.request_context.lifespan_context.client.webhooks.update = AsyncMock(side_effect=_make_validation_error())
    result = await update_webhook(ctx, subscription_id="sub_abc123", is_active=True)
    for token in expected_tokens:
        assert token in result, f"update_webhook output missing {token!r}"
    assert "Traceback" not in result
