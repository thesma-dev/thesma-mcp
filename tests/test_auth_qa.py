"""QA tests for MCP-13 OAuth Authentication — written from spec only.

Tests cover:
- ThesmaOAuthProvider unit tests (register, authorize, load/exchange codes, refresh)
- SupabaseAuth unit tests (authenticate, API key lookup/creation)
- Cleanup logic (TTL expiration for pending auths and auth codes)
- Integration tests via Starlette TestClient (endpoints, full flow, error handling)
"""

from __future__ import annotations

import base64
import hashlib
import re
import secrets
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from mcp.server.auth.provider import AuthorizationParams, TokenError
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from pydantic import AnyUrl
from starlette.testclient import TestClient


def _extract_redirect_url(body: str) -> str:
    """Parse the redirect URL out of the success HTML page."""
    match = re.search(r'window\.location\.href = "([^"]+)"', body)
    if not match:
        raise AssertionError(f"No redirect URL found in body:\n{body[:500]}")
    return match.group(1).replace("&amp;", "&")


# ---------------------------------------------------------------------------
# Helpers / factories
# ---------------------------------------------------------------------------


def _make_client_info(
    client_id: str = "test-client-id",
    redirect_uris: list[str] | None = None,
    grant_types: list[str] | None = None,
) -> OAuthClientInformationFull:
    """Create a valid OAuthClientInformationFull for testing."""
    return OAuthClientInformationFull(
        client_id=client_id,
        redirect_uris=[AnyUrl(u) for u in (redirect_uris or ["https://example.com/callback"])],
        grant_types=grant_types or ["authorization_code"],
    )


def _make_authorization_params(
    state: str = "test-state-abc",
    code_challenge: str = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM",
    redirect_uri: str = "https://example.com/callback",
) -> AuthorizationParams:
    """Create AuthorizationParams for testing."""
    return AuthorizationParams(
        state=state,
        scopes=None,
        code_challenge=code_challenge,
        redirect_uri=AnyUrl(redirect_uri),
        redirect_uri_provided_explicitly=True,
    )


# ---------------------------------------------------------------------------
# Unit Tests — ThesmaOAuthProvider
# ---------------------------------------------------------------------------


