"""MCP tools for institutional holdings."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import Context
from thesma._generated.models import FundListItem
from thesma._types import PaginatedResponse
from thesma.errors import ThesmaError

from thesma_mcp.formatters import format_currency, format_number, format_table
from thesma_mcp.resolver import CIK_PATTERN
from thesma_mcp.server import AppContext, mcp


def _get_ctx(ctx: Context[Any, AppContext, Any]) -> AppContext:
    return ctx.request_context.lifespan_context


async def _resolve_fund_cik(app: AppContext, fund_name: str) -> str:
    """Resolve a fund name or CIK to a CIK string."""
    if CIK_PATTERN.match(fund_name):
        return fund_name

    response: PaginatedResponse[FundListItem] = await app.client.request(
        "GET",
        "/v1/us/sec/funds",
        params={"search": fund_name},
        response_model=PaginatedResponse[FundListItem],
    )
    if not response.data:
        msg = f"No fund found matching '{fund_name}'. Try a different name or use the fund's CIK directly."
        raise ThesmaError(msg)

    cik: str = response.data[0].cik
    return cik


@mcp.tool(
    description=(
        "Find institutional investment managers (hedge funds, mutual funds) by name. "
        "Use this to look up a fund's CIK before querying its holdings."
    )
)
async def search_funds(
    query: str,
    ctx: Context[Any, AppContext, Any],
    limit: int = 20,
) -> str:
    """Search for institutional funds by name."""
    app = _get_ctx(ctx)
    limit = min(limit, 50)

    try:
        response: PaginatedResponse[FundListItem] = await app.client.request(
            "GET",
            "/v1/us/sec/funds",
            params={"search": query, "per_page": limit},
            response_model=PaginatedResponse[FundListItem],
        )
    except ThesmaError as e:
        return str(e)

    funds = response.data

    if not funds:
        return f'No funds found matching "{query}". Try a different name.'

    count = len(funds)
    lines = [f'Found {count} fund{"" if count == 1 else "s"} matching "{query}"', ""]

    headers = ["#", "CIK", "Fund Name"]
    rows = [[str(i), f.cik, f.name] for i, f in enumerate(funds, 1)]

    lines.append(format_table(headers, rows, alignments=["r", "l", "l"]))
    lines.append("")
    lines.append("Source: SEC EDGAR, 13F filings.")
    return "\n".join(lines)


@mcp.tool(
    description=(
        "Get which institutional funds hold a company's stock. "
        "Shows shares held, market value, and discretion type. Accepts ticker or CIK."
    )
)
async def get_institutional_holders(
    ticker: str,
    ctx: Context[Any, AppContext, Any],
    quarter: str | None = None,
    limit: int = 20,
) -> str:
    """Get institutional holders of a company's stock."""
    app = _get_ctx(ctx)
    limit = min(limit, 50)

    try:
        cik = await app.resolver.resolve(ticker)
    except ThesmaError as e:
        return str(e)

    try:
        response = await app.client.holdings.holders(cik, quarter=quarter, per_page=limit)
    except ThesmaError as e:
        return str(e)

    holders = response.data
    total = response.pagination.total

    if not holders:
        return "No institutional holders found for this company."

    # Try to get company name from a separate lookup
    try:
        company_resp = await app.client.companies.get(cik)
        comp_data = company_resp.data
        company_name = getattr(comp_data, "name", ticker.upper())
        company_ticker_str = getattr(comp_data, "ticker", ticker.upper())
    except ThesmaError:
        company_name = ticker.upper()
        company_ticker_str = ticker.upper()

    q_label = quarter or "Latest"

    title = (
        f"{company_name} ({company_ticker_str}) — Top Institutional Holders, {q_label} ({len(holders)} of {total:,})"
    )

    headers = ["#", "Fund", "Shares", "Market Value", "Discretion"]
    rows = []
    for i, h in enumerate(holders, 1):
        shares = h.shares
        value = h.market_value
        disc = h.discretion
        discretion_str = str(disc.value).title() if disc and hasattr(disc, "value") else str(disc or "").title()
        rows.append(
            [
                str(i),
                h.fund_name or "",
                format_number(shares, decimals=1) if shares is not None else "N/A",
                format_currency(value) if value is not None else "N/A",
                discretion_str,
            ]
        )

    lines = [title, ""]
    lines.append(format_table(headers, rows, alignments=["r", "l", "r", "r", "l"]))
    lines.append("")
    lines.append(f"Showing {len(holders)} of {total:,} institutional holders.")
    lines.append(f"Source: SEC EDGAR, 13F filings ({q_label}).")
    return "\n".join(lines)


