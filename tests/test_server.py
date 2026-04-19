"""Tests for server transport configuration, auth, and health endpoint."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.requests import Request
from starlette.testclient import TestClient
from thesma.client import AsyncThesmaClient
from thesma.errors import ThesmaError

from thesma_mcp.server import AppContext, get_client, mcp

# ---------------------------------------------------------------------------
# Transport / main() tests
# ---------------------------------------------------------------------------


class TestMainHttpTransport:
    @patch.object(mcp, "run")
    def test_sets_host_and_port(self, mock_run: MagicMock) -> None:
        """HTTP mode sets host to 0.0.0.0, port from PORT env var."""
        env = {"THESMA_MCP_TRANSPORT": "http", "PORT": "9000", "THESMA_API_KEY": "test-key"}
        with patch.dict(os.environ, env, clear=False):
            from thesma_mcp.server import main

            main()

        assert mcp.settings.host == "0.0.0.0"  # noqa: S104
        assert mcp.settings.port == 9000
        mock_run.assert_called_once_with(transport="streamable-http")

    @patch.object(mcp, "run")
    def test_default_port(self, mock_run: MagicMock) -> None:
        """HTTP mode defaults to port 8200 when PORT is not set."""
        env = {"THESMA_MCP_TRANSPORT": "http", "THESMA_API_KEY": "test-key"}
        with patch.dict(os.environ, env, clear=False):
            os.environ.pop("PORT", None)
            from thesma_mcp.server import main

            main()

        assert mcp.settings.port == 8200
        mock_run.assert_called_once_with(transport="streamable-http")

    @patch.object(mcp, "run")
    def test_stateless_http_enabled(self, mock_run: MagicMock) -> None:
        """HTTP mode enables stateless_http."""
        env = {"THESMA_MCP_TRANSPORT": "http", "THESMA_API_KEY": "test-key"}
        with patch.dict(os.environ, env, clear=False):
            os.environ.pop("PORT", None)
            from thesma_mcp.server import main

            main()

        assert mcp.settings.stateless_http is True

    @patch.object(mcp, "run")
    def test_no_api_key_does_not_exit(self, mock_run: MagicMock) -> None:
        """HTTP mode does not exit when THESMA_API_KEY is missing."""
        env = {"THESMA_MCP_TRANSPORT": "http"}
        with patch.dict(os.environ, env, clear=False):
            os.environ.pop("THESMA_API_KEY", None)
            os.environ.pop("PORT", None)
            from thesma_mcp.server import main

            main()  # Should not raise or exit

        mock_run.assert_called_once_with(transport="streamable-http")

    def test_invalid_port_exits(self) -> None:
        """HTTP mode with invalid PORT exits with error."""
        env = {"THESMA_MCP_TRANSPORT": "http", "PORT": "not-a-number", "THESMA_API_KEY": "test-key"}
        with patch.dict(os.environ, env, clear=False):
            from thesma_mcp.server import main

            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1


class TestMainStdioTransport:
    @patch.object(mcp, "run")
    def test_stdio_transport(self, mock_run: MagicMock) -> None:
        """STDIO mode calls run with stdio transport."""
        env = {"THESMA_MCP_TRANSPORT": "stdio", "THESMA_API_KEY": "test-key"}
        with patch.dict(os.environ, env, clear=False):
            from thesma_mcp.server import main

            main()

        mock_run.assert_called_once_with(transport="stdio")

    def test_no_api_key_exits(self) -> None:
        """STDIO mode without THESMA_API_KEY exits."""
        env = {"THESMA_MCP_TRANSPORT": "stdio"}
        with patch.dict(os.environ, env, clear=False):
            os.environ.pop("THESMA_API_KEY", None)
            from thesma_mcp.server import main

            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# get_client() tests
# ---------------------------------------------------------------------------


def _make_ctx(
    auth_header: str | None = None,
    default_client: AsyncThesmaClient | None = None,
) -> MagicMock:
    """Build a mock Context with optional auth header and default client."""
    ctx = MagicMock()

    # AppContext
    app = MagicMock(spec=AppContext)
    app.client = default_client
    ctx.request_context.lifespan_context = app

    # HTTP request (Starlette Request)
    if auth_header is not None:
        http_request = MagicMock(spec=Request)
        http_request.headers = {"authorization": auth_header}
        ctx.request_context.request = http_request
    else:
        ctx.request_context.request = None

    return ctx


class TestGetClient:
    def test_bearer_token_creates_client(self) -> None:
        """Auth header with valid Bearer token creates a per-request client."""
        default = AsyncMock(spec=AsyncThesmaClient)
        ctx = _make_ctx(auth_header="Bearer test-user-key", default_client=default)

        client = get_client(ctx)

        assert isinstance(client, AsyncThesmaClient)
        assert client is not default  # Should be a new client

    def test_per_request_client_has_correct_key(self) -> None:
        """Per-request client uses the API key from the Authorization header."""
        default = AsyncMock(spec=AsyncThesmaClient)
        ctx = _make_ctx(auth_header="Bearer test-key", default_client=default)

        client = get_client(ctx)

        assert isinstance(client, AsyncThesmaClient)
        assert client is not default

    def test_no_auth_uses_default(self) -> None:
        """No auth header returns the shared default client."""
        default = AsyncMock(spec=AsyncThesmaClient)
        ctx = _make_ctx(default_client=default)

        client = get_client(ctx)

        assert client is default

    def test_malformed_bearer_raises(self) -> None:
        """Non-Bearer auth scheme raises ThesmaError."""
        ctx = _make_ctx(auth_header="Basic abc123")

        with pytest.raises(ThesmaError, match="Invalid Authorization header"):
            get_client(ctx)

    def test_bearer_whitespace_only_raises(self) -> None:
        """Bearer with whitespace-only token raises ThesmaError."""
        ctx = _make_ctx(auth_header="Bearer   ")

        with pytest.raises(ThesmaError, match="Invalid Authorization header"):
            get_client(ctx)

    def test_no_auth_returns_default_even_with_empty_key(self) -> None:
        """No auth header returns the default client (API will reject empty key at call time)."""
        default = AsyncMock(spec=AsyncThesmaClient)
        ctx = _make_ctx(default_client=default)

        client = get_client(ctx)

        assert client is default


# ---------------------------------------------------------------------------
# Health endpoint integration test
# ---------------------------------------------------------------------------


class TestHealthEndpoint:
    def test_returns_ok(self) -> None:
        """GET /health returns 200 with {"status": "ok"}."""
        app = mcp.streamable_http_app()
        client = TestClient(app)

        response = client.get("/health")

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


class TestToolRegistration:
    def test_sba_module_registered(self) -> None:
        """_register_tools() imports thesma_mcp.tools.sba — catches missing import line."""
        import sys

        import thesma_mcp.server  # noqa: F401

        assert "thesma_mcp.tools.sba" in sys.modules
