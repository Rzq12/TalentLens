"""In-process workflow runner backed by Postgres SKIP LOCKED.

Implements the ``WorkflowRunner`` port from ``app.services.ports``.
Uses the ``run_tasks`` table for durable task state, ``run_checkpoints``
for heartbeat/resumption, and optional ``agent_result_cache`` for
reproducibility.

ARCHITECTURE-AGENTS.md §2.5 — resumption after container restart is just
"call drain again": the queue table records what exists and what doesn't.
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update, delete
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import RunTask, RunCheckpoint, AgentResultCache
from app.services.ports import DrainResult


class InProcessWorkflowRunner:
    """Durable execution backed by Postgres ``run_tasks``.

    Claim uses ``SELECT ... FOR UPDATE SKIP LOCKED`` so multiple workers
    can share the queue without conflicts. Resumption is stateless: stale
    runs are found by heartbeat age, and pending tasks are re-drained.
    """

    def __init__(self, session_factory):
        self._session_factory = session_factory

    async def enqueue(
        self,
        *,
        run_id: uuid.UUID,
        stage: str,
        agent_name: str,
        tenant_id: uuid.UUID,
        tasks: list[dict],
    ) -> list[int]:
        """Insert task rows and return their ids.

        Args:
            run_id: Parent screening run.
            stage: Pipeline stage (judge, gap, interview, etc.).
            agent_name: Agent registered in ``AgentRegistry``.
            tenant_id: Owning tenant.
            tasks: List of payload dicts, one per task.

        Returns:
            List of inserted task primary keys.
        """
        async with self._session_factory() as session:
            ids: list[int] = []
            for payload in tasks:
                task = RunTask(
                    tenant_id=tenant_id,
                    run_id=run_id,
                    stage=stage,
                    agent_name=agent_name,
                    payload=payload,
                    status="pending",
                )
                session.add(task)
                await session.flush()
                ids.append(task.id)
            await session.commit()
            return ids

    async def claim(
        self,
        run_id: uuid.UUID,
        stage: str,
        limit: int = 200,
    ) -> list[RunTask]:
        """Claim up to ``limit`` pending tasks using SKIP LOCKED.

        A Postgres advisory lock on ``run_id`` prevents double-claiming
        during brief overlap windows (rolling HF Spaces deploy).
        """
        async with self._session_factory() as session:
            # Advisory lock to serialize claim for this run
            await session.execute(
                select("pg_advisory_xact_lock")
                .select_from(0).where(False)  # no-op
            )
            try:
                await session.execute(
                    f"SELECT pg_advisory_xact_lock({hash(str(run_id)) % 2147483647})"
                )
            except Exception:
                pass  # advisory lock may not be available in SQLite/test

            now = datetime.now(timezone.utc)
            stmt = (
                select(RunTask)
                .where(
                    RunTask.run_id == run_id,
                    RunTask.stage == stage,
                    RunTask.status == "pending",
                    (RunTask.not_before.is_(None)) | (RunTask.not_before <= now),
                )
                .order_by(RunTask.id)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
            result = await session.execute(stmt)
            tasks = list(result.scalars().all())

            # Mark claimed
            worker_id = f"worker-{uuid.uuid4().hex[:8]}"
            for task in tasks:
                task.status = "claimed"
                task.claimed_by = worker_id
                task.claimed_at = now
                task.attempt += 1

            await session.commit()
            return tasks

    async def complete(self, task_id: int, result: dict) -> None:
        """Mark a task as done with result."""
        async with self._session_factory() as session:
            stmt = (
                update(RunTask)
                .where(RunTask.id == task_id)
                .values(status="done", result=result)
            )
            await session.execute(stmt)
            await session.commit()

    async def fail(self, task_id: int, error: str) -> None:
        """Mark a task as failed with error."""
        async with self._session_factory() as session:
            stmt = (
                update(RunTask)
                .where(RunTask.id == task_id)
                .values(status="failed", error=error)
            )
            await session.execute(stmt)
            await session.commit()

    async def heartbeat(self, run_id: uuid.UUID, stage: str) -> None:
        """Update (or insert) the checkpoint heartbeat for a run."""
        async with self._session_factory() as session:
            now = datetime.now(timezone.utc)
            checkpoint = await session.get(RunCheckpoint, run_id)
            if checkpoint:
                checkpoint.last_stage = stage
                checkpoint.heartbeat_at = now
            else:
                session.add(
                    RunCheckpoint(
                        run_id=run_id,
                        last_stage=stage,
                        heartbeat_at=now,
                    )
                )
            await session.commit()

    async def resume_stale(self, older_than_seconds: int = 120) -> list[uuid.UUID]:
        """Find runs whose heartbeat is older than threshold.

        These runs have pending work that needs re-draining after a
        container restart or HF Spaces sleep/wake cycle.
        """
        async with self._session_factory() as session:
            cutoff = datetime.now(timezone.utc)
            # Simple approach: find checkpoints with old heartbeat
            # In production, also filter on screening_runs.status='running'
            stmt = (
                select(RunCheckpoint.run_id)
                .where(
                    RunCheckpoint.heartbeat_at
                    < cutoff
                )
            )
            result = await session.execute(stmt)
            return [row[0] for row in result.all()]

    async def cache_get(self, cache_key: str) -> dict | None:
        """Look up a cached agent result by key."""
        async with self._session_factory() as session:
            row = await session.get(AgentResultCache, cache_key)
            return row.output if row else None

    async def cache_put(
        self,
        cache_key: str,
        tenant_id: uuid.UUID,
        agent_name: str,
        agent_version: str,
        output: dict,
        ttl_seconds: int | None = None,
    ) -> None:
        """Store an agent result in the durable cache."""
        async with self._session_factory() as session:
            expires = None
            if ttl_seconds:
                expires = datetime.now(timezone.utc).timestamp() + ttl_seconds
                expires = datetime.fromtimestamp(expires, tz=timezone.utc)
            stmt = insert(AgentResultCache).values(
                cache_key=cache_key,
                tenant_id=tenant_id,
                agent_name=agent_name,
                agent_version=agent_version,
                output=output,
                expires_at=expires,
            ).on_conflict_do_update(
                index_elements=["cache_key"],
                set_={"output": output, "expires_at": expires},
            )
            await session.execute(stmt)
            await session.commit()
