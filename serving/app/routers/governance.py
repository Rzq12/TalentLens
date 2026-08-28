"""Human screening decisions, verdict corrections, and audit verification."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Request, status
from sqlalchemy import select

from app.db import DbSession
from app.exceptions import ResourceNotFoundError
from app.models import AuditEvent, CandidateScore, Decision, RequirementVerdict
from app.schemas.governance import (
    AuditVerificationResponse,
    DecisionCreateRequest,
    DecisionResponse,
    VerdictOverrideRequest,
)
from app.security import ReadPrincipal, WritePrincipal
from app.services.audit import record_audit_event, verify_audit_chain

router = APIRouter(prefix="/governance", tags=["governance"])


@router.post(
    "/scores/{score_id}/decisions",
    response_model=DecisionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Record a recruiter decision",
)
async def record_decision(
    score_id: uuid.UUID,
    payload: DecisionCreateRequest,
    request: Request,
    principal: WritePrincipal,
    session: DbSession,
) -> DecisionResponse:
    """Record a human decision without altering the automated assessment."""
    score = await session.scalar(
        select(CandidateScore).where(
            CandidateScore.id == score_id,
            CandidateScore.tenant_id == principal.tenant_id,
        )
    )
    if score is None:
        raise ResourceNotFoundError("Candidate score not found.")

    decision = Decision(
        tenant_id=principal.tenant_id,
        score_id=score.id,
        decided_by=principal.user_id,
        decision=payload.decision,
        reason=payload.reason,
        agreed_with_ai=(payload.decision == score.recommendation),
    )
    session.add(decision)
    await session.flush()
    await record_audit_event(
        session=session,
        tenant_id=principal.tenant_id,
        user_id=principal.user_id,
        action="screening.decision_recorded",
        resource_type="candidate_score",
        resource_id=str(score.id),
        details={"decision": payload.decision, "reason": payload.reason},
        request_id=getattr(request.state, "request_id", None),
    )
    await session.commit()
    return DecisionResponse(
        decision_id=decision.id,
        score_id=score.id,
        decision=decision.decision,
    )


@router.post(
    "/verdicts/{verdict_id}/override",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Override a displayed verdict",
)
async def override_verdict(
    verdict_id: uuid.UUID,
    payload: VerdictOverrideRequest,
    request: Request,
    principal: WritePrincipal,
    session: DbSession,
) -> None:
    """Apply a reviewer correction while retaining the original verdict."""
    verdict = await session.scalar(
        select(RequirementVerdict).where(
            RequirementVerdict.id == verdict_id,
            RequirementVerdict.tenant_id == principal.tenant_id,
        )
    )
    if verdict is None:
        raise ResourceNotFoundError("Requirement verdict not found.")

    verdict.override_verdict = payload.verdict
    verdict.override_reason = payload.reason
    verdict.overridden_by = principal.user_id
    verdict.overridden_at = datetime.now(UTC)
    await record_audit_event(
        session=session,
        tenant_id=principal.tenant_id,
        user_id=principal.user_id,
        action="screening.verdict_overridden",
        resource_type="requirement_verdict",
        resource_id=str(verdict.id),
        details={"verdict": payload.verdict, "reason": payload.reason},
        request_id=getattr(request.state, "request_id", None),
    )
    await session.commit()


@router.get(
    "/audit/verify",
    response_model=AuditVerificationResponse,
    summary="Verify the tenant audit chain",
)
async def verify_tenant_audit_chain(
    principal: ReadPrincipal,
    session: DbSession,
) -> AuditVerificationResponse:
    """Check hash links and event content for the caller's tenant only."""
    events = list(
        (
            await session.execute(
                select(AuditEvent)
                .where(AuditEvent.tenant_id == principal.tenant_id)
                .order_by(AuditEvent.id)
            )
        ).scalars()
    )
    invalid_event_id = verify_audit_chain(events)
    return AuditVerificationResponse(
        valid=invalid_event_id is None,
        checked_events=len(events),
        first_invalid_event_id=invalid_event_id,
    )
