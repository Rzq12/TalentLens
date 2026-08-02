"""Provider-neutral request/response types and the failover chain.

Nothing in this module knows what a Gemini or a Groq payload looks like. It
defines what every adapter must accept and return, and the policy that decides
which adapter gets a given request — including the one rule that is not a
performance concern at all: a request carrying full candidate PII must never be
handed to a provider that has not declared it may see it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, Protocol, runtime_checkable

import structlog

from app.exceptions import (
    LLMProviderError,
    LLMRefusalError,
    NoEligibleProviderError,
)

logger = structlog.get_logger(__name__)

#: PII tiers a request may carry.
#:
#: ``T0`` no PII at all (a job description); ``T1`` PII redacted, so a cloud
#: free tier is acceptable; ``T2`` full candidate PII, which may only reach
#: infrastructure we control.
PII_TIERS: Final[frozenset[str]] = frozenset({"T0", "T1", "T2"})

#: Failure kinds worth trying the next provider for. A rate limit or a network
#: blip says nothing about the request itself, so another provider may well
#: succeed. A context overflow does not qualify: the same oversized prompt
#: would overflow the next model too, and retrying only burns quota.
_RETRYABLE_KINDS: Final[frozenset[str]] = frozenset(
    {"rate_limit", "network", "model_unavailable", "auth", "unknown"}
)


@dataclass(frozen=True, slots=True)
class LLMRequest:
    """One prompt, with the metadata that decides who may answer it.

    Attributes:
        prompt: The user-role text.
        system: Optional system instruction. Kept separate from ``prompt``
            rather than concatenated, because providers weight the two
            differently and text lifted from a resume must not be able to
            reach the system channel.
        pii_tier: One of :data:`PII_TIERS`.
        max_output_tokens: Ceiling for the response, or ``None`` for the
            provider default.
    """

    prompt: str
    system: str | None = None
    pii_tier: str = "T1"
    max_output_tokens: int | None = None

    def __post_init__(self) -> None:
        """Reject an unknown tier at construction time.

        Raises:
            ValueError: If ``pii_tier`` is not in :data:`PII_TIERS`. Validating
                here rather than at dispatch means a typo cannot silently
                widen who is allowed to see the prompt.
        """
        if self.pii_tier not in PII_TIERS:
            raise ValueError(
                f"Unknown pii_tier {self.pii_tier!r}; expected one of "
                f"{', '.join(sorted(PII_TIERS))}."
            )


@dataclass(frozen=True, slots=True)
class LLMResponse:
    """What a provider returned, normalized across vendors.

    Attributes:
        text: The generated text.
        model: Model identifier that produced it, recorded so a verdict can be
            attributed and cache-keyed.
        provider: Adapter name.
        prompt_tokens: Input tokens billed.
        completion_tokens: Output tokens billed.
    """

    text: str
    model: str
    provider: str
    prompt_tokens: int = 0
    completion_tokens: int = 0


@runtime_checkable
class LLMProvider(Protocol):
    """What the failover chain requires of an adapter."""

    name: str
    model: str
    tiers: frozenset[str]

    async def generate(self, request: LLMRequest) -> LLMResponse:
        """Answer a request, or raise a classified failure."""
        ...


@dataclass
class FailoverChain:
    """Tries providers in order until one answers.

    Order is priority, not preference: the cheapest acceptable provider comes
    first and the chain descends only on failures that another provider could
    plausibly survive.

    A provider that has not declared the request's tier is skipped **before**
    it is called, not filtered out of the results afterwards. The difference
    matters: the second would already have sent the PII.
    """

    providers: Sequence[LLMProvider]

    async def generate(self, request: LLMRequest) -> LLMResponse:
        """Return the first successful response from an eligible provider.

        Args:
            request: The prompt and its PII tier.

        Returns:
            The first successful :class:`LLMResponse`.

        Raises:
            LLMRefusalError: If a provider declined on policy grounds. The
                chain stops rather than shopping the prompt around: a second
                model would most likely refuse too, and a refusal can be
                correct.
            LLMProviderError: If a failure could not be improved on by
                retrying elsewhere, such as a context overflow.
            NoEligibleProviderError: If no provider is permitted at this tier,
                or every eligible provider failed.
        """
        attempted = 0
        last_error: LLMProviderError | None = None

        for provider in self.providers:
            if request.pii_tier not in provider.tiers:
                logger.info(
                    "llm_provider_skipped_for_tier",
                    provider=provider.name,
                    pii_tier=request.pii_tier,
                )
                continue

            attempted += 1
            try:
                return await provider.generate(request)
            except LLMRefusalError:
                raise
            except LLMProviderError as exc:
                if exc.kind not in _RETRYABLE_KINDS:
                    raise
                last_error = exc
                logger.warning(
                    "llm_provider_failed_over",
                    provider=provider.name,
                    kind=exc.kind,
                )

        if attempted == 0:
            # Deliberately says nothing about the prompt. This message reaches
            # logs and API responses, and at T2 the prompt is a full resume.
            raise NoEligibleProviderError(
                f"No configured provider is permitted to handle a {request.pii_tier} request."
            )

        raise NoEligibleProviderError(
            f"All {attempted} eligible provider(s) failed; last failure was "
            f"{last_error.kind if last_error else 'unknown'}."
        )
