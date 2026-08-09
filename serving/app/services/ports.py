"""Ports — enterprise-scale seams (ARCHITECTURE-AGENTS.md §2.3).

Every port has exactly one default adapter today. Adding Temporal, S3, or
Upstash later is a new file plus a config flip — the domain code calls the
port, not the implementation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol, runtime_checkable
from uuid import UUID

if TYPE_CHECKING:
    from app.agents.agent import AgentResult
    from app.agents.base import LLMRequest, LLMResponse
    from app.models import RunTask


class WorkflowRunner(Protocol):
    """Durable execution port. Default: InProcessWorkflowRunner.
    Swap-in: TemporalWorkflowRunner, unchanged call sites in services/."""

    async def enqueue(self, run_id: UUID, stage: str, tasks: list[dict]) -> None: ...

    async def drain(self, run_id: UUID, budget_seconds: float) -> DrainResult: ...

    async def resume_stale(self, older_than_seconds: int) -> list[UUID]: ...


@runtime_checkable
class Queue(Protocol):
    """Default: Postgres SKIP LOCKED. Swap-in: Upstash Redis / SQS."""

    async def claim(
        self, run_id: UUID, stage: str, limit: int
    ) -> list[RunTask]: ...

    async def complete(self, task_id: int, result: dict) -> None: ...

    async def fail(self, task_id: int, error: str) -> None: ...


@runtime_checkable
class LLMProvider(Protocol):
    """Default: prefix-routed Gemini/Groq/hf: adapters."""

    name: str
    model: str
    tiers: frozenset[str]

    async def generate(self, request: LLMRequest) -> LLMResponse: ...


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Default: in-process ONNX e5-small. Swap-in: hosted TEI/bge-m3."""

    async def embed(self, texts: list[str]) -> list[list[float]]: ...


@dataclass
class DrainResult:
    """Summary of one drain cycle."""

    stage: str
    attempted: int = 0
    completed: int = 0
    failed: int = 0
    rescheduled: int = 0


@dataclass
class StageOutcome:
    """Result of running one DAG stage."""

    stage: str
    attempted: int = 0
    completed: int = 0
    failed: int = 0
    details: list[dict] = field(default_factory=list)
