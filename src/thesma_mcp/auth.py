"""OAuth 2.1 authentication provider for Thesma MCP server.

Implements the OAuthAuthorizationServerProvider protocol from the MCP SDK,
authenticating users via Supabase Auth and returning their API key as the
OAuth access_token.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
import time
from dataclasses import dataclass, field
from typing import Any

import httpx
from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    RefreshToken,
    TokenError,
)
from mcp.shared.auth import InvalidRedirectUriError, OAuthClientInformationFull, OAuthToken
from pydantic import AnyUrl

logger = logging.getLogger("thesma_mcp")

# TTLs
AUTH_CODE_TTL_SECONDS = 300  # 5 minutes
PENDING_AUTH_TTL_SECONDS = 600  # 10 minutes


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class ThesmaAuthCode(AuthorizationCode):
    """Authorization code that carries the user's Thesma API key."""

    api_key: str


@dataclass
class PendingAuth:
    """Holds OAuth params between /authorize and the login form submission."""

    client_id: str
    code_challenge: str
    redirect_uri: str
    redirect_uri_provided_explicitly: bool
    state: str | None
    created_at: float = field(default_factory=time.time)


class _PermissiveClient(OAuthClientInformationFull):
    """Synthetic client that accepts any redirect_uri for the open client model."""

    def validate_redirect_uri(self, redirect_uri: AnyUrl | None) -> AnyUrl:
        """Accept any redirect_uri without validation."""
        if redirect_uri is not None:
            return redirect_uri
        raise InvalidRedirectUriError("redirect_uri is required")


# ---------------------------------------------------------------------------
# Supabase auth helper
# ---------------------------------------------------------------------------


class SupabaseAuthError(Exception):
    """Raised when Supabase authentication fails."""


class SupabaseDownError(Exception):
    """Raised when Supabase is unavailable (429/5xx/timeout)."""


