"""Tests for number and response formatting utilities."""

from __future__ import annotations

from enum import Enum

from thesma_mcp.formatters import (
    format_currency,
    format_number,
    format_pagination,
    format_percent,
    format_shares,
    format_source,
    format_table,
)


class TestFormatCurrency:
    def test_trillions(self) -> None:
        assert format_currency(1_500_000_000_000) == "$1.5T"

    def test_billions(self) -> None:
        assert format_currency(391_035_000_000) == "$391.0B"

    def test_millions(self) -> None:
        assert format_currency(17_148_000) == "$17.1M"

    def test_thousands(self) -> None:
        assert format_currency(5_500) == "$5.5K"

    def test_plain(self) -> None:
        assert format_currency(6.08) == "$6.1"

    def test_plain_exact(self) -> None:
        assert format_currency(6.08, decimals=2) == "$6.08"

    def test_none(self) -> None:
        assert format_currency(None) == "N/A"

    def test_negative(self) -> None:
        # MCP-28: sign-before-symbol convention across all currencies.
        assert format_currency(-500_000_000) == "-$500.0M"


class TestFormatNumber:
    def test_large(self) -> None:
        assert format_number(100_000) == "100.0K"

    def test_billions(self) -> None:
        assert format_number(2_500_000_000) == "2.5B"

    def test_none(self) -> None:
        assert format_number(None) == "N/A"


class TestFormatPercent:
    def test_basic(self) -> None:
        assert format_percent(46.2) == "46.2%"

    def test_none(self) -> None:
        assert format_percent(None) == "N/A"

    def test_decimals(self) -> None:
        assert format_percent(46.25, decimals=2) == "46.25%"


class TestFormatShares:
    def test_basic(self) -> None:
        assert format_shares(100_000) == "100,000 shares"

    def test_none(self) -> None:
        assert format_shares(None) == "N/A"

    def test_large(self) -> None:
        assert format_shares(1_500_000) == "1,500,000 shares"


class TestFormatTable:
    def test_basic_table(self) -> None:
        result = format_table(
            headers=["Name", "Revenue", "Growth"],
            rows=[
                ["Apple", "$391.0B", "8.1%"],
                ["Microsoft", "$211.9B", "12.3%"],
            ],
            alignments=["l", "r", "r"],
        )
        lines = result.split("\n")
        assert len(lines) == 4  # header + separator + 2 data rows
        assert "Apple" in lines[2]
        assert "Microsoft" in lines[3]

    def test_empty_rows(self) -> None:
        assert format_table(["A", "B"], []) == ""

    def test_default_alignment(self) -> None:
        result = format_table(["Col1", "Col2"], [["a", "b"]])
        assert "Col1" in result


class TestFormatSource:
    def test_with_accession(self) -> None:
        result = format_source("10-K", accession="0000320193-24-000123", data_source="ixbrl")
        assert result == "Source: SEC EDGAR, 10-K filing 0000320193-24-000123 (iXBRL)"

    def test_without_accession(self) -> None:
        result = format_source("Form 4")
        assert result == "Source: SEC EDGAR, Form 4 filings."

    def test_with_accession_no_source(self) -> None:
        result = format_source("10-K", accession="0000320193-24-000123")
        assert result == "Source: SEC EDGAR, 10-K filing 0000320193-24-000123"


