"""Retry semantics for partially completed screening runs."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from app.agents.agent import AgentResult
from app.agents.semantic_matching import JudgeOutput, VerdictOutput
from app.models import (
    Candidate,
    CandidateProfile,
    CandidateScore,
    Requirement,
    ResumeVersion,
    RubricVersion,
    ScreeningRun,
)
from app.services.screening import execute_screening_run


class _Result:
    def __init__(self, values: list[Any]) -> None:
        self._values = values

    def scalars(self) -> _Result:
        return self

    def all(self) -> list[Any]:
        return self._values

    def __iter__(self) -> Any:
        return iter(self._values)


class _Session:
    def __init__(self, responses: list[_Result]) -> None:
        self.responses = responses
        self.added: list[Any] = []

    async def execute(self, statement: Any) -> _Result:
        return self.responses.pop(0)

    def add(self, item: Any) -> None:
        self.added.append(item)

    async def flush(self) -> None:
        for item in self.added:
            if getattr(item, "id", None) is None:
                item.id = uuid.uuid4()


class _Judge:
    def __init__(self) -> None:
        self.calls = 0

    async def run(self, payload: Any, ctx: Any) -> AgentResult[JudgeOutput]:
        self.calls += 1
        return AgentResult(
            output=JudgeOutput(
                verdicts=[
                    VerdictOutput(
                        requirement_index=requirement.index,
                        verdict="met",
                        confidence=0.9,
                    )
                    for requirement in payload.requirements
                ]
            ),
            model="test-judge",
        )


def _version(tenant_id: uuid.UUID) -> ResumeVersion:
    return ResumeVersion(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        document_id=uuid.uuid4(),
        version=1,
        extracted_text="Python experience",
        text_sha256="a" * 64,
        page_offsets=[],
        parser_version="test",
        sanitization_report={},
        quarantined=False,
    )


@pytest.mark.asyncio
async def test_partial_retry_scores_only_remaining_candidate_and_reranks_all() -> None:
    tenant_id = uuid.uuid4()
    job_id = uuid.uuid4()
    rubric = RubricVersion(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        job_id=job_id,
        version=1,
        status="approved",
        source="manual",
        content_hash="b" * 64,
        must_have_fail_cap=40,
        aggregation_formula_version="v1",
    )
    requirement = Requirement(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        rubric_version_id=rubric.id,
        ordinal=0,
        text="Python",
        category="skill",
        is_must_have=True,
        weight=Decimal("1.0000"),
    )
    candidates = [
        Candidate(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            name=name,
            consent_granted_at=datetime.now(UTC),
        )
        for name in ("Ada", "Lin")
    ]
    profiles = [
        CandidateProfile(id=uuid.uuid4(), tenant_id=tenant_id, candidate_id=candidate.id)
        for candidate in candidates
    ]
    versions = [_version(tenant_id), _version(tenant_id)]
    for profile, version in zip(profiles, versions, strict=True):
        profile.resume_version_id = version.id
    run = ScreeningRun(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        job_id=job_id,
        rubric_version_id=rubric.id,
        status="failed",
        mode="interactive",
    )
    existing_score = CandidateScore(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        run_id=run.id,
        candidate_id=candidates[0].id,
        profile_id=profiles[0].id,
        overall_score=Decimal("70.00"),
        raw_weighted=Decimal("0.7000"),
        aggregation_formula_version="v1",
    )
    session = _Session(
        [
            _Result([requirement]),
            _Result(list(zip(candidates, profiles, versions, strict=True))),
            _Result([candidates[0].id]),
            _Result([existing_score]),
            _Result([]),
        ]
    )
    judge = _Judge()

    scores = await execute_screening_run(
        session=session,
        run=run,
        rubric=rubric,
        job_title="Backend Engineer",
        judge=judge,
    )

    assert judge.calls == 1
    assert {score.candidate_id for score in scores} == {candidate.id for candidate in candidates}
    assert sorted(score.rank for score in scores) == [1, 2]
    assert run.funnel_stage_counts == {
        "eligible_profiles": 2,
        "already_scored": 1,
        "judged": 1,
        "scored_total": 2,
    }
    assert len([item for item in session.added if isinstance(item, CandidateScore)]) == 1


@pytest.mark.asyncio
async def test_completed_run_returns_persisted_scores_without_judging() -> None:
    tenant_id = uuid.uuid4()
    run = ScreeningRun(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        job_id=uuid.uuid4(),
        rubric_version_id=uuid.uuid4(),
        status="completed",
        mode="interactive",
    )
    existing_score = CandidateScore(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        run_id=run.id,
        candidate_id=uuid.uuid4(),
        overall_score=Decimal("70.00"),
        raw_weighted=Decimal("0.7000"),
        aggregation_formula_version="v1",
        rank=1,
    )
    session = _Session([_Result([existing_score])])
    judge = _Judge()
    rubric = RubricVersion(
        id=run.rubric_version_id,
        tenant_id=tenant_id,
        job_id=run.job_id,
        version=1,
        status="approved",
        source="manual",
        must_have_fail_cap=40,
        aggregation_formula_version="v1",
    )

    scores = await execute_screening_run(
        session=session,
        run=run,
        rubric=rubric,
        job_title="Backend Engineer",
        judge=judge,
    )

    assert scores == [existing_score]
    assert judge.calls == 0
