"""MCP tools for executive compensation and board governance."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import Context
from thesma.errors import ThesmaError

from thesma_mcp.formatters import format_currency, format_table
from thesma_mcp.server import AppContext, mcp


def _get_ctx(ctx: Context[Any, AppContext, Any]) -> AppContext:
    return ctx.request_context.lifespan_context


@mcp.tool(
    description=(
        "Get executive compensation (salary, bonus, stock awards, total) from proxy statements. "
        "Includes CEO-to-median pay ratio when available. Accepts ticker or CIK."
    )
)
async def get_executive_compensation(
    ticker: str,
    ctx: Context[Any, AppContext, Any],
    year: int | None = None,
) -> str:
    """Get named executive officer compensation."""
    app = _get_ctx(ctx)

    try:
        cik = await app.resolver.resolve(ticker)
    except ThesmaError as e:
        return str(e)

    try:
        result = await app.client.compensation.get(cik, year=year)  # type: ignore[misc]
    except ThesmaError as e:
        return str(e)

    data = result.data
    company_name = data.company.name if data.company else ticker.upper()
    company_ticker = data.company.ticker if data.company and data.company.ticker else ticker.upper()
    fiscal_year = data.fiscal_year
    executives = data.executives
    pay_ratio = data.pay_ratio
    accession = data.filing_accession

    if not executives:
        return "No executive compensation data found for this company."

    title = f"{company_name} ({company_ticker}) — Executive Compensation, FY {fiscal_year}"

    # Build executive data as dicts for column detection
    exec_dicts: list[dict[str, Any]] = []
    for ex in executives:
        comp = ex.compensation
        exec_dicts.append(
            {
                "name": ex.name,
                "title": ex.title or "",
                "salary": comp.salary,
                "bonus": comp.bonus,
                "stock_awards": comp.stock_awards,
                "option_awards": comp.option_awards,
                "non_equity_incentive": comp.non_equity_incentive,
                "other_compensation": comp.other,
                "total_compensation": comp.total,
            }
        )

    # Determine which columns have data
    comp_fields = [
        ("salary", "Salary"),
        ("bonus", "Bonus"),
        ("stock_awards", "Stock Awards"),
        ("option_awards", "Option Awards"),
        ("non_equity_incentive", "Non-Equity Incentive"),
        ("other_compensation", "Other"),
        ("total_compensation", "Total"),
    ]

    # Only show columns that have at least one non-null value
    active_fields: list[tuple[str, str]] = []
    for key, label in comp_fields:
        if any(e.get(key) is not None for e in exec_dicts):
            active_fields.append((key, label))

    headers = ["Name", "Title", *[label for _, label in active_fields]]
    alignments = ["l", "l", *["r" for _ in active_fields]]
    rows = []
    for exec_ in exec_dicts:
        row = [
            exec_.get("name", ""),
            exec_.get("title", ""),
        ]
        for key, _ in active_fields:
            row.append(format_currency(exec_.get(key)))
        rows.append(row)

    lines = [title, ""]
    lines.append(format_table(headers, rows, alignments=alignments))

    if pay_ratio is not None:
        lines.append("")
        lines.append(f"CEO-to-Median Pay Ratio: {pay_ratio.ratio}:1")
        if pay_ratio.ceo_compensation is not None and pay_ratio.median_employee_compensation is not None:
            ceo_fmt = format_currency(pay_ratio.ceo_compensation)
            median_fmt = format_currency(pay_ratio.median_employee_compensation)
            lines.append(f"  CEO compensation: {ceo_fmt} | Median employee: {median_fmt}")

    lines.append("")
    if accession:
        lines.append(f"Source: SEC EDGAR, DEF 14A filing {accession}.")
    else:
        lines.append("Source: SEC EDGAR, DEF 14A filing.")
    return "\n".join(lines)


@mcp.tool(
    description=(
        "Get board of directors (name, age, tenure, independence, committee memberships) "
        "from proxy statements. Accepts ticker or CIK."
    )
)
async def get_board_members(
    ticker: str,
    ctx: Context[Any, AppContext, Any],
    year: int | None = None,
) -> str:
    """Get board of directors from proxy statements."""
    app = _get_ctx(ctx)

    try:
        cik = await app.resolver.resolve(ticker)
    except ThesmaError as e:
        return str(e)

    try:
        result = await app.client.compensation.board(cik)  # type: ignore[misc]
    except ThesmaError as e:
        return str(e)

    data = result.data
    company_name = data.company.name if data.company else ticker.upper()
    company_ticker = data.company.ticker if data.company and data.company.ticker else ticker.upper()
    fiscal_year = data.fiscal_year
    members = data.members
    accession = data.filing_accession

    if not members:
        return "No board data found for this company."

    total = len(members)
    suffix = "s" if total != 1 else ""
    title = f"{company_name} ({company_ticker}) — Board of Directors, FY {fiscal_year} ({total} member{suffix})"

    headers = ["Name", "Age", "Tenure", "Independent", "Committees"]
    rows = []
    independent_count = 0
    countable = 0

    for m in members:
        is_independent = m.is_independent
        if is_independent is True:
            ind_label = "Yes"
            independent_count += 1
            countable += 1
        elif is_independent is False:
            ind_label = "No"
            countable += 1
        else:
            ind_label = "N/A"

        tenure_years = m.tenure_years
        tenure_str = f"{tenure_years} yr" if tenure_years is not None else "\u2014"

        age = m.age
        age_str = str(age) if age is not None else "\u2014"

        # Use committee_details (list of CommitteeDetail) if available, else committees (list of str)
        committee_details = m.committee_details
        committees_list = m.committees
        if committee_details:
            committee_strs = []
            for c in committee_details:
                name = c.name
                is_chair = c.is_chair
                committee_strs.append(f"{name} (Chair)" if is_chair else name)
            committee_str = ", ".join(committee_strs)
        elif committees_list:
            committee_str = ", ".join(committees_list)
        else:
            committee_str = "\u2014"

        rows.append([m.name, age_str, tenure_str, ind_label, committee_str])

    lines = [title, ""]
    lines.append(format_table(headers, rows, alignments=["l", "r", "r", "l", "l"]))
    lines.append("")
    if countable > 0:
        lines.append(f"{independent_count} of {total} directors are independent.")
    if accession:
        lines.append(f"Source: SEC EDGAR, DEF 14A filing {accession}.")
    else:
        lines.append("Source: SEC EDGAR, DEF 14A filing.")
    return "\n".join(lines)
