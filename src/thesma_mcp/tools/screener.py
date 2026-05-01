"""Screen companies by financial criteria — MCP tool."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import Context
from thesma.errors import ThesmaError, TierRequiredError

from thesma_mcp.formatters import format_number, format_percent, format_table
from thesma_mcp.server import get_client, mcp

_JOLTS_FILTER_KEYS = {
    "min_industry_quits_rate",
    "max_industry_quits_rate",
    "min_industry_openings_rate",
    "max_industry_openings_rate",
}

JOLTS_FIELD_LABELS: dict[str, str] = {
    "min_industry_quits_rate": "industry quits rate",
    "max_industry_quits_rate": "industry quits rate",
    "min_industry_openings_rate": "industry openings rate",
    "max_industry_openings_rate": "industry openings rate",
}

_LAUS_FILTER_KEYS = {
    "min_local_unemployment_rate",
    "max_local_unemployment_rate",
    "local_unemployment_trend",
    "min_local_labor_force",
}

LAUS_FIELD_LABELS: dict[str, str] = {
    "min_local_unemployment_rate": "local unemployment rate",
    "max_local_unemployment_rate": "local unemployment rate",
    "local_unemployment_trend": "local unemployment trend",
    "min_local_labor_force": "local labor force",
}


def _parse_exchange(value: str | None) -> str | list[str] | None:
    """Accept a comma-separated string of exchanges; return the shape the SDK expects."""
    if value is None:
        return None
    parts = [p.strip() for p in value.split(",") if p.strip()]
    if not parts:
        return None
    if len(parts) == 1:
        return parts[0]
    return parts


def _render_exchange(value: Any) -> str:
    """Render an Exchange/Domicile enum member, plain string, or None as a cell."""
    if value is None:
        return "—"
    return str(getattr(value, "value", value))


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
    elif tier == "russell2000":
        parts.append("Russell 2000")
    elif tier == "russell3000":
        # Request-side superset; api expands to sp500 ∪ russell1000 ∪ russell2000
        # server-side. Never appears in a row's company_tier field — only as a
        # filter param.
        parts.append("Russell 3000 (sp500 + russell1000 + russell2000)")

    in_index = params.get("in_index")
    if in_index is True:
        parts.append("in any Russell index")
    elif in_index is False:
        parts.append("not in any Russell index")

    sic = params.get("sic")
    if sic:
        parts.append(f"SIC {sic}")

    exchange = params.get("exchange")
    if exchange:
        exchange_items = [p.strip() for p in exchange.split(",") if p.strip()]
        if len(exchange_items) > 1:
            parts.append(f"exchange in {', '.join(exchange_items)}")
        elif exchange_items:
            parts.append(f"exchange: {exchange_items[0]}")

    domicile = params.get("domicile")
    if domicile:
        parts.append(f"domicile: {domicile}")

    search = params.get("search")
    if search:
        parts.append(f'search: "{search}"')

    taxonomy = params.get("taxonomy")
    if taxonomy:
        parts.append(f"taxonomy: {taxonomy}")

    currency = params.get("currency")
    if currency:
        parts.append(f"currency: {currency}")

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

    # BLS filters
    bls_filter_map: list[tuple[str, str, str]] = [
        ("industry_hiring_trend", "hiring trend", "="),
        ("min_industry_employment_growth", "industry employment growth", ">="),
        ("max_industry_employment_growth", "industry employment growth", "<="),
        ("min_industry_wage_growth", "industry wage growth", ">="),
        ("min_hq_county_wage_growth", "HQ county wage growth", ">="),
        ("min_comp_to_market_ratio", "comp-to-market ratio", ">="),
    ]
    for param_name, label, op in bls_filter_map:
        val = params.get(param_name)
        if val is not None:
            if param_name == "industry_hiring_trend":
                filters.append(f"hiring trend: {val}")
            elif "growth" in label:
                filters.append(f"{label} {op} {val}%")
            else:
                filters.append(f"{label} {op} {val}")

    # LAUS filters
    laus_filter_map: list[tuple[str, str, str]] = [
        ("min_local_unemployment_rate", "local unemployment rate", ">="),
        ("max_local_unemployment_rate", "local unemployment rate", "<="),
        ("min_local_labor_force", "local labor force", ">="),
    ]
    for param_name, label, op in laus_filter_map:
        val = params.get(param_name)
        if val is not None:
            if "rate" in label:
                filters.append(f"{label} {op} {val}%")
            else:
                filters.append(f"{label} {op} {val}")
    trend_val = params.get("local_unemployment_trend")
    if trend_val is not None:
        filters.append(f"local unemployment trend: {trend_val}")

    # SBA filters
    sba_filter_map: list[tuple[str, str, str]] = [
        ("min_local_sba_loan_count", "local SBA loan count", ">="),
        ("max_local_sba_loan_count", "local SBA loan count", "<="),
        ("min_local_sba_lending_growth", "local SBA lending growth", ">="),
        ("max_local_sba_lending_growth", "local SBA lending growth", "<="),
        ("min_industry_sba_lending_growth", "industry SBA lending growth", ">="),
        ("max_industry_sba_charge_off_rate", "industry SBA charge-off rate", "<="),
    ]
    for param_name, label, op in sba_filter_map:
        val = params.get(param_name)
        if val is not None:
            if "growth" in label or "charge-off" in label or "rate" in label:
                filters.append(f"{label} {op} {val}%")
            else:
                filters.append(f"{label} {op} {val}")

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


def _get_column_value(company: Any, col: str) -> str:
    """Extract and format a column value from a screener result."""
    # ScreenerResultItem uses extra="allow" — ratios is a RatioValues model or dict
    ratios = getattr(company, "ratios", None)
    if ratios is None:
        return "N/A"
    if isinstance(ratios, dict):
        val = ratios.get(col)
    else:
        val = getattr(ratios, col, None)
    if val is None:
        return "N/A"
    return format_percent(val)


def _get_local_market(company: Any) -> dict[str, Any] | None:
    """Extract the LocalMarketContext sub-object as a dict.

    The screener API serialises ``labor_context`` as either a nested object
    (``labor_context.local_market.{unemployment_rate, ...}``) or a flat dict
    where the LocalMarketContext fields are merged into ``labor_context``
    itself. This helper handles both shapes — verified empirically in
    ``tests/test_screener.py`` against ``ScreenerResultItem(extra='allow')``.
    Returns ``None`` when no labor context is attached.
    """
    labor = getattr(company, "labor_context", None)
    if labor is None:
        return None
    # Try nested .local_market first (matches the SDK model).
    nested: Any = None
    if isinstance(labor, dict):
        nested = labor.get("local_market")
    else:
        nested = getattr(labor, "local_market", None)
    if nested is not None:
        if isinstance(nested, dict):
            return nested
        return {
            "county_name": getattr(nested, "county_name", None),
            "unemployment_rate": getattr(nested, "unemployment_rate", None),
            "labor_force": getattr(nested, "labor_force", None),
        }
    # Fall back to flat dict shape (legacy JOLTS-style serialisation).
    if isinstance(labor, dict):
        if any(k in labor for k in ("unemployment_rate", "labor_force", "county_name")):
            return {
                "county_name": labor.get("county_name"),
                "unemployment_rate": labor.get("unemployment_rate"),
                "labor_force": labor.get("labor_force"),
            }
        return None
    # Object with flat attrs.
    if any(hasattr(labor, k) for k in ("unemployment_rate", "labor_force", "county_name")):
        return {
            "county_name": getattr(labor, "county_name", None),
            "unemployment_rate": getattr(labor, "unemployment_rate", None),
            "labor_force": getattr(labor, "labor_force", None),
        }
    return None


_BLS_FILTER_KEYS = {
    "industry_hiring_trend",
    "min_industry_employment_growth",
    "max_industry_employment_growth",
    "min_industry_wage_growth",
    "min_hq_county_wage_growth",
    "min_comp_to_market_ratio",
}

BLS_FIELD_LABELS: dict[str, str] = {
    "industry_hiring_trend": "hiring trend",
    "min_industry_employment_growth": "industry employment growth",
    "max_industry_employment_growth": "industry employment growth",
    "min_industry_wage_growth": "industry wage growth",
    "min_hq_county_wage_growth": "HQ county wage growth",
    "min_comp_to_market_ratio": "comp-to-market ratio",
}

_SBA_FILTER_KEYS = {
    "min_local_sba_loan_count",
    "max_local_sba_loan_count",
    "min_local_sba_lending_growth",
    "max_local_sba_lending_growth",
    "min_industry_sba_lending_growth",
    "max_industry_sba_charge_off_rate",
}

SBA_FIELD_LABELS: dict[str, str] = {
    "min_local_sba_loan_count": "local SBA loan count",
    "max_local_sba_loan_count": "local SBA loan count",
    "min_local_sba_lending_growth": "local SBA lending growth",
    "max_local_sba_lending_growth": "local SBA lending growth",
    "min_industry_sba_lending_growth": "industry SBA lending growth",
    "max_industry_sba_charge_off_rate": "industry SBA charge-off rate",
}


def _get_lending_context(lc: Any) -> dict[str, Any] | None:
    """Extract the LendingContextSummary fields as a dict.

    ScreenerResultItem.lending_context is either a typed LendingContextSummary
    Pydantic model or a plain dict (extra="allow" passthrough). This helper
    normalises both shapes and returns None when the field is absent.
    """
    if lc is None:
        return None
    if isinstance(lc, dict):
        return {
            "local_sba_loan_count_4q": lc.get("local_sba_loan_count_4q"),
            "local_sba_lending_growth_yoy": lc.get("local_sba_lending_growth_yoy"),
            "industry_sba_lending_growth_yoy": lc.get("industry_sba_lending_growth_yoy"),
            "industry_sba_charge_off_rate": lc.get("industry_sba_charge_off_rate"),
        }
    return {
        "local_sba_loan_count_4q": getattr(lc, "local_sba_loan_count_4q", None),
        "local_sba_lending_growth_yoy": getattr(lc, "local_sba_lending_growth_yoy", None),
        "industry_sba_lending_growth_yoy": getattr(lc, "industry_sba_lending_growth_yoy", None),
        "industry_sba_charge_off_rate": getattr(lc, "industry_sba_charge_off_rate", None),
    }


@mcp.tool(
    description=(
        "Find US public companies matching financial criteria. "
        "Combine filters: profitability (margins), growth rates, leverage ratios, "
        "index membership, SIC code, stock exchange (nyse/nasdaq, comma-separated for multiple), "
        "domicile (us/adr), and insider/institutional signals. "
        "Supports labor market filters: industry hiring trend, employment growth, "
        "wage growth, comp-to-market ratio, and HQ-county LAUS local unemployment "
        "(min/max local unemployment rate, local unemployment trend, min local labor force). "
        "Supports SBA 7(a) lending filters: local loan count (trailing 4Q in HQ county), "
        "local lending growth (YoY %), industry lending growth (NAICS national YoY %), "
        "and industry charge-off rate (%). "
        "Set include='lending_context' or include='labor_context,lending_context' to surface "
        "an SBA lending context summary on each row. "
        "Note: include='labor_context' and include='lending_context' require a Pro+ plan. "
        "Free/Starter callers receive a tier upgrade message instead of enriched results. "
        "Sort by any ratio: gross_margin, operating_margin, net_margin, return_on_equity, "
        "return_on_assets, debt_to_equity, current_ratio, interest_coverage, "
        "revenue_growth_yoy, net_income_growth_yoy, eps_growth_yoy. "
        "Margin/ratio/growth filters use integer percent (20 for 20%, not 0.20). "
        "Values 0<x<1 are rejected as ambiguous. Pass 0 for no minimum. "
        "Use search='<term>' to filter by name substring or ticker prefix (case-insensitive; "
        "server trims/escapes/skips nulls; does not normalise 'BRK.B' vs 'BRK-B' and does not "
        "consult ticker aliases; omit search rather than passing an empty string, which the server "
        "treats as a no-op; any match lacking a qualifying annual CompanyRatio row is silently "
        "excluded by the screener inner-join). "
        "Filter by taxonomy='us-gaap' or 'ifrs-full' and/or by presentation currency via "
        "currency='<ISO-4217 code>' (case-insensitive, e.g. 'USD', 'EUR', 'JPY'); both are "
        "server-validated — unknown values return 400. "
        "Filter by Russell-index membership: in_index=True returns only "
        "companies in any tracked index (sp500, russell1000, or russell2000); "
        "in_index=False returns only unindexed companies. Note: combining "
        "in_index=False with a query that matches an indexed ticker (e.g. "
        "'AAPL') returns no results because the ticker is filtered out."
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
    in_index: bool | None = None,
    sic: str | None = None,
    exchange: str | None = None,
    domicile: str | None = None,
    taxonomy: str | None = None,
    currency: str | None = None,
    search: str | None = None,
    has_insider_buying: bool | None = None,
    has_institutional_increase: bool | None = None,
    min_industry_quits_rate: float | None = None,
    max_industry_quits_rate: float | None = None,
    min_industry_openings_rate: float | None = None,
    max_industry_openings_rate: float | None = None,
    min_local_unemployment_rate: float | None = None,
    max_local_unemployment_rate: float | None = None,
    local_unemployment_trend: str | None = None,
    min_local_labor_force: int | None = None,
    min_local_sba_loan_count: int | None = None,
    max_local_sba_loan_count: int | None = None,
    min_local_sba_lending_growth: float | None = None,
    max_local_sba_lending_growth: float | None = None,
    min_industry_sba_lending_growth: float | None = None,
    max_industry_sba_charge_off_rate: float | None = None,
    include: str | None = None,
    sort: str | None = None,
    order: str | None = None,
    limit: int = 20,
    industry_hiring_trend: str | None = None,
    min_industry_employment_growth: float | None = None,
    max_industry_employment_growth: float | None = None,
    min_industry_wage_growth: float | None = None,
    min_hq_county_wage_growth: float | None = None,
    min_comp_to_market_ratio: float | None = None,
) -> str:
    """Screen companies by financial criteria."""
    client = get_client(ctx)

    # Validate sort field
    if sort and sort not in VALID_SORT_FIELDS:
        valid = ", ".join(sorted(VALID_SORT_FIELDS))
        return f"Invalid sort field '{sort}'. Valid fields: {valid}"

    # Cap limit
    limit = min(limit, 50)

    # Build local params dict for summary/display logic
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
        "in_index": in_index,
        "sic": sic,
        "exchange": exchange,
        "domicile": domicile,
        "taxonomy": taxonomy,
        "currency": currency,
        "search": search,
        "has_insider_buying": has_insider_buying,
        "has_institutional_increase": has_institutional_increase,
        "min_industry_quits_rate": min_industry_quits_rate,
        "max_industry_quits_rate": max_industry_quits_rate,
        "min_industry_openings_rate": min_industry_openings_rate,
        "max_industry_openings_rate": max_industry_openings_rate,
        "min_local_unemployment_rate": min_local_unemployment_rate,
        "max_local_unemployment_rate": max_local_unemployment_rate,
        "local_unemployment_trend": local_unemployment_trend,
        "min_local_labor_force": min_local_labor_force,
        "min_local_sba_loan_count": min_local_sba_loan_count,
        "max_local_sba_loan_count": max_local_sba_loan_count,
        "min_local_sba_lending_growth": min_local_sba_lending_growth,
        "max_local_sba_lending_growth": max_local_sba_lending_growth,
        "min_industry_sba_lending_growth": min_industry_sba_lending_growth,
        "max_industry_sba_charge_off_rate": max_industry_sba_charge_off_rate,
        "include": include,
        "sort": sort,
        "order": order,
        "industry_hiring_trend": industry_hiring_trend,
        "min_industry_employment_growth": min_industry_employment_growth,
        "max_industry_employment_growth": max_industry_employment_growth,
        "min_industry_wage_growth": min_industry_wage_growth,
        "min_hq_county_wage_growth": min_hq_county_wage_growth,
        "min_comp_to_market_ratio": min_comp_to_market_ratio,
    }

    # Convert booleans for API
    api_has_insider = has_insider_buying if has_insider_buying else None
    api_has_institutional = has_institutional_increase if has_institutional_increase else None

    try:
        response = await client.screener.screen(  # type: ignore[misc]
            min_revenue=min_revenue,
            min_net_income=min_net_income,
            min_gross_margin=min_gross_margin,
            max_gross_margin=max_gross_margin,
            min_operating_margin=min_operating_margin,
            min_net_margin=min_net_margin,
            min_revenue_growth=min_revenue_growth,
            min_eps_growth=min_eps_growth,
            min_return_on_equity=min_return_on_equity,
            min_return_on_assets=min_return_on_assets,
            max_debt_to_equity=max_debt_to_equity,
            min_current_ratio=min_current_ratio,
            min_interest_coverage=min_interest_coverage,
            tier=tier,
            in_index=in_index,
            sic=sic,
            exchange=_parse_exchange(exchange),
            domicile=domicile,
            taxonomy=taxonomy,
            currency=currency,
            search=search,
            has_insider_buying=api_has_insider,
            has_institutional_increase=api_has_institutional,
            min_industry_quits_rate=min_industry_quits_rate,
            max_industry_quits_rate=max_industry_quits_rate,
            min_industry_openings_rate=min_industry_openings_rate,
            max_industry_openings_rate=max_industry_openings_rate,
            min_local_unemployment_rate=min_local_unemployment_rate,
            max_local_unemployment_rate=max_local_unemployment_rate,
            local_unemployment_trend=local_unemployment_trend,
            min_local_labor_force=min_local_labor_force,
            min_local_sba_loan_count=min_local_sba_loan_count,
            max_local_sba_loan_count=max_local_sba_loan_count,
            min_local_sba_lending_growth=min_local_sba_lending_growth,
            max_local_sba_lending_growth=max_local_sba_lending_growth,
            min_industry_sba_lending_growth=min_industry_sba_lending_growth,
            max_industry_sba_charge_off_rate=max_industry_sba_charge_off_rate,
            include=include,
            sort_by=sort,
            order=order,
            industry_hiring_trend=industry_hiring_trend,
            min_industry_employment_growth=min_industry_employment_growth,
            max_industry_employment_growth=max_industry_employment_growth,
            min_industry_wage_growth=min_industry_wage_growth,
            min_hq_county_wage_growth=min_hq_county_wage_growth,
            min_comp_to_market_ratio=min_comp_to_market_ratio,
            per_page=limit,
        )
    except TierRequiredError as e:
        current = e.current_tier or "unknown"
        required = e.required_tier or "pro"
        return (
            f"Pro tier required for cross-dataset enrichment. "
            f"Current tier: {current}. Required tier: {required}.\n\n"
            f"API message: {e.message}\n\n"
            "Try the screener without `include=` to see basic results, or upgrade your "
            "plan to access cross-dataset enrichment."
        )
    except ThesmaError as e:
        return str(e)

    data = response.data
    total = response.pagination.total

    if not data:
        return "No companies matched the specified criteria. Try broadening your filters."

    # Build summary header
    summary = _build_summary_header(local_params)

    # Pick display columns
    display_cols = _pick_display_columns(local_params, sort)

    # Detect whether BLS filters are active
    bls_active = any(local_params.get(k) is not None for k in _BLS_FILTER_KEYS)

    # Build table
    headers = ["#", "Ticker", "Company", "Exchange", "Domicile"]
    alignments = ["r", "l", "l", "l", "l"]
    for col in display_cols:
        headers.append(FIELD_LABELS.get(col, col).title())
        alignments.append("r")

    if bls_active:
        headers.extend(["Industry", "Hiring Trend", "Emp Growth", "Comp Ratio"])
        alignments.extend(["l", "l", "r", "r"])

    # Add JOLTS columns when JOLTS filters are active
    has_jolts_filter = any(local_params.get(k) is not None for k in _JOLTS_FILTER_KEYS)
    if has_jolts_filter:
        headers.extend(["Quits Rate", "Openings Rate", "Tightness"])
        alignments.extend(["r", "r", "r"])

    # Add LAUS columns when LAUS filters are active
    has_laus_filter = any(local_params.get(k) is not None for k in _LAUS_FILTER_KEYS)
    if has_laus_filter:
        headers.extend(["County", "Unemp Rate", "Labor Force"])
        alignments.extend(["l", "r", "r"])

    # Detect SBA activation: any SBA filter or include="...lending_context..."
    has_sba_filter = any(local_params.get(k) is not None for k in _SBA_FILTER_KEYS)
    wants_lending_context = include is not None and "lending_context" in include
    sba_active = has_sba_filter or wants_lending_context
    if sba_active:
        headers.extend(["Local Loans (4Q)", "Local Growth", "Industry Growth", "Industry Charge-off"])
        alignments.extend(["r", "r", "r", "r"])

    rows: list[list[str]] = []
    for i, company in enumerate(data, 1):
        # ScreenerResultItem uses extra="allow"
        tkr = getattr(company, "ticker", "")
        name = getattr(company, "name", "")
        row = [
            str(i),
            tkr or "",
            name or "",
            _render_exchange(getattr(company, "exchange", None)),
            _render_exchange(getattr(company, "domicile", None)),
        ]
        for col in display_cols:
            row.append(_get_column_value(company, col))
        if bls_active:
            bls = getattr(company, "bls", None) or {}
            if isinstance(bls, dict):
                row.append(str(bls.get("industry", "")))
                row.append(str(bls.get("hiring_trend", "")))
                eg = bls.get("employment_growth")
                row.append(f"{eg:.1f}%" if eg is not None else "N/A")
                cr = bls.get("comp_ratio")
                row.append(f"{cr:.1f}x" if cr is not None else "N/A")
            else:
                row.extend(["", "", "N/A", "N/A"])
        if has_jolts_filter:
            labor = getattr(company, "labor_context", None) or {}
            if isinstance(labor, dict):
                row.append(format_percent(labor.get("industry_quits_rate")))
                row.append(format_percent(labor.get("industry_openings_rate")))
                tightness = labor.get("labour_market_tightness")
                row.append(f"{tightness:.2f}" if tightness is not None else "N/A")
            else:
                row.append(format_percent(getattr(labor, "industry_quits_rate", None)))
                row.append(format_percent(getattr(labor, "industry_openings_rate", None)))
                tightness = getattr(labor, "labour_market_tightness", None)
                row.append(f"{tightness:.2f}" if tightness is not None else "N/A")
        if has_laus_filter:
            local_market = _get_local_market(company)
            if local_market is None:
                row.extend(["", "N/A", "N/A"])
            else:
                county_name = local_market.get("county_name") or ""
                ur = local_market.get("unemployment_rate")
                lf = local_market.get("labor_force")
                row.append(str(county_name))
                row.append(f"{ur:.1f}%" if ur is not None else "N/A")
                row.append(format_number(lf, decimals=0) if lf is not None else "N/A")
        if sba_active:
            lc = _get_lending_context(getattr(company, "lending_context", None))
            if lc is None:
                row.extend(["N/A", "N/A", "N/A", "N/A"])
            else:
                loans_4q = lc.get("local_sba_loan_count_4q")
                row.append(format_number(loans_4q, decimals=0) if loans_4q is not None else "N/A")
                row.append(format_percent(lc.get("local_sba_lending_growth_yoy")))
                row.append(format_percent(lc.get("industry_sba_lending_growth_yoy")))
                row.append(format_percent(lc.get("industry_sba_charge_off_rate")))
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
    if sba_active and data:
        first_df = getattr(data[0], "data_freshness", None)
        sba_period: str | None = None
        if first_df is not None:
            if isinstance(first_df, dict):
                sba_period = first_df.get("sba_period")
            else:
                sba_period = getattr(first_df, "sba_period", None)
        if sba_period:
            footer_parts.append(f"SBA data as of {sba_period}.")
    footer_parts.append("Source: SEC EDGAR, latest annual filings. Ratios derived from reported financials.")

    return f"{header_line}\n\n{table}\n\n" + "\n".join(footer_parts)
