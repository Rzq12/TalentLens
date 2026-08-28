"""Governance actions over the real PostgreSQL-backed HTTP path."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

pytestmark = pytest.mark.integration


async def _seed_score_and_verdict(tenant_id: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID]:
    from app.db import get_sessionmaker
    from app.models import CandidateScore, Job, Requirement, RequirementVerdict, RubricVersion, ScreeningRun

    job_id = uuid.uuid4()
    rubric_id = uuid.uuid4()
    requirement_id = uuid.uuid4()
    run_id = uuid.uuid4()
    score_id = uuid.uuid4()
    verdict_id = uuid.uuid4()
    async with get_sessionmaker()() as session:
        session.add_all(
            [
                Job(
                    id=job_id,
                    tenant_id=tenant_id,
                    created_by=uuid.uuid4(),
                    title="Backend Engineer",
                    description_raw="Role.",
                ),
                RubricVersion(
                    id=rubric_id,
                    tenant_id=tenant_id,
                    job_id=job_id,
                    version=1,
                    status="approved",
                ),
                Requirement(
                    id=requirement_id,
                    tenant_id=tenant_id,
                    rubric_version_id=rubric_id,
                    text="Python",
                    weight=Decimal("1"),
                ),
                ScreeningRun(
                    id=run_id,
                    tenant_id=tenant_id,
                    job_id=job_id,
                    rubric_version_id=rubric_id,
                ),
                CandidateScore(
                    id=score_id,
                    tenant_id=tenant_id,
                    run_id=run_id,
                    candidate_id=uuid.uuid4(),
                    overall_score=Decimal("85"),
                    raw_weighted=Decimal("0.85"),
                    recommendation="advance",
                ),
                RequirementVerdict(
                    id=verdict_id,
                    tenant_id=tenant_id,
                    score_id=score_id,
                    requirement_id=requirement_id,
                    verdict="met",
                    confidence=0.9,
                    weight_at_scoring=Decimal("1"),
                    contribution=Decimal("1"),
                ),
            ]
        )
        await session.commit()
    return score_id, verdict_id


async def test_external_jwt_can_record_decision_override_and_verify_audit(
    db_client, auth_headers, tenant_id
):
    score_id, verdict_id = await _seed_score_and_verdict(tenant_id)

    decision = await db_client.post(
        f"/api/v1/governance/scores/{score_id}/decisions",
        headers={**auth_headers, "X-Request-ID": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"},
        json={"decision": "advance", "reason": "Strong relevant experience."},
    )
    assert decision.status_code == 201

    override = await db_client.post(
        f"/api/v1/governance/verdicts/{verdict_id}/override",
        headers=auth_headers,
        json={"verdict": "partial", "reason": "Evidence supports a partial match."},
    )
    assert override.status_code == 204

    verification = await db_client.get("/api/v1/governance/audit/verify", headers=auth_headers)
    assert verification.status_code == 200
    assert verification.json() == {
        "valid": True,
        "checked_events": 2,
        "first_invalid_event_id": None,
    }


async def test_governance_rejects_invalid_reason_and_hides_other_tenant_resources(
    db_client, auth_headers, make_token, other_tenant_id
):
    score_id, verdict_id = await _seed_score_and_verdict(other_tenant_id)

    invalid_reason = await db_client.post(
        f"/api/v1/governance/scores/{score_id}/decisions",
        headers=auth_headers,
        json={"decision": "advance", "reason": "no"},
    )
    assert invalid_reason.status_code == 422

    foreign_score = await db_client.post(
        f"/api/v1/governance/scores/{score_id}/decisions",
        headers=auth_headers,
        json={"decision": "advance", "reason": "Strong relevant experience."},
    )
    assert foreign_score.status_code == 404

    foreign_verdict = await db_client.post(
        f"/api/v1/governance/verdicts/{verdict_id}/override",
        headers=auth_headers,
        json={"verdict": "partial", "reason": "Evidence supports a partial match."},
    )
    assert foreign_verdict.status_code == 404
