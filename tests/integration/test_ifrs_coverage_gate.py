"""IFRS-06 A9: deploy-order gate.

Fails-loud if MCP attempts to merge before govdata-api's IFRS-04 has
flipped ENABLE_IFRS_PARSING=on in the staging environment. Without this
gate, the MCP currency-hardcode fix would ship while the upstream API
still serves ``currency: "USD"`` for every filing — including IFRS
filers like Spotify — producing a visible correctness regression for
customers using the MCP between MCP-deploy and API-flag-flip.

The sequence that must hold:
    govdata-api IFRS-04 deploys + flag flips
      -> staging API starts returning IFRS currencies
      -> this test passes
      -> MCP PR CI goes green
      -> MCP merges + deploys.

Skipped when credentials / staging URL are not configured in CI env.
Do not mock — the point is to exercise the real API round-trip.
"""

from __future__ import annotations

import os

import pytest

# Spotify Technology S.A. — a canonical IFRS 20-F filer reporting in EUR.
SPOTIFY_CIK = "0001639920"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ifrs_filer_returns_non_usd_currency() -> None:
    """Fail-loud gate: if MCP deploys before flag-flip, Spotify returns
    currency='USD' (pre-IFRS-04 behaviour) and this test fails, blocking
    the MCP merge."""
    staging_base = os.environ.get("THESMA_STAGING_BASE_URL")
    api_key = os.environ.get("THESMA_STAGING_API_KEY")
    if not staging_base or not api_key:
        pytest.skip(
            "THESMA_STAGING_BASE_URL / THESMA_STAGING_API_KEY not set — "
            "skipping IFRS coverage gate (allowed only in developer env; "
            "CI must set both)."
        )

    try:
        from thesma import Thesma
    except ImportError:
        pytest.skip("thesma SDK not installed")

    client = Thesma(api_key=api_key, base_url=staging_base)
    try:
        result = await client.financials.get(SPOTIFY_CIK, statement="income", period="annual")
    finally:
        close = getattr(client, "aclose", None) or getattr(client, "close", None)
        if close is not None:
            close_result = close()
            if hasattr(close_result, "__await__"):
                await close_result

    assert getattr(result.data, "currency", None) != "USD", (
        f"Spotify (CIK {SPOTIFY_CIK}) returned currency='USD' on staging — suggests "
        "ENABLE_IFRS_PARSING is off or IFRS-04 has not deployed. MCP's "
        "currency-hardcode fix must NOT merge until the upstream API "
        "flips the flag."
    )
