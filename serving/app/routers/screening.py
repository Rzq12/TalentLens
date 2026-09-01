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
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.db import DbSession, get_sessionmaker, set_tenant_context
from app.exceptions import (
    BudgetExceededError,
    LLMProviderError,
    ResourceConflictError,
    ResourceNotFoundError,
)
from app.models import (
    CandidateScore,
    EvidenceSpanRecord,
    InterviewKit,
    InterviewQuestion,
    Job,
    Requirement,
    RequirementVerdict,
    RubricVersion,
    ScreeningRun,
    SkillGap,
)
from app.security import ReadPrincipal, WritePrincipal
from app.services.embedding import get_embedding_service
from app.services.orchestration import AgentRegistry, Orchestrator
from app.services.reranker import get_reranker_service
from app.services.retrieval_funnel import run_resume_version_retrieval_funnel
from app.services.screening import execute_screening_run
from app.services.screening_insights import persist_score_insights
from app.services.sse import EventType, get_sse_manager
from app.services.workflow_runner import InProcessWorkflowRunner

router = APIRouter(prefix="/screening", tags=["screening"])

# --------------------------------------------------------------------------- #
# Agent registration — called once at startup                                 #
# --------------------------------------------------------------------------- #

_registry = AgentRegistry()
_orchestrator = Orchestrator(registry=_registry, max_concurrency=16)
_sse = get_sse_manager()
_RESCHEDULABLE_ERROR_CODES = frozenset(
    {"rate_limit", "quota", "budget_exceeded", "network", "model_unavailable", "unknown"}
)
_INTERNAL_ERROR_CODE = "internal"


def get_registry() -> AgentRegistry:
    """Return the application-wide agent registry populated during startup."""
    return _registry


@dataclass(frozen=True, slots=True)
class _ExecutionOutcome:
    success: bool
    error_code: str | None = None

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

    # 3. Persist the execution request with the admitted run. The post-response
    # drain is only a wake-up hint; a later worker can safely resume this task.
    runner = InProcessWorkflowRunner(get_sessionmaker())
    await runner.enqueue_in_session(
        session=session,
        run_id=run.id,
        stage="screening",
        agent_name="screening",
        tenant_id=principal.tenant_id,
        tasks=[{}],
    )
    background_tasks.add_task(_drain_run, run.id, principal.tenant_id)

    # 4. Publish run.started event
    await _sse.publish(run.id, EventType.RUN_STARTED, {"run_id": str(run.id)})

    return {
        "run_id": str(run.id),
        "status": "queued",
        "events_url": f"/api/v1/screening/runs/{run.id}/events",
    }


