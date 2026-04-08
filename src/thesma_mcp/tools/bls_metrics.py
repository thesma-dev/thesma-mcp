"""MCP tool for discovering available BLS metrics."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import Context
from thesma.errors import ThesmaError

from thesma_mcp.formatters import format_table
from thesma_mcp.server import AppContext, mcp


def _get_ctx(ctx: Context[Any, AppContext, Any]) -> AppContext:
    return ctx.request_context.lifespan_context


@mcp.tool(
    description=(
        "Discover available BLS metrics and what data the API offers. "
        "Use this to understand what labor market data is available before making specific queries. "
        "Filter by category ('employment', 'wages', 'derived'), "
        "source ('ces', 'qcew', 'oews'), or search by name."
    )
)
async def explore_bls_metrics(
    ctx: Context[Any, AppContext, Any],
    category: str | None = None,
    source: str | None = None,
    query: str | None = None,
) -> str:
    """Discover available BLS metrics."""
    app = _get_ctx(ctx)

    try:
        response = await app.client.bls.metrics(category=category, source=source, search=query)  # type: ignore[misc]
    except ThesmaError as e:
        return str(e)

    data = response.data

    if not data:
        return "No metrics found."

    rows = [
        [
            d.canonical_name,
            d.display_name,
            d.category,
            d.source_dataset,
        ]
        for d in data
    ]
    table = format_table(["Metric", "Display Name", "Category", "Source"], rows)

    count = len(data)
    header = f"Found {count} BLS metric{'s' if count != 1 else ''}"
    lines = [header, "", table, "", "Source: Thesma BLS metric catalog."]
    return "\n".join(lines)
