"""QA tests for the webhook MCP tools (MCP-33).

Written cold against the spec at
``gov-data-docs/mcp/prompts/MCP-33-webhooks-tools.md`` (Section 3 — Verification Spec).

Mirrors the structure of ``tests/test_sections.py`` and ``tests/test_events.py``:
MagicMock-based, AsyncMock for the SDK call, no live HTTP.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import BaseModel, ValidationError
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

# ---------------------------------------------------------------------------
# Mock fixture helpers (per spec §3 — adapted from the helper templates)
# ---------------------------------------------------------------------------


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
    events: list[Any] | None = None,
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
    if events is None:
        ev = MagicMock()
        ev.value = "filing.created"
        events = [ev]
    m.events = events
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
    http_status: int | None = 200,
) -> MagicMock:
    """Mock a ``WebhookDeliveryResponse``.

    Verified fields per ``thesma._generated/models.py:3528-3577``:
    ``id``, ``event_type``, ``status``, ``attempt_count``, ``created_at`` (required),
    ``completed_at`` (optional). NO ``attempted_at`` field — explicitly absent.
    """
    m = MagicMock()
    m.id = id
    m.event_type = event_type
    m.status = status
    m.attempt_count = attempt_count
    m.http_status = http_status
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
    """Mock a ``WebhookTestResponse`` (models.py:3667+). Two fields only."""
    m = MagicMock()
    m.test_delivery_id = test_delivery_id
    m.queued_at = queued_at
    return m


def _make_replay_response(
    replay_delivery_id: str = "del_replay_001",
    queued_at: str = "2026-04-27T12:00:00Z",
) -> MagicMock:
    """Mock a ``WebhookReplayResponse`` (models.py:3598-3606). Two fields only."""
    m = MagicMock()
    m.replay_delivery_id = replay_delivery_id
    m.queued_at = queued_at
    return m


def _make_secret_rotate_response(
    id: str = "sub_abc123",
    secret: str = "wh_secret_rotated_9988aabbccddeeff0011223344556677",
) -> MagicMock:
    m = MagicMock()
    m.id = id
    m.secret = secret
    return m


def _make_ctx() -> MagicMock:
    """Build the MCP Context mock.

    Mirrors ``tests/test_sections.py:_make_ctx`` — explicitly sets
    ``ctx.request_context.request = None`` so ``get_client(ctx)`` takes the
    default-client branch instead of MagicMock auto-generating a truthy object.
    """
    app = MagicMock()
    app.client = MagicMock()
    app.client.webhooks = MagicMock()
    ctx = MagicMock()
    ctx.request_context.lifespan_context = app
    ctx.request_context.request = None
    return ctx


def _make_validation_error() -> ValidationError:
    """Construct a real ``pydantic.ValidationError`` instance.

    Pydantic v2 forbids direct instantiation of ``ValidationError`` — the supported
    way is to trigger one by validating a model with a bad payload. We use a tiny
    closed-enum field that mirrors the ``Event`` enum on ``WebhookResponse.events``.
    """
    from enum import StrEnum

    class _StubEvent(StrEnum):
        filing_created = "filing.created"

    class _Stub(BaseModel):
        event: _StubEvent

    try:
        _Stub(event="totally.not.a.valid.event")  # type: ignore[arg-type]
    except ValidationError as e:
        return e
    raise AssertionError("expected pydantic ValidationError to be raised")


# ---------------------------------------------------------------------------
# 1. list_webhook_event_types
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_event_types_basic() -> None:
    """Returns formatted catalog text including event_type, category, description."""
    ctx = _make_ctx()
    items = [
        _make_event_type(),
        _make_event_type(
            event_type="board.changed",
            category="governance",
            description="A board member was added/removed.",
        ),
    ]
    sdk_mock = AsyncMock(return_value=_make_data_response(items))
    ctx.request_context.lifespan_context.client.webhooks.list_event_types = sdk_mock

    result = await list_webhook_event_types(ctx)

    sdk_mock.assert_awaited_once()
    assert "filing.created" in result
    assert "filings" in result
    assert "A new SEC filing has been parsed and stored." in result
    assert "board.changed" in result


# ---------------------------------------------------------------------------
# 2. list_webhooks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_webhooks_empty() -> None:
    """Empty data returns the actionable 'No webhook subscriptions' hint."""
    ctx = _make_ctx()
    sdk_mock = AsyncMock(return_value=_make_data_response([]))
    ctx.request_context.lifespan_context.client.webhooks.list = sdk_mock

    result = await list_webhooks(ctx)

    sdk_mock.assert_awaited_once()
    assert "No webhook subscriptions" in result
    assert "create_webhook" in result


@pytest.mark.asyncio
async def test_list_webhooks_renders_rows() -> None:
    """Non-empty list renders ID + URL + Active column."""
    ctx = _make_ctx()
    items = [_make_webhook()]
    sdk_mock = AsyncMock(return_value=_make_data_response(items))
    ctx.request_context.lifespan_context.client.webhooks.list = sdk_mock

    result = await list_webhooks(ctx)

    sdk_mock.assert_awaited_once()
    assert "sub_abc123" in result
    assert "https://example.com/hook" in result
    # is_active=True renders as "Yes" per spec formatter
    assert "Yes" in result


# ---------------------------------------------------------------------------
# 3. create_webhook
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_webhook_minimal() -> None:
    """Minimal call: url + events only. Optional kwargs reach SDK as None.

    Output includes the secret on its own line.
    """
    ctx = _make_ctx()
    response = _make_data_response(_make_create_response())
    sdk_mock = AsyncMock(return_value=response)
    ctx.request_context.lifespan_context.client.webhooks.create = sdk_mock

    result = await create_webhook(
        ctx,
        url="https://example.com/hook",
        events=["filing.created"],
    )

    kwargs = sdk_mock.call_args.kwargs
    assert kwargs["url"] == "https://example.com/hook"
    assert kwargs["events"] == ["filing.created"]
    assert kwargs["filing_types"] is None
    assert kwargs["description"] is None
    assert "wh_secret_3f5a8b1c2d4e6f7081234567890abcde" in result
    # secret on its own line — load-bearing for LLM relay UX
    assert (
        "\n  wh_secret_3f5a8b1c2d4e6f7081234567890abcde\n" in result
        or "\nwh_secret_3f5a8b1c2d4e6f7081234567890abcde\n" in result
    )


@pytest.mark.asyncio
async def test_create_webhook_full() -> None:
    """All four kwargs reach the SDK."""
    ctx = _make_ctx()
    response = _make_data_response(_make_create_response())
    sdk_mock = AsyncMock(return_value=response)
    ctx.request_context.lifespan_context.client.webhooks.create = sdk_mock

    await create_webhook(
        ctx,
        url="https://example.com/hook",
        events=["filing.created", "amendment.filed"],
        filing_types=["10-K", "8-K"],
        description="prod hook",
    )

    kwargs = sdk_mock.call_args.kwargs
    assert kwargs["url"] == "https://example.com/hook"
    assert kwargs["events"] == ["filing.created", "amendment.filed"]
    assert kwargs["filing_types"] == ["10-K", "8-K"]
    assert kwargs["description"] == "prod hook"


@pytest.mark.asyncio
async def test_create_webhook_empty_events_rejected() -> None:
    """events=[] returns the actionable error WITHOUT hitting the SDK."""
    ctx = _make_ctx()
    sdk_mock = AsyncMock()
    ctx.request_context.lifespan_context.client.webhooks.create = sdk_mock

    result = await create_webhook(ctx, url="https://example.com/hook", events=[])

    assert "events" in result.lower()
    assert "required" in result.lower() or "at least one" in result.lower()
    sdk_mock.assert_not_called()


@pytest.mark.asyncio
async def test_create_webhook_empty_string_description_normalized() -> None:
    """description="" reaches the SDK as None."""
    ctx = _make_ctx()
    response = _make_data_response(_make_create_response())
    sdk_mock = AsyncMock(return_value=response)
    ctx.request_context.lifespan_context.client.webhooks.create = sdk_mock

    await create_webhook(
        ctx,
        url="https://example.com/hook",
        events=["filing.created"],
        description="",
    )

    kwargs = sdk_mock.call_args.kwargs
    assert kwargs["description"] is None


@pytest.mark.asyncio
async def test_create_webhook_402_renders_upgrade_message() -> None:
    """402 ThesmaError surfaces the Starter+ upgrade message instead of raw error."""
    ctx = _make_ctx()
    sdk_mock = AsyncMock(side_effect=ThesmaError("Payment required", status_code=402))
    ctx.request_context.lifespan_context.client.webhooks.create = sdk_mock

    result = await create_webhook(
        ctx,
        url="https://example.com/hook",
        events=["filing.created"],
    )

    assert "Starter+" in result
    assert "thesma.dev/pricing" in result


@pytest.mark.asyncio
async def test_create_webhook_other_error_passthrough() -> None:
    """Non-402 ThesmaError surfaces unchanged via str(e)."""
    ctx = _make_ctx()
    sdk_mock = AsyncMock(side_effect=ThesmaError("invalid url scheme", status_code=400))
    ctx.request_context.lifespan_context.client.webhooks.create = sdk_mock

    result = await create_webhook(
        ctx,
        url="ftp://nope",
        events=["filing.created"],
    )

    assert "invalid url scheme" in result
    # No upgrade message leak
    assert "Starter+" not in result


# ---------------------------------------------------------------------------
# 4. get_webhook
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_webhook() -> None:
    """Happy path: URL and events appear in the formatted detail output."""
    ctx = _make_ctx()
    sdk_mock = AsyncMock(return_value=_make_data_response(_make_webhook()))
    ctx.request_context.lifespan_context.client.webhooks.get = sdk_mock

    result = await get_webhook(ctx, "sub_abc123")

    args = sdk_mock.call_args
    # Subscription_id may be passed positionally or as kwarg — accept either.
    passed_id = args.args[0] if args.args else args.kwargs.get("subscription_id")
    assert passed_id == "sub_abc123"
    assert "sub_abc123" in result
    assert "https://example.com/hook" in result
    assert "filing.created" in result


# ---------------------------------------------------------------------------
# 5. update_webhook
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_webhook_single_field() -> None:
    """Only is_active=False set; other kwargs reach SDK as None."""
    ctx = _make_ctx()
    sdk_mock = AsyncMock(return_value=_make_data_response(_make_webhook(is_active=False)))
    ctx.request_context.lifespan_context.client.webhooks.update = sdk_mock

    await update_webhook(ctx, "sub_abc123", is_active=False)

    kwargs = sdk_mock.call_args.kwargs
    assert kwargs["is_active"] is False
    assert kwargs["url"] is None
    assert kwargs["events"] is None
    assert kwargs["filing_types"] is None
    assert kwargs["description"] is None


@pytest.mark.asyncio
async def test_update_webhook_no_fields_pre_validated() -> None:
    """No fields set: returns actionable error, SDK is not called."""
    ctx = _make_ctx()
    sdk_mock = AsyncMock()
    ctx.request_context.lifespan_context.client.webhooks.update = sdk_mock

    result = await update_webhook(ctx, "sub_abc123")

    assert "No update fields" in result or "at least one" in result.lower()
    sdk_mock.assert_not_called()


@pytest.mark.asyncio
async def test_update_webhook_empty_strings_normalized() -> None:
    """url='', description='' normalize to None before SDK call."""
    ctx = _make_ctx()
    sdk_mock = AsyncMock(return_value=_make_data_response(_make_webhook()))
    ctx.request_context.lifespan_context.client.webhooks.update = sdk_mock

    # Need at least one non-None field to bypass the pre-validation gate.
    await update_webhook(
        ctx,
        "sub_abc123",
        url="",
        description="",
        is_active=True,
    )

    kwargs = sdk_mock.call_args.kwargs
    assert kwargs["url"] is None
    assert kwargs["description"] is None
    assert kwargs["is_active"] is True


@pytest.mark.asyncio
async def test_update_webhook_empty_lists_normalized() -> None:
    """events=[], filing_types=[] normalize to None — proves _empty_list_to_none wired in."""
    ctx = _make_ctx()
    sdk_mock = AsyncMock(return_value=_make_data_response(_make_webhook()))
    ctx.request_context.lifespan_context.client.webhooks.update = sdk_mock

    # Pass is_active=True so we have at least one non-None field after normalization.
    await update_webhook(
        ctx,
        "sub_abc123",
        events=[],
        filing_types=[],
        is_active=True,
    )

    kwargs = sdk_mock.call_args.kwargs
    assert kwargs["events"] is None
    assert kwargs["filing_types"] is None


# ---------------------------------------------------------------------------
# 6. delete_webhook
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_webhook_success() -> None:
    """SDK returns None; output is the deletion confirmation."""
    ctx = _make_ctx()
    sdk_mock = AsyncMock(return_value=None)
    ctx.request_context.lifespan_context.client.webhooks.delete = sdk_mock

    result = await delete_webhook(ctx, "sub_abc123")

    sdk_mock.assert_awaited_once()
    assert "sub_abc123" in result
    assert "deleted" in result.lower()


@pytest.mark.asyncio
async def test_delete_webhook_error_passthrough() -> None:
    """ThesmaError is surfaced as text."""
    ctx = _make_ctx()
    sdk_mock = AsyncMock(side_effect=ThesmaError("Subscription not found", status_code=404))
    ctx.request_context.lifespan_context.client.webhooks.delete = sdk_mock

    result = await delete_webhook(ctx, "sub_missing")

    assert "Subscription not found" in result


# ---------------------------------------------------------------------------
# 7. list_webhook_deliveries
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_webhook_deliveries_default_limit_and_page() -> None:
    """Default limit=25 reaches SDK as per_page=25; default page=1 reaches as page=1."""
    ctx = _make_ctx()
    items = [_make_delivery()]
    sdk_mock = AsyncMock(return_value=_make_paginated_response(items))
    ctx.request_context.lifespan_context.client.webhooks.list_deliveries = sdk_mock

    await list_webhook_deliveries(ctx, "sub_abc123")

    kwargs = sdk_mock.call_args.kwargs
    assert kwargs["per_page"] == 25
    assert kwargs["page"] == 1


@pytest.mark.asyncio
async def test_list_webhook_deliveries_explicit_page() -> None:
    """page=2 forwarded as page=2 to the SDK."""
    ctx = _make_ctx()
    items = [_make_delivery()]
    sdk_mock = AsyncMock(return_value=_make_paginated_response(items, page=2, total_pages=3))
    ctx.request_context.lifespan_context.client.webhooks.list_deliveries = sdk_mock

    await list_webhook_deliveries(ctx, "sub_abc123", page=2)

    kwargs = sdk_mock.call_args.kwargs
    assert kwargs["page"] == 2


@pytest.mark.asyncio
async def test_list_webhook_deliveries_limit_capped() -> None:
    """limit=200 is clamped to per_page=50 (server cap)."""
    ctx = _make_ctx()
    items = [_make_delivery()]
    sdk_mock = AsyncMock(return_value=_make_paginated_response(items, per_page=50))
    ctx.request_context.lifespan_context.client.webhooks.list_deliveries = sdk_mock

    await list_webhook_deliveries(ctx, "sub_abc123", limit=200)

    kwargs = sdk_mock.call_args.kwargs
    assert kwargs["per_page"] == 50


@pytest.mark.asyncio
async def test_list_webhook_deliveries_renders_created_and_completed() -> None:
    """Table renders Queued At (from created_at) and Completed At (from completed_at).

    Mock fixture deliberately does NOT set an ``attempted_at`` field — that field
    does NOT exist on ``WebhookDeliveryResponse`` per ``models.py:3528-3577``.
    """
    ctx = _make_ctx()
    delivered = _make_delivery(
        id="del_111",
        status="delivered",
        attempt_count=1,
        created_at=datetime(2026, 4, 27, 12, 0, 0, tzinfo=UTC),
        completed_at=datetime(2026, 4, 27, 12, 0, 5, tzinfo=UTC),
    )
    pending = _make_delivery(
        id="del_222",
        status="queued",
        attempt_count=0,
        created_at=datetime(2026, 4, 27, 13, 0, 0, tzinfo=UTC),
        completed_at=None,
    )
    items = [delivered, pending]
    sdk_mock = AsyncMock(return_value=_make_paginated_response(items, total=2))
    ctx.request_context.lifespan_context.client.webhooks.list_deliveries = sdk_mock

    result = await list_webhook_deliveries(ctx, "sub_abc123")

    assert "Queued At" in result
    assert "Completed At" in result
    assert "del_111" in result
    assert "del_222" in result
    # The pending delivery has completed_at=None — should render as "—"
    assert "—" in result


@pytest.mark.asyncio
async def test_list_webhook_deliveries_empty() -> None:
    """Empty data renders the 'No deliveries on page N' hint."""
    ctx = _make_ctx()
    sdk_mock = AsyncMock(return_value=_make_paginated_response([], total=0))
    ctx.request_context.lifespan_context.client.webhooks.list_deliveries = sdk_mock

    result = await list_webhook_deliveries(ctx, "sub_abc123", page=2)

    assert "No deliveries" in result
    assert "page 2" in result
    assert "sub_abc123" in result


# ---------------------------------------------------------------------------
# 8. rotate_webhook_secret
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rotate_webhook_secret() -> None:
    """Output prominently includes the new secret AND the immediate-invalidation warning."""
    ctx = _make_ctx()
    rotated = _make_secret_rotate_response(
        id="sub_abc123",
        secret="wh_secret_rotated_9988aabbccddeeff0011223344556677",
    )
    sdk_mock = AsyncMock(return_value=_make_data_response(rotated))
    ctx.request_context.lifespan_context.client.webhooks.rotate_secret = sdk_mock

    result = await rotate_webhook_secret(ctx, "sub_abc123")

    sdk_mock.assert_awaited_once()
    assert "wh_secret_rotated_9988aabbccddeeff0011223344556677" in result
    # immediate-invalidation language: spec mentions "invalidated" / "previous"
    assert "invalidated" in result.lower() or "previous" in result.lower()


# ---------------------------------------------------------------------------
# 9. send_webhook_test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_webhook_test_surfaces_delivery_id() -> None:
    """Output includes test_delivery_id AND names list_webhook_deliveries as next step."""
    ctx = _make_ctx()
    test_resp = _make_test_response(
        test_delivery_id="del_test_001",
        queued_at="2026-04-27T12:00:00Z",
    )
    sdk_mock = AsyncMock(return_value=_make_data_response(test_resp))
    ctx.request_context.lifespan_context.client.webhooks.send_test = sdk_mock

    result = await send_webhook_test(ctx, "sub_abc123")

    sdk_mock.assert_awaited_once()
    assert "del_test_001" in result
    assert "list_webhook_deliveries" in result
    assert "sub_abc123" in result


# ---------------------------------------------------------------------------
# 10. replay_webhook_delivery
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_replay_webhook_delivery_happy_path_surfaces_delivery_id() -> None:
    """Output includes replay_delivery_id and queued_at fields."""
    ctx = _make_ctx()
    replay = _make_replay_response(
        replay_delivery_id="del_replay_001",
        queued_at="2026-04-27T12:00:00Z",
    )
    sdk_mock = AsyncMock(return_value=_make_data_response(replay))
    ctx.request_context.lifespan_context.client.webhooks.replay_delivery = sdk_mock

    result = await replay_webhook_delivery(ctx, "sub_abc123", "del_old_999")

    sdk_mock.assert_awaited_once()
    assert "del_replay_001" in result
    assert "2026-04-27T12:00:00Z" in result


@pytest.mark.asyncio
async def test_replay_webhook_delivery_410_renders_retention_message() -> None:
    """410 ThesmaError surfaces the 7-day retention window message + delivery_id."""
    ctx = _make_ctx()
    sdk_mock = AsyncMock(side_effect=ThesmaError("Gone", status_code=410))
    ctx.request_context.lifespan_context.client.webhooks.replay_delivery = sdk_mock

    result = await replay_webhook_delivery(ctx, "sub_abc123", "del_aged_out")

    assert "7-day retention window" in result
    assert "del_aged_out" in result


# ---------------------------------------------------------------------------
# 11. ValidationError handling — applied to all four tools that touch WebhookResponse
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tool_name,sdk_attr,call",
    [
        ("list_webhooks", "list", lambda ctx: list_webhooks(ctx)),
        ("get_webhook", "get", lambda ctx: get_webhook(ctx, "sub_abc123")),
        (
            "create_webhook",
            "create",
            lambda ctx: create_webhook(
                ctx,
                url="https://example.com/hook",
                events=["filing.created"],
            ),
        ),
        (
            "update_webhook",
            "update",
            lambda ctx: update_webhook(ctx, "sub_abc123", is_active=False),
        ),
    ],
)
async def test_validation_error_on_unknown_event_renders_actionable_message(
    tool_name: str,
    sdk_attr: str,
    call: Any,
) -> None:
    """Pydantic ValidationError raised by the SDK is caught and surfaces an actionable message.

    Required because ``WebhookResponse.events`` and ``WebhookCreateResponse.events``
    are typed ``list[Event]`` (closed enum at ``models.py:3463-3468``). If the api
    ships a new event type before the SDK regenerates, the SDK's response parsing
    raises ``pydantic.ValidationError`` — NOT a ``ThesmaError``. The tool must catch
    it and surface a "regen the SDK" hint instead of a raw Pydantic traceback.
    """
    ctx = _make_ctx()
    err = _make_validation_error()
    sdk_mock = AsyncMock(side_effect=err)
    setattr(ctx.request_context.lifespan_context.client.webhooks, sdk_attr, sdk_mock)

    result = await call(ctx)

    # Actionable message must reference the catalog tool and SDK regen guidance.
    assert "list_webhook_event_types" in result, f"{tool_name}: missing catalog tool reference"
    assert "regen" in result.lower() or "out of date" in result.lower() or "new event type" in result.lower(), (
        f"{tool_name}: missing regen / new-event-type hint"
    )
    # Should NOT include a raw Pydantic traceback (multi-line dump with "validation errors for").
    assert "validation errors for" not in result.lower(), f"{tool_name}: leaked raw Pydantic traceback"
