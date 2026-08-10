"""HF Inference API provider — free-tier, T2-capable.

Uses HuggingFace's free Serverless Inference API. OpenAI-compatible
chat completions endpoint. Accepts T2 (full PII) because HF's free
tier does NOT train on user API data.

Endpoint: https://api-inference.huggingface.co/models/{model}/v1/chat/completions
Docs: https://huggingface.co/docs/api-inference/tasks/chat-completion
"""

from __future__ import annotations

from typing import Any, Final

import httpx

from app.agents.base import LLMRequest, LLMResponse
from app.agents.classifier import classify_provider_error
from app.exceptions import LLMProviderError, LLMRefusalError

_HF_API_URL: Final = "https://api-inference.huggingface.co/models"

# HF free tier: no training on user data, so T2 is acceptable.
# This is the key difference from Gemini/Groq free tiers.
_HF_TIERS: Final[frozenset[str]] = frozenset({"T0", "T1", "T2"})
_HF_REFUSALS: Final[frozenset[str]] = frozenset({"content_filter", "length"})
_DEFAULT_TIMEOUT: Final = 90.0  # HF free tier can be slow


class HFProvider:
    """Adapter for HuggingFace Serverless Inference API.

    Uses the OpenAI-compatible chat completions endpoint. Token counts
    are estimated when the API doesn't return them.
    """

    name = "hf"
    model: str
    tiers: frozenset[str]

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        self._api_key = api_key
        self.model = model
        self.tiers = _HF_TIERS
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None

    def __repr__(self) -> str:
        return f"<HFProvider model={self.model!r}>"

    __str__ = __repr__

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout)
        return self._client

    async def generate(self, request: LLMRequest) -> LLMResponse:
        """Run one completion via HF Inference API.

        Returns:
            LLMResponse with estimated token counts.
        """
        messages: list[dict[str, str]] = []
        if request.system:
            messages.append({"role": "system", "content": request.system})
        messages.append({"role": "user", "content": request.prompt})

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.0,
            "max_tokens": request.max_output_tokens or 2048,
        }

        url = f"{_HF_API_URL}/{self.model}/v1/chat/completions"
        client = await self._get_client()

        try:
            response = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
            body = response.json()
        except httpx.HTTPStatusError as exc:
            kind = classify_provider_error(exc)
            if exc.response.status_code == 429:
                raise LLMProviderError(
                    "HF rate limited. Retry after cooldown.",
                    kind="rate_limit",
                    provider=self.name,
                ) from exc
            raise LLMProviderError(
                f"HF returned HTTP {exc.response.status_code}.",
                kind=kind,
                provider=self.name,
            ) from exc
        except httpx.HTTPError as exc:
            raise LLMProviderError(
                "HF was unreachable.", kind="network", provider=self.name
            ) from exc

        choices = body.get("choices") or []
        if not choices:
            raise LLMProviderError(
                "HF returned no choice.", kind="unknown", provider=self.name
            )

        finish_reason = choices[0].get("finish_reason", "")
        if finish_reason in _HF_REFUSALS:
            raise LLMRefusalError(
                f"HF stopped generating ({finish_reason})."
            )

        text = (choices[0].get("message") or {}).get("content") or ""

        usage = body.get("usage") or {}
        prompt_tokens = int(usage.get("prompt_tokens", 0))
        completion_tokens = int(usage.get("completion_tokens", 0))

        # Estimate when API doesn't return usage (free tier sometimes omits)
        if not prompt_tokens:
            prompt_tokens = len(request.prompt) // 4
        if not completion_tokens:
            completion_tokens = len(text) // 4

        return LLMResponse(
            text=text,
            model=self.model,
            provider=self.name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )
