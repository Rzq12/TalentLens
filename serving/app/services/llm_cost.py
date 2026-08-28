"""Configured LLM token-cost accounting.

Rates are deployment configuration rather than source constants because provider
pricing is contractual and changes independently of application releases.
"""

from __future__ import annotations

from decimal import Decimal

from app.config import Settings, get_settings

_PER_MILLION = Decimal("1000000")


def response_cost_usd(
    *,
    provider: str | None,
    input_tokens: int,
    output_tokens: int,
    settings: Settings | None = None,
) -> Decimal:
    """Calculate a response cost from explicitly configured per-million rates.

    Unknown providers and absent configuration have a zero rate, rather than a
    guessed one. The caller accumulates the returned ``Decimal`` directly into
    ``ScreeningRun.cost_usd``.
    """
    cfg = settings or get_settings()
    input_rate, output_rate = _rates_for_provider(provider, cfg)
    return (
        Decimal(input_tokens) * input_rate + Decimal(output_tokens) * output_rate
    ) / _PER_MILLION


def _rates_for_provider(provider: str | None, settings: Settings) -> tuple[Decimal, Decimal]:
    """Return configured input/output rates for one normalized provider name."""
    rates = {
        "gemini": (
            settings.gemini_input_usd_per_million_tokens,
            settings.gemini_output_usd_per_million_tokens,
        ),
        "groq": (
            settings.groq_input_usd_per_million_tokens,
            settings.groq_output_usd_per_million_tokens,
        ),
        "huggingface": (
            settings.hf_input_usd_per_million_tokens,
            settings.hf_output_usd_per_million_tokens,
        ),
    }
    input_rate, output_rate = rates.get(provider or "", ("0", "0"))
    return Decimal(input_rate), Decimal(output_rate)
