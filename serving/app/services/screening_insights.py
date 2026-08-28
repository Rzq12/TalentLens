"""Persist best-effort insight outputs for completed candidate scores."""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.agent import AgentContext, AgentResult
from app.agents.interview import InterviewInput, InterviewOutput
from app.agents.recommendation import RecommendInput, RecommendOutput
from app.agents.skill_gap import SkillGapInput, SkillGapOutput
from app.models import (
    CandidateScore,
    InterviewKit,
    InterviewQuestion,
    Requirement,
    RequirementVerdict,
    SkillGap,
)

_RECOMMENDATIONS = frozenset({"strong_advance", "advance", "hold", "not_a_fit"})
_SEVERITIES = frozenset({"critical", "high", "medium", "low"})
_GAP_TYPES = frozenset(
    {"skill_missing", "experience_shortfall", "education_gap", "certification_gap"}
)
_QUESTION_CATEGORIES = frozenset({"gap_probe", "claim_verify", "depth", "scenario"})
_DIFFICULTIES = frozenset({"easy", "medium", "hard"})


class SkillGapAnalyst(Protocol):
    """Produces ranked skill gaps from completed verdicts."""

    async def run(
        self, payload: SkillGapInput, ctx: AgentContext
    ) -> AgentResult[SkillGapOutput]: ...


class InterviewDesigner(Protocol):
    """Produces an interview kit from verdicts and skill gaps."""

    async def run(
        self, payload: InterviewInput, ctx: AgentContext
    ) -> AgentResult[InterviewOutput]: ...


class RecommendationAnalyst(Protocol):
    """Produces an advisory hiring recommendation."""

    async def run(
        self, payload: RecommendInput, ctx: AgentContext
    ) -> AgentResult[RecommendOutput]: ...


async def persist_score_insights(
    *,
    session: AsyncSession,
    score: CandidateScore,
    skill_gap_agent: SkillGapAnalyst,
    interview_agent: InterviewDesigner,
    recommendation_agent: RecommendationAnalyst,
) -> None:
    """Generate advisory insights without affecting the completed score."""
    result = await session.execute(
        select(RequirementVerdict, Requirement)
        .join(Requirement, Requirement.id == RequirementVerdict.requirement_id)
        .where(
            RequirementVerdict.tenant_id == score.tenant_id,
            RequirementVerdict.score_id == score.id,
            Requirement.tenant_id == score.tenant_id,
        )
        .order_by(Requirement.ordinal)
    )
    rows: Sequence[tuple[RequirementVerdict, Requirement]] = result.all()
    if not rows:
        return

    existing_kit = await session.scalar(
        select(InterviewKit.id).where(
            InterviewKit.tenant_id == score.tenant_id,
            InterviewKit.score_id == score.id,
        )
    )
    if existing_kit is not None:
        return

    existing_gaps = list(
        (
            await session.execute(
                select(SkillGap).where(
                    SkillGap.tenant_id == score.tenant_id,
                    SkillGap.score_id == score.id,
                )
            )
        ).scalars().all()
    )
    verdicts = [
        {
            "requirement_id": str(requirement.id),
            "verdict": verdict.verdict,
            "confidence": verdict.confidence,
            "weight": float(verdict.weight_at_scoring),
            "is_must_have": requirement.is_must_have,
        }
        for verdict, requirement in rows
    ]
    verdicts_json = json.dumps(verdicts)
    requirement_ids = {str(requirement.id) for _, requirement in rows}
    context = _context(score, "insights")

    try:
        gap_result = await skill_gap_agent.run(
            SkillGapInput(verdicts_json=verdicts_json), context
        )
    except Exception:
        gap_result = None
    gaps: list[dict[str, object]] = [
        {
            "requirement_id": str(gap.requirement_id),
            "severity": gap.severity,
            "gap_type": gap.gap_type,
            "suggested_probe": gap.suggested_probe,
            "weight": gap.weight,
        }
        for gap in existing_gaps
    ]
    if (
        not existing_gaps
        and gap_result is not None
        and gap_result.status == "ok"
        and gap_result.output is not None
    ):
        for gap in gap_result.output.gaps:
            if (
                gap.requirement_id not in requirement_ids
                or gap.severity not in _SEVERITIES
                or gap.gap_type not in _GAP_TYPES
            ):
                continue
            try:
                requirement_id = uuid.UUID(gap.requirement_id)
            except ValueError:
                continue
            item = {
                "requirement_id": str(requirement_id),
                "severity": gap.severity,
                "gap_type": gap.gap_type,
                "suggested_probe": gap.suggested_probe,
                "weight": float(gap.weight),
            }
            gaps.append(item)
            session.add(
                SkillGap(
                    tenant_id=score.tenant_id,
                    score_id=score.id,
                    requirement_id=requirement_id,
                    severity=gap.severity,
                    gap_type=gap.gap_type,
                    suggested_probe=gap.suggested_probe,
                    weight=float(gap.weight),
                )
            )

    try:
        interview_result = await interview_agent.run(
            InterviewInput(verdicts_json=verdicts_json, gaps_json=json.dumps(gaps)), context
        )
    except Exception:
        interview_result = None
    if (
        interview_result is not None
        and interview_result.status == "ok"
        and interview_result.output is not None
    ):
        questions = [
            question
            for question in interview_result.output.questions
            if question.question.strip()
            and question.category in _QUESTION_CATEGORIES
            and question.difficulty in _DIFFICULTIES
            and (
                question.targets_requirement_id is None
                or question.targets_requirement_id in requirement_ids
            )
        ]
        if questions:
            kit = InterviewKit(tenant_id=score.tenant_id, score_id=score.id)
            session.add(kit)
            await session.flush()
            for question in sorted(questions, key=lambda item: item.ordinal):
                target_id = (
                    uuid.UUID(question.targets_requirement_id)
                    if question.targets_requirement_id
                    else None
                )
                session.add(
                    InterviewQuestion(
                        kit_id=kit.id,
                        ordinal=question.ordinal,
                        question=question.question,
                        category=question.category,
                        targets_requirement_id=target_id,
                        difficulty=question.difficulty,
                        rationale=question.rationale,
                        expected_signal=question.expected_signal,
                        follow_ups={"items": question.follow_ups},
                    )
                )

    try:
        recommendation_result = await recommendation_agent.run(
            RecommendInput(
                score_json=json.dumps({"overall_score": float(score.overall_score)}),
                verdicts_json=verdicts_json,
                gaps_json=json.dumps(gaps),
            ),
            context,
        )
    except Exception:
        return
    if recommendation_result.status != "ok" or recommendation_result.output is None:
        return
    recommendation = recommendation_result.output
    if recommendation.recommendation not in _RECOMMENDATIONS:
        return
    if not 0.0 <= recommendation.confidence <= 1.0:
        return
    score.recommendation = recommendation.recommendation
    score.recommendation_confidence = recommendation.confidence
    score.summary = recommendation.narrative or None


def _context(score: CandidateScore, stage: str) -> AgentContext:
    return AgentContext(
        request_id=uuid.uuid4(),
        tenant_id=score.tenant_id,
        run_id=score.run_id,
        pii_tier="T1",
        idempotency_key=f"{score.run_id}:{score.id}:{stage}",
    )
