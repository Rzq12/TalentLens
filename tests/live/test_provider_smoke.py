"""Opt-in external-provider contract checks using only synthetic T0 content."""

from __future__ import annotations

import os

import pytest

from app.agents.base import LLMRequest
from app.agents.factory import build_failover_chain
from app.config import Settings

pytestmark = pytest.mark.live


@pytest.mark.asyncio
async def test_configured_provider_returns_nonempty_synthetic_completion() -> None:
    """Verify credentials and basic provider contract without candidate data."""
    if os.getenv("TALENTLENS_RUN_LIVE_PROVIDER_TESTS") != "1":
        pytest.skip("Set TALENTLENS_RUN_LIVE_PROVIDER_TESTS=1 to enable provider smoke tests.")

    settings = Settings(
        google_api_key=os.getenv("TALENTLENS_LIVE_GOOGLE_API_KEY", ""),
        groq_api_key=os.getenv("TALENTLENS_LIVE_GROQ_API_KEY", ""),
        hf_api_key=os.getenv("TALENTLENS_LIVE_HF_API_KEY", ""),
    )
    if not (settings.google_api_key or settings.groq_api_key or settings.hf_api_key):
        pytest.skip("Configure at least one TALENTLENS_LIVE_*_API_KEY to run this test.")

    chain = build_failover_chain(settings)
    response = await chain.generate(
        LLMRequest(
            system="Reply with exactly the word: ready",
            prompt="Synthetic health check. Do not include personal data.",
            pii_tier="T0",
            max_output_tokens=8,
        )
    )

    assert response.text.strip()
    assert response.provider
    assert response.model