@router.get(
    "/runs",
    summary="List screening runs",
)
async def list_screening_runs(
    session: DbSession,
    principal: ReadPrincipal,
    job_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    """Return recent screening runs visible to the caller."""
    stmt = (
        select(ScreeningRun)
        .where(ScreeningRun.tenant_id == principal.tenant_id)
        .order_by(ScreeningRun.created_at.desc())
        .limit(limit)
    )
    if job_id is not None:
        stmt = stmt.where(ScreeningRun.job_id == job_id)
    runs = (await session.execute(stmt)).scalars().all()
    items = [
        {
            "run_id": str(run.id),
            "job_id": str(run.job_id),
            "status": run.status,
            "candidate_count": run.candidate_count,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        }
        for run in runs
    ]
    return {"items": items, "count": len(items), "next_cursor": None}


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
    score_ids = [score.id for score in scores]
    details = await _result_details(session, principal.tenant_id, score_ids)

    return {
        "run_id": str(run.id),
        "status": run.status,
        "count": len(scores),
        "results": [
            {
                "score_id": str(score.id),
                "rank": score.rank,
                "candidate_id": str(score.candidate_id),
                "overall_score": float(score.overall_score),
                "recommendation": score.recommendation,
                "recommendation_confidence": score.recommendation_confidence,
                "summary": score.summary,
                **details.get(score.id, {}),
            }
            for score in scores
        ],
    }


async def _result_details(
    session: DbSession, tenant_id: uuid.UUID, score_ids: list[uuid.UUID]
) -> dict[uuid.UUID, dict[str, Any]]:
    """Read persisted explanations without loading resume text into the response."""
    details: dict[uuid.UUID, dict[str, Any]] = {
        score_id: {"skill_gaps": [], "interview_questions": [], "verdicts": []}
        for score_id in score_ids
    }
    if not score_ids:
        return details

    gaps = await session.execute(
        select(SkillGap).where(
            SkillGap.tenant_id == tenant_id, SkillGap.score_id.in_(score_ids)
        )
    )
    for gap in gaps.scalars():
        details[gap.score_id]["skill_gaps"].append(
            {
                "requirement_id": str(gap.requirement_id),
                "severity": gap.severity,
                "gap_type": gap.gap_type,
                "suggested_probe": gap.suggested_probe,
                "weight": gap.weight,
            }
        )

    questions = await session.execute(
        select(InterviewKit.score_id, InterviewQuestion)
        .join(InterviewQuestion, InterviewQuestion.kit_id == InterviewKit.id)
        .where(InterviewKit.tenant_id == tenant_id, InterviewKit.score_id.in_(score_ids))
        .order_by(InterviewKit.score_id, InterviewQuestion.ordinal)
    )
    for score_id, question in questions.all():
        details[score_id]["interview_questions"].append(
            {
                "ordinal": question.ordinal,
                "question": question.question,
                "category": question.category,
                "difficulty": question.difficulty,
                "targets_requirement_id": (
                    str(question.targets_requirement_id)
                    if question.targets_requirement_id
                    else None
                ),
                "rationale": question.rationale,
                "expected_signal": question.expected_signal,
                "follow_ups": question.follow_ups.get("items", []) if question.follow_ups else [],
            }
        )

    verdicts = await session.execute(
        select(RequirementVerdict, Requirement, EvidenceSpanRecord)
        .join(Requirement, Requirement.id == RequirementVerdict.requirement_id)
        .outerjoin(EvidenceSpanRecord, EvidenceSpanRecord.verdict_id == RequirementVerdict.id)
        .where(
            RequirementVerdict.tenant_id == tenant_id,
            RequirementVerdict.score_id.in_(score_ids),
            Requirement.tenant_id == tenant_id,
        )
        .order_by(RequirementVerdict.score_id, Requirement.ordinal)
    )
    for verdict, requirement, evidence in verdicts.all():
        score_verdicts = details[verdict.score_id]["verdicts"]
        existing = next(
            (item for item in score_verdicts if item["requirement_id"] == str(requirement.id)),
            None,
        )
        if existing is None:
            existing = {
                "requirement_id": str(requirement.id),
                "requirement": requirement.text,
                "verdict": verdict.override_verdict or verdict.verdict,
                "confidence": verdict.confidence,
                "reasoning": verdict.reasoning,
                "weight": float(verdict.weight_at_scoring),
                "contribution": float(verdict.contribution),
                "overridden": verdict.override_verdict is not None,
                "evidence": [],
            }
            score_verdicts.append(existing)
        if evidence is not None and evidence.verbatim_verified:
            existing["evidence"].append(
                {
                    "page": evidence.page,
                    "start_char": evidence.start_char,
                    "end_char": evidence.end_char,
                    "quoted_text": evidence.quoted_text,
                    "relevance": evidence.relevance,
                }
            )
    return details


async def _drain_run(run_id: uuid.UUID, tenant_id: uuid.UUID) -> None:
    """Claim and execute the durable screening task for one admitted run."""
    runner = InProcessWorkflowRunner(get_sessionmaker())
    tasks = await runner.claim(run_id, "screening", limit=1)
    if not tasks:
        return
    task = tasks[0]
    await runner.heartbeat(run_id, "screening")
    outcome = await _execute_run(run_id, tenant_id)
    if outcome.success:
        await runner.complete(task.id, {"status": "ok", "run_id": str(run_id)})
    else:
        await runner.fail(
            task.id,
            "screening execution failed",
            error_code=outcome.error_code or "unknown",
        )


async def _execute_run(run_id: uuid.UUID, tenant_id: uuid.UUID) -> _ExecutionOutcome:
    """Execute one claimed run using a dedicated worker transaction."""
    set_tenant_context(tenant_id)
    async with get_sessionmaker()() as session:
        try:
            run = await session.get(ScreeningRun, run_id)
            if run is None or run.tenant_id != tenant_id:
                return _ExecutionOutcome(success=True)

            rubric = await session.get(RubricVersion, run.rubric_version_id)
            job = await session.get(Job, run.job_id)
            if rubric is None or job is None:
                raise RuntimeError("Screening run dependencies are unavailable.")
            await _sse.publish(run.id, EventType.STAGE_STARTED, {"stage": "judge"})
            judge = _registry.resolve("semantic_matching")
            embedder = get_embedding_service()
            reranker = get_reranker_service()

            async def retrieve_candidate_evidence(version: Any, query: str) -> Any:
                chunks, funnel = await run_resume_version_retrieval_funnel(
                    session=session,
                    embedder=embedder,
                    reranker=reranker,
                    tenant_id=tenant_id,
                    resume_version_id=version.id,
                    query=query,
                )
                return [item.chunk for item in chunks], funnel

            scores = await execute_screening_run(
                session=session,
                run=run,
                rubric=rubric,
                job_title=job.title,
                judge=judge,
                evidence_retriever=retrieve_candidate_evidence,
            )
            await _sse.publish(run.id, EventType.STAGE_STARTED, {"stage": "insights"})
            for score in scores:
                await persist_score_insights(
                    session=session,
                    score=score,
                    skill_gap_agent=_registry.resolve("skill_gap"),
                    interview_agent=_registry.resolve("interview"),
                    recommendation_agent=_registry.resolve("recommendation"),
                )
            await session.commit()
            await _sse.publish(
                run.id,
                EventType.STAGE_COMPLETE,
                {"stage": "judge", "candidate_count": len(scores)},
            )
            await _sse.publish(
                run.id,
                EventType.STAGE_COMPLETE,
                {"stage": "insights", "candidate_count": len(scores)},
            )

            await _sse.publish(
                run.id,
                EventType.RUN_COMPLETE,
                {"run_id": str(run.id), "candidate_count": len(scores)},
            )
            return _ExecutionOutcome(success=True)
        except Exception as exc:
            await session.rollback()
            error_code = _screening_error_code(exc)
            run = await session.get(ScreeningRun, run_id)
            if run is not None and run.tenant_id == tenant_id:
                run.status = "queued" if error_code in _RESCHEDULABLE_ERROR_CODES else "failed"
                await session.commit()
            await _sse.publish(
                run_id,
                EventType.RUN_FAILED,
                {
                    "run_id": str(run_id),
                    "message": "Screening run failed. Please retry later.",
                },
            )
            return _ExecutionOutcome(success=False, error_code=error_code)


def _screening_error_code(exc: Exception) -> str:
    """Map safe, typed upstream failures onto durable runner policy codes."""
    if isinstance(exc, BudgetExceededError):
        return "budget_exceeded"
    if isinstance(exc, LLMProviderError):
        return exc.kind
    return _INTERNAL_ERROR_CODE
