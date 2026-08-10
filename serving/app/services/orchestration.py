"""In-process orchestrator — coordinates agent invocations along fixed
per-pipeline stage lists (ARCHITECTURE-AGENTS.md §2.4).

Owns: sequencing, concurrency bounds, checkpointing, cancellation.
Does NOT own: prompts, scoring formula, retrieval algorithms, business rules.
Calls agents as opaque stages; knows nothing about their internals.

CORE stages (parse, extract, recall, rerank, judge, aggregate): a failure
aborts the run — a silently incomplete verdict set is worse than no score.

INSIGHT stages (gap, interview, recommend, bias, fraud): a failure degrades
the run — the score remains valid, insight is marked unavailable.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass
from typing import Final

from app.agents.agent import Agent, AgentContext
from app.models import RunTask as RunTaskModel
from app.services.ports import DrainResult, StageOutcome

# --------------------------------------------------------------------------- #
# Stage classification                                                        #
# --------------------------------------------------------------------------- #

CORE_STAGES: Final[frozenset[str]] = frozenset(
    {"parse", "extract", "recall", "rerank", "judge", "aggregate"}
)
INSIGHT_STAGES: Final[frozenset[str]] = frozenset(
    {"gap", "interview", "recommend", "bias", "fraud"}
)
CHAT_STAGES: Final[frozenset[str]] = frozenset({"chat"})

ALL_STAGES: Final[frozenset[str]] = CORE_STAGES | INSIGHT_STAGES | CHAT_STAGES


# --------------------------------------------------------------------------- #
# Agent registry                                                              #
# --------------------------------------------------------------------------- #


class AgentRegistry:
    """Maps versioned agent names to classes. New agents register here
    and nowhere else — the orchestrator never imports a concrete agent
    class directly.

    Keys are ``{name}@{version}`` (e.g. ``semantic_matching@1.0.0``).
    """

    def __init__(self) -> None:
        self._agents: dict[str, type[Agent]] = {}

    def register(self, agent_cls: type[Agent]) -> None:
        key = f"{agent_cls.name}@{agent_cls.version}"
        self._agents[key] = agent_cls

    def resolve(self, name: str, version: str = "") -> Agent:
        if version:
            key = f"{name}@{version}"
            if key in self._agents:
                return self._agents[key]()
        # Find latest version of named agent
        matching = sorted(
            (k for k in self._agents if k.startswith(f"{name}@")),
            reverse=True,
        )
        if matching:
            return self._agents[matching[0]]()
        raise KeyError(f"Agent '{name}' not found in registry")

    def list_agents(self) -> list[str]:
        return sorted(self._agents)


# --------------------------------------------------------------------------- #
# Orchestrator                                                                #
# --------------------------------------------------------------------------- #


@dataclass
class Orchestrator:
    """Coordinates agent invocations along fixed per-pipeline stage lists.

    Deliberately not a general workflow engine: stage order is a Python
    list per pipeline, not derived from a graph solver. Capability
    declarations (``Agent.requires``/``produces``) are used only to
    validate that hardcoded wiring is internally consistent, never to
    infer it at runtime.
    """

    registry: AgentRegistry
    max_concurrency: int = 16

    async def run_stage(
        self,
        *,
        run_id: uuid.UUID,
        stage: str,
        tasks: list[RunTaskModel],
        tenant_id: uuid.UUID,
    ) -> StageOutcome:
        """Drain pending tasks for one DAG stage.

        Bounded by a semaphore (provider/tenant fairness) and dispatched
        via ``asyncio.TaskGroup`` for CORE stages so one task's exception
        cancels remaining siblings. INSIGHT stages use ``asyncio.gather``
        with ``return_exceptions=True`` — one insight failure does not
        abort its siblings.

        Args:
            run_id: Parent screening run.
            stage: Stage name (parse, judge, gap, etc.).
            tasks: Claimed ``RunTask`` rows to execute.
            tenant_id: Owning tenant for context.

        Returns:
            ``StageOutcome`` with counts and per-task details.
        """
        if not tasks:
            return StageOutcome(stage=stage, attempted=0)

        semaphore = asyncio.Semaphore(self.max_concurrency)
        details: list[dict] = []

        async def _run_one(task: RunTaskModel) -> None:
            async with semaphore:
                agent = self.registry.resolve(task.agent_name)
                ctx = AgentContext(
                    request_id=uuid.uuid4(),
                    tenant_id=tenant_id,
                    run_id=run_id,
                    pii_tier=agent.pii_tier,
                    idempotency_key=f"{run_id}:{task.id}",
                )
                result = await agent.run(task.payload, ctx)
                details.append(
                    {
                        "task_id": task.id,
                        "agent": agent.name,
                        "status": result.status,
                        "cache_hit": result.cache_hit,
                    }
                )
                if result.status == "failed" and stage in CORE_STAGES:
                    raise CoreStageFailedError(
                        f"Core stage '{stage}' failed for task {task.id}"
                    )

        if stage in CORE_STAGES:
            async with asyncio.TaskGroup() as tg:
                for t in tasks:
                    tg.create_task(_run_one(t))
        else:
            await asyncio.gather(
                *(_run_one(t) for t in tasks), return_exceptions=True
            )

        completed = sum(1 for d in details if d["status"] == "ok")
        failed = sum(1 for d in details if d["status"] == "failed")
        return StageOutcome(
            stage=stage,
            attempted=len(tasks),
            completed=completed,
            failed=failed,
            details=details,
        )

    async def drain(
        self,
        *,
        run_id: uuid.UUID,
        stage: str,
        tenant_id: uuid.UUID,
        budget_seconds: float = 30.0,
        claim_fn,
        complete_fn,
        fail_fn,
    ) -> DrainResult:
        """Drain one stage with a time budget.

        Args:
            run_id: Parent screening run.
            stage: Stage to drain.
            tenant_id: Owning tenant.
            budget_seconds: Max wall-clock time for this drain cycle.
            claim_fn: Async callable ``(run_id, stage, limit) -> list[RunTask]``.
            complete_fn: Async callable ``(task_id, result) -> None``.
            fail_fn: Async callable ``(task_id, error) -> None``.

        Returns:
            ``DrainResult`` with attempted/completed/failed/rescheduled counts.
        """
        started = time.monotonic()
        total_attempted = 0
        total_completed = 0
        total_failed = 0
        total_rescheduled = 0

        while time.monotonic() - started < budget_seconds:
            tasks = await claim_fn(run_id, stage, limit=200)
            if not tasks:
                break

            outcome = await self.run_stage(
                run_id=run_id, stage=stage, tasks=tasks, tenant_id=tenant_id
            )
            total_attempted += outcome.attempted
            total_completed += outcome.completed
            total_failed += outcome.failed

            # Persist results — complete or fail each task
            for detail in outcome.details:
                if detail["status"] == "ok":
                    await complete_fn(detail["task_id"], {"status": "ok"})
                else:
                    await fail_fn(detail["task_id"], "stage execution failed")

        return DrainResult(
            stage=stage,
            attempted=total_attempted,
            completed=total_completed,
            failed=total_failed,
            rescheduled=total_rescheduled,
        )


class CoreStageFailedError(Exception):
    """A CORE stage task failed — the run cannot proceed with an incomplete
    verdict set.
    """