@mcp.tool(
    description=(
        "Get a fund's portfolio holdings. Shows what stocks a fund owns, "
        "with share counts and market values. Accepts fund name or CIK."
    )
)
async def get_fund_holdings(
    fund_name: str,
    ctx: Context[Any, AppContext, Any],
    quarter: str | None = None,
    position_type: str = "equity",
    limit: int = 20,
) -> str:
    """Get a fund's portfolio holdings."""
    app = _get_ctx(ctx)
    limit = min(limit, 50)

    try:
        fund_cik = await _resolve_fund_cik(app, fund_name)
    except ThesmaError as e:
        return str(e)

    try:
        response = await app.client.holdings.fund_holdings(fund_cik, quarter=quarter, per_page=limit)
    except ThesmaError as e:
        return str(e)

    holdings = response.data
    total = response.pagination.total

    if not holdings:
        return "No holdings found for this fund."

    fund_display = fund_name.upper()
    q_label = quarter or "Latest"
    type_label = position_type.title() if position_type != "all" else "All"

    title = f"{fund_display} — Portfolio Holdings, {q_label} ({type_label}, {len(holdings)} of {total:,})"

    headers = ["#", "Ticker", "Company", "Shares", "Market Value"]
    rows = []
    for i, h in enumerate(holdings, 1):
        shares = h.shares
        value = h.market_value
        rows.append(
            [
                str(i),
                h.held_company_ticker or "",
                h.held_company_name or "",
                format_number(shares, decimals=1) if shares is not None else "N/A",
                format_currency(value) if value is not None else "N/A",
            ]
        )

    lines = [title, ""]
    lines.append(format_table(headers, rows, alignments=["r", "l", "l", "r", "r"]))
    lines.append("")
    lines.append(f"Showing {len(holdings)} of {total:,} {type_label.lower()} positions.")
    lines.append(f"Source: SEC EDGAR, 13F filing ({q_label}).")
    return "\n".join(lines)


@mcp.tool(
    description=(
        "Get quarter-over-quarter changes in institutional holdings. "
        "Use 'ticker' to see which funds are buying/selling a company, "
        "or 'fund_name' to see what a fund is buying/selling. Provide exactly one."
    )
)
async def get_holding_changes(
    ctx: Context[Any, AppContext, Any],
    ticker: str | None = None,
    fund_name: str | None = None,
    quarter: str | None = None,
    change: str | None = None,
    limit: int = 20,
) -> str:
    """Get quarter-over-quarter position changes."""
    if (ticker and fund_name) or (not ticker and not fund_name):
        return (
            "Provide exactly one of 'ticker' or 'fund_name'. "
            "Use ticker to see which funds changed positions, or fund_name to see what positions changed."
        )

    app = _get_ctx(ctx)
    limit = min(limit, 50)

    if ticker:
        try:
            cik = await app.resolver.resolve(ticker)
        except ThesmaError as e:
            return str(e)
        try:
            response = await app.client.holdings.holder_changes(cik, per_page=limit)
        except ThesmaError as e:
            return str(e)
        return _format_changes_by_ticker(response, ticker)
    else:
        assert fund_name is not None
        try:
            fund_cik = await _resolve_fund_cik(app, fund_name)
        except ThesmaError as e:
            return str(e)
        try:
            response = await app.client.holdings.fund_changes(fund_cik, per_page=limit)
        except ThesmaError as e:
            return str(e)
        return _format_changes_by_fund(response, fund_name)


