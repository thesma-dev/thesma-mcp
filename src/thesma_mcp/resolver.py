"""Ticker-to-CIK resolution with in-memory cache."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from thesma.errors import ThesmaError

if TYPE_CHECKING:
    from thesma.client import AsyncThesmaClient

CIK_PATTERN = re.compile(r"^0\d{9}$")


class TickerResolver:
    """Resolves stock tickers to SEC CIKs, caching results in memory."""

    def __init__(self, client: Any) -> None:
        self._client: AsyncThesmaClient = client
        self._cache: dict[str, str] = {}

    async def resolve(self, ticker_or_cik: str) -> str:
        """Resolve a ticker or CIK to a 10-digit zero-padded CIK string.

        If the input is already a CIK (10-digit zero-padded starting with "0"),
        return it as-is. Otherwise, look up the ticker via the Thesma API.
        """
        if CIK_PATTERN.match(ticker_or_cik):
            return ticker_or_cik

        cache_key = ticker_or_cik.upper()
        if cache_key in self._cache:
            return self._cache[cache_key]

        try:
            response = await self._client.companies.list(ticker=cache_key)
        except ThesmaError as e:
            msg = f"No company found for ticker '{ticker_or_cik}'. Try searching with search_companies."
            raise ThesmaError(msg) from e

        if not response.data:
            msg = f"No company found for ticker '{ticker_or_cik}'. Try searching with search_companies."
            raise ThesmaError(msg)

        cik: str = response.data[0].cik
        self._cache[cache_key] = cik
        return cik