class TestThesmaOAuthProvider:
    """Unit tests for the ThesmaOAuthProvider class."""

    @pytest.fixture()
    def provider(self) -> Any:
        """Create a ThesmaOAuthProvider instance for testing."""
        from thesma_mcp.auth import SupabaseAuth, ThesmaOAuthProvider

        supabase_auth = SupabaseAuth("https://test-project.supabase.co", "test-service-key")
        return ThesmaOAuthProvider(supabase_auth=supabase_auth)

    async def test_register_client_stores_client(self, provider: Any) -> None:
        """register_client stores client, get_client retrieves it."""
        client_info = _make_client_info(client_id="reg-test-123")
        await provider.register_client(client_info)

        result = await provider.get_client("reg-test-123")
        assert result is not None
        assert result.client_id == "reg-test-123"
        assert result.redirect_uris is not None
        assert len(result.redirect_uris) == 1

    async def test_get_client_unknown_returns_synthetic(self, provider: Any) -> None:
        """Unknown client_id returns a synthetic permissive client (not None)."""
        result = await provider.get_client("never-registered-xyz")
        assert result is not None
        assert result.client_id == "never-registered-xyz"
        assert result.grant_types == ["authorization_code"]

    async def test_authorize_returns_login_url(self, provider: Any) -> None:
        """authorize() returns a URL starting with /login?session= and stores PendingAuth."""
        client_info = _make_client_info()
        params = _make_authorization_params()

        url = await provider.authorize(client_info, params)

        assert url.startswith("/login?session=")
        session_token = url.split("session=")[1]
        assert len(session_token) > 0

        # Verify PendingAuth was stored

        assert session_token in provider._pending_auths
        pending = provider._pending_auths[session_token]
        assert pending.state == "test-state-abc"
        assert pending.code_challenge == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"

    async def test_authorize_triggers_cleanup(self, provider: Any) -> None:
        """authorize() sweeps expired entries from auth code dict."""
        from thesma_mcp.auth import ThesmaAuthCode

        # Pre-populate with an expired auth code
        expired_code = ThesmaAuthCode(
            code="expired-code",
            scopes=[],
            expires_at=time.time() - 600,  # 10 min in the past
            client_id="some-client",
            code_challenge="challenge",
            redirect_uri=AnyUrl("https://example.com/callback"),
            redirect_uri_provided_explicitly=True,
            api_key="gd_live_expired",
        )
        provider._auth_codes["expired-code"] = expired_code

        # Call authorize — should trigger cleanup
        client_info = _make_client_info()
        params = _make_authorization_params()
        await provider.authorize(client_info, params)

        assert "expired-code" not in provider._auth_codes

    async def test_load_authorization_code_returns_entry(self, provider: Any) -> None:
        """Stored auth code is retrieved by load_authorization_code."""
        from thesma_mcp.auth import ThesmaAuthCode

        code_entry = ThesmaAuthCode(
            code="valid-code-123",
            scopes=[],
            expires_at=time.time() + 300,  # 5 min in the future
            client_id="test-client-id",
            code_challenge="challenge",
            redirect_uri=AnyUrl("https://example.com/callback"),
            redirect_uri_provided_explicitly=True,
            api_key="gd_live_testkey",
        )
        provider._auth_codes["valid-code-123"] = code_entry

        client_info = _make_client_info(client_id="test-client-id")
        result = await provider.load_authorization_code(client_info, "valid-code-123")

        assert result is not None
        assert result.code == "valid-code-123"
        assert result.api_key == "gd_live_testkey"

    async def test_load_authorization_code_unknown_returns_none(self, provider: Any) -> None:
        """Unknown code returns None."""
        client_info = _make_client_info()
        result = await provider.load_authorization_code(client_info, "nonexistent-code")
        assert result is None

    async def test_exchange_authorization_code_returns_api_key(self, provider: Any) -> None:
        """exchange_authorization_code returns OAuthToken with api_key as access_token."""
        from thesma_mcp.auth import ThesmaAuthCode

        code_entry = ThesmaAuthCode(
            code="exchange-code",
            scopes=[],
            expires_at=time.time() + 300,
            client_id="test-client-id",
            code_challenge="challenge",
            redirect_uri=AnyUrl("https://example.com/callback"),
            redirect_uri_provided_explicitly=True,
            api_key="gd_live_test123",
        )
        # Store it so exchange can find/delete it
        provider._auth_codes["exchange-code"] = code_entry

        client_info = _make_client_info(client_id="test-client-id")
        token = await provider.exchange_authorization_code(client_info, code_entry)

        assert isinstance(token, OAuthToken)
        assert token.access_token == "gd_live_test123"
        assert token.token_type == "Bearer"

    async def test_load_refresh_token_returns_none(self, provider: Any) -> None:
        """load_refresh_token always returns None (no refresh tokens)."""
        client_info = _make_client_info()
        result = await provider.load_refresh_token(client_info, "any-token")
        assert result is None

    async def test_exchange_refresh_token_raises(self, provider: Any) -> None:
        """exchange_refresh_token raises TokenError (refresh not supported)."""
        client_info = _make_client_info()
        # Create a minimal mock refresh token
        mock_refresh = MagicMock()
        with pytest.raises(TokenError):
            await provider.exchange_refresh_token(client_info, mock_refresh, [])


# ---------------------------------------------------------------------------
# Unit Tests — SupabaseAuth
# ---------------------------------------------------------------------------


