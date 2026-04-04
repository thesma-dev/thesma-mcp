"""Screen companies by financial criteria — MCP tool."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import Context

from thesma_mcp.formatters import format_percent, format_table
from thesma_mcp.server import AppContext, mcp

_BLS_FILTER_KEYS = {
    "min_industry_quits_rate",
    "max_industry_quits_rate",
    "min_industry_openings_rate",
    "max_industry_openings_rate",
}

BLS_FIELD_LABELS: dict[str, str] = {
    "min_industry_quits_rate": "industry quits rate",
    "max_industry_quits_rate": "industry quits rate",
    "min_industry_openings_rate": "industry openings rate",
    "max_industry_openings_rate": "industry openings rate",
}

VALID_SORT_FIELDS = {
    "gross_margin",
    "operating_margin",
    "net_margin",
    "return_on_equity",
    "return_on_assets",
    "debt_to_equity",
    "current_ratio",
    "interest_coverage",
    "revenue_growth_yoy",
    "net_income_growth_yoy",
    "eps_growth_yoy",
}

# Human-readable labels for sort fields and filters
FIELD_LABELS: dict[str, str] = {
    "gross_margin": "gross margin",
    "operating_margin": "operating margin",
    "net_margin": "net margin",
    "return_on_equity": "ROE",
    "return_on_assets": "ROA",
    "debt_to_equity": "debt-to-equity",
    "current_ratio": "current ratio",
    "interest_coverage": "interest coverage",
    "revenue_growth_yoy": "revenue growth",
    "net_income_growth_yoy": "net income growth",
    "eps_growth_yoy": "EPS growth",
}


def _build_summary_header(params: dict[str, Any]) -> str:
    """Build a natural-language summary of applied filters."""
    parts: list[str] = []

    tier = params.get("tier")
    if tier == "sp500":
        parts.append("S&P 500")
    elif tier == "russell1000":
        parts.append("Russell 1000")

    sic = params.get("sic")
    if sic:
        parts.append(f"SIC {sic}")

    filters: list[str] = []
    filter_map: list[tuple[str, str, str]] = [
        ("min_revenue", "revenue", ">="),
        ("min_net_income", "net income", ">="),
        ("min_gross_margin", "gross margin", ">="),
        ("max_gross_margin", "gross margin", "<="),
        ("min_operating_margin", "operating margin", ">="),
        ("min_net_margin", "net margin", ">="),
        ("min_revenue_growth", "revenue growth", ">="),
        ("min_eps_growth", "EPS growth", ">="),
        ("min_return_on_equity", "ROE", ">="),
        ("min_return_on_assets", "ROA", ">="),
        ("max_debt_to_equity", "debt-to-equity", "<="),
        ("min_current_ratio", "current ratio", ">="),
        ("min_interest_coverage", "interest coverage", ">="),
        ("min_industry_quits_rate", "industry quits rate", ">="),
        ("max_industry_quits_rate", "industry quits rate", "<="),
        ("min_industry_openings_rate", "industry openings rate", ">="),
        ("max_industry_openings_rate", "industry openings rate", "<="),
    ]
    for param_name, label, op in filter_map:
        val = params.get(param_name)
        if val is not None:
            if "margin" in label or "growth" in label or "rate" in label or label in ("ROE", "ROA"):
                filters.append(f"{label} {op} {val}%")
            else:
                filters.append(f"{label} {op} {val}")

    if params.get("has_insider_buying"):
        filters.append("insider buying")
    if params.get("has_institutional_increase"):
        filters.append("institutional position increases")

    prefix = " ".join(parts) + " companies" if parts else "Companies"
    if filters:
        return f"{prefix} with {' and '.join(filters)}"
    if parts:
        return f"{prefix}"
    return "All screened companies"


def _pick_display_columns(params: dict[str, Any], sort_field: str | None) -> list[str]:
    """Pick the most relevant ratio columns for the table.

    Always include the sort field. Add up to 2 additional columns from the filters.
    """
    columns: list[str] = []

    # Candidate columns from filters
    filter_to_col: dict[str, str] = {
        "min_gross_margin": "gross_margin",
        "max_gross_margin": "gross_margin",
        "min_operating_margin": "operating_margin",
        "min_net_margin": "net_margin",
        "min_revenue_growth": "revenue_growth_yoy",
        "min_eps_growth": "eps_growth_yoy",
        "min_return_on_equity": "return_on_equity",
        "min_return_on_assets": "return_on_assets",
        "max_debt_to_equity": "debt_to_equity",
        "min_current_ratio": "current_ratio",
        "min_interest_coverage": "interest_coverage",
        "min_net_income": "net_margin",
    }

    for param_name, col in filter_to_col.items():
        if params.get(param_name) is not None and col not in columns:
            columns.append(col)

    # Ensure sort field is included
    if sort_field and sort_field not in columns:
        columns.insert(0, sort_field)

    # Default columns if nothing selected
    if not columns:
        columns = ["gross_margin", "net_margin", "revenue_growth_yoy"]

    # Sort field first, then up to 2 additional
    if sort_field and sort_field in columns:
        columns.remove(sort_field)
        columns = [sort_field] + columns[:2]
    else:
        columns = columns[:3]

    return columns


def _get_column_value(company: dict[str, Any], col: str) -> str:
    """Extract and format a column value from a screener result."""
    ratios = company.get("ratios", {}) or {}
    val = ratios.get(col)
    if val is None:
        return "N/A"
    return format_percent(val)


@mcp.tool(
    description=(
        "Find US public companies matching financial criteria. "
        "Combine filters: profitability (margins), growth rates, leverage ratios, "
        "index membership, SIC code, and insider/institutional signals. "
        "Sort by any ratio: gross_margin, operating_margin, net_margin, return_on_equity, "
        "return_on_assets, debt_to_equity, current_ratio, interest_coverage, "
        "revenue_growth_yoy, net_income_growth_yoy, eps_growth_yoy."
    )
)
async def screen_companies(
    ctx: Context[Any, Any],
    min_revenue: float | None = None,
    min_net_income: float | None = None,
    min_gross_margin: float | None = None,
    max_gross_margin: float | None = None,
    min_operating_margin: float | None = None,
    min_net_margin: float | None = None,
    min_revenue_growth: float | None = None,
    min_eps_growth: float | None = None,
    min_return_on_equity: float | None = None,
    min_return_on_assets: float | None = None,
    max_debt_to_equity: float | None = None,
    min_current_ratio: float | None = None,
    min_interest_coverage: float | None = None,
    tier: str | None = None,
    sic: str | None = None,
    has_insider_buying: bool | None = None,
    has_institutional_increase: bool | None = None,
    min_industry_quits_rate: float | None = None,
    max_industry_quits_rate: float | None = None,
    min_industry_openings_rate: float | None = None,
    max_industry_openings_rate: float | None = None,
    sort: str | None = None,
    order: str | None = None,
    limit: int = 20,
) -> str:
    """Screen companies by financial criteria."""
    app: AppContext = ctx.request_context.lifespan_context

    # Validate sort field
    if sort and sort not in VALID_SORT_FIELDS:
        valid = ", ".join(sorted(VALID_SORT_FIELDS))
        return f"Invalid sort field '{sort}'. Valid fields: {valid}"

    # Cap limit
    limit = min(limit, 50)

    # Build API params — only include non-None values
    local_params: dict[str, Any] = {
        "min_revenue": min_revenue,
        "min_net_income": min_net_income,
        "min_gross_margin": min_gross_margin,
        "max_gross_margin": max_gross_margin,
        "min_operating_margin": min_operating_margin,
        "min_net_margin": min_net_margin,
        "min_revenue_growth": min_revenue_growth,
        "min_eps_growth": min_eps_growth,
        "min_return_on_equity": min_return_on_equity,
        "min_return_on_assets": min_return_on_assets,
        "max_debt_to_equity": max_debt_to_equity,
        "min_current_ratio": min_current_ratio,
        "min_interest_coverage": min_interest_coverage,
        "tier": tier,
        "sic": sic,
        "has_insider_buying": has_insider_buying,
        "has_institutional_increase": has_institutional_increase,
        "min_industry_quits_rate": min_industry_quits_rate,
        "max_industry_quits_rate": max_industry_quits_rate,
        "min_industry_openings_rate": min_industry_openings_rate,
        "max_industry_openings_rate": max_industry_openings_rate,
        "sort": sort,
        "order": order,
    }

    api_params: dict[str, Any] = {"per_page": limit}
    for k, v in local_params.items():
        if v is not None:
            # Only send boolean signals when true
            if k in ("has_insider_buying", "has_institutional_increase"):
                if v:
                    api_params[k] = "true"
            else:
                api_params[k] = v

    response = await app.client.get("/v1/us/sec/screener", params=api_params)

    data = response.get("data", [])
    pagination = response.get("pagination", {})
    total = pagination.get("total", len(data))

    if not data:
        return "No companies matched the specified criteria. Try broadening your filters."

    # Build summary header
    summary = _build_summary_header(local_params)

    # Pick display columns
    display_cols = _pick_display_columns(local_params, sort)

    # Build table
    headers = ["#", "Ticker", "Company"]
    alignments = ["r", "l", "l"]
    for col in display_cols:
        headers.append(FIELD_LABELS.get(col, col).title())
        alignments.append("r")

    # Add JOLTS columns when JOLTS filters are active
    has_jolts_filter = any(local_params.get(k) is not None for k in _BLS_FILTER_KEYS)
    if has_jolts_filter:
        headers.extend(["Quits Rate", "Openings Rate", "Tightness"])
        alignments.extend(["r", "r", "r"])

    rows: list[list[str]] = []
    for i, company in enumerate(data, 1):
        row = [str(i), company.get("ticker", ""), company.get("name", "")]
        for col in display_cols:
            row.append(_get_column_value(company, col))
        if has_jolts_filter:
            labor = company.get("labor_context", {}) or {}
            row.append(format_percent(labor.get("industry_quits_rate")))
            row.append(format_percent(labor.get("industry_openings_rate")))
            tightness = labor.get("labour_market_tightness")
            row.append(f"{tightness:.2f}" if tightness is not None else "N/A")
        rows.append(row)

    table = format_table(headers, rows, alignments)

    # Footer
    count_shown = len(data)
    if total > count_shown:
        header_line = f"{summary} (top {count_shown} of {total:,} matches)"
    else:
        header_line = f"{summary} ({total:,} matches)"
    footer_parts: list[str] = []
    if total > count_shown:
        footer_parts.append(f"{total:,} companies matched. Showing top {count_shown}")
    else:
        footer_parts.append(f"{total:,} companies matched.")
    if sort:
        order_label = "ascending" if order == "asc" else "descending"
        sort_label = FIELD_LABELS.get(sort, sort)
        footer_parts[-1] = footer_parts[-1].rstrip(".") + f" sorted by {sort_label} ({order_label})."
    footer_parts.append("Source: SEC EDGAR, latest annual filings. Ratios derived from reported financials.")

    return f"{header_line}\n\n{table}\n\n" + "\n".join(footer_parts)
