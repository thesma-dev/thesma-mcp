"""MCP tools for company discovery."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import Context
from thesma.errors import ThesmaError

from thesma_mcp.formatters import format_currency, format_number, format_table
from thesma_mcp.server import AppContext, get_client, mcp


def _get_ctx(ctx: Context[Any, AppContext, Any]) -> AppContext:
    return ctx.request_context.lifespan_context


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


@mcp.tool(
    description=(
        "Find US public companies by name substring or ticker prefix (case-insensitive). "
        "Use this to look up a company before querying its financials, ratios, or filings. "
        "Optional filters: taxonomy='us-gaap' or 'ifrs-full' to narrow to US-GAAP 10-K vs "
        "IFRS 20-F filers; currency='<ISO-4217 code>' (e.g. 'USD', 'EUR') to narrow by "
        "presentation currency."
    )
)
async def search_companies(
    query: str,
    ctx: Context[Any, AppContext, Any],
    tier: str | None = None,
    exchange: str | None = None,
    domicile: str | None = None,
    taxonomy: str | None = None,
    currency: str | None = None,
    limit: int = 20,
) -> str:
    """Search for companies by name, ticker, or sector."""
    client = get_client(ctx)
    limit = min(limit, 50)
    exchange_value = _parse_exchange(exchange)

    # Try exact ticker match first
    try:
        response = await client.companies.list(  # type: ignore[misc]
            ticker=query.upper(),
            exchange=exchange_value,
            domicile=domicile,
            taxonomy=taxonomy,
            currency=currency,
        )
        if response.data:
            return _format_company_list(response.data, query)
    except ThesmaError:
        pass

    # Fall back to name search
    try:
        response = await client.companies.list(  # type: ignore[misc]
            search=query,
            tier=tier,
            exchange=exchange_value,
            domicile=domicile,
            taxonomy=taxonomy,
            currency=currency,
            per_page=limit,
        )
    except ThesmaError as e:
        return str(e)

    if not response.data:
        return f'No companies found matching "{query}". Try a different search term or check the spelling.'

    return _format_company_list(response.data, query)


def _format_company_list(companies: list[Any], query: str) -> str:
    """Format a list of companies as a table."""
    count = len(companies)
    lines = [f'Found {count} company{"" if count == 1 else "ies"} matching "{query}"', ""]

    headers = ["#", "Ticker", "CIK", "Company", "Index", "Exchange", "Domicile"]
    rows = []
    for i, c in enumerate(companies, 1):
        tier = str(c.company_tier.value) if hasattr(c.company_tier, "value") else str(c.company_tier or "")
        index_label = _tier_label(tier)
        rows.append(
            [
                str(i),
                c.ticker or "",
                c.cik,
                c.name,
                index_label,
                _render_exchange(getattr(c, "exchange", None)),
                _render_exchange(getattr(c, "domicile", None)),
            ]
        )

    table = format_table(headers, rows, alignments=["r", "l", "l", "l", "l", "l", "l"])
    lines.append(table)
    lines.append("")
    lines.append("Source: SEC EDGAR company registry.")
    return "\n".join(lines)


def _tier_label(tier: str | None) -> str:
    """Convert tier value to display label."""
    if not tier:
        return "Other"
    mapping = {"sp500": "S&P 500", "russell1000": "Russell 1000"}
    return mapping.get(tier, tier)


# MCP-27: ?include= composition primitive — MCP mirrors all 9 API expander values
# end-to-end (`labor_context`, `lending_context`, `financials`, `ratios`, `events`,
# `insider_trades`, `holders`, `compensation`, `board`). Events was previously
# pre-rejected; T-215 (govdata-api) + SDK-34 (thesma 0.10.1.1) enabled the expander.

VALID_INCLUDES: frozenset[str] = frozenset(
    {
        "labor_context",
        "lending_context",
        "financials",
        "ratios",
        "events",
        "insider_trades",
        "holders",
        "compensation",
        "board",
    }
)

# Canonical render order — labor + lending first (preserves pre-MCP-26 section
# positions for backwards-compat), then financials → ratios → insider_trades →
# holders → events → compensation → board. Events sits between the capital-
# markets block and the personnel block, reflecting "material corporate action."
INCLUDE_RENDER_ORDER: list[str] = [
    "labor_context",
    "lending_context",
    "financials",
    "ratios",
    "insider_trades",
    "holders",
    "events",
    "compensation",
    "board",
]

DEFAULT_INCLUDE = "labor_context,lending_context"


def _validate_include(include: str) -> str | None:
    """Validate an include= string. Returns an error message or None.

    Unknown tokens surface a generic error listing all accepted values.
    """
    tokens = [t.strip() for t in include.split(",") if t.strip()]
    accepted_list = ", ".join(sorted(VALID_INCLUDES))
    if not tokens:
        return f"Unknown include value(s): '{include}'. Accepted: {accepted_list}."
    unknown = [t for t in tokens if t not in VALID_INCLUDES]
    if unknown:
        return f"Unknown include value(s): {', '.join(unknown)}. Accepted: {accepted_list}."
    return None


def _format_company_header(data: Any, ticker: str, cik: str) -> list[str]:
    """Render the CIK / SIC / Index / Exchange / Domicile / Fiscal Year End block."""
    name = getattr(data, "name", "Unknown")
    tkr = getattr(data, "ticker", ticker.upper())
    sic_code = getattr(data, "sic_code", "")
    sic_description = getattr(data, "sic_description", "")
    tier_raw = getattr(data, "company_tier", "")
    tier = str(tier_raw.value) if hasattr(tier_raw, "value") else str(tier_raw or "")
    fiscal_year_end = getattr(data, "fiscal_year_end", "")
    data_cik = getattr(data, "cik", cik)

    sic_line = f"{sic_code} — {sic_description}" if sic_description else str(sic_code)

    return [
        f"{name} ({tkr})",
        "",
        f"{'CIK:':<18}{data_cik}",
        f"{'Ticker:':<18}{tkr}",
        f"{'SIC Code:':<18}{sic_line}",
        f"{'Index:':<18}{_tier_label(tier)}",
        f"{'Exchange:':<18}{_render_exchange(getattr(data, 'exchange', None))}",
        f"{'Domicile:':<18}{_render_exchange(getattr(data, 'domicile', None))}",
        f"{'Fiscal Year End:':<18}{fiscal_year_end}",
        "",
        "Source: SEC EDGAR company registry.",
    ]


@mcp.tool(
    description=(
        "Get company profile plus any combination of sub-resources in one call: financials, ratios, "
        "insider trades, institutional holders, 8-K corporate events, executive compensation, board, "
        "labor market context, or SBA lending context. Pass include='financials,ratios,events' "
        "(comma-separated) to compose exactly what you need. Default includes labor_context + "
        "lending_context for the company profile view."
    )
)
async def get_company(
    ticker: str,
    ctx: Context[Any, AppContext, Any],
    include: str | None = None,
) -> str:
    """Get details for a single company, optionally composing sub-resources."""
    app = _get_ctx(ctx)
    client = get_client(ctx)

    try:
        cik = await app.resolver.resolve(ticker, client=client)
    except ThesmaError as e:
        return str(e)

    # When include is None, fall back to the pre-MCP-26 default for
    # backwards compatibility (labor_context + lending_context).
    resolved_include = include if include is not None else DEFAULT_INCLUDE
    validation_error = _validate_include(resolved_include)
    if validation_error:
        return validation_error

    # Tokenize resolved_include into a set BEFORE the render loop. Substring
    # checking (`slot_name not in resolved_include`) works today by coincidence
    # (no current include value is a substring of another), but is
    # correct-by-accident — "ratio" in "ratios", future "boarding" collides with
    # "board". Set membership is correct-by-construction.
    requested: set[str] = {t.strip() for t in resolved_include.split(",") if t.strip()}

    try:
        result = await client.companies.get(cik, include=resolved_include)  # type: ignore[misc]
    except ThesmaError as e:
        return str(e)

    data = result.data
    extra: dict[str, Any] = getattr(data, "model_extra", None) or {}

    lines = _format_company_header(data, ticker, cik)

    for slot_name in INCLUDE_RENDER_ORDER:
        if slot_name not in requested:
            continue
        slot_value = _resolve_slot_value(data, extra, slot_name)
        if slot_value is None:
            # Slot was requested but API did not return it. Silently skip —
            # matches the pre-MCP-26 behavior for labor/lending (the only two
            # expanders the default include=None path requests). Consumers
            # who want a "no data" message can request the expander
            # explicitly and inspect the response text.
            continue
        # Partial-failure detection: slot is a dict carrying a typed `error`
        # sub-dict. The inner isinstance guard defends against a degenerate API
        # response shape where `error` is a string — calling error.get() on
        # that would AttributeError in _format_expander_error.
        if isinstance(slot_value, dict) and "error" in slot_value and isinstance(slot_value["error"], dict):
            lines.append("")
            lines.extend(_format_expander_error(slot_name, slot_value["error"]))
            continue
        lines.append("")
        lines.extend(_render_expander(slot_name, slot_value))

    return "\n".join(lines)


def _resolve_slot_value(data: Any, extra: dict[str, Any], slot_name: str) -> Any:
    """Read an expander slot value from either a typed attribute or model_extra.

    Some sub-objects (labor_context / lending_context) may be emitted as typed
    attributes by codegen in certain SDK versions; others (financials / ratios /
    etc.) always live in model_extra. Check typed attribute first, fall back to
    model_extra. Treat empty dict `{}` as absent for labor/lending to preserve
    the MCP-24 behaviour.
    """
    attr_value = getattr(data, slot_name, None)
    if attr_value is None:
        attr_value = extra.get(slot_name)
    if slot_name in ("labor_context", "lending_context"):
        if isinstance(attr_value, dict) and not attr_value:
            return None
    return attr_value


def _render_expander(slot_name: str, slot_value: Any) -> list[str]:
    """Dispatch to the appropriate per-expander formatter."""
    if slot_name == "labor_context":
        rendered = (
            _format_labor_context(slot_value)
            if isinstance(slot_value, dict)
            else _format_labor_context_model(slot_value)
        )
        return rendered.splitlines()
    if slot_name == "lending_context":
        rendered = (
            _format_lending_context(slot_value)
            if isinstance(slot_value, dict)
            else _format_lending_context_model(slot_value)
        )
        return rendered.splitlines()
    if slot_name == "financials":
        return _format_financials_teaser(slot_value)
    if slot_name == "ratios":
        return _format_ratios_teaser(slot_value)
    if slot_name == "insider_trades":
        return _format_insider_trades_teaser(slot_value)
    if slot_name == "holders":
        return _format_holders_teaser(slot_value)
    if slot_name == "events":
        return _format_events_teaser(slot_value)
    if slot_name == "compensation":
        return _format_compensation_teaser(slot_value)
    if slot_name == "board":
        return _format_board_teaser(slot_value)
    return []


def _format_expander_error(slot_name: str, error: dict[str, Any]) -> list[str]:
    """Render a partial-failure error slot with a warning marker."""
    titles = {
        "labor_context": "Labor Market Context",
        "lending_context": "Lending Market Context",
        "financials": "Financials",
        "ratios": "Ratios",
        "insider_trades": "Insider Trades",
        "holders": "Institutional Holders",
        "events": "Recent 8-K Events",
        "compensation": "Executive Compensation",
        "board": "Board of Directors",
    }
    code = error.get("code", "unknown")
    message = error.get("message", "Unavailable due to upstream error.")
    return [
        f"## {titles.get(slot_name, slot_name)}",
        f"⚠ Unavailable ({code}): {message}",
    ]


def _slot_get(slot: Any, key: str, default: Any = None) -> Any:
    """Helper: read a field from a dict slot or a model-like slot."""
    if isinstance(slot, dict):
        return slot.get(key, default)
    return getattr(slot, key, default)


def _format_financials_teaser(slot: Any) -> list[str]:
    """Render the income-statement teaser — 5 income fields + EPS.

    Only income-statement fields (revenue / cost_of_revenue / gross_profit /
    operating_income / net_income / eps_diluted). Balance-sheet / cash-flow
    fields are NOT included; the SDK-32 `financials` inline payload is the
    latest annual income statement, so total_equity / common_shares_outstanding
    would always be null on this slot.
    """
    from thesma_mcp.formatters import format_currency

    line_items = _slot_get(slot, "line_items", {}) or {}
    currency = _slot_get(slot, "currency", "USD") or "USD"
    lines = ["## Financials"]
    rendered_any = False
    for key, label in (
        ("revenue", "Revenue"),
        ("cost_of_revenue", "Cost of Revenue"),
        ("gross_profit", "Gross Profit"),
        ("operating_income", "Operating Income"),
        ("net_income", "Net Income"),
    ):
        value = line_items.get(key)
        if value is None:
            continue
        lines.append(f"{label + ':':<20}{format_currency(value)}")
        rendered_any = True
    eps = line_items.get("eps_diluted")
    if eps is not None:
        lines.append(f"{'EPS (diluted):':<20}{format_currency(eps, decimals=2)}")
        rendered_any = True
    if not rendered_any:
        lines.append("_(no income-statement data in response)_")
    lines.append(f"Currency: {currency}")
    return lines


def _format_ratios_teaser(slot: Any) -> list[str]:
    """Render the top-6 ratios as a compact block."""
    from thesma_mcp.formatters import format_percent

    lines = ["## Ratios"]
    rendered_any = False
    for key, label, is_pct in (
        ("gross_margin", "Gross Margin", True),
        ("operating_margin", "Operating Margin", True),
        ("net_margin", "Net Margin", True),
        ("return_on_equity", "Return on Equity", True),
        ("debt_to_equity", "Debt-to-Equity", False),
        ("current_ratio", "Current Ratio", False),
    ):
        value = _slot_get(slot, key)
        if value is None:
            continue
        formatted = format_percent(value) if is_pct else f"{value:.2f}"
        lines.append(f"{label + ':':<20}{formatted}")
        rendered_any = True
    if not rendered_any:
        lines.append("_(no ratios data in response)_")
    return lines


def _format_insider_trades_teaser(slot: Any) -> list[str]:
    """Render the top-5 insider trades as a compact table."""
    from thesma_mcp.formatters import format_currency, format_table

    if not isinstance(slot, list):
        return ["## Insider Trades", "_(unexpected payload shape)_"]
    lines = ["## Insider Trades"]
    if not slot:
        lines.append("_(no recent insider trades)_")
        return lines
    rows = []
    for row in slot[:5]:
        person = _slot_get(row, "person") or {}
        person_name = _slot_get(person, "name") or ""
        date_str = str(_slot_get(row, "transaction_date", ""))
        trade_type = str(_slot_get(row, "type", "") or "")
        value = _slot_get(row, "total_value")
        rows.append([date_str, person_name, trade_type, format_currency(value) if value is not None else "N/A"])
    lines.append(format_table(["Date", "Person", "Type", "Value"], rows, alignments=["l", "l", "l", "r"]))
    return lines


def _format_holders_teaser(slot: Any) -> list[str]:
    """Render the top-5 institutional holders + temporal context in the header."""
    from thesma_mcp.formatters import format_currency, format_number, format_table

    if not isinstance(slot, list):
        return ["## Institutional Holders", "_(unexpected payload shape)_"]
    if not slot:
        return ["## Institutional Holders", "_(no holders in response)_"]
    # Surface the MCP-24 temporal anchor when rows carry report_quarter.
    first = slot[0]
    report_quarter = _slot_get(first, "report_quarter")
    header = "## Institutional Holders"
    if report_quarter:
        header += f" (as of {report_quarter})"
    lines = [header]
    rows = []
    for i, h in enumerate(slot[:5], 1):
        shares = _slot_get(h, "shares")
        value = _slot_get(h, "market_value")
        rows.append(
            [
                str(i),
                _slot_get(h, "fund_name") or "",
                format_number(shares, decimals=1) if shares is not None else "N/A",
                format_currency(value) if value is not None else "N/A",
            ]
        )
    lines.append(format_table(["#", "Fund", "Shares", "Value"], rows, alignments=["r", "l", "r", "r"]))
    return lines


def _format_events_teaser(slot: Any) -> list[str]:
    """Render the top-10 recent 8-K filings as a compact list.

    Each row is a dict with ``filing_accession``, ``filed_at`` (ISO 8601 str or
    ``None``), ``category`` (one of 9 slugs — pass-through; the renderer does
    not hardcode the set so API additions surface automatically), and ``items``
    (list of ``{"code": str, "description": str}``; may be empty). The API
    already caps the slot at 10 rows; this renderer trusts that contract.

    Per-row defensive guards: ``filed_at`` may be ``None`` or non-string →
    render ``"unknown date"`` placeholder; ``items=[]`` → render the one-liner
    with just date + category (no code+description fragment); ``items[0]``
    missing ``code``/``description`` → fall back to empty strings. The
    renderer must never crash on one malformed row.
    """
    if not isinstance(slot, list):
        return ["## Recent 8-K Events", "_(unexpected payload shape)_"]
    lines = ["## Recent 8-K Events"]
    if not slot:
        lines.append("_No recent 8-K filings._")
        return lines
    for row in slot[:10]:
        # filed_at: tolerate None / non-string; slice first 10 chars for YYYY-MM-DD.
        fa_raw = _slot_get(row, "filed_at")
        fa_str = str(fa_raw) if fa_raw else ""
        date_part = fa_str[:10] if fa_str else "unknown date"
        category = str(_slot_get(row, "category", "") or "")
        items = _slot_get(row, "items", []) or []
        # items=[]: render date + category alone (no code+description fragment).
        if items and isinstance(items, list):
            first = items[0] if isinstance(items[0], dict) else {}
            code = str(first.get("code", "") or "")
            description = str(first.get("description", "") or "")
            if code or description:
                lines.append(f"- {date_part} · {category} — {code} {description}".rstrip())
            else:
                lines.append(f"- {date_part} · {category}")
        else:
            lines.append(f"- {date_part} · {category}")
    return lines


def _format_compensation_teaser(slot: Any) -> list[str]:
    """Render the top-3 NEOs by total compensation + the pay ratio."""
    from thesma_mcp.formatters import format_currency

    executives = _slot_get(slot, "executives") or []
    pay_ratio_obj = _slot_get(slot, "pay_ratio")
    lines = ["## Executive Compensation"]
    if not executives:
        lines.append("_(no executives in response)_")
    else:
        # Sort by total compensation descending; missing values sink to the bottom.
        def _total(e: Any) -> float:
            comp = _slot_get(e, "compensation") or {}
            total = _slot_get(comp, "total")
            return float(total) if isinstance(total, (int, float)) else 0.0

        top_three = sorted(executives, key=_total, reverse=True)[:3]
        for e in top_three:
            name = _slot_get(e, "name") or "Unknown"
            title = _slot_get(e, "title") or ""
            comp = _slot_get(e, "compensation") or {}
            total = _slot_get(comp, "total")
            total_str = format_currency(total) if total is not None else "N/A"
            lines.append(f"- {name} ({title}): {total_str}")
    if pay_ratio_obj is not None:
        ratio = _slot_get(pay_ratio_obj, "ratio")
        if ratio is not None:
            lines.append(f"CEO-to-Median Pay Ratio: {ratio}:1")
    return lines


def _format_board_teaser(slot: Any) -> list[str]:
    """Render the board roster (up to 10 members) as a compact table."""
    from thesma_mcp.formatters import format_table

    members = _slot_get(slot, "members") or []
    lines = ["## Board of Directors"]
    if not members:
        lines.append("_(no board members in response)_")
        return lines
    rows = []
    for m in members[:10]:
        name = _slot_get(m, "name") or ""
        is_indep = _slot_get(m, "is_independent")
        if is_indep is True:
            indep = "Yes"
        elif is_indep is False:
            indep = "No"
        else:
            indep = "N/A"
        committees = _slot_get(m, "committees") or []
        committees_str = ", ".join(committees) if isinstance(committees, list) else ""
        rows.append([name, indep, committees_str])
    lines.append(format_table(["Name", "Independent", "Committees"], rows, alignments=["l", "l", "l"]))
    return lines


def _yoy_indicator(value: float | None) -> str:
    """Return arrow indicator for YoY percentage. Empty string if null or zero."""
    if value is None or value == 0:
        return ""
    if value > 0:
        return f"\u25b2 {value:.1f}%"
    return f"\u25bc {abs(value):.1f}%"


def _format_summary_model_or_dict(summary: Any) -> list[str] | None:
    """Render the labor_context.summary derived-classification block.

    Accepts a ``LaborContextSummary`` Pydantic model OR a dict (``extra='allow'``
    passthrough path). Returns ``None`` when every sub-field is null so the
    caller can skip the section header entirely — avoids emitting a bare
    ``**Derived Signals**`` block with no content under it.
    """

    def _get(attr: str) -> Any:
        if isinstance(summary, dict):
            return summary.get(attr)
        return getattr(summary, attr, None)

    hiring = _get("industry_hiring_trend")
    unemp = _get("local_unemployment_trend")
    ratio = _get("comp_to_market_ratio")
    tightness = _get("labour_market_tightness")
    if hiring is None and unemp is None and ratio is None and tightness is None:
        return None
    lines: list[str] = ["**Derived Signals**"]
    # Guard with `is not None`, NOT truthiness — the API can return an
    # empty-string classification label for un-classified cohorts; `if hiring:`
    # would silently drop those. Matches the `if emp is not None` pattern in
    # the existing industry / local-market renderers below.
    if hiring is not None:
        lines.append(f"- Industry Hiring Trend: {hiring}")
    if unemp is not None:
        lines.append(f"- Local Unemployment Trend: {unemp}")
    if ratio is not None:
        lines.append(f"- Comp-to-Market Ratio: {ratio:.1f}x")
    if tightness is not None:
        # 1.0 ± 0.05 dead band avoids "tight / loose" flipping on trivial
        # decimal jitter around parity.
        if tightness >= 1.05:
            label = "(tight)"
        elif tightness <= 0.95:
            label = "(loose)"
        else:
            label = ""
        suffix = f" {label}" if label else ""
        lines.append(f"- Labour Market Tightness: {tightness:.2f}{suffix}")
    return lines


def _format_data_freshness_model_or_dict(freshness: Any) -> list[str] | None:
    """Render the labor_context.data_freshness period-anchor block.

    Accepts a ``DataFreshness`` model or dict. Returns ``None`` when all 6
    period anchors are null so the section is omitted.
    """

    def _get(attr: str) -> Any:
        if isinstance(freshness, dict):
            return freshness.get(attr)
        return getattr(freshness, attr, None)

    periods = [
        ("CES", _get("ces_period")),
        ("QCEW", _get("qcew_period")),
        ("JOLTS", _get("jolts_period")),
        ("LAUS", _get("laus_period")),
        ("OEWS", _get("oews_period")),
        ("SEC Exec Comp Snapshot", _get("sec_exec_comp_snapshot_date")),
    ]
    # Explicit `is not None` — an empty-string period value should still render
    # so the operator sees the shape rather than a silent suppression.
    non_null = [(label, val) for label, val in periods if val is not None]
    if not non_null:
        return None
    lines: list[str] = ["**Data Freshness**"]
    for label, val in non_null:
        lines.append(f"- {label}: {val}")
    return lines


def _format_labor_context_model(labor_ctx: Any) -> str:
    """Format the labor market context from a LaborContext Pydantic model."""
    sections: list[str] = ["## Labor Market Context"]

    industry = getattr(labor_ctx, "industry", None)
    if industry:
        naics = getattr(industry, "naics_code", "")
        desc = getattr(industry, "naics_description", "")
        header = f"**Industry (NAICS {naics}"
        if desc:
            header += f" - {desc}"
        header += ")**"
        sections.append("")
        sections.append(header)

        emp = getattr(industry, "total_employment_thousands", None)
        if emp is not None:
            emp_line = f"- Employment: {format_number(emp)}K"
            yoy = _yoy_indicator(getattr(industry, "employment_yoy_pct", None))
            if yoy:
                emp_line += f" ({yoy} YoY)"
            sections.append(emp_line)

        earnings = getattr(industry, "avg_hourly_earnings", None)
        if earnings is not None:
            earn_line = f"- Avg Hourly Earnings: {format_currency(earnings, decimals=2)}"
            yoy = _yoy_indicator(getattr(industry, "earnings_yoy_pct", None))
            if yoy:
                earn_line += f" ({yoy} YoY)"
            sections.append(earn_line)

    local = getattr(labor_ctx, "local_market", None)
    if local:
        county_name = getattr(local, "county_name", "")
        sections.append("")
        sections.append(f"**Local Market ({county_name})**")

        ind_emp = getattr(local, "industry_employment", None)
        if ind_emp is not None:
            sections.append(f"- Industry Employment: {format_number(ind_emp)}")

        avg_wage = getattr(local, "avg_weekly_wage", None)
        if avg_wage is None:
            avg_wage = getattr(local, "industry_avg_weekly_wage", None)
        if avg_wage is not None:
            wage_line = f"- Avg Weekly Wage: {format_currency(avg_wage, decimals=0)}"
            yoy = _yoy_indicator(getattr(local, "industry_wage_yoy_pct", None))
            if yoy:
                wage_line += f" ({yoy} YoY)"
            sections.append(wage_line)

    comp = getattr(labor_ctx, "compensation_benchmark", None)
    if comp:
        soc_code = getattr(comp, "soc_code", "")
        soc_title = getattr(comp, "soc_title", "")
        sections.append("")
        sections.append("**CEO Compensation Benchmark**")

        median = getattr(comp, "market_median_annual_wage", None)
        if median is not None:
            sections.append(f"- Market Median: {format_currency(median, decimals=0)} (SOC {soc_code}, {soc_title})")

        p75 = getattr(comp, "market_75th_percentile", None)
        if p75 is not None:
            sections.append(f"- Market 75th Percentile: {format_currency(p75, decimals=0)}")

        p90 = getattr(comp, "market_90th_percentile", None)
        if p90 is not None:
            sections.append(f"- Market 90th Percentile: {format_currency(p90, decimals=0)}")

        ratio = getattr(comp, "comp_to_market_ratio", None)
        if ratio is not None:
            sections.append(f"- Company CEO Comp-to-Market: {ratio:.1f}x")

    # MCP-24: post-S3 LaborContext gained `summary` (4 derived classification
    # labels) and `data_freshness` (6 period anchors). Append both blocks at
    # the bottom of the labor_context section, after compensation_benchmark.
    summary = getattr(labor_ctx, "summary", None)
    if summary is not None:
        summary_block = _format_summary_model_or_dict(summary)
        if summary_block is not None:
            sections.append("")
            sections.extend(summary_block)

    freshness = getattr(labor_ctx, "data_freshness", None)
    if freshness is not None:
        freshness_block = _format_data_freshness_model_or_dict(freshness)
        if freshness_block is not None:
            sections.append("")
            sections.extend(freshness_block)

    return "\n".join(sections)


def _format_labor_context(labor_ctx: dict[str, Any]) -> str:
    """Format the labor market context section from get_company response (dict form)."""
    sections: list[str] = ["## Labor Market Context"]

    # Industry section
    industry = labor_ctx.get("industry")
    if industry:
        naics = industry.get("naics_code", "")
        desc = industry.get("naics_description", "")
        header = f"**Industry (NAICS {naics}"
        if desc:
            header += f" - {desc}"
        header += ")**"
        sections.append("")
        sections.append(header)

        emp = industry.get("total_employment_thousands")
        if emp is not None:
            emp_line = f"- Employment: {format_number(emp)}K"
            yoy = _yoy_indicator(industry.get("employment_yoy_pct"))
            if yoy:
                emp_line += f" ({yoy} YoY)"
            sections.append(emp_line)

        earnings = industry.get("avg_hourly_earnings")
        if earnings is not None:
            earn_line = f"- Avg Hourly Earnings: {format_currency(earnings, decimals=2)}"
            yoy = _yoy_indicator(industry.get("earnings_yoy_pct"))
            if yoy:
                earn_line += f" ({yoy} YoY)"
            sections.append(earn_line)

    # Local market section
    local = labor_ctx.get("local_market")
    if local:
        county_name = local.get("county_name", "")
        sections.append("")
        sections.append(f"**Local Market ({county_name})**")

        ind_emp = local.get("industry_employment")
        if ind_emp is not None:
            sections.append(f"- Industry Employment: {format_number(ind_emp)}")

        avg_wage = local.get("avg_weekly_wage")
        if avg_wage is not None:
            wage_line = f"- Avg Weekly Wage: {format_currency(avg_wage, decimals=0)}"
            yoy = _yoy_indicator(local.get("industry_wage_yoy_pct"))
            if yoy:
                wage_line += f" ({yoy} YoY)"
            sections.append(wage_line)

    # Compensation benchmark section
    comp = labor_ctx.get("compensation_benchmark")
    if comp:
        soc_code = comp.get("soc_code", "")
        soc_title = comp.get("soc_title", "")
        sections.append("")
        sections.append("**CEO Compensation Benchmark**")

        median = comp.get("market_median_annual_wage")
        if median is not None:
            sections.append(f"- Market Median: {format_currency(median, decimals=0)} (SOC {soc_code}, {soc_title})")

        p75 = comp.get("market_75th_percentile")
        if p75 is not None:
            sections.append(f"- Market 75th Percentile: {format_currency(p75, decimals=0)}")

        p90 = comp.get("market_90th_percentile")
        if p90 is not None:
            sections.append(f"- Market 90th Percentile: {format_currency(p90, decimals=0)}")

        ratio = comp.get("comp_to_market_ratio")
        if ratio is not None:
            sections.append(f"- Company CEO Comp-to-Market: {ratio:.1f}x")

    # Same summary + data_freshness appends as the model-path twin above.
    summary = labor_ctx.get("summary")
    if summary is not None:
        summary_block = _format_summary_model_or_dict(summary)
        if summary_block is not None:
            sections.append("")
            sections.extend(summary_block)

    freshness = labor_ctx.get("data_freshness")
    if freshness is not None:
        freshness_block = _format_data_freshness_model_or_dict(freshness)
        if freshness_block is not None:
            sections.append("")
            sections.extend(freshness_block)

    return "\n".join(sections)


def _yoy_signed(value: float | None) -> str:
    """Render a signed YoY percentage using the existing arrow indicator, or '—' if None."""
    if value is None:
        return "\u2014"
    return _yoy_indicator(value) or "0.0%"


def _format_lending_context_model(lending_ctx: Any) -> str:
    """Format the lending market context from a LendingContext Pydantic model."""
    sections: list[str] = ["## Lending Market Context"]

    local = getattr(lending_ctx, "local_market", None)
    industry = getattr(lending_ctx, "industry_lending", None)

    if local is None and industry is None:
        sections.append("")
        sections.append("_(no lending context available — county FIPS may be unmapped or no SBA data exists)_")
        return "\n".join(sections)

    if local is not None:
        county_name = getattr(local, "county_name", None) or "county unknown"
        county_fips = getattr(local, "county_fips", None) or "\u2014"
        sections.append("")
        sections.append(f"**Local Market ({county_name}, FIPS {county_fips})**")

        loan_count = getattr(local, "quarterly_loan_count", None)
        if loan_count is not None:
            sections.append(f"- Quarterly Loan Count: {format_number(loan_count, decimals=0)}")

        total_amount = getattr(local, "quarterly_total_amount", None)
        if total_amount is not None:
            sections.append(f"- Quarterly Total Amount: {format_currency(total_amount, decimals=0)}")

        avg_size = getattr(local, "avg_loan_size", None)
        if avg_size is not None:
            sections.append(f"- Avg Loan Size: {format_currency(avg_size, decimals=0)}")

        yoy = getattr(local, "quarterly_yoy_change_pct", None)
        sections.append(f"- YoY Change: {_yoy_signed(yoy)}")

        charge_off = getattr(local, "charge_off_rate_trailing_4q", None)
        if charge_off is not None:
            sections.append(f"- Charge-off Rate (trailing 4Q): {charge_off:.2f}%")

        top_naics = getattr(local, "top_industry_naics", None)
        top_name = getattr(local, "top_industry_name", None)
        if top_naics or top_name:
            sections.append(f"- Top Industry: NAICS {top_naics or '—'} — {top_name or '—'}")

        period = getattr(local, "data_period", None)
        if period:
            sections.append(f"- Data Period: {period}")

        # _render_exchange is a misnomer — body works for any enum/string/None.
        confidence = _render_exchange(getattr(local, "county_fips_confidence", None))
        sections.append(f"- Match Confidence: {confidence}")

    if industry is not None:
        naics = getattr(industry, "naics_code", "") or ""
        desc = getattr(industry, "naics_description", "") or ""
        sections.append("")
        sections.append(f"**Industry Lending (NAICS {naics} — {desc})**")

        match_level = getattr(industry, "naics_match_level", None)
        if match_level:
            sections.append(f"- Match Level: {match_level}")

        nat_count = getattr(industry, "national_quarterly_loan_count", None)
        if nat_count is not None:
            sections.append(f"- National Quarterly Loan Count: {format_number(nat_count, decimals=0)}")

        nat_amount = getattr(industry, "national_quarterly_total_amount", None)
        if nat_amount is not None:
            sections.append(f"- National Quarterly Total Amount: {format_currency(nat_amount, decimals=0)}")

        nat_avg = getattr(industry, "national_avg_loan_size", None)
        if nat_avg is not None:
            sections.append(f"- National Avg Loan Size: {format_currency(nat_avg, decimals=0)}")

        nat_yoy = getattr(industry, "national_yoy_change_pct", None)
        sections.append(f"- National YoY Change: {_yoy_signed(nat_yoy)}")

        nat_charge_off = getattr(industry, "national_charge_off_rate_trailing_4q", None)
        if nat_charge_off is not None:
            sections.append(f"- National Charge-off Rate (trailing 4Q): {nat_charge_off:.2f}%")

        period = getattr(industry, "data_period", None)
        if period:
            sections.append(f"- Data Period: {period}")

    return "\n".join(sections)


def _format_lending_context(lending_ctx: dict[str, Any]) -> str:
    """Format the lending market context from a dict (extra='allow' passthrough)."""
    sections: list[str] = ["## Lending Market Context"]

    local = lending_ctx.get("local_market")
    industry = lending_ctx.get("industry_lending")

    if not local and not industry:
        sections.append("")
        sections.append("_(no lending context available — county FIPS may be unmapped or no SBA data exists)_")
        return "\n".join(sections)

    if local:
        county_name = local.get("county_name") or "county unknown"
        county_fips = local.get("county_fips") or "\u2014"
        sections.append("")
        sections.append(f"**Local Market ({county_name}, FIPS {county_fips})**")

        loan_count = local.get("quarterly_loan_count")
        if loan_count is not None:
            sections.append(f"- Quarterly Loan Count: {format_number(loan_count, decimals=0)}")

        total_amount = local.get("quarterly_total_amount")
        if total_amount is not None:
            sections.append(f"- Quarterly Total Amount: {format_currency(total_amount, decimals=0)}")

        avg_size = local.get("avg_loan_size")
        if avg_size is not None:
            sections.append(f"- Avg Loan Size: {format_currency(avg_size, decimals=0)}")

        yoy = local.get("quarterly_yoy_change_pct")
        sections.append(f"- YoY Change: {_yoy_signed(yoy)}")

        charge_off = local.get("charge_off_rate_trailing_4q")
        if charge_off is not None:
            sections.append(f"- Charge-off Rate (trailing 4Q): {charge_off:.2f}%")

        top_naics = local.get("top_industry_naics")
        top_name = local.get("top_industry_name")
        if top_naics or top_name:
            sections.append(f"- Top Industry: NAICS {top_naics or '—'} — {top_name or '—'}")

        period = local.get("data_period")
        if period:
            sections.append(f"- Data Period: {period}")

        confidence = local.get("county_fips_confidence") or "\u2014"
        sections.append(f"- Match Confidence: {confidence}")

    if industry:
        naics = industry.get("naics_code", "") or ""
        desc = industry.get("naics_description", "") or ""
        sections.append("")
        sections.append(f"**Industry Lending (NAICS {naics} — {desc})**")

        match_level = industry.get("naics_match_level")
        if match_level:
            sections.append(f"- Match Level: {match_level}")

        nat_count = industry.get("national_quarterly_loan_count")
        if nat_count is not None:
            sections.append(f"- National Quarterly Loan Count: {format_number(nat_count, decimals=0)}")

        nat_amount = industry.get("national_quarterly_total_amount")
        if nat_amount is not None:
            sections.append(f"- National Quarterly Total Amount: {format_currency(nat_amount, decimals=0)}")

        nat_avg = industry.get("national_avg_loan_size")
        if nat_avg is not None:
            sections.append(f"- National Avg Loan Size: {format_currency(nat_avg, decimals=0)}")

        nat_yoy = industry.get("national_yoy_change_pct")
        sections.append(f"- National YoY Change: {_yoy_signed(nat_yoy)}")

        nat_charge_off = industry.get("national_charge_off_rate_trailing_4q")
        if nat_charge_off is not None:
            sections.append(f"- National Charge-off Rate (trailing 4Q): {nat_charge_off:.2f}%")

        period = industry.get("data_period")
        if period:
            sections.append(f"- Data Period: {period}")

    return "\n".join(sections)
