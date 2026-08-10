"""Screening run endpoints — MVP.

POST /api/v1/jobs/{job_id}/screening-runs — start a run (202 + SSE)
GET /api/v1/screening/runs/{run_id} — poll status
GET /api/v1/screening/runs/{run_id}/events — SSE stream
GET /api/v1/screening/runs/{run_id}/results — ranked candidates
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, status
from fastapi.responses import StreamingResponse

from app.db import DbSession, get_sessionmaker
from app.exceptions import ResourceNotFoundError, ValidationFailedError
from app.models import ScreeningRun, RubricVersion, CandidateScore
from app.security import ReadPrincipal, WritePrincipal
from app.services.orchestration import AgentRegistry, Orchestrator
from app.services.sse import EventType, get_sse_manager
from app.services.workflow_runner import InProcessWorkflowRunner

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
)
async def start_screening_run(
    *,
    job_id: uuid.UUID,
    session: DbSession,
    principal: WritePrincipal,
) -> dict:
    """Create a screening run for a job. Requires an approved rubric.

    Returns 202 + run id. Progress is streamed via SSE at
    ``GET /screening/runs/{run_id}/events``.
    """
    # 1. Find approved rubric for this job
    from sqlalchemy import select

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
        raise ValidationFailedError(
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

    # 3. Enqueue judge tasks (one per candidate-requirement group)
    runner = InProcessWorkflowRunner(get_sessionmaker)
    await runner.enqueue(
        run_id=run.id,
        stage="judge",
        agent_name="semantic_matching",
        tenant_id=principal.tenant_id,
        tasks=[],  # Populated when funnel runs
    )

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
) -> dict:
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
    run_id: uuid.UUID,
) -> StreamingResponse:
    """Stream screening run progress as Server-Sent Events."""
    import asyncio

    cancel_event = asyncio.Event()

    async def _generate():
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
) -> dict:
    """Return ranked candidate scores for a completed run."""
    from sqlalchemy import select

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