class SupabaseAuth:
    """Async helper for Supabase Auth and API key REST calls."""

    def __init__(self, supabase_url: str, supabase_service_key: str) -> None:
        self._url = supabase_url.rstrip("/")
        self._key = supabase_service_key

    async def authenticate(self, email: str, password: str) -> str:
        """Authenticate a user via Supabase GoTrue. Returns user_id."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                resp = await client.post(
                    f"{self._url}/auth/v1/token",
                    params={"grant_type": "password"},
                    headers={"apikey": self._key, "Content-Type": "application/json"},
                    json={"email": email, "password": password},
                )
            except httpx.TimeoutException as exc:
                raise SupabaseDownError("Authentication service temporarily unavailable. Please try again.") from exc

            if resp.status_code in (429, 500, 502, 503, 504):
                raise SupabaseDownError("Authentication service temporarily unavailable. Please try again.")

            if resp.status_code != 200:
                raise SupabaseAuthError("Invalid email or password.")

            data: dict[str, Any] = resp.json()
            user: dict[str, Any] = data["user"]
            user_id: str = user["id"]
            return user_id

    async def create_mcp_oauth_key(self, user_id: str) -> str:
        """Create a new MCP OAuth API key, deactivating any previous ones for this user.

        Plaintext is only available at creation time (only hash + prefix are stored),
        so we always create a new key rather than trying to retrieve an existing one.
        """
        plaintext = f"gd_live_{secrets.token_hex(16)}"
        key_hash = hashlib.sha256(plaintext.encode()).hexdigest()
        key_prefix = plaintext[:12]

        async with httpx.AsyncClient(timeout=10.0) as client:
            # Step 1: Deactivate any existing active mcp_oauth keys for this user
            try:
                patch_resp = await client.patch(
                    f"{self._url}/rest/v1/api_keys",
                    params={
                        "user_id": f"eq.{user_id}",
                        "source": "eq.mcp_oauth",
                        "is_active": "eq.true",
                    },
                    headers={
                        "apikey": self._key,
                        "Authorization": f"Bearer {self._key}",
                        "Content-Type": "application/json",
                        "Prefer": "return=minimal",
                    },
                    json={"is_active": False, "revoked_at": "now()"},
                )
            except httpx.TimeoutException as exc:
                raise SupabaseDownError("Authentication service temporarily unavailable. Please try again.") from exc

            if patch_resp.status_code not in (200, 204):
                raise SupabaseDownError("Authentication service temporarily unavailable. Please try again.")

            # Step 2: Create the new key
            try:
                post_resp = await client.post(
                    f"{self._url}/rest/v1/api_keys",
                    headers={
                        "apikey": self._key,
                        "Authorization": f"Bearer {self._key}",
                        "Content-Type": "application/json",
                        "Prefer": "return=minimal",
                    },
                    json={
                        "user_id": user_id,
                        "key_hash": key_hash,
                        "key_prefix": key_prefix,
                        "name": "MCP OAuth",
                        "source": "mcp_oauth",
                        "is_active": True,
                    },
                )
            except httpx.TimeoutException as exc:
                raise SupabaseDownError("Authentication service temporarily unavailable. Please try again.") from exc

            if post_resp.status_code not in (200, 201):
                raise SupabaseDownError("Authentication service temporarily unavailable. Please try again.")

        return plaintext


# ---------------------------------------------------------------------------
# OAuth provider
# ---------------------------------------------------------------------------


class ThesmaOAuthProvider:
    """MCP OAuth 2.1 provider backed by Supabase Auth.

    Implements the OAuthAuthorizationServerProvider protocol.
    """

    def __init__(self, supabase_auth: SupabaseAuth) -> None:
        self.supabase_auth = supabase_auth
        self._clients: dict[str, OAuthClientInformationFull] = {}
        self._auth_codes: dict[str, ThesmaAuthCode] = {}
        self._pending_auths: dict[str, PendingAuth] = {}

    # -- Client registration --------------------------------------------------

    async def get_client(self, client_id: str) -> OAuthClientInformationFull:
        """Return registered client or synthetic permissive client for unknown IDs.

        NEVER returns None — the SDK's AuthorizationHandler returns 400 on None.
        """
        if client_id in self._clients:
            return self._clients[client_id]

        # Open client model: return a synthetic permissive client
        return _PermissiveClient.model_construct(
            client_id=client_id,
            redirect_uris=None,
            grant_types=["authorization_code"],
            response_types=["code"],
        )

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        """Store client registration in memory."""
        if client_info.client_id is not None:
            self._clients[client_info.client_id] = client_info

    # -- Authorization flow ---------------------------------------------------

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        """Store pending auth params and return the login page URL."""
        self._cleanup_expired()

        session_token = secrets.token_hex(20)
        self._pending_auths[session_token] = PendingAuth(
            client_id=client.client_id or "",
            code_challenge=params.code_challenge,
            redirect_uri=str(params.redirect_uri),
            redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
            state=params.state,
        )
        return f"/login?session={session_token}"

    # -- Authorization code ---------------------------------------------------

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> ThesmaAuthCode | None:
        """Look up an authorization code. Returns None if not found or client mismatch."""
        self._cleanup_expired()

        entry = self._auth_codes.get(authorization_code)
        if entry is None:
            return None
        if entry.client_id != (client.client_id or ""):
            return None
        return entry

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: ThesmaAuthCode
    ) -> OAuthToken:
        """Exchange auth code for an access token (the user's API key).

        Removes the code to enforce single-use.
        """
        # Remove to enforce single-use
        self._auth_codes.pop(authorization_code.code, None)

        return OAuthToken(
            access_token=authorization_code.api_key,
            token_type="Bearer",
        )

    # -- Refresh tokens (not supported) ---------------------------------------

    async def load_refresh_token(self, client: OAuthClientInformationFull, refresh_token: str) -> RefreshToken | None:
        """Refresh tokens are not supported."""
        return None

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        """Refresh tokens are not supported."""
        raise TokenError(error="invalid_grant", error_description="Refresh tokens are not supported")

    # -- Access token / revocation --------------------------------------------

    async def load_access_token(self, token: str) -> AccessToken | None:
        """Accept any non-empty bearer token so the middleware passes it through.

        Actual API key validation happens in get_client(ctx) at the tool level.
        The SDK auto-creates a ProviderTokenVerifier that calls this method for
        every request, so we return a permissive AccessToken to let requests
        through to the MCP endpoint.
        """
        if not token or not token.strip():
            return None
        return AccessToken(
            token=token,
            client_id="",
            scopes=[],
        )

    async def revoke_token(
        self,
        token: AccessToken | RefreshToken,
    ) -> None:
        """Token revocation is a no-op."""

    # -- Cleanup --------------------------------------------------------------

    def _cleanup_expired(self) -> None:
        """Sweep expired auth codes and stale pending auths."""
        now = time.time()

        # Auth codes: 5-minute TTL
        expired_codes = [code for code, entry in self._auth_codes.items() if entry.expires_at < now]
        for code in expired_codes:
            del self._auth_codes[code]

        # Pending auths: 10-minute TTL
        expired_pending = [
            token for token, entry in self._pending_auths.items() if now - entry.created_at > PENDING_AUTH_TTL_SECONDS
        ]
        for token in expired_pending:
            del self._pending_auths[token]


# ---------------------------------------------------------------------------
# Login page HTML
# ---------------------------------------------------------------------------

LOGIN_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Thesma - Sign In</title>
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      background: #f5f5f5;
      display: flex;
      justify-content: center;
      align-items: center;
      min-height: 100vh;
    }
    .card {
      background: white;
      border-radius: 12px;
      box-shadow: 0 2px 16px rgba(0,0,0,0.08);
      padding: 40px;
      width: 100%;
      max-width: 400px;
    }
    .logo {
      text-align: center;
      margin-bottom: 24px;
      font-size: 24px;
      font-weight: 700;
      color: #111;
    }
    .subtitle {
      text-align: center;
      color: #666;
      margin-bottom: 24px;
      font-size: 14px;
    }
    .error {
      background: #fef2f2;
      border: 1px solid #fecaca;
      color: #dc2626;
      padding: 12px;
      border-radius: 8px;
      margin-bottom: 16px;
      font-size: 14px;
    }
    label {
      display: block;
      font-size: 14px;
      font-weight: 500;
      color: #333;
      margin-bottom: 6px;
    }
    input[type="email"], input[type="password"] {
      width: 100%;
      padding: 10px 12px;
      border: 1px solid #ddd;
      border-radius: 8px;
      font-size: 14px;
      margin-bottom: 16px;
    }
    input[type="email"]:focus, input[type="password"]:focus {
      outline: none;
      border-color: #111;
    }
    button {
      width: 100%;
      padding: 12px;
      background: #111;
      color: white;
      border: none;
      border-radius: 8px;
      font-size: 14px;
      font-weight: 600;
      cursor: pointer;
    }
    button:hover { background: #333; }
    .signup {
      text-align: center;
      margin-top: 20px;
      font-size: 13px;
      color: #666;
    }
    .signup a { color: #111; text-decoration: underline; }
  </style>
</head>
<body>
  <div class="card">
    <div class="logo">Thesma</div>
    <div class="subtitle">Sign in to connect your account</div>
    {error_html}
    <form method="POST" action="/login">
      <label for="email">Email</label>
      <input type="email" id="email" name="email" required>
      <label for="password">Password</label>
      <input type="password" id="password" name="password" required>
      <input type="hidden" name="session" value="{session}">
      <button type="submit">Sign In</button>
    </form>
    <div class="signup">
      Don't have an account? <a href="https://portal.thesma.dev">Sign up at portal.thesma.dev</a>
    </div>
  </div>
</body>
</html>"""
