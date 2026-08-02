"""Provider layer: error classification, adapters, failover, and tier enforcement.

Every test here runs against an `httpx.MockTransport`. Nothing reaches the
network, so the suite stays fast, free, and deterministic. What these tests
prove is the *wiring*: that a 429 becomes a reschedulable `rate_limit` rather
than a hard failure, that a T2 request never leaves our infrastructure, and
that an API key never appears in a URL, a log, or a repr.

What they deliberately do *not* prove is that a real model returns usable
output. That belongs in the live contract tests, which are marked `live` and
excluded from the default run.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from app.agents.base import FailoverChain, LLMRequest, LLMResponse
from app.agents.classifier import classify_provider_error
from app.agents.providers import GeminiProvider, GroqProvider
from app.config import Settings
from app.exceptions import (
    BudgetExceededError,
    LLMProviderError,
    LLMRefusalError,
    NoEligibleProviderError,
    TalentLensError,
)

FAKE_GOOGLE_KEY = "AIzaSy-not-a-real-key-000000000000000000"
FAKE_GROQ_KEY = "gsk_not_a_real_key_0000000000000000000000000000000000"


def _gemini_ok(
    text: str = "hello", *, prompt_tokens: int = 11, out_tokens: int = 3
) -> dict[str, Any]:
    """Build a minimal successful Gemini `generateContent` body."""
    return {
        "candidates": [
            {"content": {"parts": [{"text": text}]}, "finishReason": "STOP"},
        ],
        "usageMetadata": {
            "promptTokenCount": prompt_tokens,
            "candidatesTokenCount": out_tokens,
        },
    }


def _groq_ok(
    text: str = "hello", *, prompt_tokens: int = 11, out_tokens: int = 3
) -> dict[str, Any]:
    """Build a minimal successful Groq chat-completions body."""
    return {
        "choices": [{"message": {"content": text}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": out_tokens},
    }


def _transport(handler: Any) -> httpx.MockTransport:
    """Wrap a request handler in a mock transport."""
    return httpx.MockTransport(handler)


def _always(status: int, body: Any) -> httpx.MockTransport:
    """Return a transport that answers every request identically."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=body)

    return _transport(handler)


def _gemini(transport: httpx.MockTransport, **kwargs: Any) -> GeminiProvider:
    """Construct a Gemini provider bound to a mock transport."""
    return GeminiProvider(
        api_key=FAKE_GOOGLE_KEY, model="gemini-test", transport=transport, **kwargs
    )


def _groq(transport: httpx.MockTransport, **kwargs: Any) -> GroqProvider:
    """Construct a Groq provider bound to a mock transport."""
    return GroqProvider(api_key=FAKE_GROQ_KEY, model="groq-test", transport=transport, **kwargs)


# ---------------------------------------------------------------------------
# Error classification
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (429, "rate_limit"),
        (401, "auth"),
        (403, "auth"),
        (404, "model_unavailable"),
        (500, "unknown"),
        (503, "model_unavailable"),
    ],
)
def test_http_status_maps_to_the_documented_kind(status: int, expected: str) -> None:
    response = httpx.Response(status, request=httpx.Request("POST", "https://x/y"))
    exc = httpx.HTTPStatusError("boom", request=response.request, response=response)

    assert classify_provider_error(exc) == expected


def test_a_context_length_complaint_is_classified_as_context_not_unknown() -> None:
    request = httpx.Request("POST", "https://x/y")
    response = httpx.Response(
        400,
        json={"error": {"message": "input token count exceeds the maximum context length"}},
        request=request,
    )
    exc = httpx.HTTPStatusError("boom", request=request, response=response)

    assert classify_provider_error(exc) == "context"


def test_a_plain_400_without_a_context_hint_is_unknown() -> None:
    request = httpx.Request("POST", "https://x/y")
    response = httpx.Response(400, json={"error": {"message": "malformed field"}}, request=request)
    exc = httpx.HTTPStatusError("boom", request=request, response=response)

    assert classify_provider_error(exc) == "unknown"


def test_a_connect_error_is_network() -> None:
    assert classify_provider_error(httpx.ConnectError("refused")) == "network"


