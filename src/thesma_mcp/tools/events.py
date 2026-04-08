"""Corporate events (8-K) — MCP tool."""

from __future__ import annotations

import re
from typing import Any

from mcp.server.fastmcp import Context
from thesma.errors import ThesmaError

from thesma_mcp.formatters import format_table
from thesma_mcp.server import AppContext, get_client, mcp

CATEGORY_LABELS: dict[str, str] = {
    "ma": "M&A",
    "earnings": "Earnings",
    "leadership": "Leadership",
    "agreements": "Agreements",
    "governance": "Governance",
    "accounting": "Accounting",
    "distress": "Distress",
    "regulatory": "Regulatory",
    "other": "Other",
}

VALID_CATEGORIES = frozenset(
    {
        "earnings",
        "ma",
        "leadership",
        "agreements",
        "governance",
        "accounting",
        "distress",
        "regulatory",
        "other",
    }
)

DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _validate_date(value: str) -> str | None:
    """Return an error message if the date is not YYYY-MM-DD, else None."""
    if not DATE_PATTERN.match(value):
        return f"Invalid date format '{value}'. Expected YYYY-MM-DD."
    return None


def _event_description(event: Any) -> str:
    """Extract a display description from an event."""
    items = event.items if hasattr(event, "items") else []
    if items:
        item = items[0]
        desc = getattr(item, "description", None)
        if desc is None and hasattr(item, "model_extra"):
            desc = item.model_extra.get("description", "")
        return str(desc or "")
    return ""


@mcp.tool(
    description=(
        "Get 8-K corporate events (earnings, M&A, leadership changes, material agreements). "
        "Use ticker to scope to one company, or omit to search across all companies. "
        "Filter by category and date range."
    )
)
async def get_events(
    ctx: Context[Any, Any],
    ticker: str | None = None,
    category: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    limit: int = 20,
) -> str:
    """Get 8-K corporate events."""
    app: AppContext = ctx.request_context.lifespan_context
    client = get_client(ctx)

    # Treat empty/whitespace ticker as None
    if ticker is not None and not ticker.strip():
        ticker = None

    # Validate category
    if category and category not in VALID_CATEGORIES:
        valid = ", ".join(sorted(VALID_CATEGORIES))
        return f"Invalid category '{category}'. Valid categories: {valid}."

    # Validate dates
    for date_val, label in [(from_date, "from_date"), (to_date, "to_date")]:
        if date_val:
            err = _validate_date(date_val)
            if err:
                return err

    # Cap limit
    limit = min(limit, 50)

    # Determine endpoint
    company_name: str | None = None
    company_ticker: str | None = None
    try:
        if ticker:
            cik = await app.resolver.resolve(ticker, client=client)
            response = await client.events.list(  # type: ignore[misc]
                cik, from_date=from_date, to_date=to_date, category=category, per_page=limit
            )
            # Get company info from the first event if available
            if response.data:
                company_name = response.data[0].company_name or ticker
                company_ticker = response.data[0].company_ticker or ticker.upper()
            else:
                company_name = ticker
                company_ticker = ticker.upper()
        else:
            response = await client.events.list_all(  # type: ignore[misc]
                from_date=from_date, to_date=to_date, category=category, per_page=limit
            )
    except ThesmaError as e:
        return str(e)

    data = response.data
    total = response.pagination.total

    if not data:
        scope = f"for {company_name}" if company_name else ""
        cat_filter = f" in category '{category}'" if category else ""
        return f"No events found{' ' + scope if scope else ''}{cat_filter}. Try adjusting your filters."

    count_shown = len(data)
    cat_label = CATEGORY_LABELS.get(category, category.title()) if category else "Corporate Events"

    # Build header
    if company_name:
        header = f"{company_name} ({company_ticker}) — {cat_label} ({count_shown} of {total:,})"
    else:
        header = f"Recent {cat_label} ({count_shown} of {total:,})"

    # Build table
    if company_name:
        headers = ["Date", "Category", "Description"]
        alignments = ["l", "l", "l"]
        rows = [
            [
                str(event.filed_at.date()) if hasattr(event.filed_at, "date") else str(event.filed_at)[:10],
                event.category,
                _event_description(event),
            ]
            for event in data
        ]
    else:
        headers = ["Date", "Ticker", "Company", "Description"]
        alignments = ["l", "l", "l", "l"]
        rows = [
            [
                str(event.filed_at.date()) if hasattr(event.filed_at, "date") else str(event.filed_at)[:10],
                event.company_ticker or "",
                event.company_name or "",
                _event_description(event),
            ]
            for event in data
        ]

    table = format_table(headers, rows, alignments)

    # Footer
    cat_suffix = f" {category}" if category else ""
    footer = f"Showing {count_shown} of {total:,}{cat_suffix} events.\nSource: SEC EDGAR, 8-K filings."

    return f"{header}\n\n{table}\n\n{footer}"
