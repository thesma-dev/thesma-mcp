"""MCP tools for webhook subscription management and delivery debugging."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import Context
from pydantic import ValidationError
from thesma.errors import ThesmaError

from thesma_mcp.formatters import format_table
from thesma_mcp.server import AppContext, get_client, mcp

_LIMIT_CAP = 50  # api caps per_page at 50; clamp at MCP boundary for predictable LLM behavior


def _get_ctx(ctx: Context[Any, AppContext, Any]) -> AppContext:
    return ctx.request_context.lifespan_context


def _empty_to_none(value: str | None) -> str | None:
    """Treat empty / whitespace-only strings as None (LLMs sometimes pass '')."""
    if value is None or not value.strip():
        return None
    return value


def _empty_list_to_none(value: list[str] | None) -> list[str] | None:
    """Treat empty lists as None for optional list kwargs."""
    if value is None or len(value) == 0:
        return None
    return value


@mcp.tool(
    description=(
        "List the event types you can subscribe a webhook to (filing.created, "
        "corporate_event.created, compensation.filed, board.changed, amendment.filed). "
        "Returns the catalog with descriptions and links to payload schemas."
    )
)
async def list_webhook_event_types(ctx: Context[Any, AppContext, Any]) -> str:
    client = get_client(ctx)
    try:
        response = await client.webhooks.list_event_types()  # type: ignore[misc]
    except ThesmaError as e:
        return str(e)
    return _format_event_types(response.data)


@mcp.tool(
    description=(
        "List your webhook subscriptions — each row shows id, url, events, "
        "active/inactive status, and last-delivery timestamp."
    )
)
async def list_webhooks(ctx: Context[Any, AppContext, Any]) -> str:
    client = get_client(ctx)
    try:
        response = await client.webhooks.list()  # type: ignore[misc]
    except ValidationError as e:
        return _format_event_validation_error(e)
    except ThesmaError as e:
        return str(e)
    if not response.data:
        return "No webhook subscriptions. Use `create_webhook` to subscribe to api events."
    return _format_webhook_list(response.data)


@mcp.tool(
    description=(
        "Create a webhook subscription. Required: url (HTTPS) and events (e.g. "
        "['filing.created']). Optional: filing_types to narrow events to specific "
        "form types ('10-K', '8-K'); description for your own notes. Returns the "
        "new subscription details PLUS a one-time HMAC signing secret you MUST "
        "save — the api will not show it again. Free-tier callers receive a 402 "
        "error; webhooks require Starter+ plan."
    )
)
async def create_webhook(
    ctx: Context[Any, AppContext, Any],
    url: str,
    events: list[str],
    filing_types: list[str] | None = None,
    description: str | None = None,
) -> str:
    client = get_client(ctx)
    description = _empty_to_none(description)
    filing_types = _empty_list_to_none(filing_types)
    if not events:
        return "events is required — pass at least one event type (e.g. ['filing.created'])."
    try:
        response = await client.webhooks.create(  # type: ignore[misc]
            url=url,
            events=events,
            filing_types=filing_types,
            description=description,
        )
    except ValidationError as e:
        return _format_event_validation_error(e)
    except ThesmaError as e:
        if e.status_code == 402:
            return (
                "Webhooks require a Starter+ plan. The current API key is on free tier and "
                "received a 402 from the api. Visit https://thesma.dev/pricing to upgrade."
            )
        return str(e)
    return _format_webhook_with_secret(response.data)


@mcp.tool(
    description="Get details for one webhook subscription by id (e.g. 'sub_abc123').",
)
async def get_webhook(ctx: Context[Any, AppContext, Any], subscription_id: str) -> str:
    client = get_client(ctx)
    try:
        response = await client.webhooks.get(subscription_id)  # type: ignore[misc]
    except ValidationError as e:
        return _format_event_validation_error(e)
    except ThesmaError as e:
        return str(e)
    return _format_webhook_detail(response.data)


@mcp.tool(
    description=(
        "Update a webhook subscription. Pass only the fields you want to change — "
        "unset fields are left untouched. Use is_active=false to disable a hook "
        "without deleting it. Note: `events=[]` and `filing_types=[]` are treated "
        "as 'no change' (api does not support setting these to empty via this "
        "tool); to stop receiving any events, use is_active=false instead."
    )
)
async def update_webhook(
    ctx: Context[Any, AppContext, Any],
    subscription_id: str,
    url: str | None = None,
    events: list[str] | None = None,
    filing_types: list[str] | None = None,
    is_active: bool | None = None,
    description: str | None = None,
) -> str:
    client = get_client(ctx)
    url = _empty_to_none(url)
    description = _empty_to_none(description)
    events = _empty_list_to_none(events)
    filing_types = _empty_list_to_none(filing_types)
    # Pre-flight: at least one field must be set, else api 400s.
    if all(v is None for v in (url, events, filing_types, is_active, description)):
        return "No update fields provided. Pass at least one of: url, events, filing_types, is_active, description."
    try:
        response = await client.webhooks.update(  # type: ignore[misc]
            subscription_id,
            url=url,
            events=events,
            filing_types=filing_types,
            is_active=is_active,
            description=description,
        )
    except ValidationError as e:
        return _format_event_validation_error(e)
    except ThesmaError as e:
        return str(e)
    return _format_webhook_detail(response.data)


@mcp.tool(
    description=(
        "Delete a webhook subscription. Delivery history is retained server-side; "
        "the subscription itself stops receiving new events. Irreversible."
    )
)
async def delete_webhook(ctx: Context[Any, AppContext, Any], subscription_id: str) -> str:
    client = get_client(ctx)
    try:
        await client.webhooks.delete(subscription_id)
    except ThesmaError as e:
        return str(e)
    return f"Webhook subscription {subscription_id} deleted."


@mcp.tool(
    description=(
        "Show delivery attempts for a webhook subscription. Useful for debugging — "
        "each row shows event type, status, attempt count, and queued/completed "
        "timestamps. Pagination is offset-based: pass page=2 for the next batch. "
        "limit (per page) is capped at 50 server-side."
    )
)
async def list_webhook_deliveries(
    ctx: Context[Any, AppContext, Any],
    subscription_id: str,
    limit: int = 25,
    page: int = 1,
) -> str:
    client = get_client(ctx)
    limit = max(1, min(limit, _LIMIT_CAP))
    page = max(1, page)
    try:
        response = await client.webhooks.list_deliveries(  # type: ignore[misc]
            subscription_id, page=page, per_page=limit
        )
    except ThesmaError as e:
        return str(e)
    if not response.data:
        return f"No deliveries on page {page} for {subscription_id}."
    return _format_deliveries(subscription_id, response.data, response.pagination)


@mcp.tool(
    description=(
        "Generate a new HMAC signing secret for a webhook subscription. The "
        "PREVIOUS secret is invalidated immediately — there is no grace period. "
        "Update your HMAC verifier before, or atomically with, calling this tool, "
        "or incoming deliveries will start failing verification. The new secret "
        "is shown ONCE — save it immediately. If this call returns an error after "
        "the api has already processed the rotation (e.g. network timeout), the "
        "previous secret may already be invalidated server-side — call this tool "
        "again to get a fresh secret rather than retrying with the old one."
    )
)
async def rotate_webhook_secret(ctx: Context[Any, AppContext, Any], subscription_id: str) -> str:
    client = get_client(ctx)
    try:
        response = await client.webhooks.rotate_secret(subscription_id)  # type: ignore[misc]
    except ThesmaError as e:
        return str(e)
    return _format_rotated_secret(response.data)


@mcp.tool(
    description=(
        "Enqueue a synthetic 'webhook.test' delivery to verify your endpoint is "
        "reachable and your HMAC verification works. Rate-limited to 5 calls per "
        "60 seconds. Use list_webhook_deliveries afterward to see the result. "
        "If the subscription has is_active=False, the api may reject the request — "
        "call update_webhook(is_active=True) to re-enable first."
    )
)
async def send_webhook_test(ctx: Context[Any, AppContext, Any], subscription_id: str) -> str:
    client = get_client(ctx)
    try:
        response = await client.webhooks.send_test(subscription_id)  # type: ignore[misc]
    except ThesmaError as e:
        return str(e)
    # WebhookTestResponse fields (verified models.py:3667+): test_delivery_id, queued_at.
    return (
        f"Test event enqueued for {subscription_id}.\n\n"
        f"Test delivery ID: {response.data.test_delivery_id}\n"
        f"Queued at: {response.data.queued_at}\n\n"
        f"Use `list_webhook_deliveries(subscription_id='{subscription_id}')` "
        f"to see the delivery result (typically arrives within a few seconds)."
    )


@mcp.tool(
    description=(
        "Re-queue a past webhook delivery for redelivery. Useful if your endpoint "
        "was temporarily down. Deliveries older than the 7-day retention window "
        "return a 410 error and cannot be replayed."
    )
)
async def replay_webhook_delivery(
    ctx: Context[Any, AppContext, Any],
    subscription_id: str,
    delivery_id: str,
) -> str:
    client = get_client(ctx)
    try:
        response = await client.webhooks.replay_delivery(  # type: ignore[misc]
            subscription_id, delivery_id
        )
    except ThesmaError as e:
        if e.status_code == 410:
            return f"Delivery {delivery_id} is older than the 7-day retention window and cannot be replayed."
        return str(e)
    # WebhookReplayResponse fields (verified models.py:3598-3606): replay_delivery_id, queued_at.
    return (
        f"Delivery {delivery_id} re-queued for redelivery.\n\n"
        f"New replay delivery ID: {response.data.replay_delivery_id}\n"
        f"Queued at: {response.data.queued_at}\n\n"
        f"Use `list_webhook_deliveries(subscription_id='{subscription_id}')` "
        f"to see the new delivery's outcome."
    )


def _format_event_validation_error(e: ValidationError) -> str:
    """Surface a Pydantic ValidationError on Webhook(Create)Response.events as actionable text.

    The api may have shipped a new event type (the SDK's `Event` enum at
    `_generated/models.py:3463-3468` is closed-valued). Catching here keeps the tool
    output readable instead of bubbling a multi-line Pydantic traceback to the LLM.
    """
    return (
        "Webhook response failed Pydantic validation — the SDK's `Event` enum may "
        "be out of date with the api's catalog (a new event type may have shipped). "
        "Run `list_webhook_event_types` to see the current api catalog and bump the "
        "`thesma` SDK pin / regenerate models if a new event type appears. "
        f"Underlying error: {e.errors()[0]['msg'] if e.errors() else str(e)}"
    )


def _format_event_types(items: list[Any]) -> str:
    headers = ["Event Type", "Category", "Description"]
    rows = [[i.event_type, i.category, i.description] for i in items]
    table = format_table(headers, rows, alignments=["l", "l", "l"])
    return f"Webhook event types ({len(items)}):\n\n{table}"


def _format_webhook_list(items: list[Any]) -> str:
    headers = ["ID", "URL", "Events", "Active", "Last Delivery"]
    rows = [
        [
            i.id,
            i.url,
            ", ".join(getattr(e, "value", str(e)) for e in i.events),
            "Yes" if i.is_active else "No",
            str(i.last_delivery_at)[:19] if i.last_delivery_at else "—",
        ]
        for i in items
    ]
    table = format_table(headers, rows, alignments=["l", "l", "l", "l", "l"])
    return f"Webhook subscriptions ({len(items)}):\n\n{table}"


def _format_webhook_detail(w: Any) -> str:
    lines = [
        f"Webhook {w.id}",
        "",
        f"URL: {w.url}",
        f"Events: {', '.join(getattr(e, 'value', str(e)) for e in w.events)}",
        f"Filing types: {', '.join(w.filing_types) if w.filing_types else '(all)'}",
        f"Active: {'Yes' if w.is_active else 'No'}",
        f"Description: {w.description or '—'}",
        f"Consecutive failures: {w.consecutive_failure_count}",
        f"Created: {str(w.created_at)[:19]}",
        f"Updated: {str(w.updated_at)[:19]}",
    ]
    if w.last_delivery_at:
        lines.append(f"Last delivery: {str(w.last_delivery_at)[:19]}")
    if w.success_rate_last_100 is not None:
        lines.append(f"Success rate (last 100): {w.success_rate_last_100:.1%}")
    return "\n".join(lines)


def _format_webhook_with_secret(w: Any) -> str:
    """Used by `create_webhook`. Surfaces the one-time secret prominently."""
    detail = _format_webhook_detail(w)
    return (
        f"{detail}\n\n"
        "HMAC signing secret (one-time display — store this NOW; the api will not return it again):\n\n"
        f"  {w.secret}\n\n"
        "Use this to verify incoming webhook payloads via HMAC-SHA256. "
        "If you lose it, call `rotate_webhook_secret` to generate a new one (which invalidates this one)."
    )


def _format_rotated_secret(r: Any) -> str:
    """Used by `rotate_webhook_secret`. Same secret-prominence requirement."""
    return (
        f"Webhook {r.id} secret rotated.\n\n"
        "New HMAC signing secret (one-time display — store this NOW):\n\n"
        f"  {r.secret}\n\n"
        "The previous secret is invalidated as of this response — update your HMAC "
        "verifier before incoming deliveries are signed with the new key."
    )


def _format_deliveries(subscription_id: str, items: list[Any], pagination: Any) -> str:
    # Verified WebhookDeliveryResponse fields (models.py:3528-3577): id, event_type, status,
    # attempt_count, http_status (optional), created_at (required, when queued),
    # completed_at (optional, when delivered/abandoned). NO `attempted_at` field — earlier
    # drafts of this prompt cited that name; it does not exist on the model.
    headers = ["Delivery ID", "Event", "Status", "Attempts", "Queued At", "Completed At"]
    rows = []
    for d in items:
        queued = str(d.created_at)[:19]
        completed = str(d.completed_at)[:19] if d.completed_at else "—"
        rows.append([d.id, d.event_type, str(d.status), str(d.attempt_count), queued, completed])
    table = format_table(headers, rows, alignments=["l", "l", "l", "r", "l", "l"])
    total = pagination.total if hasattr(pagination, "total") else len(items)
    page = pagination.page if hasattr(pagination, "page") else 1
    total_pages = pagination.total_pages if hasattr(pagination, "total_pages") else 1
    page_suffix = f" — page {page}/{total_pages}" if total_pages and total_pages > 1 else ""
    return f"Deliveries for {subscription_id} ({len(items)} of {total}{page_suffix}):\n\n{table}"
