"""In-process workflow runner backed by Postgres SKIP LOCKED.

Implements the ``WorkflowRunner`` port from ``app.services.ports``.
Uses the ``run_tasks`` table for durable task state, ``run_checkpoints``
for heartbeat/resumption, and optional ``agent_result_cache`` for
reproducibility.

ARCHITECTURE-AGENTS.md §2.5 — resumption after container restart is just
"call drain again": the queue table records what exists and what doesn't.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert

from app.models import AgentResultCache, RunCheckpoint, RunTask, ScreeningRun


def _advisory_lock_key(run_id: uuid.UUID) -> int:
    """Return a process-stable signed 64-bit PostgreSQL advisory lock key."""
    value = int.from_bytes(run_id.bytes[:8], byteorder="big", signed=False)
    return value - (1 << 64) if value >= (1 << 63) else value


class InProcessWorkflowRunner:
    """Durable execution backed by Postgres ``run_tasks``.

    Claim uses ``SELECT ... FOR UPDATE SKIP LOCKED`` so multiple workers
    can share the queue without conflicts. Resumption is stateless: stale
    runs are found by heartbeat age, and pending tasks are re-drained.
    """

    def __init__(self, session_factory: Callable[[], AbstractAsyncContextManager[Any]]) -> None:
        self._session_factory = session_factory

    async def enqueue(
        self,
        *,
        run_id: uuid.UUID,
        stage: str,
        agent_name: str,
        tenant_id: uuid.UUID,
        tasks: list[dict[str, Any]],
    ) -> list[int]:
        """Insert durable task rows in an independent transaction."""
        async with self._session_factory() as session:
            ids = await self.enqueue_in_session(
                session=session,
                run_id=run_id,
                stage=stage,
                agent_name=agent_name,
                tenant_id=tenant_id,
                tasks=tasks,
            )
            await session.commit()
            return ids

    async def enqueue_in_session(
        self,
        *,
        session: Any,
        run_id: uuid.UUID,
        stage: str,
        agent_name: str,
        tenant_id: uuid.UUID,
        tasks: list[dict[str, Any]],
    ) -> list[int]:
        """Insert tasks into the caller's transaction with run admission."""
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
        return ids

    async def recover_claimed(self, older_than_seconds: int = 120) -> list[uuid.UUID]:
        """Requeue work abandoned by a stopped worker and return affected runs."""
        async with self._session_factory() as session:
            cutoff = datetime.now(UTC) - timedelta(seconds=older_than_seconds)
            result = await session.execute(
                select(RunTask.run_id)
                .where(RunTask.status == "claimed", RunTask.claimed_at < cutoff)
                .distinct()
            )
            run_ids = [row[0] for row in result.all()]
            if run_ids:
                await session.execute(
                    update(RunTask)
                    .where(
                        RunTask.run_id.in_(run_ids),
                        RunTask.status == "claimed",
                        RunTask.claimed_at < cutoff,
                    )
                    .values(status="pending", claimed_by=None, claimed_at=None)
                )
                for run_id in run_ids:
                    checkpoint = await session.get(RunCheckpoint, run_id)
                    if checkpoint is None:
                        session.add(
                            RunCheckpoint(
                                run_id=run_id,
                                last_stage="screening",
                                heartbeat_at=datetime.now(UTC),
                                resumed_count=1,
                            )
                        )
                    else:
                        checkpoint.resumed_count += 1
                await session.commit()
            return run_ids

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
            # PostgreSQL lock values must be stable across independently-started workers.
            try:
                await session.execute(
                    select(func.pg_advisory_xact_lock(_advisory_lock_key(run_id)))
                )
            except Exception:
                pass  # advisory lock may not be available in SQLite/test

            now = datetime.now(UTC)
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

    async def complete(self, task_id: int, result: dict[str, Any]) -> None:
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
            now = datetime.now(UTC)
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

    async def ready_runs(
        self,
        stage: str = "screening",
        limit: int = 100,
    ) -> list[tuple[uuid.UUID, uuid.UUID]]:
        """Return tenant-scoped runs that have ready work for a durable worker."""
        async with self._session_factory() as session:
            now = datetime.now(UTC)
            result = await session.execute(
                select(RunTask.run_id, RunTask.tenant_id)
                .where(
                    RunTask.stage == stage,
                    RunTask.status == "pending",
                    (RunTask.not_before.is_(None)) | (RunTask.not_before <= now),
                )
                .order_by(RunTask.id)
                .limit(limit)
                .distinct()
            )
            return [(row[0], row[1]) for row in result.all()]

    async def resume_stale(self, older_than_seconds: int = 120) -> list[uuid.UUID]:
        """Find runs whose heartbeat is older than threshold.

        These runs have pending work that needs re-draining after a
        container restart or HF Spaces sleep/wake cycle.
        """
        async with self._session_factory() as session:
            cutoff = datetime.now(UTC) - timedelta(seconds=older_than_seconds)
            stmt = (
                select(RunCheckpoint.run_id)
                .join(ScreeningRun, ScreeningRun.id == RunCheckpoint.run_id)
                .where(
                    RunCheckpoint.heartbeat_at < cutoff,
                    ScreeningRun.status.in_(("queued", "running")),
                )
            )
            result = await session.execute(stmt)
            return [row[0] for row in result.all()]

    async def cache_get(self, cache_key: str) -> dict[str, Any] | None:
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
        output: dict[str, Any],
        ttl_seconds: int | None = None,
    ) -> None:
        """Store an agent result in the durable cache."""
        async with self._session_factory() as session:
            expires: datetime | None = None
            if ttl_seconds:
                expires = datetime.now(UTC) + timedelta(seconds=ttl_seconds)
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
