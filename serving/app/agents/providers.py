"""Concrete adapters for the free-tier providers the chain uses.

Each adapter owns exactly one thing: translating :class:`LLMRequest` into a
vendor's wire format and the vendor's answer back into :class:`LLMResponse`.
Retry policy, ordering, and PII gating live in :mod:`app.agents.base` — an
adapter that retried itself would defeat the chain's accounting.

Two rules hold in both adapters and are each covered by a test:

* **The key travels in a header, never in a URL.** URLs reach access logs,
  error messages, and traces; headers do not.
* **The key never appears in a ``repr``, a ``str``, or an exception message.**
  A stack trace is the most common way a credential escapes.
"""

from __future__ import annotations

from typing import Any, Final

import httpx
import structlog

from app.agents.base import LLMRequest, LLMResponse
from app.agents.classifier import classify_provider_error
from app.exceptions import LLMProviderError, LLMRefusalError

logger = structlog.get_logger(__name__)

_GEMINI_BASE_URL: Final = "https://generativelanguage.googleapis.com/v1beta"
_GROQ_URL: Final = "https://api.groq.com/openai/v1/chat/completions"

#: Cloud free tiers may see redacted data only. ``T2`` — a full resume — is
#: absent deliberately, and :class:`app.agents.base.FailoverChain` reads this
#: to skip the provider before the request is built.
_CLOUD_TIERS: Final[frozenset[str]] = frozenset({"T0", "T1"})

#: Finish reasons that mean the model declined rather than failed.
_GEMINI_REFUSALS: Final[frozenset[str]] = frozenset({"SAFETY", "BLOCKLIST", "PROHIBITED_CONTENT"})
_GROQ_REFUSALS: Final[frozenset[str]] = frozenset({"content_filter"})

_DEFAULT_TIMEOUT_SECONDS: Final = 60.0


class _HTTPProviderBase:
    """Shared plumbing: transport ownership, POSTing, and error normalization.

    Holds the API key in a private attribute and overrides ``__repr__`` so the
    default rendering — which would print every field — cannot put it in a log
    line.
    """

    name: str = "unknown"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        tiers: frozenset[str] | None = None,
        timeout: float = _DEFAULT_TIMEOUT_SECONDS,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        """Configure the adapter.

        Args:
            api_key: Provider credential. Never logged, never rendered.
            model: Model identifier, supplied by ``Settings``.
            tiers: PII tiers this provider may serve. Defaults to cloud tiers.
            timeout: Per-request timeout in seconds.
            transport: Injected transport. Tests pass an
                ``httpx.MockTransport`` so no test can reach the network.
        """
        self._api_key = api_key
        self.model = model
        self.tiers = tiers if tiers is not None else _CLOUD_TIERS
        self._timeout = timeout
        self._transport = transport

    def __repr__(self) -> str:
        """Render without the credential.

        Returns:
            A description carrying the provider and model only.
        """
        return f"<{type(self).__name__} provider={self.name!r} model={self.model!r}>"

    __str__ = __repr__

    async def _post(self, url: str, *, headers: dict[str, str], payload: dict[str, Any]) -> Any:
        """POST a payload and return the decoded JSON body.

        Args:
            url: Absolute endpoint URL, with no credential in it.
            headers: Request headers, including the credential.
            payload: JSON request body.

        Returns:
            The decoded response body.

        Raises:
            LLMProviderError: On any transport failure, non-2xx status, or
                undecodable body. The message carries the provider and the
                status — never the key and never the prompt.
        """
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout, transport=self._transport
            ) as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as exc:
            kind = classify_provider_error(exc)
            logger.warning(
                "llm_provider_http_error",
                provider=self.name,
                model=self.model,
                status=exc.response.status_code,
                kind=kind,
            )
            raise LLMProviderError(
                f"{self.name} returned HTTP {exc.response.status_code}.",
                kind=kind,
                provider=self.name,
            ) from exc
        except httpx.HTTPError as exc:
            kind = classify_provider_error(exc)
            logger.warning(
                "llm_provider_transport_error",
                provider=self.name,
                model=self.model,
                kind=kind,
            )
            raise LLMProviderError(
                f"{self.name} was unreachable.", kind=kind, provider=self.name
            ) from exc
        except ValueError as exc:
            # json() on a body that is not JSON. Treated as a provider fault,
            # not a bug here, so the chain may try the next one.
            raise LLMProviderError(
                f"{self.name} returned a body that was not valid JSON.",
                kind="unknown",
                provider=self.name,
            ) from exc


