"""Screening run endpoints — MVP.

POST /api/v1/jobs/{job_id}/screening-runs — start a run (202 + SSE)
GET /api/v1/screening/runs/{run_id} — poll status
GET /api/v1/screening/runs/{run_id}/events — SSE stream
GET /api/v1/screening/runs/{run_id}/results — ranked candidates
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, BackgroundTasks, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.db import DbSession, get_sessionmaker, set_tenant_context
from app.exceptions import ResourceConflictError, ResourceNotFoundError
from app.models import CandidateScore, Job, RubricVersion, ScreeningRun
from app.security import ReadPrincipal, WritePrincipal
from app.services.orchestration import AgentRegistry, Orchestrator
from app.services.screening import execute_screening_run
from app.services.sse import EventType, get_sse_manager

router = APIRouter(prefix="/screening", tags=["screening"])

# --------------------------------------------------------------------------- #
# Agent registration — called once at startup                                 #
# --------------------------------------------------------------------------- #

_registry = AgentRegistry()
_orchestrator = Orchestrator(registry=_registry, max_concurrency=16)
_sse = get_sse_manager()


def get_registry() -> AgentRegistry:
    return _registry


def get_orchestrator() -> Orchestrator:
    return _orchestrator


# --------------------------------------------------------------------------- #
# API                                                                         #
# --------------------------------------------------------------------------- #


@router.post(
    "/jobs/{job_id}/runs",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start a screening run",
    description=(
        "Admits a job for screening and answers `202` with the run id. The job "
        "must have an approved rubric: without one the answer is `409`, meaning "
        "*approve a rubric and retry*, which a caller may act on. It is not "
        "`422` — the request itself is well-formed, so a client that stops "
        "retrying on a payload error would wrongly abandon the job."
    ),
)
async def start_screening_run(
    *,
    job_id: uuid.UUID,
    session: DbSession,
    principal: WritePrincipal,
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    """Create a screening run for a job. Requires an approved rubric.

    Args:
        job_id: Job to screen against.
        session: Request-scoped database session.
        principal: Authenticated caller; supplies the tenant scope and is
            recorded as the run's trigger.
        background_tasks: Schedules post-response screening execution.

    Returns:
        The run id, its initial status, and the SSE URL to follow progress on.

    Raises:
        ResourceConflictError: If the job has no approved rubric yet.
    """
    # 1. Find approved rubric for this job
    stmt = (
        select(RubricVersion)
        .where(
            RubricVersion.job_id == job_id,
            RubricVersion.tenant_id == principal.tenant_id,
            RubricVersion.status == "approved",
        )
        .order_by(RubricVersion.version.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    rubric = result.scalar_one_or_none()

    if rubric is None:
        # 409, not 422: the request is well-formed — the job simply is not ready
        # to screen yet. task.md Phase 4 fixes 409 for this admission case, and
        # the distinction is load-bearing: a client retries on 409 and treats
        # 422 as a payload bug it must not retry.
        raise ResourceConflictError(
            "No approved rubric exists for this job. Create and approve a rubric first."
        )

    # 2. Create screening run
    run = ScreeningRun(
        tenant_id=principal.tenant_id,
        job_id=job_id,
        rubric_version_id=rubric.id,
        status="queued",
        mode="interactive",
        triggered_by=principal.user_id,
    )
    session.add(run)
    await session.flush()

    # 3. Schedule execution after the admission transaction commits.
    background_tasks.add_task(_execute_run, run.id, principal.tenant_id)

    # 4. Publish run.started event
    await _sse.publish(run.id, EventType.RUN_STARTED, {"run_id": str(run.id)})

    return {
        "run_id": str(run.id),
        "status": "queued",
        "events_url": f"/api/v1/screening/runs/{run.id}/events",
    }


@router.get(
    "/runs/{run_id}",
    summary="Poll run status",
)
async def get_run_status(
    *,
    run_id: uuid.UUID,
    session: DbSession,
    principal: ReadPrincipal,
) -> dict[str, Any]:
    """Return current run metadata."""
    run = await session.get(ScreeningRun, run_id)
    if run is None or run.tenant_id != principal.tenant_id:
        raise ResourceNotFoundError("Screening run not found.")

    return {
        "run_id": str(run.id),
        "job_id": str(run.job_id),
        "status": run.status,
        "candidate_count": run.candidate_count,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
    }


@router.get(
    "/runs/{run_id}/events",
    summary="SSE stream for run events",
)
async def stream_run_events(
    *,
    run_id: uuid.UUID,
    session: DbSession,
    principal: ReadPrincipal,
) -> StreamingResponse:
    """Stream screening run progress as Server-Sent Events.

    Authorization is checked once, before the stream opens: an SSE connection
    outlives the request that created it, so there is no later point at which
    to reject the caller. The tenant check mirrors ``get_run_status`` — a run
    belonging to another tenant is reported as absent rather than forbidden,
    so the endpoint does not confirm that a given run id exists.

    Args:
        run_id: Run whose progress to stream.
        session: Request-scoped database session.
        principal: Authenticated caller; supplies the tenant scope.

    Returns:
        A ``text/event-stream`` response that closes when the run reaches a
        terminal state or the client disconnects.

    Raises:
        ResourceNotFoundError: If the run does not exist, or belongs to a
            different tenant.
    """
    run = await session.get(ScreeningRun, run_id)
    if run is None or run.tenant_id != principal.tenant_id:
        raise ResourceNotFoundError("Screening run not found.")

    cancel_event = asyncio.Event()

    async def _generate() -> AsyncIterator[bytes]:
        async for chunk in _sse.subscribe(run_id, cancel_event):
            yield chunk

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get(
    "/runs/{run_id}/results",
    summary="Get ranked results",
)
async def get_run_results(
    *,
    run_id: uuid.UUID,
    session: DbSession,
    principal: ReadPrincipal,
) -> dict[str, Any]:
    """Return ranked candidate scores for a completed run."""
    run = await session.get(ScreeningRun, run_id)
    if run is None or run.tenant_id != principal.tenant_id:
        raise ResourceNotFoundError("Screening run not found.")

    if run.status not in ("completed", "running"):
        return {"run_id": str(run.id), "status": run.status, "results": []}

    stmt = (
        select(CandidateScore)
        .where(
            CandidateScore.run_id == run_id,
            CandidateScore.rank.isnot(None),
        )
        .order_by(CandidateScore.rank)
    )
    result = await session.execute(stmt)
    scores = result.scalars().all()

    return {
        "run_id": str(run.id),
        "status": run.status,
        "count": len(scores),
        "results": [
            {
                "rank": s.rank,
                "candidate_id": str(s.candidate_id),
                "overall_score": float(s.overall_score),
                "recommendation": s.recommendation,
            }
            for s in scores
        ],
    }


async def _execute_run(run_id: uuid.UUID, tenant_id: uuid.UUID) -> None:
    """Execute one admitted run using a dedicated post-response transaction."""
    set_tenant_context(tenant_id)
    async with get_sessionmaker()() as session:
        try:
            run = await session.get(ScreeningRun, run_id)
            if run is None or run.tenant_id != tenant_id:
                return
            rubric = await session.get(RubricVersion, run.rubric_version_id)
            job = await session.get(Job, run.job_id)
            if rubric is None or job is None:
                raise RuntimeError("Screening run dependencies are unavailable.")
            await _sse.publish(run.id, EventType.STAGE_STARTED, {"stage": "judge"})
            judge = _registry.resolve("semantic_matching")
            scores = await execute_screening_run(
                session=session,
                run=run,
                rubric=rubric,
                job_title=job.title,
                judge=judge,
            )
            await session.commit()
            await _sse.publish(
                run.id,
                EventType.STAGE_COMPLETE,
                {"stage": "judge", "candidate_count": len(scores)},
            )
            await _sse.publish(
                run.id,
                EventType.RUN_COMPLETE,
                {"run_id": str(run.id), "candidate_count": len(scores)},
            )
        except Exception:
            await session.rollback()
            run = await session.get(ScreeningRun, run_id)
            if run is not None and run.tenant_id == tenant_id:
                run.status = "failed"
                await session.commit()
            await _sse.publish(
                run_id,
                EventType.RUN_FAILED,
                {
                    "run_id": str(run_id),
                    "message": "Screening run failed. Please retry later.",
                },
            )