class TestFormatCurrencyMulti:
    """MCP-28: multi-currency symbol map + sign-before-symbol convention."""

    def test_usd_default_prefix_positive(self) -> None:
        assert format_currency(17_200_000_000) == "$17.2B"

    def test_usd_default_prefix_negative_sign_before_symbol(self) -> None:
        assert format_currency(-266_000_000) == "-$266.0M"

    def test_usd_explicit_currency_equivalent_to_default(self) -> None:
        assert format_currency(17_200_000_000, currency="USD") == format_currency(17_200_000_000)

    def test_usd_case_insensitive(self) -> None:
        assert format_currency(17_200_000_000, currency="usd") == "$17.2B"

    def test_eur_symbol_positive(self) -> None:
        assert format_currency(17_200_000_000, currency="EUR") == "€17.2B"

    def test_eur_symbol_negative(self) -> None:
        assert format_currency(-266_000_000, currency="EUR") == "-€266.0M"

    def test_eur_eps_two_decimals(self) -> None:
        assert format_currency(10.77, decimals=2, currency="EUR") == "€10.77"

    def test_gbp_symbol(self) -> None:
        assert format_currency(500_000_000, currency="GBP") == "£500.0M"

    def test_brl_multichar_symbol(self) -> None:
        assert format_currency(1_200_000_000, currency="BRL") == "R$1.2B"
        assert format_currency(-50_000_000, currency="BRL") == "-R$50.0M"

    def test_cad_multichar_symbol(self) -> None:
        assert format_currency(22_000_000, currency="CAD") == "CA$22.0M"

    def test_inr_symbol(self) -> None:
        assert format_currency(100_000_000, currency="INR") == "₹100.0M"

    def test_suffix_form_chf(self) -> None:
        assert format_currency(17_200_000_000, currency="CHF") == "CHF 17.2B"
        assert format_currency(-50_000_000, currency="CHF") == "-CHF 50.0M"

    def test_suffix_form_sek(self) -> None:
        assert format_currency(212_400_000_000, currency="SEK") == "SEK 212.4B"

    def test_suffix_form_case_normalised(self) -> None:
        assert format_currency(17_200_000_000, currency="chf") == "CHF 17.2B"

    def test_missing_currency_sentinel_renders_question_marks(self) -> None:
        assert format_currency(17_200_000_000, currency="???") == "??? 17.2B"

    def test_empty_string_currency_defaults_to_usd(self) -> None:
        assert format_currency(100_000, currency="") == "$100.0K"

    def test_none_value_returns_na_regardless_of_currency(self) -> None:
        assert format_currency(None, currency="EUR") == "N/A"


class TestFormatSourceEnumCoercion:
    """MCP-28: format_source accepts Enum instances and coerces via .value."""

    def test_str_ixbrl_renders_ixbrl_label(self) -> None:
        result = format_source("10-K", accession="0000320193-26-000012", data_source="ixbrl")
        assert result.endswith("(iXBRL)")

    def test_enum_ixbrl_coerces_via_value(self) -> None:
        class _FakeSource(Enum):
            ixbrl = "ixbrl"

        result = format_source("10-K", accession="0000320193-26-000012", data_source=_FakeSource.ixbrl)
        assert result.endswith("(iXBRL)")
        assert "Source.ixbrl" not in result
        assert "_FakeSource" not in result

    def test_enum_companyfacts_coerces(self) -> None:
        class _FakeSource(Enum):
            companyfacts = "companyfacts"

        result = format_source("10-K", accession="abc", data_source=_FakeSource.companyfacts)
        assert result.endswith("(CompanyFacts)")

    def test_enum_mixed_coerces(self) -> None:
        class _FakeSource(Enum):
            mixed = "mixed"

        result = format_source("10-K", accession="abc", data_source=_FakeSource.mixed)
        assert result.endswith("(Mixed)")

    def test_str_mixed_renders(self) -> None:
        result = format_source("10-K", accession="abc", data_source="mixed")
        assert result.endswith("(Mixed)")

    def test_none_data_source_no_suffix(self) -> None:
        result = format_source("10-K", accession="abc", data_source=None)
        assert not result.endswith(")")

    def test_unknown_enum_value_falls_back_to_raw(self) -> None:
        class _FakeSource(Enum):
            future = "future"

        result = format_source("10-K", accession="abc", data_source=_FakeSource.future)
        assert result.endswith("(future)")
        assert "Source.future" not in result
        assert "_FakeSource" not in result


class TestFormatPagination:
    def test_all_shown(self) -> None:
        result = format_pagination(5, 5)
        assert result == "5 results found."

    def test_partial(self) -> None:
        result = format_pagination(25, 127)
        assert result == "Showing 1-25 of 127."

    def test_with_sort(self) -> None:
        result = format_pagination(5, 47, sort_description="revenue growth (descending)")
        assert "Showing 1-5 of 47" in result
        assert "sorted by revenue growth (descending)" in result

    def test_single_result(self) -> None:
        result = format_pagination(1, 1)
        assert result == "1 result found."