class GeminiProvider(_HTTPProviderBase):
    """Adapter for Google Generative Language ``generateContent``."""

    name = "gemini"

    async def generate(self, request: LLMRequest) -> LLMResponse:
        """Run one completion.

        Args:
            request: Prompt, optional system instruction, and PII tier.

        Returns:
            The model's answer with token usage attached.

        Raises:
            LLMRefusalError: If the prompt was blocked or the candidate was cut
                for safety.
            LLMProviderError: On any transport or protocol failure, and when
                the response carries no candidate at all — an empty string
                would otherwise be scored as if the model had answered.
        """
        generation_config: dict[str, Any] = {"temperature": 0.0}
        if request.max_output_tokens is not None:
            generation_config["maxOutputTokens"] = request.max_output_tokens

        payload: dict[str, Any] = {
            "contents": [{"role": "user", "parts": [{"text": request.prompt}]}],
            # Temperature is pinned, not passed through. A screening score that
            # changed between runs on identical input would not be defensible.
            "generationConfig": generation_config,
        }
        if request.system is not None:
            # Sent on its own channel. Folding it into `contents` would let
            # resume text sit at the same level of authority as our own
            # instructions.
            payload["systemInstruction"] = {"parts": [{"text": request.system}]}

        body = await self._post(
            f"{_GEMINI_BASE_URL}/models/{self.model}:generateContent",
            headers={"x-goog-api-key": self._api_key, "content-type": "application/json"},
            payload=payload,
        )

        block_reason = (body.get("promptFeedback") or {}).get("blockReason")
        if block_reason:
            raise LLMRefusalError(f"Gemini blocked the prompt ({block_reason}).")

        candidates = body.get("candidates") or []
        if not candidates:
            raise LLMProviderError(
                "Gemini returned no candidate.", kind="unknown", provider=self.name
            )

        finish_reason = candidates[0].get("finishReason")
        if finish_reason in _GEMINI_REFUSALS:
            raise LLMRefusalError(f"Gemini stopped generating ({finish_reason}).")

        parts = (candidates[0].get("content") or {}).get("parts") or []
        text = "".join(part.get("text", "") for part in parts)

        usage = body.get("usageMetadata") or {}
        return LLMResponse(
            text=text,
            model=self.model,
            provider=self.name,
            prompt_tokens=int(usage.get("promptTokenCount", 0)),
            completion_tokens=int(usage.get("candidatesTokenCount", 0)),
        )


class GroqProvider(_HTTPProviderBase):
    """Adapter for Groq's OpenAI-compatible chat completions."""

    name = "groq"

    async def generate(self, request: LLMRequest) -> LLMResponse:
        """Run one completion.

        Args:
            request: Prompt, optional system instruction, and PII tier.

        Returns:
            The model's answer with token usage attached.

        Raises:
            LLMRefusalError: If generation stopped on a content filter.
            LLMProviderError: On any transport or protocol failure, and when
                the response carries no choice.
        """
        messages: list[dict[str, str]] = []
        if request.system is not None:
            messages.append({"role": "system", "content": request.system})
        messages.append({"role": "user", "content": request.prompt})

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.0,
        }
        if request.max_output_tokens is not None:
            payload["max_tokens"] = request.max_output_tokens

        body = await self._post(
            _GROQ_URL,
            headers={
                "authorization": f"Bearer {self._api_key}",
                "content-type": "application/json",
            },
            payload=payload,
        )

        choices = body.get("choices") or []
        if not choices:
            raise LLMProviderError("Groq returned no choice.", kind="unknown", provider=self.name)

        finish_reason = choices[0].get("finish_reason")
        if finish_reason in _GROQ_REFUSALS:
            raise LLMRefusalError(f"Groq stopped generating ({finish_reason}).")

        text = (choices[0].get("message") or {}).get("content") or ""

        usage = body.get("usage") or {}
        return LLMResponse(
            text=text,
            model=self.model,
            provider=self.name,
            prompt_tokens=int(usage.get("prompt_tokens", 0)),
            completion_tokens=int(usage.get("completion_tokens", 0)),
        )