class TestSupabaseAuth:
    """Unit tests for the SupabaseAuth helper class."""

    @pytest.fixture()
    def supabase(self) -> Any:
        """Create a SupabaseAuth instance with test config."""
        from thesma_mcp.auth import SupabaseAuth

        return SupabaseAuth(
            supabase_url="https://test-project.supabase.co",
            supabase_service_key="test-service-key",
        )

    async def test_authenticate_success(self, supabase: Any) -> None:
        """Successful Supabase auth returns user_id."""
        mock_response = httpx.Response(
            200,
            json={"user": {"id": "uuid-123"}},
            request=httpx.Request("POST", "https://test-project.supabase.co/auth/v1/token"),
        )

        with patch("thesma_mcp.auth.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            result = await supabase.authenticate("user@test.com", "password123")

        assert result == "uuid-123"

    async def test_authenticate_invalid_credentials(self, supabase: Any) -> None:
        """Invalid credentials from Supabase results in error."""
        mock_response = httpx.Response(
            400,
            json={"error": "invalid_grant", "error_description": "Invalid login credentials"},
            request=httpx.Request("POST", "https://test-project.supabase.co/auth/v1/token"),
        )

        with patch("thesma_mcp.auth.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            with pytest.raises(Exception):
                await supabase.authenticate("user@test.com", "wrong-password")

    async def test_authenticate_supabase_down(self, supabase: Any) -> None:
        """Supabase 500 raises appropriate error for downtime handling."""
        mock_response = httpx.Response(
            500,
            json={"message": "Internal server error"},
            request=httpx.Request("POST", "https://test-project.supabase.co/auth/v1/token"),
        )

        with patch("thesma_mcp.auth.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            with pytest.raises(Exception):
                await supabase.authenticate("user@test.com", "password123")

    async def test_authenticate_timeout(self, supabase: Any) -> None:
        """httpx timeout raises appropriate error."""
        with patch("thesma_mcp.auth.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(side_effect=httpx.TimeoutException("Connection timed out"))
            mock_client_cls.return_value = mock_client

            with pytest.raises(Exception):
                await supabase.authenticate("user@test.com", "password123")

    async def test_create_mcp_oauth_key_always_creates_new(self, supabase: Any) -> None:
        """create_mcp_oauth_key always creates a fresh key (PATCH + POST)."""
        patch_response = httpx.Response(
            204,
            request=httpx.Request("PATCH", "https://test-project.supabase.co/rest/v1/api_keys"),
        )
        create_response = httpx.Response(
            201,
            json={},
            request=httpx.Request("POST", "https://test-project.supabase.co/rest/v1/api_keys"),
        )

        with patch("thesma_mcp.auth.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.patch = AsyncMock(return_value=patch_response)
            mock_client.post = AsyncMock(return_value=create_response)
            mock_client_cls.return_value = mock_client

            result = await supabase.create_mcp_oauth_key("uuid-123")

        assert result.startswith("gd_live_")
        assert mock_client.patch.call_count == 1
        assert mock_client.post.call_count == 1

        # Verify the POST body shape
        call_args = mock_client.post.call_args
        body = call_args.kwargs["json"]
        assert body["source"] == "mcp_oauth"
        assert body["name"] == "MCP OAuth"
        assert body["key_prefix"] == result[:12]
        assert "key_plaintext" not in body


# ---------------------------------------------------------------------------
# Unit Tests — Cleanup
# ---------------------------------------------------------------------------


class TestCleanup:
    """Tests for TTL-based cleanup of pending auths and auth codes."""

    @pytest.fixture()
    def provider(self) -> Any:
        """Create a ThesmaOAuthProvider instance for testing."""
        from thesma_mcp.auth import SupabaseAuth, ThesmaOAuthProvider

        supabase_auth = SupabaseAuth("https://test-project.supabase.co", "test-service-key")
        return ThesmaOAuthProvider(supabase_auth=supabase_auth)

    async def test_pending_auth_expires_after_ttl(self, provider: Any) -> None:
        """PendingAuth older than 10 minutes is removed by cleanup."""
        from thesma_mcp.auth import PendingAuth

        # Create a PendingAuth 11 minutes in the past
        old_pending = PendingAuth(
            client_id="test-client",
            code_challenge="challenge",
            redirect_uri="https://example.com/callback",
            redirect_uri_provided_explicitly=True,
            state="old-state",
            created_at=time.time() - 660,  # 11 minutes ago
        )
        provider._pending_auths["old-session"] = old_pending

        provider._cleanup_expired()

        assert "old-session" not in provider._pending_auths

    async def test_auth_code_expires_after_ttl(self, provider: Any) -> None:
        """Auth code with expires_at in the past is removed by cleanup."""
        from thesma_mcp.auth import ThesmaAuthCode

        expired_code = ThesmaAuthCode(
            code="expired-code",
            scopes=[],
            expires_at=time.time() - 60,  # 1 minute in the past
            client_id="test-client",
            code_challenge="challenge",
            redirect_uri=AnyUrl("https://example.com/callback"),
            redirect_uri_provided_explicitly=True,
            api_key="gd_live_expired",
        )
        provider._auth_codes["expired-code"] = expired_code

        provider._cleanup_expired()

        assert "expired-code" not in provider._auth_codes

    async def test_valid_entries_survive_cleanup(self, provider: Any) -> None:
        """Within-TTL entries are kept after cleanup."""
        from thesma_mcp.auth import PendingAuth, ThesmaAuthCode

        # Valid pending auth (just created)
        valid_pending = PendingAuth(
            client_id="test-client",
            code_challenge="challenge",
            redirect_uri="https://example.com/callback",
            redirect_uri_provided_explicitly=True,
            state="fresh-state",
            created_at=time.time(),  # Now
        )
        provider._pending_auths["fresh-session"] = valid_pending

        # Valid auth code (5 minutes in the future)
        valid_code = ThesmaAuthCode(
            code="valid-code",
            scopes=[],
            expires_at=time.time() + 300,
            client_id="test-client",
            code_challenge="challenge",
            redirect_uri=AnyUrl("https://example.com/callback"),
            redirect_uri_provided_explicitly=True,
            api_key="gd_live_valid",
        )
        provider._auth_codes["valid-code"] = valid_code

        provider._cleanup_expired()

        assert "fresh-session" in provider._pending_auths
        assert "valid-code" in provider._auth_codes


# ---------------------------------------------------------------------------
# Integration Tests — Starlette TestClient
# ---------------------------------------------------------------------------


def _make_oauth_app() -> tuple[Any, Any]:
    """Create a FastMCP app with OAuth configured for integration testing.

    Returns (starlette_app, provider) so tests can access the provider for mocking.
    """
    from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions
    from mcp.server.fastmcp import FastMCP

    from thesma_mcp.auth import SupabaseAuth, ThesmaOAuthProvider
    from thesma_mcp.server import _register_login_routes, _register_routes, app_lifespan

    supabase_auth = SupabaseAuth("https://test-project.supabase.co", "test-service-key")
    provider = ThesmaOAuthProvider(supabase_auth=supabase_auth)

    mcp_server = FastMCP(
        "thesma",
        lifespan=app_lifespan,
        auth_server_provider=provider,
        auth=AuthSettings(
            issuer_url="https://test.example.com",  # type: ignore[arg-type]
            resource_server_url="https://test.example.com",  # type: ignore[arg-type]
            client_registration_options=ClientRegistrationOptions(enabled=True),
        ),
    )
    _register_routes(mcp_server)
    _register_login_routes(mcp_server, provider)

    return mcp_server.streamable_http_app(), provider


def _make_no_oauth_app() -> Any:
    """Create a FastMCP app WITHOUT OAuth for testing 503 behavior."""
    from mcp.server.fastmcp import FastMCP

    from thesma_mcp.server import _register_oauth_stub_routes, _register_routes, app_lifespan

    mcp_server = FastMCP("thesma", lifespan=app_lifespan)
    _register_routes(mcp_server)
    _register_oauth_stub_routes(mcp_server)

    return mcp_server.streamable_http_app()


class TestIntegrationHealth:
    """Health endpoint tests with OAuth configured."""

    def test_health_still_unauthenticated(self) -> None:
        """GET /health returns 200 even with OAuth configured."""
        app, _ = _make_oauth_app()
        client = TestClient(app)

        response = client.get("/health")

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


class TestIntegrationWellKnown:
    """OAuth discovery endpoint tests."""

    def test_well_known_metadata_endpoint(self) -> None:
        """GET /.well-known/oauth-authorization-server returns metadata with S256."""
        app, _ = _make_oauth_app()
        client = TestClient(app)

        response = client.get("/.well-known/oauth-authorization-server")

        assert response.status_code == 200
        data = response.json()
        assert "authorization_endpoint" in data
        assert "token_endpoint" in data
        assert "registration_endpoint" in data
        assert "code_challenge_methods_supported" in data
        assert "S256" in data["code_challenge_methods_supported"]


class TestIntegrationRegister:
    """Client registration endpoint tests."""

    def test_register_endpoint_creates_client(self) -> None:
        """POST /register returns 201 with client_id."""
        app, _ = _make_oauth_app()
        client = TestClient(app)

        response = client.post(
            "/register",
            json={
                "redirect_uris": ["https://example.com/callback"],
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "client_name": "Test Client",
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert "client_id" in data
        assert data["client_id"] is not None


class TestIntegrationAuthorize:
    """Authorization endpoint tests."""

    def test_authorize_redirects_to_login(self) -> None:
        """GET /authorize with valid params returns 302 redirect to /login?session=..."""
        app, _ = _make_oauth_app()
        client = TestClient(app, follow_redirects=False)

        # First register a client
        reg = client.post(
            "/register",
            json={
                "redirect_uris": ["https://example.com/callback"],
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "client_name": "Test Client",
            },
        )
        client_id = reg.json()["client_id"]

        response = client.get(
            "/authorize",
            params={
                "client_id": client_id,
                "redirect_uri": "https://example.com/callback",
                "code_challenge": "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM",
                "code_challenge_method": "S256",
                "response_type": "code",
                "state": "test-state-123",
            },
        )

        assert response.status_code == 302
        location = response.headers.get("location", "")
        assert "/login?session=" in location


class TestIntegrationLogin:
    """Login page tests."""

    def _get_session_token(self, client: TestClient) -> tuple[str, str]:
        """Register a client, authorize, and return (session_token, client_id)."""
        reg = client.post(
            "/register",
            json={
                "redirect_uris": ["https://example.com/callback"],
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
            },
        )
        client_id = reg.json()["client_id"]

        response = client.get(
            "/authorize",
            params={
                "client_id": client_id,
                "redirect_uri": "https://example.com/callback",
                "code_challenge": "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM",
                "code_challenge_method": "S256",
                "response_type": "code",
                "state": "test-state-value",
            },
            follow_redirects=False,
        )
        location = response.headers["location"]
        parsed = urlparse(location)
        session = parse_qs(parsed.query)["session"][0]
        return session, client_id

    def test_login_get_renders_form(self) -> None:
        """GET /login?session=valid returns 200 with HTML form."""
        app, _ = _make_oauth_app()
        client = TestClient(app, follow_redirects=False)
        session, _ = self._get_session_token(client)

        response = client.get(f"/login?session={session}")

        assert response.status_code == 200
        body = response.text
        assert "<form" in body.lower()
        assert "email" in body.lower()
        assert "password" in body.lower()

    def test_login_get_invalid_session(self) -> None:
        """GET /login?session=nonexistent returns 400."""
        app, _ = _make_oauth_app()
        client = TestClient(app)

        response = client.get("/login?session=nonexistent-session-token")

        assert response.status_code == 400

    def test_login_post_success_redirects_with_code(self) -> None:
        """POST /login with valid credentials redirects with code and state."""
        app, provider = _make_oauth_app()
        client = TestClient(app, follow_redirects=False)
        session, client_id = self._get_session_token(client)

        # Mock SupabaseAuth on the provider's instance
        with (
            patch.object(provider.supabase_auth, "authenticate", new_callable=AsyncMock, return_value="uuid-user-123"),
            patch.object(
                provider.supabase_auth,
                "create_mcp_oauth_key",
                new_callable=AsyncMock,
                return_value="gd_live_testkey123456",
            ),
        ):
            response = client.post(
                "/login",
                data={
                    "email": "user@test.com",
                    "password": "password123",
                    "session": session,
                },
            )

        assert response.status_code == 200
        assert "Signed in successfully" in response.text
        location = _extract_redirect_url(response.text)
        parsed = urlparse(location)
        query = parse_qs(parsed.query)
        assert "code" in query
        assert "state" in query
        assert query["state"][0] == "test-state-value"

    def test_login_post_bad_credentials_rerenders(self) -> None:
        """POST /login with bad credentials returns 200 with error message."""
        from thesma_mcp.auth import SupabaseAuthError

        app, provider = _make_oauth_app()
        client = TestClient(app, follow_redirects=False)
        session, _ = self._get_session_token(client)

        with patch.object(
            provider.supabase_auth,
            "authenticate",
            new_callable=AsyncMock,
            side_effect=SupabaseAuthError("Invalid email or password."),
        ):
            response = client.post(
                "/login",
                data={
                    "email": "user@test.com",
                    "password": "wrong-password",
                    "session": session,
                },
            )

        assert response.status_code == 200
        body = response.text
        # Form should be re-rendered with an error
        assert "<form" in body.lower()
        assert "Invalid email or password" in body

    def test_login_post_supabase_down_rerenders(self) -> None:
        """POST /login during Supabase downtime returns 200 with unavailable message."""
        from thesma_mcp.auth import SupabaseDownError

        app, provider = _make_oauth_app()
        client = TestClient(app, follow_redirects=False)
        session, _ = self._get_session_token(client)

        with patch.object(
            provider.supabase_auth,
            "authenticate",
            new_callable=AsyncMock,
            side_effect=SupabaseDownError("Authentication service temporarily unavailable. Please try again."),
        ):
            response = client.post(
                "/login",
                data={
                    "email": "user@test.com",
                    "password": "password123",
                    "session": session,
                },
            )

        assert response.status_code == 200
        assert "temporarily unavailable" in response.text


class TestIntegrationFullFlow:
    """End-to-end OAuth flow integration tests."""

    def _register_client(self, client: TestClient) -> tuple[str, str]:
        """Register a client and return (client_id, client_secret)."""
        reg = client.post(
            "/register",
            json={
                "redirect_uris": ["https://example.com/callback"],
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
            },
        )
        data = reg.json()
        return data["client_id"], data.get("client_secret", "")

    def _generate_pkce_pair(self) -> tuple[str, str]:
        """Generate a PKCE code_verifier and code_challenge (S256)."""
        code_verifier = secrets.token_urlsafe(32)
        digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
        code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
        return code_verifier, code_challenge

    def test_full_oauth_flow(self) -> None:
        """End-to-end: register -> authorize -> login -> token exchange."""
        code_verifier, code_challenge = self._generate_pkce_pair()

        app, provider = _make_oauth_app()
        client = TestClient(app, follow_redirects=False)

        # 1. Register
        client_id, client_secret = self._register_client(client)

        # 2. Authorize (with our PKCE challenge)
        response = client.get(
            "/authorize",
            params={
                "client_id": client_id,
                "redirect_uri": "https://example.com/callback",
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
                "response_type": "code",
                "state": "e2e-state-value",
            },
            follow_redirects=False,
        )
        assert response.status_code == 302
        location = response.headers["location"]
        session = parse_qs(urlparse(location).query)["session"][0]

        # 3. Login
        with (
            patch.object(provider.supabase_auth, "authenticate", new_callable=AsyncMock, return_value="uuid-user-123"),
            patch.object(
                provider.supabase_auth,
                "create_mcp_oauth_key",
                new_callable=AsyncMock,
                return_value="gd_live_e2ekey12345",
            ),
        ):
            login_response = client.post(
                "/login",
                data={
                    "email": "user@test.com",
                    "password": "password123",
                    "session": session,
                },
                follow_redirects=False,
            )

        assert login_response.status_code == 200
        redirect_location = _extract_redirect_url(login_response.text)
        redirect_query = parse_qs(urlparse(redirect_location).query)
        code = redirect_query["code"][0]
        assert redirect_query["state"][0] == "e2e-state-value"

        # 4. Token exchange
        token_response = client.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": "https://example.com/callback",
                "client_id": client_id,
                "client_secret": client_secret,
                "code_verifier": code_verifier,
            },
        )

        assert token_response.status_code == 200
        token_data = token_response.json()
        assert token_data["access_token"] == "gd_live_e2ekey12345"
        assert token_data["token_type"] == "Bearer"

    def test_auth_code_single_use(self) -> None:
        """Auth code can only be exchanged once; second attempt returns 400."""
        code_verifier, code_challenge = self._generate_pkce_pair()

        app, provider = _make_oauth_app()
        client = TestClient(app, follow_redirects=False)

        client_id, client_secret = self._register_client(client)

        # Authorize
        response = client.get(
            "/authorize",
            params={
                "client_id": client_id,
                "redirect_uri": "https://example.com/callback",
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
                "response_type": "code",
                "state": "single-use-state",
            },
            follow_redirects=False,
        )
        session = parse_qs(urlparse(response.headers["location"]).query)["session"][0]

        # Login
        with (
            patch.object(provider.supabase_auth, "authenticate", new_callable=AsyncMock, return_value="uuid-user-123"),
            patch.object(
                provider.supabase_auth,
                "create_mcp_oauth_key",
                new_callable=AsyncMock,
                return_value="gd_live_singleuse",
            ),
        ):
            login_response = client.post(
                "/login",
                data={"email": "user@test.com", "password": "password123", "session": session},
                follow_redirects=False,
            )

        code = parse_qs(urlparse(_extract_redirect_url(login_response.text)).query)["code"][0]

        # First exchange — should succeed
        token_response_1 = client.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": "https://example.com/callback",
                "client_id": client_id,
                "client_secret": client_secret,
                "code_verifier": code_verifier,
            },
        )
        assert token_response_1.status_code == 200

        # Second exchange — should fail
        token_response_2 = client.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": "https://example.com/callback",
                "client_id": client_id,
                "client_secret": client_secret,
                "code_verifier": code_verifier,
            },
        )
        assert token_response_2.status_code == 400
        error_data = token_response_2.json()
        assert error_data["error"] == "invalid_grant"

    def test_state_echoed_exactly(self) -> None:
        """State parameter in redirect matches original authorize request exactly."""
        app, provider = _make_oauth_app()
        client = TestClient(app, follow_redirects=False)

        client_id, _ = self._register_client(client)
        unique_state = "unique-random-value-123"

        code_verifier = "some-verifier-for-pkce-test-state-echo"
        sha256_digest = hashlib.sha256(code_verifier.encode()).digest()
        code_challenge = base64.urlsafe_b64encode(sha256_digest).rstrip(b"=").decode()

        response = client.get(
            "/authorize",
            params={
                "client_id": client_id,
                "redirect_uri": "https://example.com/callback",
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
                "response_type": "code",
                "state": unique_state,
            },
            follow_redirects=False,
        )
        session = parse_qs(urlparse(response.headers["location"]).query)["session"][0]

        with (
            patch.object(provider.supabase_auth, "authenticate", new_callable=AsyncMock, return_value="uuid-user-123"),
            patch.object(
                provider.supabase_auth,
                "create_mcp_oauth_key",
                new_callable=AsyncMock,
                return_value="gd_live_statetest",
            ),
        ):
            login_response = client.post(
                "/login",
                data={"email": "user@test.com", "password": "password123", "session": session},
                follow_redirects=False,
            )

        redirect_location = _extract_redirect_url(login_response.text)
        redirect_query = parse_qs(urlparse(redirect_location).query)
        assert redirect_query["state"][0] == unique_state

    def test_redirect_uri_mismatch_registered_client_returns_400(self) -> None:
        """Registered client with mismatched redirect_uri gets 400, not a redirect."""
        app, _ = _make_oauth_app()
        client = TestClient(app, follow_redirects=False)

        # Register with specific redirect_uri
        reg = client.post(
            "/register",
            json={
                "redirect_uris": ["https://allowed.example.com/callback"],
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
            },
        )
        client_id = reg.json()["client_id"]

        # Authorize with a DIFFERENT redirect_uri
        response = client.get(
            "/authorize",
            params={
                "client_id": client_id,
                "redirect_uri": "https://evil.example.com/steal",
                "code_challenge": "test-challenge",
                "code_challenge_method": "S256",
                "response_type": "code",
                "state": "mismatch-state",
            },
        )

        assert response.status_code == 400


class TestIntegrationNoOAuth:
    """Tests for behavior when OAuth is not configured (no Supabase vars)."""

    def test_oauth_endpoints_503_when_supabase_not_configured(self) -> None:
        """Without Supabase config, OAuth endpoints return 503."""
        app = _make_no_oauth_app()
        client = TestClient(app, raise_server_exceptions=False)

        # OAuth endpoints should return 503
        resp_auth = client.get("/authorize")
        assert resp_auth.status_code == 503
        assert resp_auth.json() == {"error": "OAuth not configured"}

        resp_token = client.post("/token")
        assert resp_token.status_code == 503
        assert resp_token.json() == {"error": "OAuth not configured"}

        resp_register = client.post("/register")
        assert resp_register.status_code == 503
        assert resp_register.json() == {"error": "OAuth not configured"}

        # Health should still work
        resp_health = client.get("/health")
        assert resp_health.status_code == 200