def _format_changes_by_ticker(response: Any, ticker: str) -> str:
    """Format holding changes for a company (who's buying/selling?)."""
    changes = response.data
    total = response.pagination.total

    if not changes:
        return "No position changes found for this company in the selected quarter."

    first = changes[0]
    company_name = ticker.upper()
    company_ticker = ticker.upper()
    q_label = first.quarter

    count_shown = len(changes)
    title = (
        f"{company_name} ({company_ticker}) — Institutional Position Changes, {q_label} ({count_shown} of {total:,})"
    )

    headers = ["#", "Fund", "Change", "Shares Delta", "% Change", "Current Value"]
    rows = []
    for i, c in enumerate(changes, 1):
        change_type = str(c.change_type.value) if hasattr(c.change_type, "value") else str(c.change_type)
        rows.append(
            [
                str(i),
                c.fund_name or "",
                _change_label(change_type),
                _format_delta(c.share_delta, change_type),
                _format_pct_change(c.pct_change, change_type),
                _format_current_value(c.current_market_value, change_type),
            ]
        )

    lines = [title, ""]
    lines.append(format_table(headers, rows, alignments=["r", "l", "l", "r", "r", "r"]))
    lines.append("")
    lines.append(f"Showing {len(changes)} of {total:,} position changes.")
    lines.append(f"Source: SEC EDGAR, 13F filings ({q_label}).")
    return "\n".join(lines)


def _format_changes_by_fund(response: Any, fund_name: str) -> str:
    """Format holding changes for a fund (what's the fund buying/selling?)."""
    changes = response.data
    total = response.pagination.total

    if not changes:
        return "No position changes found for this fund in the selected quarter."

    first = changes[0]
    fund_display = fund_name.upper()
    q_label = first.quarter

    title = f"{fund_display} — Position Changes, {q_label} ({len(changes)} of {total:,})"

    headers = ["#", "Ticker", "Company", "Change", "Shares Delta", "% Change", "Current Value"]
    rows = []
    for i, c in enumerate(changes, 1):
        change_type = str(c.change_type.value) if hasattr(c.change_type, "value") else str(c.change_type)
        rows.append(
            [
                str(i),
                c.held_company_ticker or "",
                c.held_company_name or "",
                _change_label(change_type),
                _format_delta(c.share_delta, change_type),
                _format_pct_change(c.pct_change, change_type),
                _format_current_value(c.current_market_value, change_type),
            ]
        )

    lines = [title, ""]
    lines.append(format_table(headers, rows, alignments=["r", "l", "l", "l", "r", "r", "r"]))
    lines.append("")
    lines.append(f"Showing {len(changes)} of {total:,} position changes.")
    lines.append(f"Source: SEC EDGAR, 13F filings ({q_label}).")
    return "\n".join(lines)


def _change_label(change_type: str) -> str:
    """Format change type for display."""
    return {
        "new": "New",
        "exited": "Exited",
        "increased": "Increased",
        "decreased": "Decreased",
        "unchanged": "Unchanged",
    }.get(change_type, change_type.title() if change_type else "")


def _format_delta(shares_delta: float | int | None, change_type: str) -> str:
    """Format shares delta with +/- prefix."""
    if shares_delta is None:
        return "\u2014"
    formatted = format_number(abs(shares_delta), decimals=1)
    if change_type in ("new", "increased"):
        return f"+{formatted}"
    elif change_type in ("exited", "decreased"):
        return f"-{formatted}"
    return formatted


def _format_pct_change(pct: float | None, change_type: str) -> str:
    """Format percentage change, showing \u2014 for new positions."""
    if change_type == "new":
        return "\u2014"
    if pct is None:
        return "\u2014"
    sign = "+" if pct > 0 else ""
    return f"{sign}{pct:.1f}%"


def _format_current_value(value: float | int | None, change_type: str) -> str:
    """Format current value, showing \u2014 for exited positions."""
    if change_type == "exited":
        return "\u2014"
    if value is None:
        return "N/A"
    return format_currency(value)