def test_a_timeout_is_network() -> None:
    assert classify_provider_error(httpx.ReadTimeout("slow")) == "network"


def test_an_unrecognised_exception_is_unknown_rather_than_raising() -> None:
    assert classify_provider_error(ValueError("???")) == "unknown"


def test_an_unmapped_5xx_is_model_unavailable_so_the_chain_still_falls_over() -> None:
    request = httpx.Request("POST", "https://x/y")
    response = httpx.Response(507, request=request)
    exc = httpx.HTTPStatusError("boom", request=request, response=response)

    assert classify_provider_error(exc) == "model_unavailable"


def test_an_unmapped_4xx_is_unknown() -> None:
    request = httpx.Request("POST", "https://x/y")
    response = httpx.Response(418, request=request)
    exc = httpx.HTTPStatusError("boom", request=request, response=response)

    assert classify_provider_error(exc) == "unknown"


def test_a_protocol_error_is_network_because_it_is_still_transport() -> None:
    assert classify_provider_error(httpx.ProtocolError("bad framing")) == "network"


def test_an_unread_body_does_not_crash_the_context_check() -> None:
    """A streamed 400 must classify, not raise, when its body was never read."""

    class _Unread(httpx.SyncByteStream):
        def __iter__(self) -> Any:
            yield b"context length exceeded"

    request = httpx.Request("POST", "https://x/y")
    response = httpx.Response(400, stream=_Unread(), request=request)
    exc = httpx.HTTPStatusError("boom", request=request, response=response)

    # Falls back to the status mapping rather than propagating ResponseNotRead.
    assert classify_provider_error(exc) == "unknown"


# ---------------------------------------------------------------------------
# Exception contracts
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("exc_type", "status", "code"),
    [
        (LLMRefusalError, 422, "LLM_REFUSAL"),
        (NoEligibleProviderError, 503, "NO_ELIGIBLE_PROVIDER"),
        (BudgetExceededError, 429, "BUDGET_EXCEEDED"),
    ],
)
def test_each_new_exception_carries_its_documented_status_and_code(
    exc_type: type[TalentLensError], status: int, code: str
) -> None:
    assert exc_type.status_code == status
    assert exc_type.error_code == code
    assert issubclass(exc_type, TalentLensError)


def test_a_provider_error_remembers_which_kind_it_was() -> None:
    exc = LLMProviderError("upstream said no", kind="rate_limit", provider="gemini")

    assert exc.kind == "rate_limit"
    assert exc.provider == "gemini"


# ---------------------------------------------------------------------------
# Gemini adapter
# ---------------------------------------------------------------------------


async def test_gemini_returns_the_text_the_model_produced() -> None:
    provider = _gemini(_always(200, _gemini_ok("42")))

    result = await provider.generate(LLMRequest(prompt="what is six times seven"))

    assert isinstance(result, LLMResponse)
    assert result.text == "42"
    assert result.provider == "gemini"
    assert result.model == "gemini-test"


async def test_gemini_reports_token_usage_for_the_ledger() -> None:
    provider = _gemini(_always(200, _gemini_ok(prompt_tokens=120, out_tokens=7)))

    result = await provider.generate(LLMRequest(prompt="x"))

    assert result.prompt_tokens == 120
    assert result.completion_tokens == 7


async def test_gemini_sends_the_key_in_a_header_never_in_the_url() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["header"] = request.headers.get("x-goog-api-key")
        return httpx.Response(200, json=_gemini_ok())

    await _gemini(_transport(handler)).generate(LLMRequest(prompt="x"))

    assert seen["header"] == FAKE_GOOGLE_KEY
    assert FAKE_GOOGLE_KEY not in seen["url"]


async def test_gemini_pins_temperature_to_zero_for_reproducibility() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=_gemini_ok())

    await _gemini(_transport(handler)).generate(LLMRequest(prompt="x"))

    assert seen["body"]["generationConfig"]["temperature"] == 0.0


async def test_gemini_forwards_the_system_instruction_separately_from_the_prompt() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=_gemini_ok())

    await _gemini(_transport(handler)).generate(
        LLMRequest(prompt="user text", system="you are a judge")
    )

    body = seen["body"]
    assert "you are a judge" in json.dumps(body["systemInstruction"])
    assert "you are a judge" not in json.dumps(body["contents"])


