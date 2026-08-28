"""Persisted screening vertical slice: candidate pool, judging, aggregation, and ranking."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.agent import AgentContext, AgentResult
from app.agents.semantic_matching import (
    EvidenceChunk,
    JudgeInput,
    JudgeOutput,
    RubricRequirement,
    VerdictOutput,
)
from app.models import (
    Candidate,
    CandidateProfile,
    CandidateScore,
    EvidenceSpanRecord,
    Requirement,
    RequirementVerdict,
    ResumeChunk,
    ResumeVersion,
    RubricVersion,
    ScreeningRun,
)
from app.services.scoring import Verdict, aggregate_score, verify_evidence_span


class Judge(Protocol):
    """The narrow judge contract needed by the screening pipeline."""

    async def run(
        self, payload: JudgeInput, ctx: AgentContext
    ) -> AgentResult[JudgeOutput]: ...


def _batches(items: Sequence[Requirement], size: int = 6) -> list[Sequence[Requirement]]:
    """Split requirements into bounded judge batches."""
    return [items[index : index + size] for index in range(0, len(items), size)]


async def _candidate_profiles(
    session: AsyncSession, tenant_id: uuid.UUID
) -> list[tuple[Candidate, CandidateProfile, ResumeVersion]]:
    """Return each consented candidate's newest non-quarantined resume profile."""
    result = await session.execute(
        select(Candidate, CandidateProfile, ResumeVersion)
        .join(CandidateProfile, CandidateProfile.candidate_id == Candidate.id)
        .join(ResumeVersion, ResumeVersion.id == CandidateProfile.resume_version_id)
        .where(
            Candidate.tenant_id == tenant_id,
            CandidateProfile.tenant_id == tenant_id,
            ResumeVersion.tenant_id == tenant_id,
            Candidate.consent_granted_at.isnot(None),
            ResumeVersion.quarantined.is_(False),
        )
        .order_by(Candidate.id, CandidateProfile.created_at.desc())
    )
    newest: dict[uuid.UUID, tuple[Candidate, CandidateProfile, ResumeVersion]] = {}
    for candidate, profile, version in result.all():
        newest.setdefault(candidate.id, (candidate, profile, version))
    return list(newest.values())


async def _evidence_for_version(
    session: AsyncSession, version: ResumeVersion
) -> tuple[list[EvidenceChunk], list[uuid.UUID]]:
    """Load stored child chunks, falling back to sanitized resume text."""
    result = await session.execute(
        select(ResumeChunk)
        .where(
            ResumeChunk.tenant_id == version.tenant_id,
            ResumeChunk.resume_version_id == version.id,
            ResumeChunk.is_parent.is_(False),
        )
        .order_by(ResumeChunk.chunk_index)
        .limit(12)
    )
    chunks = list(result.scalars().all())
    if not chunks:
        return (
            [
                EvidenceChunk(
                    chunk_id="",
                    content=version.extracted_text,
                    start_char=0,
                    end_char=len(version.extracted_text),
                )
            ],
            [],
        )
    return (
        [
            EvidenceChunk(
                chunk_id=str(chunk.id),
                content=chunk.content,
                section=chunk.section,
                page_from=chunk.page_from,
                page_to=chunk.page_to,
                start_char=chunk.start_char,
                end_char=chunk.end_char,
            )
            for chunk in chunks
        ],
        [chunk.id for chunk in chunks],
    )


