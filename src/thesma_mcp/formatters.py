"""Number and response formatting utilities for LLM-friendly output."""

from __future__ import annotations

from enum import Enum

_CURRENCY_SYMBOL_MAP: dict[str, str] = {
    "USD": "$",
    "EUR": "€",
    "GBP": "£",
    "JPY": "¥",
    "CNY": "¥",
    "BRL": "R$",
    "CAD": "CA$",
    "AUD": "A$",
    "HKD": "HK$",
    "INR": "₹",
    "KRW": "₩",
    "ZAR": "R",
    "TWD": "NT$",
    "ILS": "₪",
    "SGD": "S$",
}


def format_currency(value: float | int | None, decimals: int = 1, currency: str | None = None) -> str:
    """Format a number as currency with unit suffix. Returns 'N/A' for None.

    When ``currency`` is ``None``, an empty string, or ``"USD"``, emit the
    default dollar-prefix form (``$17.2B``). For known non-USD codes, prefix
    with the mapped symbol (``€17.2B``). For any other non-empty code
    (``CHF``, ``SEK``), suffix with the ISO code and a space (``CHF 17.2B``).
    The sign is placed BEFORE the symbol / code across all paths
    (``-$266.0M``, ``-€266.0M``, ``-CHF 266.0M``).
    """
    if value is None:
        return "N/A"
    value_f = float(value)
    sign = "-" if value_f < 0 else ""
    body = _format_abs_with_unit(abs(value_f), decimals)

    normalized = currency.strip().upper() if currency else None
    if not normalized or normalized == "USD":
        return f"{sign}${body}"
    if normalized in _CURRENCY_SYMBOL_MAP:
        return f"{sign}{_CURRENCY_SYMBOL_MAP[normalized]}{body}"
    return f"{sign}{normalized} {body}"


def format_number(value: float | int | None, decimals: int = 1) -> str:
    """Format a number with unit suffix (no dollar sign). Returns 'N/A' for None."""
    if value is None:
        return "N/A"
    value_f = float(value)
    sign = "-" if value_f < 0 else ""
    return sign + _format_abs_with_unit(abs(value_f), decimals)


def format_percent(value: float | int | None, decimals: int = 1) -> str:
    """Format a number as a percentage. Returns 'N/A' for None."""
    if value is None:
        return "N/A"
    return f"{value:.{decimals}f}%"


def format_shares(value: int | float | None) -> str:
    """Format a number as comma-separated shares. Returns 'N/A' for None."""
    if value is None:
        return "N/A"
    return f"{int(value):,} shares"


def _format_abs_with_unit(abs_value: float, decimals: int) -> str:
    """Format a non-negative magnitude with T/B/M/K unit suffix (no sign)."""
    if abs_value >= 1_000_000_000_000:
        return f"{abs_value / 1_000_000_000_000:.{decimals}f}T"
    elif abs_value >= 1_000_000_000:
        return f"{abs_value / 1_000_000_000:.{decimals}f}B"
    elif abs_value >= 1_000_000:
        return f"{abs_value / 1_000_000:.{decimals}f}M"
    elif abs_value >= 1_000:
        return f"{abs_value / 1_000:.{decimals}f}K"
    else:
        if abs_value != int(abs_value) or decimals > 0:
            return f"{abs_value:.{decimals}f}"
        return f"{int(abs_value)}"


def format_table(headers: list[str], rows: list[list[str]], alignments: list[str] | None = None) -> str:
    """Format data as an aligned text table.

    Args:
        headers: Column header strings.
        rows: List of rows, each a list of cell strings.
        alignments: Per-column alignment, "l" for left or "r" for right.
                    Defaults to left for all columns.
    """
    if not rows:
        return ""

    if alignments is None:
        alignments = ["l"] * len(headers)

    all_rows = [headers, *rows]
    col_widths = [max(len(str(row[i])) for row in all_rows) for i in range(len(headers))]

    def _format_row(row: list[str]) -> str:
        cells = []
        for i, cell in enumerate(row):
            width = col_widths[i]
            if alignments[i] == "r":
                cells.append(str(cell).rjust(width))
            else:
                cells.append(str(cell).ljust(width))
        return "  ".join(cells)

    lines = [_format_row(headers)]
    lines.append("  ".join("-" * w for w in col_widths))
    for row in rows:
        lines.append(_format_row(row))

    return "\n".join(lines)


def format_source(filing_type: str, accession: str | None = None, data_source: str | Enum | None = None) -> str:
    """Produce a source attribution line.

    Args:
        filing_type: E.g., "10-K", "Form 4".
        accession: Optional filing accession number.
        data_source: Either a string code ("ixbrl", "companyfacts", "mixed"),
            an Enum instance whose ``.value`` is one of those codes, or None.
    """
    if isinstance(data_source, Enum):
        data_source = str(data_source.value)
    source_label = {
        "ixbrl": "iXBRL",
        "companyfacts": "CompanyFacts",
        "mixed": "Mixed",
    }.get(data_source or "", data_source or "")

    if accession:
        suffix = f" ({source_label})" if source_label else ""
        return f"Source: SEC EDGAR, {filing_type} filing {accession}{suffix}"
    else:
        return f"Source: SEC EDGAR, {filing_type} filings."


def format_pagination(shown: int, total: int, sort_description: str | None = None) -> str:
    """Produce a pagination/count summary line."""
    if shown == total:
        base = f"{total} result{'s' if total != 1 else ''} found."
    elif shown < total:
        base = f"Showing 1-{shown} of {total}."
    else:
        base = f"{shown} results shown."

    if sort_description:
        base = base.rstrip(".") + f" sorted by {sort_description}."

    return base