async def test_gemini_raises_a_refusal_when_the_prompt_is_blocked() -> None:
    body = {"promptFeedback": {"blockReason": "SAFETY"}, "candidates": []}
    provider = _gemini(_always(200, body))

    with pytest.raises(LLMRefusalError):
        await provider.generate(LLMRequest(prompt="x"))


async def test_gemini_raises_a_refusal_when_the_candidate_is_cut_for_safety() -> None:
    body = {"candidates": [{"finishReason": "SAFETY", "content": {"parts": []}}]}
    provider = _gemini(_always(200, body))

    with pytest.raises(LLMRefusalError):
        await provider.generate(LLMRequest(prompt="x"))


async def test_gemini_turns_a_429_into_a_classified_provider_error() -> None:
    provider = _gemini(_always(429, {"error": {"message": "quota"}}))

    with pytest.raises(LLMProviderError) as excinfo:
        await provider.generate(LLMRequest(prompt="x"))

    assert excinfo.value.kind == "rate_limit"


async def test_gemini_never_leaks_the_key_in_its_error_message() -> None:
    provider = _gemini(_always(401, {"error": {"message": "bad key"}}))

    with pytest.raises(LLMProviderError) as excinfo:
        await provider.generate(LLMRequest(prompt="x"))

    assert FAKE_GOOGLE_KEY not in str(excinfo.value)


async def test_an_empty_candidate_list_is_a_provider_error_not_an_empty_string() -> None:
    provider = _gemini(_always(200, {"candidates": []}))

    with pytest.raises(LLMProviderError):
        await provider.generate(LLMRequest(prompt="x"))


# ---------------------------------------------------------------------------
# Groq adapter
# ---------------------------------------------------------------------------


async def test_groq_returns_the_text_the_model_produced() -> None:
    provider = _groq(_always(200, _groq_ok("ok")))

    result = await provider.generate(LLMRequest(prompt="x"))

    assert result.text == "ok"
    assert result.provider == "groq"


async def test_groq_authenticates_with_a_bearer_header() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization")
        seen["url"] = str(request.url)
        return httpx.Response(200, json=_groq_ok())

    await _groq(_transport(handler)).generate(LLMRequest(prompt="x"))

    assert seen["auth"] == f"Bearer {FAKE_GROQ_KEY}"
    assert FAKE_GROQ_KEY not in seen["url"]


async def test_groq_pins_temperature_to_zero() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=_groq_ok())

    await _groq(_transport(handler)).generate(LLMRequest(prompt="x"))

    assert seen["body"]["temperature"] == 0.0


async def test_groq_raises_a_refusal_on_a_content_filter_finish() -> None:
    body = {
        "choices": [{"message": {"content": ""}, "finish_reason": "content_filter"}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 0},
    }
    provider = _groq(_always(200, body))

    with pytest.raises(LLMRefusalError):
        await provider.generate(LLMRequest(prompt="x"))


async def test_groq_turns_a_429_into_a_rate_limit_kind() -> None:
    provider = _groq(_always(429, {"error": {"message": "slow down"}}))

    with pytest.raises(LLMProviderError) as excinfo:
        await provider.generate(LLMRequest(prompt="x"))

    assert excinfo.value.kind == "rate_limit"


async def test_groq_sends_the_system_instruction_as_a_system_role_message() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=_groq_ok())

    await _groq(_transport(handler)).generate(
        LLMRequest(prompt="user text", system="you are a judge")
    )

    messages = seen["body"]["messages"]
    assert messages[0] == {"role": "system", "content": "you are a judge"}
    assert messages[1] == {"role": "user", "content": "user text"}


async def test_an_empty_choice_list_is_a_provider_error_not_an_empty_string() -> None:
    provider = _groq(_always(200, {"choices": [], "usage": {}}))

    with pytest.raises(LLMProviderError):
        await provider.generate(LLMRequest(prompt="x"))


