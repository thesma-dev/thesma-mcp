"""Tests for OAuth authentication — provider, Supabase auth, login routes, and integration."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import time
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx
from mcp.server.auth.provider import AuthorizationParams, TokenError
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions
from mcp.server.fastmcp import FastMCP
from mcp.shared.auth import OAuthClientInformationFull
from pydantic import AnyUrl
from starlette.testclient import TestClient

from thesma_mcp.auth import (
    AUTH_CODE_TTL_SECONDS,
    PENDING_AUTH_TTL_SECONDS,
    PendingAuth,
    SupabaseAuth,
    SupabaseAuthError,
    SupabaseDownError,
    ThesmaAuthCode,
    ThesmaOAuthProvider,
)


def _extract_redirect_url(body: str) -> str:
    """Parse the redirect URL out of the success HTML page."""
    match = re.search(r'window\.location\.href = "([^"]+)"', body)
    if not match:
        raise AssertionError(f"No redirect URL found in body:\n{body[:500]}")
    # Unescape HTML entities
    return match.group(1).replace("&amp;", "&")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SUPABASE_URL = "https://test.supabase.co"
SUPABASE_KEY = "test-service-key"
REDIRECT_URI = "https://example.com/callback"


def _make_provider() -> ThesmaOAuthProvider:
    """Create a ThesmaOAuthProvider with a mocked SupabaseAuth."""
    supabase_auth = SupabaseAuth(SUPABASE_URL, SUPABASE_KEY)
    return ThesmaOAuthProvider(supabase_auth=supabase_auth)


def _make_client_info(
    client_id: str = "test-client",
    redirect_uris: list[str] | None = None,
) -> OAuthClientInformationFull:
    """Create a valid OAuthClientInformationFull for testing."""
    uris: list[AnyUrl] | None = None
    if redirect_uris is not None:
        uris = [AnyUrl(u) for u in redirect_uris]
    else:
        uris = [AnyUrl(REDIRECT_URI)]
    return OAuthClientInformationFull(
        client_id=client_id,
        redirect_uris=uris,
        grant_types=["authorization_code"],
        response_types=["code"],
    )


def _make_auth_params(
    state: str = "test-state",
    code_challenge: str = "test-challenge",
    redirect_uri: str = REDIRECT_URI,
) -> AuthorizationParams:
    """Create AuthorizationParams for testing."""
    return AuthorizationParams(
        state=state,
        scopes=None,
        code_challenge=code_challenge,
        redirect_uri=AnyUrl(redirect_uri),
        redirect_uri_provided_explicitly=True,
    )


def _make_auth_code(
    code: str = "test-code",
    client_id: str = "test-client",
    api_key: str = "gd_live_test123",
    expires_at: float | None = None,
) -> ThesmaAuthCode:
    """Create a ThesmaAuthCode for testing."""
    return ThesmaAuthCode(
        code=code,
        scopes=[],
        expires_at=expires_at or (time.time() + AUTH_CODE_TTL_SECONDS),
        client_id=client_id,
        code_challenge="test-challenge",
        redirect_uri=REDIRECT_URI,
        redirect_uri_provided_explicitly=True,
        api_key=api_key,
    )


# ---------------------------------------------------------------------------
# ThesmaOAuthProvider unit tests
# ---------------------------------------------------------------------------


class TestThesmaOAuthProvider:
    async def test_register_client_stores_client(self) -> None:
        provider = _make_provider()
        client_info = _make_client_info(client_id="registered-client")

        await provider.register_client(client_info)
        result = await provider.get_client("registered-client")

        assert result is client_info
        assert result.client_id == "registered-client"

    async def test_get_client_unknown_returns_synthetic(self) -> None:
        provider = _make_provider()
        result = await provider.get_client("unknown-client")

        assert result is not None
        assert result.client_id == "unknown-client"
        assert result.grant_types == ["authorization_code"]

    async def test_authorize_returns_login_url(self) -> None:
        provider = _make_provider()
        client_info = _make_client_info()
        params = _make_auth_params()

        url = await provider.authorize(client_info, params)

        assert url.startswith("/login?session=")
        session_token = url.split("=", 1)[1]
        assert session_token in provider._pending_auths

    async def test_authorize_triggers_cleanup(self) -> None:
        provider = _make_provider()
        # Pre-populate with an expired auth code
        expired_code = _make_auth_code(code="expired", expires_at=time.time() - 10)
        provider._auth_codes["expired"] = expired_code

        client_info = _make_client_info()
        params = _make_auth_params()
        await provider.authorize(client_info, params)

        assert "expired" not in provider._auth_codes

    async def test_load_authorization_code_returns_entry(self) -> None:
        provider = _make_provider()
        auth_code = _make_auth_code(code="abc123", client_id="test-client")
        provider._auth_codes["abc123"] = auth_code

        client_info = _make_client_info(client_id="test-client")
        result = await provider.load_authorization_code(client_info, "abc123")

        assert result is not None
        assert result.code == "abc123"
        assert result.api_key == "gd_live_test123"

    async def test_load_authorization_code_wrong_client_returns_none(self) -> None:
        provider = _make_provider()
        auth_code = _make_auth_code(code="abc123", client_id="client-a")
        provider._auth_codes["abc123"] = auth_code

        client_b = _make_client_info(client_id="client-b")
        result = await provider.load_authorization_code(client_b, "abc123")

        assert result is None

    async def test_load_authorization_code_unknown_returns_none(self) -> None:
        provider = _make_provider()
        client_info = _make_client_info()
        result = await provider.load_authorization_code(client_info, "nonexistent")

        assert result is None

    async def test_exchange_authorization_code_returns_api_key(self) -> None:
        provider = _make_provider()
        auth_code = _make_auth_code(api_key="gd_live_test123")
        provider._auth_codes[auth_code.code] = auth_code

        client_info = _make_client_info()
        token = await provider.exchange_authorization_code(client_info, auth_code)

        assert token.access_token == "gd_live_test123"
        assert token.token_type == "Bearer"
        # Code should be removed (single-use)
        assert auth_code.code not in provider._auth_codes

    async def test_load_refresh_token_returns_none(self) -> None:
        provider = _make_provider()
        client_info = _make_client_info()
        result = await provider.load_refresh_token(client_info, "any-token")

        assert result is None

    async def test_exchange_refresh_token_raises(self) -> None:
        from mcp.server.auth.provider import RefreshToken

        provider = _make_provider()
        client_info = _make_client_info()
        rt = RefreshToken(token="t", client_id="c", scopes=[])

        with pytest.raises(TokenError):
            await provider.exchange_refresh_token(client_info, rt, [])


# ---------------------------------------------------------------------------
# SupabaseAuth unit tests
# ---------------------------------------------------------------------------


class TestSupabaseAuth:
    async def test_authenticate_success(self) -> None:
        auth = SupabaseAuth(SUPABASE_URL, SUPABASE_KEY)

        with respx.mock:
            respx.post(f"{SUPABASE_URL}/auth/v1/token").mock(
                return_value=httpx.Response(
                    200,
                    json={"user": {"id": "uuid-123"}, "access_token": "jwt-token"},
                )
            )

            user_id = await auth.authenticate("test@example.com", "password123")

        assert user_id == "uuid-123"

    async def test_authenticate_invalid_credentials(self) -> None:
        auth = SupabaseAuth(SUPABASE_URL, SUPABASE_KEY)

        with respx.mock:
            respx.post(f"{SUPABASE_URL}/auth/v1/token").mock(
                return_value=httpx.Response(400, json={"error": "invalid_grant"})
            )

            with pytest.raises(SupabaseAuthError, match="Invalid email or password"):
                await auth.authenticate("test@example.com", "wrong-password")

    async def test_authenticate_supabase_down(self) -> None:
        auth = SupabaseAuth(SUPABASE_URL, SUPABASE_KEY)

        with respx.mock:
            respx.post(f"{SUPABASE_URL}/auth/v1/token").mock(
                return_value=httpx.Response(500, json={"error": "internal"})
            )

            with pytest.raises(SupabaseDownError, match="temporarily unavailable"):
                await auth.authenticate("test@example.com", "password123")

    async def test_authenticate_timeout(self) -> None:
        auth = SupabaseAuth(SUPABASE_URL, SUPABASE_KEY)

        with respx.mock:
            respx.post(f"{SUPABASE_URL}/auth/v1/token").mock(side_effect=httpx.TimeoutException("Connection timed out"))

            with pytest.raises(SupabaseDownError, match="temporarily unavailable"):
                await auth.authenticate("test@example.com", "password123")

    async def test_create_mcp_oauth_key_deactivates_existing_and_creates_new(self) -> None:
        auth = SupabaseAuth(SUPABASE_URL, SUPABASE_KEY)

        with respx.mock:
            patch_route = respx.patch(f"{SUPABASE_URL}/rest/v1/api_keys").mock(return_value=httpx.Response(204))
            post_route = respx.post(f"{SUPABASE_URL}/rest/v1/api_keys").mock(return_value=httpx.Response(201, json={}))

            key = await auth.create_mcp_oauth_key("uuid-123")

        assert key.startswith("gd_live_")
        assert len(key) == 40

        # PATCH was called
        assert patch_route.called
        patch_request = patch_route.calls[0].request
        # All three filter params present
        assert "user_id=eq.uuid-123" in str(patch_request.url)
        assert "source=eq.mcp_oauth" in str(patch_request.url)
        assert "is_active=eq.true" in str(patch_request.url)
        # PATCH body
        patch_body = json.loads(patch_request.content)
        assert patch_body["is_active"] is False
        assert patch_body["revoked_at"] is not None

        # POST was called
        assert post_route.called
        post_body = json.loads(post_route.calls[0].request.content)
        assert post_body["user_id"] == "uuid-123"
        assert post_body["key_hash"] == hashlib.sha256(key.encode()).hexdigest()
        assert post_body["key_prefix"] == key[:12]
        assert post_body["name"] == "MCP OAuth"
        assert post_body["source"] == "mcp_oauth"
        assert post_body["is_active"] is True
        # Regression: key_plaintext must NOT be in the body
        assert "key_plaintext" not in post_body

    async def test_create_mcp_oauth_key_no_existing_keys(self) -> None:
        """PATCH matching 0 rows returns 204 — still valid, POST proceeds."""
        auth = SupabaseAuth(SUPABASE_URL, SUPABASE_KEY)

        with respx.mock:
            patch_route = respx.patch(f"{SUPABASE_URL}/rest/v1/api_keys").mock(return_value=httpx.Response(204))
            post_route = respx.post(f"{SUPABASE_URL}/rest/v1/api_keys").mock(return_value=httpx.Response(201, json={}))

            key = await auth.create_mcp_oauth_key("uuid-456")

        assert key.startswith("gd_live_")
        assert patch_route.call_count == 1
        assert post_route.call_count == 1

    async def test_create_mcp_oauth_key_patch_failure_raises(self) -> None:
        auth = SupabaseAuth(SUPABASE_URL, SUPABASE_KEY)

        with respx.mock:
            respx.patch(f"{SUPABASE_URL}/rest/v1/api_keys").mock(return_value=httpx.Response(500))
            post_route = respx.post(f"{SUPABASE_URL}/rest/v1/api_keys").mock(return_value=httpx.Response(201, json={}))

            with pytest.raises(SupabaseDownError):
                await auth.create_mcp_oauth_key("uuid-123")

        # POST must NOT have been called
        assert not post_route.called

    async def test_create_mcp_oauth_key_post_failure_raises(self) -> None:
        auth = SupabaseAuth(SUPABASE_URL, SUPABASE_KEY)

        with respx.mock:
            respx.patch(f"{SUPABASE_URL}/rest/v1/api_keys").mock(return_value=httpx.Response(204))
            respx.post(f"{SUPABASE_URL}/rest/v1/api_keys").mock(return_value=httpx.Response(500))

            with pytest.raises(SupabaseDownError):
                await auth.create_mcp_oauth_key("uuid-123")

    async def test_create_mcp_oauth_key_timeout_raises(self) -> None:
        auth = SupabaseAuth(SUPABASE_URL, SUPABASE_KEY)

        with respx.mock:
            respx.patch(f"{SUPABASE_URL}/rest/v1/api_keys").mock(side_effect=httpx.TimeoutException("timeout"))

            with pytest.raises(SupabaseDownError, match="temporarily unavailable"):
                await auth.create_mcp_oauth_key("uuid-123")

    async def test_auth_py_does_not_reference_key_plaintext(self) -> None:
        """Regression: the string `key_plaintext` must not appear in auth.py."""
        import pathlib

        auth_py = pathlib.Path(__file__).parent.parent / "src" / "thesma_mcp" / "auth.py"
        content = auth_py.read_text()
        assert "key_plaintext" not in content


# ---------------------------------------------------------------------------
# PendingAuth / cleanup tests
# ---------------------------------------------------------------------------


class TestCleanup:
    async def test_pending_auth_expires_after_ttl(self) -> None:
        provider = _make_provider()
        provider._pending_auths["old-session"] = PendingAuth(
            client_id="c",
            code_challenge="ch",
            redirect_uri="https://example.com/cb",
            redirect_uri_provided_explicitly=True,
            state="s",
            created_at=time.time() - PENDING_AUTH_TTL_SECONDS - 60,
        )

        provider._cleanup_expired()

        assert "old-session" not in provider._pending_auths

    async def test_auth_code_expires_after_ttl(self) -> None:
        provider = _make_provider()
        provider._auth_codes["expired-code"] = _make_auth_code(code="expired-code", expires_at=time.time() - 10)

        provider._cleanup_expired()

        assert "expired-code" not in provider._auth_codes

    async def test_valid_entries_survive_cleanup(self) -> None:
        provider = _make_provider()
        provider._auth_codes["valid-code"] = _make_auth_code(code="valid-code", expires_at=time.time() + 300)
        provider._pending_auths["valid-session"] = PendingAuth(
            client_id="c",
            code_challenge="ch",
            redirect_uri="https://example.com/cb",
            redirect_uri_provided_explicitly=True,
            state="s",
            created_at=time.time(),
        )

        provider._cleanup_expired()

        assert "valid-code" in provider._auth_codes
        assert "valid-session" in provider._pending_auths


# ---------------------------------------------------------------------------
# Integration tests — OAuth-configured app
# ---------------------------------------------------------------------------


def _create_oauth_app() -> tuple[FastMCP, ThesmaOAuthProvider]:
    """Create an OAuth-configured FastMCP instance for testing."""
    from thesma_mcp.auth import SupabaseAuth, ThesmaOAuthProvider
    from thesma_mcp.server import _register_login_routes, _register_routes, app_lifespan

    supabase_auth = SupabaseAuth(SUPABASE_URL, SUPABASE_KEY)
    provider = ThesmaOAuthProvider(supabase_auth=supabase_auth)

    mcp_instance = FastMCP(
        "thesma",
        lifespan=app_lifespan,
        auth_server_provider=provider,
        auth=AuthSettings(
            issuer_url="https://test.example.com",  # type: ignore[arg-type]
            resource_server_url="https://test.example.com",  # type: ignore[arg-type]
            client_registration_options=ClientRegistrationOptions(enabled=True),
        ),
    )
    _register_routes(mcp_instance)
    _register_login_routes(mcp_instance, provider)
    return mcp_instance, provider


class TestIntegration:
    def test_health_still_unauthenticated(self) -> None:
        mcp_instance, _ = _create_oauth_app()
        app = mcp_instance.streamable_http_app()
        client = TestClient(app)

        response = client.get("/health")

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_well_known_metadata_endpoint(self) -> None:
        mcp_instance, _ = _create_oauth_app()
        app = mcp_instance.streamable_http_app()
        client = TestClient(app)

        response = client.get("/.well-known/oauth-authorization-server")

        assert response.status_code == 200
        data = response.json()
        assert "authorization_endpoint" in data
        assert "token_endpoint" in data
        assert "registration_endpoint" in data
        assert "S256" in data.get("code_challenge_methods_supported", [])

    def test_register_endpoint_creates_client(self) -> None:
        mcp_instance, _ = _create_oauth_app()
        app = mcp_instance.streamable_http_app()
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

    def test_authorize_redirects_to_login(self) -> None:
        mcp_instance, _ = _create_oauth_app()
        app = mcp_instance.streamable_http_app()
        client = TestClient(app, follow_redirects=False)

        # Register a client first
        reg_resp = client.post(
            "/register",
            json={
                "redirect_uris": [REDIRECT_URI],
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
            },
        )
        client_id = reg_resp.json()["client_id"]

        # Generate a proper PKCE code challenge
        code_verifier = "test-verifier-that-is-long-enough-for-pkce-requirements"
        sha256 = hashlib.sha256(code_verifier.encode()).digest()
        code_challenge = base64.urlsafe_b64encode(sha256).rstrip(b"=").decode()

        response = client.get(
            "/authorize",
            params={
                "client_id": client_id,
                "redirect_uri": REDIRECT_URI,
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
                "response_type": "code",
                "state": "test-state",
            },
        )

        assert response.status_code == 302
        location = response.headers["location"]
        assert location.startswith("/login?session=")

    def test_login_get_renders_form(self) -> None:
        mcp_instance, provider = _create_oauth_app()
        app = mcp_instance.streamable_http_app()
        client = TestClient(app)

        # Manually create a pending auth
        session_token = "test-session-token"
        provider._pending_auths[session_token] = PendingAuth(
            client_id="test-client",
            code_challenge="test-challenge",
            redirect_uri=REDIRECT_URI,
            redirect_uri_provided_explicitly=True,
            state="test-state",
        )

        response = client.get(f"/login?session={session_token}")

        assert response.status_code == 200
        body = response.text
        assert "<form" in body
        assert 'name="email"' in body
        assert 'name="password"' in body

    def test_login_get_invalid_session(self) -> None:
        mcp_instance, _ = _create_oauth_app()
        app = mcp_instance.streamable_http_app()
        client = TestClient(app)

        response = client.get("/login?session=nonexistent")

        assert response.status_code == 400

    def test_login_post_success_redirects_with_code(self) -> None:
        mcp_instance, provider = _create_oauth_app()
        app = mcp_instance.streamable_http_app()
        client = TestClient(app, follow_redirects=False)

        # Set up pending auth
        session_token = "test-session"
        provider._pending_auths[session_token] = PendingAuth(
            client_id="test-client",
            code_challenge="test-challenge",
            redirect_uri=REDIRECT_URI,
            redirect_uri_provided_explicitly=True,
            state="test-state",
        )

        # Mock Supabase calls
        with (
            patch.object(provider.supabase_auth, "authenticate", new_callable=AsyncMock, return_value="uuid-123"),
            patch.object(
                provider.supabase_auth, "create_mcp_oauth_key", new_callable=AsyncMock, return_value="gd_live_testkey"
            ),
        ):
            response = client.post(
                "/login",
                data={
                    "email": "test@example.com",
                    "password": "password123",
                    "session": session_token,
                },
            )

        assert response.status_code == 200
        assert "Signed in successfully" in response.text
        location = _extract_redirect_url(response.text)
        parsed = urlparse(location)
        params = parse_qs(parsed.query)
        assert "code" in params
        assert params["state"] == ["test-state"]

    def test_login_post_bad_credentials_rerenders(self) -> None:
        mcp_instance, provider = _create_oauth_app()
        app = mcp_instance.streamable_http_app()
        client = TestClient(app)

        session_token = "test-session"
        provider._pending_auths[session_token] = PendingAuth(
            client_id="test-client",
            code_challenge="test-challenge",
            redirect_uri=REDIRECT_URI,
            redirect_uri_provided_explicitly=True,
            state="test-state",
        )

        with patch.object(
            provider.supabase_auth,
            "authenticate",
            new_callable=AsyncMock,
            side_effect=SupabaseAuthError("Invalid email or password."),
        ):
            response = client.post(
                "/login",
                data={
                    "email": "test@example.com",
                    "password": "wrong",
                    "session": session_token,
                },
            )

        assert response.status_code == 200
        assert "Invalid email or password" in response.text

    def test_login_post_supabase_down_rerenders(self) -> None:
        mcp_instance, provider = _create_oauth_app()
        app = mcp_instance.streamable_http_app()
        client = TestClient(app)

        session_token = "test-session"
        provider._pending_auths[session_token] = PendingAuth(
            client_id="test-client",
            code_challenge="test-challenge",
            redirect_uri=REDIRECT_URI,
            redirect_uri_provided_explicitly=True,
            state="test-state",
        )

        with patch.object(
            provider.supabase_auth,
            "authenticate",
            new_callable=AsyncMock,
            side_effect=SupabaseDownError("Authentication service temporarily unavailable. Please try again."),
        ):
            response = client.post(
                "/login",
                data={
                    "email": "test@example.com",
                    "password": "password123",
                    "session": session_token,
                },
            )

        assert response.status_code == 200
        assert "temporarily unavailable" in response.text

    def test_full_oauth_flow(self) -> None:
        """End-to-end: register -> authorize -> login -> token exchange."""
        mcp_instance, provider = _create_oauth_app()
        app = mcp_instance.streamable_http_app()
        client = TestClient(app, follow_redirects=False)

        # 1. Register client
        reg_resp = client.post(
            "/register",
            json={
                "redirect_uris": [REDIRECT_URI],
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
            },
        )
        assert reg_resp.status_code == 201
        reg_data = reg_resp.json()
        client_id = reg_data["client_id"]
        client_secret = reg_data.get("client_secret", "")

        # 2. Authorize (get session)
        code_verifier = "test-verifier-that-is-long-enough-for-pkce-requirements"
        sha256 = hashlib.sha256(code_verifier.encode()).digest()
        code_challenge = base64.urlsafe_b64encode(sha256).rstrip(b"=").decode()

        auth_resp = client.get(
            "/authorize",
            params={
                "client_id": client_id,
                "redirect_uri": REDIRECT_URI,
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
                "response_type": "code",
                "state": "unique-state-123",
            },
        )
        assert auth_resp.status_code == 302
        session_token = auth_resp.headers["location"].split("session=")[1]

        # 3. Login POST (get code)
        with (
            patch.object(provider.supabase_auth, "authenticate", new_callable=AsyncMock, return_value="uuid-123"),
            patch.object(
                provider.supabase_auth,
                "create_mcp_oauth_key",
                new_callable=AsyncMock,
                return_value="gd_live_full_flow_key",
            ),
        ):
            login_resp = client.post(
                "/login",
                data={
                    "email": "test@example.com",
                    "password": "password123",
                    "session": session_token,
                },
            )
        assert login_resp.status_code == 200
        location = _extract_redirect_url(login_resp.text)
        parsed = urlparse(location)
        query_params = parse_qs(parsed.query)
        auth_code = query_params["code"][0]
        assert query_params["state"] == ["unique-state-123"]

        # 4. Exchange code at /token
        token_resp = client.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "code": auth_code,
                "redirect_uri": REDIRECT_URI,
                "client_id": client_id,
                "client_secret": client_secret,
                "code_verifier": code_verifier,
            },
        )
        assert token_resp.status_code == 200
        token_data = token_resp.json()
        assert token_data["access_token"] == "gd_live_full_flow_key"
        assert token_data["token_type"] == "Bearer"

    def test_auth_code_single_use(self) -> None:
        """Auth code can only be exchanged once."""
        mcp_instance, provider = _create_oauth_app()
        app = mcp_instance.streamable_http_app()
        client = TestClient(app, follow_redirects=False)

        # Register client
        reg_resp = client.post(
            "/register",
            json={
                "redirect_uris": [REDIRECT_URI],
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
            },
        )
        reg_data = reg_resp.json()
        client_id = reg_data["client_id"]
        client_secret = reg_data.get("client_secret", "")

        # Get code
        code_verifier = "test-verifier-that-is-long-enough-for-pkce-requirements"
        sha256 = hashlib.sha256(code_verifier.encode()).digest()
        code_challenge = base64.urlsafe_b64encode(sha256).rstrip(b"=").decode()

        auth_resp = client.get(
            "/authorize",
            params={
                "client_id": client_id,
                "redirect_uri": REDIRECT_URI,
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
                "response_type": "code",
                "state": "state-1",
            },
        )
        session_token = auth_resp.headers["location"].split("session=")[1]

        with (
            patch.object(provider.supabase_auth, "authenticate", new_callable=AsyncMock, return_value="uuid-123"),
            patch.object(
                provider.supabase_auth, "create_mcp_oauth_key", new_callable=AsyncMock, return_value="gd_live_key"
            ),
        ):
            login_resp = client.post(
                "/login",
                data={"email": "a@b.com", "password": "p", "session": session_token},
            )
        auth_code = parse_qs(urlparse(_extract_redirect_url(login_resp.text)).query)["code"][0]

        # First exchange — success
        resp1 = client.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "code": auth_code,
                "redirect_uri": REDIRECT_URI,
                "client_id": client_id,
                "client_secret": client_secret,
                "code_verifier": code_verifier,
            },
        )
        assert resp1.status_code == 200

        # Second exchange — fail
        resp2 = client.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "code": auth_code,
                "redirect_uri": REDIRECT_URI,
                "client_id": client_id,
                "client_secret": client_secret,
                "code_verifier": code_verifier,
            },
        )
        assert resp2.status_code == 400
        assert resp2.json()["error"] == "invalid_grant"

    def test_state_echoed_exactly(self) -> None:
        mcp_instance, provider = _create_oauth_app()
        app = mcp_instance.streamable_http_app()
        client = TestClient(app, follow_redirects=False)

        # Register
        reg_resp = client.post(
            "/register",
            json={
                "redirect_uris": [REDIRECT_URI],
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
            },
        )
        client_id = reg_resp.json()["client_id"]

        code_verifier = "some-verifier-for-pkce-test-state-echo"
        sha256 = hashlib.sha256(code_verifier.encode()).digest()
        code_challenge = base64.urlsafe_b64encode(sha256).rstrip(b"=").decode()

        unique_state = "unique-random-value-123"
        auth_resp = client.get(
            "/authorize",
            params={
                "client_id": client_id,
                "redirect_uri": REDIRECT_URI,
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
                "response_type": "code",
                "state": unique_state,
            },
        )
        session_token = auth_resp.headers["location"].split("session=")[1]

        with (
            patch.object(provider.supabase_auth, "authenticate", new_callable=AsyncMock, return_value="uuid-123"),
            patch.object(
                provider.supabase_auth, "create_mcp_oauth_key", new_callable=AsyncMock, return_value="gd_live_key"
            ),
        ):
            login_resp = client.post(
                "/login",
                data={"email": "a@b.com", "password": "p", "session": session_token},
            )

        location = _extract_redirect_url(login_resp.text)
        params = parse_qs(urlparse(location).query)
        assert params["state"] == [unique_state]

    def test_redirect_uri_mismatch_registered_client_returns_400(self) -> None:
        mcp_instance, _ = _create_oauth_app()
        app = mcp_instance.streamable_http_app()
        client = TestClient(app, follow_redirects=False)

        # Register with specific redirect_uri
        reg_resp = client.post(
            "/register",
            json={
                "redirect_uris": ["https://allowed.example.com/callback"],
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
            },
        )
        client_id = reg_resp.json()["client_id"]

        # Try with different redirect_uri
        response = client.get(
            "/authorize",
            params={
                "client_id": client_id,
                "redirect_uri": "https://evil.example.com/steal",
                "code_challenge": "test-challenge",
                "code_challenge_method": "S256",
                "response_type": "code",
                "state": "test-state",
            },
        )

        assert response.status_code == 400

    def test_oauth_endpoints_503_when_supabase_not_configured(self) -> None:
        """When OAuth is not configured, OAuth endpoints return 503."""
        from thesma_mcp.server import _register_oauth_stub_routes, _register_routes, app_lifespan

        # Create plain FastMCP without OAuth, but with stub routes
        mcp_instance = FastMCP("thesma", lifespan=app_lifespan)
        _register_routes(mcp_instance)
        _register_oauth_stub_routes(mcp_instance)
        app = mcp_instance.streamable_http_app()
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
