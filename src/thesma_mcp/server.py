"""Thesma MCP server — FastMCP instance, lifespan, and transport configuration."""

from __future__ import annotations

import logging
import os
import secrets
import sys
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response
from thesma.client import AsyncThesmaClient
from thesma.errors import ThesmaError

logger = logging.getLogger("thesma_mcp")


@dataclass
class AppContext:
    """Application context holding shared resources."""

    client: AsyncThesmaClient | None


@asynccontextmanager
async def app_lifespan(server: Any) -> AsyncIterator[AppContext]:
    """Create and tear down shared resources."""
    api_key = os.environ.get("THESMA_API_KEY", "")
    transport = os.environ.get("THESMA_MCP_TRANSPORT", "stdio")

    has_key = bool(api_key and api_key.strip())

    if has_key:
        client: AsyncThesmaClient | None = AsyncThesmaClient(api_key=api_key)
        if transport == "http":
            logger.info("Default API key configured — unauthenticated requests will use free tier")
    else:
        client = None
        if transport == "http":
            logger.info("No default API key — all requests require Authorization header")

    try:
        yield AppContext(client=client)
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


# Module-level mcp instance — default (non-OAuth) for backwards compatibility.
# Tool modules import this at module level for @mcp.tool() registration.
# main() may replace it with an OAuth-configured instance.
mcp: FastMCP = FastMCP("thesma", lifespan=app_lifespan)


def _register_routes(mcp_instance: FastMCP) -> None:
    """Register custom HTTP routes on the given FastMCP instance."""

    @mcp_instance.custom_route("/health", methods=["GET"])  # type: ignore[untyped-decorator]
    async def health_check(request: Request) -> Response:
        """Health check endpoint for Railway."""
        return JSONResponse({"status": "ok"})


def _register_oauth_stub_routes(mcp_instance: FastMCP) -> None:
    """Register 503 stub routes for OAuth endpoints when Supabase is not configured."""

    @mcp_instance.custom_route("/authorize", methods=["GET", "POST"])  # type: ignore[untyped-decorator]
    async def authorize_stub(request: Request) -> Response:
        return JSONResponse({"error": "OAuth not configured"}, status_code=503)

    @mcp_instance.custom_route("/token", methods=["POST"])  # type: ignore[untyped-decorator]
    async def token_stub(request: Request) -> Response:
        return JSONResponse({"error": "OAuth not configured"}, status_code=503)

    @mcp_instance.custom_route("/register", methods=["POST"])  # type: ignore[untyped-decorator]
    async def register_stub(request: Request) -> Response:
        return JSONResponse({"error": "OAuth not configured"}, status_code=503)


def _register_login_routes(
    mcp_instance: FastMCP,
    provider: Any,
) -> None:
    """Register /login GET and POST routes for OAuth login flow."""
    from thesma_mcp.auth import (
        LOGIN_HTML,
        SUCCESS_HTML,
        SupabaseAuthError,
        SupabaseDownError,
        ThesmaAuthCode,
    )

    @mcp_instance.custom_route("/login", methods=["GET", "POST"])  # type: ignore[untyped-decorator]
    async def login_handler(request: Request) -> Response:
        """Handle login form: GET serves the form, POST processes credentials."""
        if request.method == "GET":
            return await _login_get(request)
        return await _login_post(request)

    async def _login_get(request: Request) -> Response:
        """Serve the login form."""
        session = request.query_params.get("session", "")
        if not session or session not in provider._pending_auths:
            return JSONResponse({"error": "Invalid or expired session"}, status_code=400)

        html = LOGIN_HTML.replace("{session}", session).replace("{error_html}", "")
        return HTMLResponse(html)

    async def _login_post(request: Request) -> Response:
        """Process login form and redirect with auth code."""
        form = await request.form()
        email = str(form.get("email", ""))
        password = str(form.get("password", ""))
        session = str(form.get("session", ""))

        # Validate session
        pending = provider._pending_auths.get(session)
        if not pending:
            return JSONResponse({"error": "Invalid or expired session"}, status_code=400)

        # Authenticate with Supabase
        try:
            user_id = await provider.supabase_auth.authenticate(email, password)
            api_key = await provider.supabase_auth.create_mcp_oauth_key(user_id)
        except SupabaseAuthError:
            error_html = '<div class="error">Invalid email or password.</div>'
            html = LOGIN_HTML.replace("{session}", session).replace("{error_html}", error_html)
            return HTMLResponse(html)
        except SupabaseDownError:
            error_html = '<div class="error">Authentication service temporarily unavailable. Please try again.</div>'
            html = LOGIN_HTML.replace("{session}", session).replace("{error_html}", error_html)
            return HTMLResponse(html)

        # Remove pending auth
        del provider._pending_auths[session]

        # Create auth code
        code = secrets.token_hex(20)
        provider._auth_codes[code] = ThesmaAuthCode(
            code=code,
            scopes=[],
            expires_at=time.time() + 300,  # 5 minutes
            client_id=pending.client_id,
            code_challenge=pending.code_challenge,
            redirect_uri=pending.redirect_uri,
            redirect_uri_provided_explicitly=pending.redirect_uri_provided_explicitly,
            api_key=api_key,
        )

        # Build the redirect URL with code and state
        params: dict[str, str] = {"code": code}
        if pending.state:
            params["state"] = pending.state

        redirect_uri = pending.redirect_uri
        separator = "&" if "?" in redirect_uri else "?"
        redirect_url = f"{redirect_uri}{separator}{urlencode(params)}"

        # Return a success page that immediately JS-redirects. The user briefly
        # sees confirmation that our side worked; if Claude.ai's callback is slow
        # or hangs, they still see our success state instead of a blank page.
        success_html = SUCCESS_HTML.replace("{redirect_url}", redirect_url)
        return HTMLResponse(success_html)


