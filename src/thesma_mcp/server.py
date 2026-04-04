"""Thesma MCP server — FastMCP instance, lifespan, and transport configuration."""

from __future__ import annotations

import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from mcp.server.fastmcp import FastMCP

from thesma_mcp.client import ThesmaClient
from thesma_mcp.resolver import TickerResolver


@dataclass
class AppContext:
    """Application context holding shared resources."""

    client: ThesmaClient
    resolver: TickerResolver


@asynccontextmanager
async def app_lifespan(server: Any) -> AsyncIterator[AppContext]:
    """Create and tear down shared resources."""
    client = ThesmaClient()
    resolver = TickerResolver(client)
    try:
        yield AppContext(client=client, resolver=resolver)
    finally:
        await client.close()


mcp = FastMCP("thesma", lifespan=app_lifespan)

# Register tool modules — importing them triggers @mcp.tool() registration
import thesma_mcp.tools.bls_turnover as _bls_turnover_tools  # noqa: F401, E402
import thesma_mcp.tools.companies as _companies_tools  # noqa: F401, E402
import thesma_mcp.tools.compensation as _compensation_tools  # noqa: F401, E402
import thesma_mcp.tools.events as _events_tools  # noqa: F401, E402
import thesma_mcp.tools.filings as _filings_tools  # noqa: F401, E402
import thesma_mcp.tools.financials as _financials_tools  # noqa: F401, E402
import thesma_mcp.tools.holdings as _holdings_tools  # noqa: F401, E402
import thesma_mcp.tools.insider_trades as _insider_trades_tools  # noqa: F401, E402
import thesma_mcp.tools.ratios as _ratios_tools  # noqa: F401, E402
import thesma_mcp.tools.screener as _screener_tools  # noqa: F401, E402


def main() -> None:
    """Run the MCP server."""
    # Validate API key before starting
    api_key = os.environ.get("THESMA_API_KEY", "")
    if not api_key or not api_key.strip():
        print("THESMA_API_KEY not set. Get an API key at https://portal.thesma.dev", file=sys.stderr)
        sys.exit(1)

    transport = os.environ.get("THESMA_MCP_TRANSPORT", "stdio")

    if transport == "http":
        # Streamable HTTP transport for hosted version (future).
        # When activated, configure host/port via MCP settings or environment.
        # Default port: 8200.
        mcp.run(transport="streamable-http")
    else:
        mcp.run(transport="stdio")
