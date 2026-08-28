"""Focused tests for the persisted screening execution slice."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from app.agents.agent import AgentResult
from app.agents.semantic_matching import JudgeOutput, VerdictOutput
from app.config import Settings
from app.models import (
    Candidate,
    CandidateProfile,
    Requirement,
    ResumeVersion,
    RubricVersion,
    ScreeningRun,
)
from app.services.screening import _resolve_quote, execute_screening_run


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
        self.statements: list[Any] = []

    async def execute(self, statement: Any) -> _Result:
        self.statements.append(statement)
        return self.responses.pop(0)

    def add(self, item: Any) -> None:
        self.added.append(item)

    async def flush(self) -> None:
        for item in self.added:
            if getattr(item, "id", None) is None:
                item.id = uuid.uuid4()


class _Judge:
    async def run(self, payload: Any, ctx: Any) -> AgentResult[JudgeOutput]:
        return AgentResult(
            output=JudgeOutput(
                verdicts=[
                    VerdictOutput(
                        requirement_index=requirement.index,
                        verdict="met" if "Python" in requirement.text else "partial",
                        confidence=0.9,
                        reasoning="Supported by resume.",
                        evidence_quote=(
                            "Eight years of Python"
                            if "Python" in requirement.text
                            else None
                        ),
                    )
                    for requirement in payload.requirements
                ]
            ),
            agent_name="semantic_matching",
            agent_version="1.0.0",
            prompt_version="v1",
            model="test-judge",
            provider="gemini",
            input_tokens=11,
            output_tokens=7,
        )


def _version(tenant_id: uuid.UUID, *, quarantined: bool = False) -> ResumeVersion:
    return ResumeVersion(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        document_id=uuid.uuid4(),
        version=1,
        extracted_text="Eight years of Python and systems design.",
        text_sha256="a" * 64,
        page_offsets=[],
        parser_version="test",
        sanitization_report={},
        quarantined=quarantined,
    )


@pytest.mark.asyncio
async def test_execute_screening_run_persists_complete_ranked_scores() -> None:
    tenant_id = uuid.uuid4()
    rubric = RubricVersion(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        job_id=uuid.uuid4(),
        version=1,
        status="approved",
        source="manual",
        content_hash="b" * 64,
        must_have_fail_cap=40,
        aggregation_formula_version="v1",
    )
    requirements = [
        Requirement(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            rubric_version_id=rubric.id,
            ordinal=0,
            text="Python",
            category="skill",
            is_must_have=True,
            weight=Decimal("0.6000"),
        ),
        Requirement(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            rubric_version_id=rubric.id,
            ordinal=1,
            text="Architecture",
            category="skill",
            is_must_have=False,
            weight=Decimal("0.4000"),
        ),
    ]
    candidates = [
        Candidate(
            id=uuid.uuid4(), tenant_id=tenant_id, name="Ada", consent_granted_at=datetime.now(UTC)
        ),
        Candidate(
            id=uuid.uuid4(), tenant_id=tenant_id, name="Lin", consent_granted_at=datetime.now(UTC)
        ),
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
        job_id=rubric.job_id,
        rubric_version_id=rubric.id,
        status="queued",
        mode="interactive",
    )
    session = _Session(
        [
            _Result(requirements),
            _Result(list(zip(candidates, profiles, versions, strict=True))),
            _Result([]),
            _Result([]),
            _Result([]),
            _Result([]),
        ]
    )

    scores = await execute_screening_run(
        session=session, run=run, rubric=rubric, job_title="Backend Engineer", judge=_Judge()
    )

    assert run.status == "completed"
    assert run.completed_at is not None
    assert run.candidate_count == 2
    assert sorted(score.rank for score in scores) == [1, 2]
    assert all(score.overall_score == Decimal("80.00") for score in scores)
    verdicts = [item for item in session.added if item.__class__.__name__ == "RequirementVerdict"]
    assert len(verdicts) == 4
    assert all(verdict.retrieved_chunk_ids is None for verdict in verdicts)
    evidence = [item for item in session.added if item.__class__.__name__ == "EvidenceSpanRecord"]
    assert len(evidence) == 2
    assert all(span.verbatim_verified for span in evidence)
    assert all(span.verdict is not None for span in evidence)
    profile_query = str(session.statements[1]).lower()
    assert "resume_versions.quarantined is false" in profile_query


def test_resolve_quote_returns_exact_unique_offsets() -> None:
    document = "Experience: Eight years of Python and systems design."

    assert _resolve_quote(document, "Eight years of Python") == (12, 33)


@pytest.mark.parametrize("quote", ["", "Not present", "Python"])
def test_resolve_quote_rejects_missing_or_ambiguous_quotes(quote: str) -> None:
    document = "Python developer with Python mentoring experience."

    assert _resolve_quote(document, quote) is None


@pytest.mark.asyncio
async def test_screening_run_accumulates_cost_from_configured_rate_card(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = uuid.uuid4()
    rubric = RubricVersion(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        job_id=uuid.uuid4(),
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
    candidate = Candidate(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        name="Ada",
        consent_granted_at=datetime.now(UTC),
    )
    profile = CandidateProfile(id=uuid.uuid4(), tenant_id=tenant_id, candidate_id=candidate.id)
    version = _version(tenant_id)
    profile.resume_version_id = version.id
    run = ScreeningRun(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        job_id=rubric.job_id,
        rubric_version_id=rubric.id,
        status="queued",
        mode="interactive",
        cost_usd=Decimal("0"),
    )
    session = _Session(
        [
            _Result([requirement]),
            _Result([(candidate, profile, version)]),
            _Result([]),
            _Result([]),
            _Result([]),
        ]
    )
    settings = Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://x/y",
        jwt_secret="s" * 32,
        gemini_input_usd_per_million_tokens="2",
        gemini_output_usd_per_million_tokens="4",
    )
    monkeypatch.setattr("app.services.llm_cost.get_settings", lambda: settings)
    judge = _Judge()

    await execute_screening_run(
        session=session,
        run=run,
        rubric=rubric,
        job_title="Backend Engineer",
        judge=judge,
    )

    assert run.cost_usd == Decimal("0.000050")