def _register_tools() -> None:
    """Import tool modules to trigger @mcp.tool() registration."""
    import thesma_mcp.tools.bls_counties as _bls_counties_tools  # noqa: F401
    import thesma_mcp.tools.bls_industries as _bls_industries_tools  # noqa: F401
    import thesma_mcp.tools.bls_laus as _bls_laus_tools  # noqa: F401
    import thesma_mcp.tools.bls_metrics as _bls_metrics_tools  # noqa: F401
    import thesma_mcp.tools.bls_occupations as _bls_occupations_tools  # noqa: F401
    import thesma_mcp.tools.bls_turnover as _bls_turnover_tools  # noqa: F401
    import thesma_mcp.tools.census_geographies as _census_geographies_tools  # noqa: F401
    import thesma_mcp.tools.census_metrics as _census_metrics_tools  # noqa: F401
    import thesma_mcp.tools.census_places as _census_places_tools  # noqa: F401
    import thesma_mcp.tools.companies as _companies_tools  # noqa: F401
    import thesma_mcp.tools.compensation as _compensation_tools  # noqa: F401
    import thesma_mcp.tools.events as _events_tools  # noqa: F401
    import thesma_mcp.tools.filings as _filings_tools  # noqa: F401
    import thesma_mcp.tools.financials as _financials_tools  # noqa: F401
    import thesma_mcp.tools.holdings as _holdings_tools  # noqa: F401
    import thesma_mcp.tools.insider_trades as _insider_trades_tools  # noqa: F401
    import thesma_mcp.tools.ratios as _ratios_tools  # noqa: F401
    import thesma_mcp.tools.sba as _sba_tools  # noqa: F401
    import thesma_mcp.tools.screener as _screener_tools  # noqa: F401
    import thesma_mcp.tools.sections as _sections_tools  # noqa: F401
    import thesma_mcp.tools.webhooks as _webhooks_tools  # noqa: F401


# Register tools on the default module-level mcp instance
_register_routes(mcp)
_register_tools()


def main() -> None:
    """Run the MCP server."""
    global mcp

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

        # Check for OAuth configuration
        supabase_url = os.environ.get("SUPABASE_URL", "")
        supabase_key = os.environ.get("SUPABASE_SERVICE_KEY", "")

        if supabase_url and supabase_key:
            from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions

            from thesma_mcp.auth import SupabaseAuth, ThesmaOAuthProvider

            base_url = os.environ.get("MCP_BASE_URL", "https://thesma-mcp-production.up.railway.app")

            supabase_auth = SupabaseAuth(supabase_url, supabase_key)
            provider = ThesmaOAuthProvider(supabase_auth=supabase_auth)

            old_mcp = mcp
            mcp = FastMCP(
                "thesma",
                lifespan=app_lifespan,
                auth_server_provider=provider,
                auth=AuthSettings(
                    issuer_url=base_url,  # type: ignore[arg-type]
                    resource_server_url=base_url,  # type: ignore[arg-type]
                    client_registration_options=ClientRegistrationOptions(enabled=True),
                ),
            )

            _register_routes(mcp)
            _register_login_routes(mcp, provider)
            # Copy tools from the default mcp (already registered at import time)
            mcp._tool_manager._tools.update(old_mcp._tool_manager._tools)  # type: ignore[unused-ignore,attr-defined]

            logger.info("OAuth configured — Supabase auth enabled")
        else:
            _register_oauth_stub_routes(mcp)
            logger.warning("OAuth not configured — SUPABASE_URL/SUPABASE_SERVICE_KEY not set")

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
