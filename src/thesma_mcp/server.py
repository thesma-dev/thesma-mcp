"""Thesma MCP server — FastMCP instance, lifespan, and transport configuration."""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from thesma.client import AsyncThesmaClient
from thesma.errors import ThesmaError

from thesma_mcp.resolver import TickerResolver

logger = logging.getLogger("thesma_mcp")


@dataclass
class AppContext:
    """Application context holding shared resources."""

    client: AsyncThesmaClient | None
    resolver: TickerResolver


@asynccontextmanager
async def app_lifespan(server: Any) -> AsyncIterator[AppContext]:
    """Create and tear down shared resources."""
    api_key = os.environ.get("THESMA_API_KEY", "")
    transport = os.environ.get("THESMA_MCP_TRANSPORT", "stdio")

    has_key = bool(api_key and api_key.strip())

    if has_key:
        client: AsyncThesmaClient | None = AsyncThesmaClient(api_key=api_key)
        resolver = TickerResolver(client)
        if transport == "http":
            logger.info("Default API key configured — unauthenticated requests will use free tier")
    else:
        client = None
        resolver = TickerResolver(None)
        if transport == "http":
            logger.info("No default API key — all requests require Authorization header")

    try:
        yield AppContext(client=client, resolver=resolver)
    finally:
        if client:
            await client.close()


def get_client(ctx: Context[Any, AppContext, Any]) -> AsyncThesmaClient:
    """Get a ThesmaClient for the current request, respecting auth headers.

    If an Authorization: Bearer header is present, creates a per-request client
    with that key. Otherwise, returns the shared default client from the lifespan.
    """
    app: AppContext = ctx.request_context.lifespan_context

    # Check for Authorization header from the HTTP request
    http_request = ctx.request_context.request
    if http_request is not None and isinstance(http_request, Request):
        auth_header = http_request.headers.get("authorization")
        if auth_header is not None:
            parts = auth_header.split(" ", 1)
            if len(parts) != 2 or parts[0] != "Bearer":
                msg = "Invalid Authorization header — expected `Bearer <api-key>`."
                raise ThesmaError(msg)
            token = parts[1].strip()
            if not token:
                msg = "Invalid Authorization header — expected `Bearer <api-key>`."
                raise ThesmaError(msg)
            logger.debug("Using per-request API key from Authorization header")
            return AsyncThesmaClient(api_key=token)

    # Fall back to default client
    if app.client is None:
        msg = "No API key provided. Set THESMA_API_KEY or pass an Authorization: Bearer header."
        raise ThesmaError(msg)
    return app.client


mcp = FastMCP("thesma", lifespan=app_lifespan)


@mcp.custom_route("/health", methods=["GET"])  # type: ignore[untyped-decorator]
async def health_check(request: Request) -> Response:
    """Health check endpoint for Railway."""
    return JSONResponse({"status": "ok"})


# Register tool modules — importing them triggers @mcp.tool() registration
import thesma_mcp.tools.bls_counties as _bls_counties_tools  # noqa: F401, E402
import thesma_mcp.tools.bls_industries as _bls_industries_tools  # noqa: F401, E402
import thesma_mcp.tools.bls_metrics as _bls_metrics_tools  # noqa: F401, E402
import thesma_mcp.tools.bls_occupations as _bls_occupations_tools  # noqa: F401, E402
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
    transport = os.environ.get("THESMA_MCP_TRANSPORT", "stdio")
    api_key = os.environ.get("THESMA_API_KEY", "")

    if transport == "http":
        # Validate PORT if provided
        port_str = os.environ.get("PORT", "8200")
        try:
            int(port_str)
        except ValueError:
            print(f"Invalid PORT value: '{port_str}'. Must be an integer.", file=sys.stderr)
            sys.exit(1)

        # Configure FastMCP settings for HTTP mode
        mcp.settings.host = "0.0.0.0"  # noqa: S104
        mcp.settings.port = int(port_str)
        mcp.settings.stateless_http = True
        # Disable DNS rebinding protection — Railway proxies external traffic
        mcp.settings.transport_security = TransportSecuritySettings(enable_dns_rebinding_protection=False)

        if not api_key or not api_key.strip():
            logger.warning("THESMA_API_KEY not set — requests require Authorization header")

        mcp.run(transport="streamable-http")
    else:
        # STDIO mode — require API key at startup
        if not api_key or not api_key.strip():
            print("THESMA_API_KEY not set. Get an API key at https://portal.thesma.dev", file=sys.stderr)
            sys.exit(1)

        mcp.run(transport="stdio")
