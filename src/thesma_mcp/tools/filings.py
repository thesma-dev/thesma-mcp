"""MCP tools for SEC filing search."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import Context
from thesma.errors import ThesmaError

from thesma_mcp.formatters import format_table
from thesma_mcp.server import AppContext, get_client, mcp


def _get_ctx(ctx: Context[Any, AppContext, Any]) -> AppContext:
    return ctx.request_context.lifespan_context


@mcp.tool(
    description=(
        "Search SEC filings by company, type (10-K, 10-Q, 8-K, 4, DEF 14A, 13F-HR), and date range. "
        "Returns filing metadata with accession numbers. "
        "Args:\n"
        "    ticker: Stock ticker (e.g. 'AAPL'), 10-digit CIK ('0000320193'), stripped CIK "
        "('320193'), or historical ticker ('FB' resolves to META). Omit to search all companies."
    )
)
async def search_filings(
    ctx: Context[Any, AppContext, Any],
    ticker: str | None = None,
    type: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    limit: int = 20,
) -> str:
    """Search SEC filings by company, type, and date range."""
    if ticker is not None and not ticker.strip():
        return "Invalid ticker — must be non-empty (or omit to search across all companies)."

    client = get_client(ctx)
    limit = min(limit, 50)

    # Option B: filings.list_all is the cross-company `?cik=` query filter (NOT renamed
    # by SDK-40; query param does not resolve ticker). When the caller passes a ticker,
    # call companies.get(ticker) first to derive the canonical CIK, then forward as cik=.
    # The companies.get response is also reused for display-name enrichment in the title
    # (replaces the second companies.get(cik) call that lived here pre-MCP-36).
    cik: str | None = None
    comp_data: Any | None = None

    if ticker:
        try:
            company_resp = await client.companies.get(ticker)  # type: ignore[misc]
        except ThesmaError as e:
            return str(e)
        comp_data = company_resp.data
        cik = getattr(comp_data, "cik", None)

    try:
        response = await client.filings.list_all(  # type: ignore[misc]
            cik=cik,
            filing_type=type,
            start_date=from_date,
            end_date=to_date,
            per_page=limit,
        )
    except ThesmaError as e:
        return str(e)

    filings = response.data
    total = response.pagination.total

    if not filings:
        return "No filings found matching the search criteria."

    # Build title — reuse comp_data fetched above instead of a second companies.get call.
    if ticker and comp_data is not None:
        comp_name = getattr(comp_data, "name", ticker.upper())
        comp_ticker = getattr(comp_data, "ticker", ticker.upper())
        title = f"{comp_name} ({comp_ticker}) — SEC Filings ({len(filings)} of {total:,})"
    else:
        title = f"SEC Filings ({len(filings)} of {total:,})"

    headers = ["Date", "Type", "Period", "Accession Number"]
    rows = []
    for f in filings:
        filed_date = str(f.filed_at.date()) if hasattr(f.filed_at, "date") else str(f.filed_at)[:10]
        filing_type = f.filing_type
        period = str(f.period_of_report) if f.period_of_report else "\u2014"
        accession = f.accession_number
        rows.append([filed_date, filing_type, period, accession])

    lines = [title, ""]
    lines.append(format_table(headers, rows, alignments=["l", "l", "l", "l"]))
    lines.append("")
    lines.append(f"Showing {len(filings)} of {total:,} filings.")
    lines.append("Source: SEC EDGAR filing index.")
    return "\n".join(lines)