async def execute_screening_run(
    *,
    session: AsyncSession,
    run: ScreeningRun,
    rubric: RubricVersion,
    job_title: str,
    judge: Judge,
) -> list[CandidateScore]:
    """Judge all eligible profiles, persist deterministic scores, and assign ranks.

    A judge failure is intentionally raised to the caller: publishing a partial
    ranking would make omitted candidates indistinguishable from weak candidates.
    """
    if run.status == "completed":
        existing = await session.execute(
            select(CandidateScore)
            .where(CandidateScore.run_id == run.id)
            .order_by(CandidateScore.rank)
        )
        return list(existing.scalars().all())

    run.status = "running"
    run.started_at = run.started_at or datetime.now(UTC)
    requirements = list(
        (
            await session.execute(
                select(Requirement)
                .where(
                    Requirement.tenant_id == run.tenant_id,
                    Requirement.rubric_version_id == rubric.id,
                )
                .order_by(Requirement.ordinal, Requirement.id)
            )
        ).scalars().all()
    )
    profiles = await _candidate_profiles(session, run.tenant_id)
    existing_scores = await session.execute(
        select(CandidateScore.candidate_id).where(CandidateScore.run_id == run.id)
    )
    completed_candidates = set(existing_scores.scalars().all())
    profiles_to_score = [
        profile for profile in profiles if profile[0].id not in completed_candidates
    ]
    run.candidate_count = len(profiles)
    run.funnel_stage_counts = {
        "eligible_profiles": len(profiles),
        "already_scored": len(completed_candidates),
        "judged": len(profiles_to_score),
    }
    scores: list[CandidateScore] = list(
        (
            await session.execute(
                select(CandidateScore).where(CandidateScore.run_id == run.id)
            )
        ).scalars().all()
    )

    for candidate, profile, version in profiles_to_score:
        evidence, chunk_ids = await _evidence_for_version(session, version)
        judged: list[tuple[Requirement, VerdictOutput, AgentResult[JudgeOutput]]] = []
        for batch in _batches(requirements):
            payload = JudgeInput(
                requirements=[
                    RubricRequirement(
                        requirement_id=str(requirement.id),
                        index=index,
                        text=requirement.text,
                        category=requirement.category,
                        is_must_have=requirement.is_must_have,
                        weight=float(requirement.weight),
                        min_years=(
                            float(requirement.min_years)
                            if requirement.min_years
                            else None
                        ),
                        min_seniority=requirement.min_seniority,
                    )
                    for index, requirement in enumerate(batch)
                ],
                evidence=evidence,
                resume_version_id=str(version.id),
                rubric_content_hash=rubric.content_hash or "",
                job_title=job_title,
            )
            result = await judge.run(
                payload,
                AgentContext(
                    request_id=uuid.uuid4(),
                    tenant_id=run.tenant_id,
                    run_id=run.id,
                    pii_tier="T1",
                    idempotency_key=f"{run.id}:{candidate.id}:{batch[0].id}",
                ),
            )
            if result.status != "ok" or result.output is None:
                raise RuntimeError(f"Judge failed for candidate {candidate.id}.")
            by_index = {item.requirement_index: item for item in result.output.verdicts}
            if set(by_index) != set(range(len(batch))):
                raise RuntimeError(
                    "Judge returned an incomplete requirement batch for "
                    f"{candidate.id}."
                )
            judged.extend(
                (requirement, by_index[index], result)
                for index, requirement in enumerate(batch)
            )
            run.total_input_tokens = (run.total_input_tokens or 0) + result.input_tokens
            run.total_output_tokens = (
                (run.total_output_tokens or 0) + result.output_tokens
            )

        aggregation = aggregate_score(
            rubric=rubric,
            requirements=requirements,
            verdicts=[
                Verdict(requirement_id=requirement.id, verdict=output.verdict)
                for requirement, output, _ in judged
            ],
        )
        contributions = {item.requirement_id: item for item in aggregation.contributions}
        score = CandidateScore(
            tenant_id=run.tenant_id,
            run_id=run.id,
            candidate_id=candidate.id,
            profile_id=profile.id,
            overall_score=aggregation.score,
            raw_weighted=aggregation.raw_score,
            cap_applied=rubric.must_have_fail_cap if aggregation.cap_applied else None,
            recommendation="advance" if aggregation.score >= Decimal("70") else "review",
            aggregation_formula_version=aggregation.formula_version,
        )
        session.add(score)
        await session.flush()
        for requirement, output, judge_result in judged:
            contribution = contributions[requirement.id]
            verdict = RequirementVerdict(
                tenant_id=run.tenant_id,
                score_id=score.id,
                requirement_id=requirement.id,
                verdict=output.verdict,
                confidence=output.confidence,
                weight_at_scoring=contribution.weight,
                contribution=contribution.points,
                reasoning=output.reasoning or None,
                judge_model=judge_result.model,
                judge_prompt_version=judge_result.prompt_version,
                input_tokens=judge_result.input_tokens,
                output_tokens=judge_result.output_tokens,
                latency_ms=judge_result.latency_ms,
                cache_hit=judge_result.cache_hit,
                retrieved_chunk_ids=chunk_ids or None,
            )
            session.add(verdict)
            quote_range = _resolve_quote(version.extracted_text, output.evidence_quote or "")
            if quote_range:
                session.add(
                    EvidenceSpanRecord(
                        tenant_id=run.tenant_id,
                        verdict=verdict,
                        resume_version_id=version.id,
                        start_char=quote_range[0],
                        end_char=quote_range[1],
                        quoted_text=output.evidence_quote or "",
                        verbatim_verified=True,
                    )
                )
        scores.append(score)

    for rank, score in enumerate(
        sorted(scores, key=lambda row: (-row.overall_score, str(row.candidate_id))),
        start=1,
    ):
        score.rank = rank
    run.funnel_stage_counts["scored_total"] = len(scores)
    run.status = "completed"
    run.completed_at = datetime.now(UTC)
    return scores


def _resolve_quote(document_text: str, quote: str) -> tuple[int, int] | None:
    """Resolve a quote only when it appears exactly once in the resume."""
    if not quote:
        return None
    start = document_text.find(quote)
    if start < 0 or document_text.find(quote, start + 1) >= 0:
        return None
    end = start + len(quote)
    verify_evidence_span(
        document_text=document_text,
        start_char=start,
        end_char=end,
        quoted_text=quote,
    )
    return start, end