# ---------------------------------------------------------------------------
# Transport failures
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("build", [_gemini, _groq])
async def test_a_connection_failure_becomes_a_network_kind_so_the_chain_can_fall_over(
    build: Any,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(LLMProviderError) as excinfo:
        await build(_transport(handler)).generate(LLMRequest(prompt="x"))

    assert excinfo.value.kind == "network"


@pytest.mark.parametrize("build", [_gemini, _groq])
async def test_a_timeout_becomes_a_network_kind(build: Any) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(LLMProviderError) as excinfo:
        await build(_transport(handler)).generate(LLMRequest(prompt="x"))

    assert excinfo.value.kind == "network"


@pytest.mark.parametrize("build", [_gemini, _groq])
async def test_a_body_that_is_not_json_is_a_provider_error_rather_than_a_crash(
    build: Any,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"<html>gateway</html>")

    with pytest.raises(LLMProviderError):
        await build(_transport(handler)).generate(LLMRequest(prompt="x"))


@pytest.mark.parametrize("build", [_gemini, _groq])
async def test_a_transport_failure_message_names_the_provider_but_not_the_key(
    build: Any,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(LLMProviderError) as excinfo:
        await build(_transport(handler)).generate(LLMRequest(prompt="x"))

    rendered = str(excinfo.value)
    assert FAKE_GOOGLE_KEY not in rendered
    assert FAKE_GROQ_KEY not in rendered


# ---------------------------------------------------------------------------
# Output ceiling
# ---------------------------------------------------------------------------


async def test_gemini_forwards_an_output_ceiling_when_one_is_requested() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=_gemini_ok())

    await _gemini(_transport(handler)).generate(LLMRequest(prompt="x", max_output_tokens=256))

    assert seen["body"]["generationConfig"]["maxOutputTokens"] == 256


async def test_groq_forwards_an_output_ceiling_when_one_is_requested() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=_groq_ok())

    await _groq(_transport(handler)).generate(LLMRequest(prompt="x", max_output_tokens=256))

    assert seen["body"]["max_tokens"] == 256


# ---------------------------------------------------------------------------
# Secret hygiene
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("build", [_gemini, _groq])
def test_a_provider_repr_does_not_contain_its_api_key(build: Any) -> None:
    provider = build(_always(200, {}))

    rendered = f"{provider!r} {provider}"

    assert FAKE_GOOGLE_KEY not in rendered
    assert FAKE_GROQ_KEY not in rendered


# ---------------------------------------------------------------------------
# Failover chain
# ---------------------------------------------------------------------------


class _StubProvider:
    """A provider that replays a scripted sequence of outcomes."""

    def __init__(self, name: str, outcomes: list[Any], tiers: frozenset[str] | None = None) -> None:
        """Record the script and the tiers this stub is allowed to serve."""
        self.name = name
        self.model = f"{name}-model"
        self.tiers = tiers if tiers is not None else frozenset({"T0", "T1"})
        self._outcomes = list(outcomes)
        self.calls = 0

    async def generate(self, request: LLMRequest) -> LLMResponse:
        """Return or raise the next scripted outcome."""
        self.calls += 1
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _ok(provider: str = "stub") -> LLMResponse:
    """Build a successful response attributed to `provider`."""
    return LLMResponse(
        text="ok",
        model=f"{provider}-model",
        provider=provider,
        prompt_tokens=1,
        completion_tokens=1,
    )


async def test_the_chain_uses_the_first_provider_when_it_succeeds() -> None:
    first = _StubProvider("a", [_ok("a")])
    second = _StubProvider("b", [_ok("b")])

    result = await FailoverChain([first, second]).generate(LLMRequest(prompt="x"))

    assert result.provider == "a"
    assert second.calls == 0


async def test_a_rate_limited_primary_falls_through_to_the_secondary() -> None:
    first = _StubProvider("a", [LLMProviderError("429", kind="rate_limit", provider="a")])
    second = _StubProvider("b", [_ok("b")])

    result = await FailoverChain([first, second]).generate(LLMRequest(prompt="x"))

    assert result.provider == "b"
    assert first.calls == 1


