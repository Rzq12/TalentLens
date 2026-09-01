"""Focused tests for persisted post-screening advisory insights."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import pytest

from app.agents.agent import AgentResult
from app.agents.interview import InterviewOutput, InterviewQuestion
from app.agents.recommendation import RecommendOutput
from app.agents.skill_gap import SkillGapItem, SkillGapOutput
from app.models import CandidateScore, Requirement, RequirementVerdict
from app.services.screening_insights import persist_score_insights


class _Result:
    def __init__(self, values: list[Any]) -> None:
        self._values = values

    def all(self) -> list[Any]:
        return self._values

    def scalars(self) -> _Result:
        return self

    def __iter__(self) -> Any:
        return iter(self._values)


class _Session:
    def __init__(self, rows: list[tuple[RequirementVerdict, Requirement]]) -> None:
        self.rows = rows
        self.added: list[Any] = []
        self.execute_count = 0

    async def execute(self, statement: Any) -> _Result:
        self.execute_count += 1
        return _Result(self.rows if self.execute_count == 1 else [])

    async def scalar(self, statement: Any) -> None:
        return None

    def add(self, item: Any) -> None:
        self.added.append(item)

    async def flush(self) -> None:
        for item in self.added:
            if getattr(item, "id", None) is None:
                item.id = uuid.uuid4()


class _GapAgent:
    def __init__(self, requirement_id: uuid.UUID) -> None:
        self.requirement_id = requirement_id

    async def run(self, payload: Any, ctx: Any) -> AgentResult[SkillGapOutput]:
        return AgentResult(
            output=SkillGapOutput(
                gaps=[
                    SkillGapItem(
                        requirement_id=str(self.requirement_id),
                        severity="high",
                        gap_type="skill_missing",
                        suggested_probe="Describe your Python API design.",
                        weight=0.8,
                    )
                ]
            )
        )


class _InterviewAgent:
    def __init__(self, requirement_id: uuid.UUID) -> None:
        self.requirement_id = requirement_id

    async def run(self, payload: Any, ctx: Any) -> AgentResult[InterviewOutput]:
        return AgentResult(
            output=InterviewOutput(
                questions=[
                    InterviewQuestion(
                        ordinal=1,
                        question="How would you structure this service?",
                        category="gap_probe",
                        targets_requirement_id=str(self.requirement_id),
                        difficulty="medium",
                        follow_ups=["What trade-off would you make?"],
                    )
                ]
            )
        )


class _RecommendationAgent:
    async def run(self, payload: Any, ctx: Any) -> AgentResult[RecommendOutput]:
        return AgentResult(
            output=RecommendOutput(
                recommendation="advance",
                narrative="The candidate has a manageable skill gap.",
                confidence=0.82,
            )
        )


class _FailingGapAgent:
    async def run(self, payload: Any, ctx: Any) -> AgentResult[SkillGapOutput]:
        raise RuntimeError("provider unavailable")


@pytest.mark.asyncio
async def test_persist_score_insights_writes_valid_agent_outputs() -> None:
    tenant_id = uuid.uuid4()
    score = CandidateScore(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        run_id=uuid.uuid4(),
        candidate_id=uuid.uuid4(),
        overall_score=Decimal("76.00"),
        raw_weighted=Decimal("0.7600"),
        aggregation_formula_version="v1",
    )
    requirement = Requirement(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        rubric_version_id=uuid.uuid4(),
        ordinal=1,
        text="Python",
        category="skill",
        is_must_have=True,
        weight=Decimal("0.8000"),
    )
    verdict = RequirementVerdict(
        tenant_id=tenant_id,
        score_id=score.id,
        requirement_id=requirement.id,
        verdict="partial",
        confidence=0.7,
        weight_at_scoring=Decimal("0.8000"),
        contribution=Decimal("0.4000"),
    )
    session = _Session([(verdict, requirement)])

    await persist_score_insights(
        session=session,
        score=score,
        skill_gap_agent=_GapAgent(requirement.id),
        interview_agent=_InterviewAgent(requirement.id),
        recommendation_agent=_RecommendationAgent(),
    )

    added_names = [item.__class__.__name__ for item in session.added]
    assert added_names == ["SkillGap", "InterviewKit", "InterviewQuestion"]
    assert score.recommendation == "advance"
    assert score.recommendation_confidence == 0.82
    assert score.summary == "The candidate has a manageable skill gap."


@pytest.mark.asyncio
async def test_persist_score_insights_ignores_degraded_agents() -> None:
    tenant_id = uuid.uuid4()
    score = CandidateScore(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        run_id=uuid.uuid4(),
        candidate_id=uuid.uuid4(),
        overall_score=Decimal("76.00"),
        raw_weighted=Decimal("0.7600"),
        aggregation_formula_version="v1",
    )
    session = _Session([])

    await persist_score_insights(
        session=session,
        score=score,
        skill_gap_agent=_GapAgent(uuid.uuid4()),
        interview_agent=_InterviewAgent(uuid.uuid4()),
        recommendation_agent=_RecommendationAgent(),
    )

    assert session.added == []
    assert score.recommendation is None


@pytest.mark.asyncio
async def test_persist_score_insights_degrades_when_an_agent_raises() -> None:
    tenant_id = uuid.uuid4()
    score = CandidateScore(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        run_id=uuid.uuid4(),
        candidate_id=uuid.uuid4(),
        overall_score=Decimal("76.00"),
        raw_weighted=Decimal("0.7600"),
        aggregation_formula_version="v1",
    )
    requirement = Requirement(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        rubric_version_id=uuid.uuid4(),
        ordinal=1,
        text="Python",
        category="skill",
        is_must_have=True,
        weight=Decimal("0.8000"),
    )
    verdict = RequirementVerdict(
        tenant_id=tenant_id,
        score_id=score.id,
        requirement_id=requirement.id,
        verdict="partial",
        confidence=0.7,
        weight_at_scoring=Decimal("0.8000"),
        contribution=Decimal("0.4000"),
    )

    await persist_score_insights(
        session=_Session([(verdict, requirement)]),
        score=score,
        skill_gap_agent=_FailingGapAgent(),
        interview_agent=_InterviewAgent(requirement.id),
        recommendation_agent=_RecommendationAgent(),
    )

    assert score.recommendation == "advance"
