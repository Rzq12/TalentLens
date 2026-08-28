"""Request and response schemas for recruiter governance actions."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field


class DecisionCreateRequest(BaseModel):
    """A human decision recorded against a ranked candidate."""

    decision: str = Field(pattern="^(advance|reject|hold)$")
    reason: str = Field(min_length=3, max_length=2_000)


class VerdictOverrideRequest(BaseModel):
    """A recruiter correction to one model-generated verdict."""

    verdict: str = Field(pattern="^(met|partial|missing|not_applicable)$")
    reason: str = Field(min_length=3, max_length=2_000)


class AuditVerificationResponse(BaseModel):
    """Integrity status for the tenant audit chain."""

    valid: bool
    checked_events: int
    first_invalid_event_id: int | None = None


class DecisionResponse(BaseModel):
    """Persisted human decision metadata."""

    decision_id: uuid.UUID
    score_id: uuid.UUID
    decision: str
