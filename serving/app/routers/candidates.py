"""Candidate assessment endpoints."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter
from sqlalchemy import select

from app.db import DbSession
from app.exceptions import ResourceNotFoundError
from app.models import CandidateScore, Decision
from app.routers.screening import _result_details
from app.security import ReadPrincipal

router = APIRouter(prefix="/candidates", tags=["candidates"])


@router.get("/{candidate_id}")
async def read_candidate_assessment(
    candidate_id: uuid.UUID,
    session: DbSession,
    principal: ReadPrincipal,
) -> dict[str, Any]:
    """Return the latest tenant-scoped assessment for a candidate."""
    score = await session.scalar(
        select(CandidateScore)
        .where(
            CandidateScore.candidate_id == candidate_id,
            CandidateScore.tenant_id == principal.tenant_id,
        )
        .order_by(CandidateScore.created_at.desc())
        .limit(1)
    )
    if score is None:
        raise ResourceNotFoundError("Candidate assessment not found.")

    decision = await session.scalar(
        select(Decision)
        .where(
            Decision.score_id == score.id,
            Decision.tenant_id == principal.tenant_id,
        )
        .order_by(Decision.decided_at.desc())
        .limit(1)
    )
    details = (await _result_details(session, principal.tenant_id, [score.id]))[score.id]
    return {
        "score_id": str(score.id),
        "candidate_id": str(score.candidate_id),
        "run_id": str(score.run_id),
        "rank": score.rank,
        "score": float(score.overall_score),
        "recommendation": score.recommendation,
        "decision": decision.decision if decision else None,
        "decided_by": str(decision.decided_by) if decision else None,
        "decided_at": decision.decided_at.isoformat() if decision else None,
        "overridden": any(item.get("overridden", False) for item in details["verdicts"]),
        "override_reason": None,
        "findings": details["verdicts"],
        "resume_id": str(score.profile_id) if score.profile_id else str(score.candidate_id),
        "document_id": str(score.candidate_id),
        "summary": score.summary,
        "skill_gaps": details["skill_gaps"],
        "interview_questions": details["interview_questions"],
    }