async def test_a_network_failure_falls_through_to_the_secondary() -> None:
    first = _StubProvider("a", [LLMProviderError("down", kind="network", provider="a")])
    second = _StubProvider("b", [_ok("b")])

    result = await FailoverChain([first, second]).generate(LLMRequest(prompt="x"))

    assert result.provider == "b"


async def test_a_refusal_stops_the_chain_and_is_not_retried_elsewhere() -> None:
    first = _StubProvider("a", [LLMRefusalError("policy")])
    second = _StubProvider("b", [_ok("b")])

    with pytest.raises(LLMRefusalError):
        await FailoverChain([first, second]).generate(LLMRequest(prompt="x"))

    assert second.calls == 0


async def test_a_context_overflow_stops_the_chain_because_a_retry_cannot_help() -> None:
    first = _StubProvider("a", [LLMProviderError("too long", kind="context", provider="a")])
    second = _StubProvider("b", [_ok("b")])

    with pytest.raises(LLMProviderError):
        await FailoverChain([first, second]).generate(LLMRequest(prompt="x"))

    assert second.calls == 0


async def test_when_every_provider_fails_the_chain_raises_no_eligible_provider() -> None:
    first = _StubProvider("a", [LLMProviderError("429", kind="rate_limit", provider="a")])
    second = _StubProvider("b", [LLMProviderError("down", kind="network", provider="b")])

    with pytest.raises(NoEligibleProviderError):
        await FailoverChain([first, second]).generate(LLMRequest(prompt="x"))


async def test_an_empty_chain_raises_rather_than_returning_nothing() -> None:
    with pytest.raises(NoEligibleProviderError):
        await FailoverChain([]).generate(LLMRequest(prompt="x"))


# ---------------------------------------------------------------------------
# PII tier enforcement
# ---------------------------------------------------------------------------


async def test_a_t2_request_never_reaches_a_cloud_provider() -> None:
    cloud = _StubProvider("gemini", [_ok("gemini")], tiers=frozenset({"T0", "T1"}))

    with pytest.raises(NoEligibleProviderError):
        await FailoverChain([cloud]).generate(LLMRequest(prompt="full CV", pii_tier="T2"))

    assert cloud.calls == 0


async def test_a_t2_request_is_served_by_a_provider_that_declares_t2() -> None:
    cloud = _StubProvider("gemini", [_ok("gemini")], tiers=frozenset({"T0", "T1"}))
    dedicated = _StubProvider("hf", [_ok("hf")], tiers=frozenset({"T0", "T1", "T2"}))

    result = await FailoverChain([cloud, dedicated]).generate(
        LLMRequest(prompt="full CV", pii_tier="T2")
    )

    assert result.provider == "hf"
    assert cloud.calls == 0


async def test_the_tier_refusal_message_does_not_echo_the_prompt() -> None:
    cloud = _StubProvider("gemini", [_ok("gemini")], tiers=frozenset({"T0", "T1"}))
    secret = "Budi Santoso, budi@example.com, +62 812 3456 7890"

    with pytest.raises(NoEligibleProviderError) as excinfo:
        await FailoverChain([cloud]).generate(LLMRequest(prompt=secret, pii_tier="T2"))

    assert secret not in str(excinfo.value)
    assert "budi@example.com" not in str(excinfo.value)


def test_an_unknown_tier_is_rejected_when_the_request_is_built() -> None:
    with pytest.raises(ValueError, match="pii_tier"):
        LLMRequest(prompt="x", pii_tier="T9")


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def test_provider_keys_default_to_empty_so_a_dev_box_still_boots() -> None:
    settings = Settings(
        _env_file=None, database_url="postgresql+asyncpg://x/y", jwt_secret="s" * 32
    )

    assert settings.google_api_key == ""
    assert settings.groq_api_key == ""


def test_model_ids_live_in_config_so_a_deprecation_is_a_config_change() -> None:
    settings = Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://x/y",
        jwt_secret="s" * 32,
        gemini_model="gemini-9-experimental",
    )

    assert settings.gemini_model == "gemini-9-experimental"


def test_llm_temperature_defaults_to_zero() -> None:
    settings = Settings(
        _env_file=None, database_url="postgresql+asyncpg://x/y", jwt_secret="s" * 32
    )

    assert settings.llm_temperature == 0.0
