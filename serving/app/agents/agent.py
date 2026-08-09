"""Agent base classes — the uniform contract all 14 agents implement.

``Agent`` is what the orchestrator calls. Two concrete base classes sit under it:
``DeterministicAgent`` (no LLM — CV Parser, OCR, ATS Scoring) and ``LLMAgent``
(owns prompt assembly, repair-retry, refusal detection, token ledger, cache).
Both implement the same interface, so the orchestrator calls ``await agent.run()``
uniformly whether tokens are involved or not.

Every agent's ``run()`` receives all data via ``payload`` — no agent imports
``repositories/``. All LLM keys, provider secrets, and PII-gating logic live
in ``agents/base.py`` (provider layer), not here.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import ClassVar, Generic, Literal, TypeVar
from uuid import UUID

from pydantic import BaseModel

TIn = TypeVar("TIn", bound=BaseModel)
TOut = TypeVar("TOut", bound=BaseModel)
PiiTier = Literal["T0", "T1", "T2"]


class AgentContext(BaseModel):
    """Immutable per-invocation context passed to every agent.

    Carries identity, tenancy, and policy only — never business data.
    Business data flows exclusively through the typed ``payload`` argument
    to ``Agent.run``.

    Attributes:
        request_id: Correlates this invocation across logs, traces, and
            the ``llm_invocations`` ledger row it writes.
        tenant_id: Owning tenant; used for cache scoping and RLS context.
        run_id: Parent screening run, if this call is part of one.
        pii_tier: Resolved tier this payload is allowed to reach. Set by
            the calling service, asserted (not trusted) by the adapter.
        idempotency_key: Stable across retries of the same logical unit
            of work, so a retried invocation cannot double-write or
            double-bill the token ledger.
        deadline: Wall-clock cutoff this invocation must respect.
    """

    request_id: UUID
    tenant_id: UUID
    run_id: UUID | None = None
    pii_tier: PiiTier = "T1"
    idempotency_key: str = ""
    deadline: datetime | None = None


class AgentResult(BaseModel, Generic[TOut]):
    """Uniform result envelope every agent invocation returns.

    Attributes:
        status: ``ok`` — use ``output`` as-is. ``degraded`` — ``output`` may be
            partial or absent; caller surfaces a caveat. ``failed`` —
            ``output`` is ``None``; caller applies this agent's failure policy.
        cache_hit: ``True`` if served from ``agent_result_cache`` with zero
            LLM spend.
    """

    output: TOut | None = None
    status: Literal["ok", "degraded", "failed"] = "ok"
    agent_name: str = ""
    agent_version: str = ""
    prompt_version: str | None = None
    model: str | None = None
    provider: str | None = None
    cache_hit: bool = False
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    warnings: list[str] = []


class Agent(ABC, Generic[TIn, TOut]):
    """Base contract implemented by all agents, LLM-backed or not.

    Subclasses declare identity and capability metadata as class
    variables so the orchestrator can validate DAG wiring without
    hardcoding per-agent knowledge. ``run`` must not import from
    ``repositories/`` — all data it needs arrives via ``payload``.
    """

    name: ClassVar[str]
    version: ClassVar[str]
    requires_llm: ClassVar[bool]
    pii_tier: ClassVar[PiiTier] = "T1"
    requires: ClassVar[frozenset[str]] = frozenset()
    produces: ClassVar[frozenset[str]] = frozenset()

    @abstractmethod
    async def run(self, payload: TIn, ctx: AgentContext) -> AgentResult[TOut]:
        """Execute the agent once.

        Raises:
            OutputParseError: Structured output failed validation after
                the repair prompt.
            LLMRefusalError: The provider declined the request.
            LLMProviderError: Unrecoverable upstream failure after
                retry/failover exhaustion.
        """
        ...


class DeterministicAgent(Agent[TIn, TOut], ABC):
    """Base for agents that need no LLM — CV Parser, OCR, ATS Scoring.

    No prompt assembly, no provider calls, no token ledger. Deterministic
    by construction: same input → same output every time.
    """

    requires_llm: ClassVar[bool] = False
    pii_tier: ClassVar[PiiTier] = "T0"


class LLMAgent(Agent[TIn, TOut], ABC):
    """Base for agents that call an LLM provider.

    Owns: prompt assembly with stable cached prefix, repair-retry loop,
    refusal detection, token-ledger recording, OTel spans. Subclasses
    implement ``build_request()`` and ``parse_response()`` — the base
    class owns the retry/cache/record lifecycle.
    """

    requires_llm: ClassVar[bool] = True
    prompt_version: ClassVar[str]

    @abstractmethod
    def build_request(self, payload: TIn, ctx: AgentContext) -> "LLMRequest":  # noqa: F821  — circular with base.py
        """Build the provider request from typed payload and context.

        The system prompt / rubric prefix is stable and cacheable.
        Evidence is volatile suffix inside ``<candidate_evidence untrusted="true">``.
        """
        ...

    @abstractmethod
    def parse_response(self, text: str, payload: TIn) -> TOut:
        """Validate and structure the raw provider answer.

        Raises:
            OutputParseError: If the answer cannot be parsed. The base
                class runs one repair-prompt retry before propagating.
        """
        ...


class OutputParseError(Exception):
    """Structured-output validation failed after the repair attempt."""
