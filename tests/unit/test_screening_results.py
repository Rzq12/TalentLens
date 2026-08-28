"""Persisted screening-result detail serialization."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import pytest

from app.models import EvidenceSpanRecord, Requirement, RequirementVerdict, SkillGap
from app.routers.screening import _result_details


class _Result:
    """Minimal SQLAlchemy result substitute for ordered query responses."""

    def __init__(self, rows: list[Any], scalar_rows: bool = False) -> None:
        """Store rows and choose scalar or tuple projection."""
        self.rows = rows
        self.scalar_rows = scalar_rows

    def scalars(self) -> _Result:
        """Return this result for scalar iteration."""
        return self

    def __iter__(self) -> Any:
        """Iterate scalar rows."""
        return iter(self.rows)

    def all(self) -> list[Any]:
        """Return tuple rows."""
        return self.rows


class _Session:
    """Returns the pre-arranged gap, question, and verdict query results."""

    def __init__(self, results: list[_Result]) -> None:
        """Store results in expected query order."""
        self.results = results

    async def execute(self, statement: object) -> _Result:
        """Return the next result without interpreting the statement."""
        return self.results.pop(0)


@pytest.mark.asyncio
async def test_result_details_exposes_verified_evidence_and_advisory_insights() -> None:
    """Result details retain explainability while excluding unverified quotes."""
    tenant_id = uuid.uuid4()
    score_id = uuid.uuid4()
    requirement_id = uuid.uuid4()
    gap = SkillGap(
        tenant_id=tenant_id,
        score_id=score_id,
        requirement_id=requirement_id,
        severity="high",
        gap_type="skill_missing",
        suggested_probe="Explain production Kubernetes troubleshooting.",
        weight=0.6,
    )
    requirement = Requirement(
        id=requirement_id,
        tenant_id=tenant_id,
        text="Kubernetes production experience",
        ordinal=1,
        category="skill",
        is_must_have=True,
        weight=Decimal("0.6000"),
    )
    verdict = RequirementVerdict(
        tenant_id=tenant_id,
        score_id=score_id,
        requirement_id=requirement_id,
        verdict="partial",
        confidence=0.8,
        weight_at_scoring=Decimal("0.6000"),
        contribution=Decimal("0.3000"),
        reasoning="Relevant but limited production evidence.",
    )
    verified = EvidenceSpanRecord(
        tenant_id=tenant_id,
        verdict_id=verdict.id,
        resume_version_id=uuid.uuid4(),
        start_char=5,
        end_char=15,
        quoted_text="Kubernetes",
        verbatim_verified=True,
        page=1,
    )
    unverified = EvidenceSpanRecord(
        tenant_id=tenant_id,
        verdict_id=verdict.id,
        resume_version_id=uuid.uuid4(),
        start_char=20,
        end_char=30,
        quoted_text="invented quote",
        verbatim_verified=False,
        page=1,
    )
    session = _Session(
        [
            _Result([gap], scalar_rows=True),
            _Result([]),
            _Result([(verdict, requirement, verified), (verdict, requirement, unverified)]),
        ]
    )

    details = await _result_details(session, tenant_id, [score_id])

    assert details[score_id]["skill_gaps"] == [
        {
            "requirement_id": str(requirement_id),
            "severity": "high",
            "gap_type": "skill_missing",
            "suggested_probe": "Explain production Kubernetes troubleshooting.",
            "weight": 0.6,
        }
    ]
    result_verdict = details[score_id]["verdicts"][0]
    assert result_verdict["requirement"] == "Kubernetes production experience"
    assert result_verdict["evidence"] == [
        {
            "page": 1,
            "start_char": 5,
            "end_char": 15,
            "quoted_text": "Kubernetes",
            "relevance": None,
        }
    ]
