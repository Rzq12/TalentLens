"""Durable orchestration result handling."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from pydantic import BaseModel

from app.agents.agent import Agent, AgentContext, AgentResult
from app.models import RunTask
from app.services.orchestration import AgentRegistry, Orchestrator


class _Output(BaseModel):
    """A typed agent response that must survive durable persistence."""

    verdict: str


class _Agent(Agent[dict[str, str], _Output]):
    """Deterministic agent fixture for the durable stage runner."""

    name = "fixture"
    version = "1.0.0"
    requires_llm = False

    async def run(
        self, payload: dict[str, str], ctx: AgentContext
    ) -> AgentResult[_Output]:
        """Return a typed output envelope."""
        return AgentResult(output=_Output(verdict=payload["verdict"]))


@pytest.mark.asyncio
async def test_drain_persists_serialized_agent_output() -> None:
    """A successful durable task retains its structured result rather than a marker."""
    registry = AgentRegistry()
    registry.register(_Agent)
    orchestrator = Orchestrator(registry=registry)
    run_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    task = RunTask(
        id=1,
        run_id=run_id,
        tenant_id=tenant_id,
        stage="chat",
        agent_name="fixture",
        payload={"verdict": "match"},
    )
    persisted: list[tuple[int, dict[str, Any]]] = []

    async def claim(*args: Any) -> list[RunTask]:
        """Return work once, then stop the drain."""
        return [task] if not persisted else []

    async def complete(task_id: int, result: dict[str, Any]) -> None:
        """Capture the durable task payload."""
        persisted.append((task_id, result))

    async def fail(task_id: int, error: str) -> None:
        """A successful agent must not use the failure writer."""
        raise AssertionError(error)

    outcome = await orchestrator.drain(
        run_id=run_id,
        stage="chat",
        tenant_id=tenant_id,
        budget_seconds=1,
        claim_fn=claim,
        complete_fn=complete,
        fail_fn=fail,
    )

    assert outcome.completed == 1
    assert persisted == [
        (
            1,
            {
                "status": "ok",
                "agent": "fixture",
                "cache_hit": False,
                "output": {"verdict": "match"},
            },
        )
    ]
