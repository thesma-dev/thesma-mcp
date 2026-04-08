"""Insider trading (Form 4) — MCP tool."""

from __future__ import annotations

import re
from typing import Any

from mcp.server.fastmcp import Context
from thesma.errors import ThesmaError

from thesma_mcp.formatters import format_currency, format_table
from thesma_mcp.server import AppContext, get_client, mcp

VALID_TYPES = frozenset({"purchase", "sale", "grant", "exercise"})

DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")

MAX_TITLE_LEN = 15


def _validate_date(value: str) -> str | None:
    """Return an error message if the date is not YYYY-MM-DD, else None."""
    if not DATE_PATTERN.match(value):
        return f"Invalid date format '{value}'. Expected YYYY-MM-DD."
    return None


def _truncate_title(title: str | None) -> str:
    """Truncate a title to MAX_TITLE_LEN characters."""
    if not title:
        return ""
    if len(title) <= MAX_TITLE_LEN:
        return title
    return title[: MAX_TITLE_LEN - 1] + "\u2026"


def _format_shares_compact(value: float | int | None) -> str:
    """Format shares as a compact comma-separated number."""
    if value is None:
        return "N/A"
    return f"{int(value):,}"


def _format_price(value: float | None) -> str:
    """Format a per-share price."""
    if value is None:
        return "N/A"
    return f"${value:,.2f}"


@mcp.tool(
    description=(
        "Get insider trading transactions (Form 4) — purchases, sales, grants, and option exercises. "
        "Use ticker to scope to one company, or omit to search across all companies. "
        "Filter by transaction type, minimum value, and date range."
    )
)
async def get_insider_trades(
    ctx: Context[Any, Any],
    ticker: str | None = None,
    type: str | None = None,
    min_value: float | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    limit: int = 20,
) -> str:
    """Get insider trading transactions from Form 4."""
    app: AppContext = ctx.request_context.lifespan_context
    client = get_client(ctx)

    # Treat empty/whitespace ticker as None
    if ticker is not None and not ticker.strip():
        ticker = None

    # Validate type
    if type and type not in VALID_TYPES:
        valid = ", ".join(sorted(VALID_TYPES))
        return f"Invalid type '{type}'. Valid types: {valid}."

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
            response = await client.insider_trades.list(  # type: ignore[misc]
                cik, from_date=from_date, to_date=to_date, trade_type=type, per_page=limit
            )
            # Get company info from the first trade if available
            if response.data:
                company_name = response.data[0].company_name or ticker
                company_ticker = response.data[0].company_ticker or ticker.upper()
            else:
                company_name = ticker
                company_ticker = ticker.upper()
        else:
            response = await client.insider_trades.list_all(from_date=from_date, to_date=to_date, per_page=limit)  # type: ignore[misc]
    except ThesmaError as e:
        return str(e)

    data = response.data
    total = response.pagination.total

    if not data:
        scope = f"for {company_name}" if company_name else ""
        type_filter = f" of type '{type}'" if type else ""
        return f"No insider trades found{' ' + scope if scope else ''}{type_filter}. Try adjusting your filters."

    count_shown = len(data)
    type_label = f"Insider {type.title()}s" if type else "Insider Trades"

    # Build header
    min_val_label = f" over {format_currency(min_value)}" if min_value else ""
    if company_name:
        header = f"{company_name} ({company_ticker}) — Recent {type_label} ({count_shown} of {total:,})"
    else:
        header = f"Recent {type_label}{min_val_label} ({count_shown} of {total:,})"

    # Build table — different columns for company-scoped vs all-companies
    if company_name:
        headers = ["Date", "Person", "Title", "Shares", "Price", "Value"]
        alignments = ["l", "l", "l", "r", "r", "r"]
        rows = [
            [
                str(trade.transaction_date),
                trade.person.name,
                _truncate_title(trade.person.title),
                _format_shares_compact(trade.shares),
                _format_price(trade.price_per_share),
                format_currency(trade.total_value),
            ]
            for trade in data
        ]
    else:
        headers = ["Date", "Ticker", "Person", "Title", "Value", "Planned?"]
        alignments = ["l", "l", "l", "l", "r", "l"]
        rows = [
            [
                str(trade.transaction_date),
                trade.company_ticker or "",
                trade.person.name,
                _truncate_title(trade.person.title),
                format_currency(trade.total_value),
                "Yes" if trade.is_planned_trade else "No",
            ]
            for trade in data
        ]

    table = format_table(headers, rows, alignments)

    # Footer
    footer = (
        f"{total:,} total {type_label.lower()} found. Showing most recent {count_shown}.\n"
        "Source: SEC EDGAR, Form 4 filings."
    )

    return f"{header}\n\n{table}\n\n{footer}"
