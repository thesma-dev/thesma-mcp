"""Semantic search across SEC filing section content — MCP tool."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import Context
from thesma.errors import ThesmaError

from thesma_mcp.server import AppContext, get_client, mcp

_QUERY_MIN_CHARS = 3
_LIMIT_CAP = 50


def _get_ctx(ctx: Context[Any, AppContext, Any]) -> AppContext:
    return ctx.request_context.lifespan_context


def _empty_to_none(value: str | None) -> str | None:
    """Treat empty / whitespace-only strings as None (LLMs sometimes pass '')."""
    if value is None or not value.strip():
        return None
    return value


@mcp.tool(
    description=(
        "Semantic search across SEC filing section content (10-K Risk Factors, 10-Q MD&A, "
        "etc.) using natural-language queries. Returns matching text excerpts ranked by "
        "cosine similarity. Optionally scope by ticker (one company), filing_type (e.g. "
        "'10-K'), section_type (e.g. 'item_1a' for Risk Factors, 'item_7' for MD&A), "
        "fiscal year, or minimum similarity threshold. "
        "Args:\n"
        "    ticker: Stock ticker (e.g. 'AAPL'), 10-digit CIK ('0000320193'), stripped CIK "
        "('320193'), or historical ticker ('FB' resolves to META). Omit to search all companies."
    )
)
async def search_filing_sections(
    ctx: Context[Any, AppContext, Any],
    query: str,
    ticker: str | None = None,
    filing_type: str | None = None,
    section_type: str | None = None,
    year: int | None = None,
    min_similarity: float | None = None,
    limit: int = 20,
) -> str:
    """Semantic search of SEC filing section content."""
    client = get_client(ctx)

    if len(query.strip()) < _QUERY_MIN_CHARS:
        return f"Query too short. Use at least {_QUERY_MIN_CHARS} non-whitespace characters."

    ticker = _empty_to_none(ticker)
    filing_type = _empty_to_none(filing_type)
    section_type = _empty_to_none(section_type)

    # sections.search is the cross-company query filter. Per SDK-42 (T-230)
    # the kwarg is `identifier=`. The local `cik` variable is the canonical
    # CIK extracted from companies.get above and is forwarded as identifier=
    # because the api accepts CIK on this filter (alongside ticker and
    # stripped-CIK forms).
    cik: str | None = None
    if ticker:
        try:
            company_resp = await client.companies.get(ticker)  # type: ignore[misc]
        except ThesmaError as e:
            return str(e)
        cik = getattr(company_resp.data, "cik", None)

    limit = max(1, min(limit, _LIMIT_CAP))

    try:
        response = await client.sections.search(  # type: ignore[misc]
            query=query,
            identifier=cik,
            filing_type=filing_type,
            section_type=section_type,
            year=year,
            min_similarity=min_similarity,
            per_page=limit,
        )
    except ThesmaError as e:
        return str(e)

    results = response.data
    if not results:
        return _format_no_results(query, ticker, filing_type, section_type, year, min_similarity)

    return _format_results(query, results, response.pagination, ticker, filing_type, section_type, year, min_similarity)


def _filter_summary(
    ticker: str | None,
    filing_type: str | None,
    section_type: str | None,
    year: int | None,
    min_similarity: float | None,
) -> list[str]:
    filters: list[str] = []
    if ticker:
        filters.append(f"ticker={ticker.upper()}")
    if filing_type:
        filters.append(f"filing_type={filing_type}")
    if section_type:
        filters.append(f"section_type={section_type}")
    if year is not None:
        filters.append(f"year={year}")
    if min_similarity is not None:
        filters.append(f"min_similarity={min_similarity}")
    return filters


def _format_no_results(
    query: str,
    ticker: str | None,
    filing_type: str | None,
    section_type: str | None,
    year: int | None,
    min_similarity: float | None,
) -> str:
    filters = _filter_summary(ticker, filing_type, section_type, year, min_similarity)
    filter_suffix = f" with filters [{', '.join(filters)}]" if filters else ""
    return (
        f"No matches found for {query!r}{filter_suffix}. Try a broader query, a lower min_similarity, or fewer filters."
    )


def _format_results(
    query: str,
    results: list[Any],
    pagination: Any,
    ticker: str | None,
    filing_type: str | None,
    section_type: str | None,
    year: int | None,
    min_similarity: float | None,
) -> str:
    filters = _filter_summary(ticker, filing_type, section_type, year, min_similarity)
    filter_suffix = f" — filters: {', '.join(filters)}" if filters else ""
    count = len(results)
    header = f"Filing-section search: {query!r}{filter_suffix} ({count} match{'es' if count != 1 else ''})"

    blocks: list[str] = []
    for i, r in enumerate(results, start=1):
        filed = str(r.filed_at.date()) if hasattr(r.filed_at, "date") else str(r.filed_at)[:10]
        meta = (
            f"{i}. {r.company_name} — {r.filing_type}, {filed}, {r.section_type} "
            f"(score {r.similarity_score:.2f}, {r.word_count} words, accession {r.accession_number})"
        )
        excerpt = r.chunk_text.strip()
        blocks.append(f"{meta}\n   {excerpt}")

    has_more = getattr(pagination, "has_more", False)
    more_suffix = " (more available; raise limit or paginate to see additional results)" if has_more else ""
    footer = f"Source: SEC EDGAR, semantic search over filing section chunks.{more_suffix}"

    return f"{header}\n\n" + "\n\n".join(blocks) + f"\n\n{footer}"
