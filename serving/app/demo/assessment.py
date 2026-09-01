"""Deterministic CV ranking for the five-candidate assessment demo.

This deliberately stays smaller than the production pipeline. It demonstrates
parseable input, transparent weighted criteria, evidence, ranking, and human
review without requiring a database or paid LLM API.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

_CASE_PATH = (
    Path(__file__).resolve().parents[3]
    / "examples"
    / "assessment"
    / "junior_architect_case.json"
)
_YEAR_PATTERN = re.compile(r"(?P<years>\d+(?:\.\d+)?)\s*\+?\s*years?", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class Criterion:
    """One transparent scoring criterion."""

    key: str
    label: str
    weight: float
    terms: tuple[str, ...]
    minimum_matches: int
    gap_message: str
    minimum_years: float | None = None


@dataclass(frozen=True, slots=True)
class JobCase:
    """Job title and its approved assessment criteria."""

    title: str
    criteria: tuple[Criterion, ...]


@dataclass(frozen=True, slots=True)
class CandidateCase:
    """One synthetic candidate used only by the demo."""

    name: str
    text: str


@dataclass(frozen=True, slots=True)
class CriterionResult:
    """How one candidate matched one criterion."""

    criterion_key: str
    label: str
    weight: float
    match_ratio: float
    weighted_points: float
    evidence: tuple[str, ...]
    gap: str | None


@dataclass(frozen=True, slots=True)
class CandidateResult:
    """Explainable candidate score and recruiter-facing summary."""

    rank: int
    candidate_name: str
    score: float
    status: str
    strengths: tuple[str, ...]
    gaps: tuple[str, ...]
    breakdown: tuple[CriterionResult, ...]


@dataclass(frozen=True, slots=True)
class AssessmentReport:
    """Ranked output for one job."""

    job_title: str
    candidate_count: int
    results: tuple[CandidateResult, ...]


def load_assessment_case(path: Path = _CASE_PATH) -> tuple[JobCase, tuple[CandidateCase, ...]]:
    """Load the synthetic Junior Architect case from JSON."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    job_raw = raw["job"]
    criteria = tuple(
        Criterion(
            key=item["key"],
            label=item["label"],
            weight=float(item["weight"]),
            terms=tuple(item["terms"]),
            minimum_matches=int(item["minimum_matches"]),
            minimum_years=(
                float(item["minimum_years"])
                if item.get("minimum_years") is not None
                else None
            ),
            gap_message=item["gap_message"],
        )
        for item in job_raw["criteria"]
    )
    if round(sum(item.weight for item in criteria), 6) != 1.0:
        raise ValueError("Assessment criterion weights must sum to 1.0.")

    job = JobCase(title=job_raw["title"], criteria=criteria)
    candidates = tuple(
        CandidateCase(name=item["name"], text=item["text"])
        for item in raw["candidates"]
    )
    return job, candidates


def _years_evidenced(text: str) -> float:
    """Return the highest explicit year count in candidate text."""
    values = [float(match.group("years")) for match in _YEAR_PATTERN.finditer(text)]
    return max(values, default=0.0)


def _score_criterion(candidate: CandidateCase, criterion: Criterion) -> CriterionResult:
    text_lower = candidate.text.casefold()
    matched = tuple(term for term in criterion.terms if term.casefold() in text_lower)
    term_ratio = min(len(matched) / max(criterion.minimum_matches, 1), 1.0)
    evidence = matched

    if criterion.minimum_years is not None:
        years = _years_evidenced(candidate.text)
        years_ratio = min(years / criterion.minimum_years, 1.0)
        match_ratio = (term_ratio + years_ratio) / 2
        evidence = (*evidence, f"{years:g} years explicitly stated")
    else:
        match_ratio = term_ratio

    match_ratio = round(match_ratio, 4)
    weighted_points = round(match_ratio * criterion.weight * 100, 2)
    gap = criterion.gap_message if match_ratio < 1.0 else None
    if not evidence:
        evidence = ("No matching evidence found in the CV text.",)

    return CriterionResult(
        criterion_key=criterion.key,
        label=criterion.label,
        weight=criterion.weight,
        match_ratio=match_ratio,
        weighted_points=weighted_points,
        evidence=evidence,
        gap=gap,
    )


def _status_for_score(score: float) -> str:
    if score >= 80:
        return "Strong Match"
    if score >= 60:
        return "Potential Match"
    return "Needs Review"


def _score_candidate(job: JobCase, candidate: CandidateCase) -> CandidateResult:
    breakdown = tuple(_score_criterion(candidate, criterion) for criterion in job.criteria)
    score = round(sum(item.weighted_points for item in breakdown), 2)
    strongest = sorted(breakdown, key=lambda item: (-item.match_ratio, -item.weight))[:3]
    gaps = tuple(item.gap for item in breakdown if item.gap is not None)

    return CandidateResult(
        rank=0,
        candidate_name=candidate.name,
        score=score,
        status=_status_for_score(score),
        strengths=tuple(item.label for item in strongest if item.match_ratio > 0),
        gaps=gaps or ("No material gap identified from the supplied CV text.",),
        breakdown=breakdown,
    )


def run_assessment(
    *, job: JobCase, candidates: tuple[CandidateCase, ...]
) -> AssessmentReport:
    """Score, rank, and explain all candidates deterministically."""
    scored = [_score_candidate(job, candidate) for candidate in candidates]
    ordered = sorted(scored, key=lambda item: (-item.score, item.candidate_name))
    ranked = tuple(
        CandidateResult(
            rank=index,
            candidate_name=item.candidate_name,
            score=item.score,
            status=item.status,
            strengths=item.strengths,
            gaps=item.gaps,
            breakdown=item.breakdown,
        )
        for index, item in enumerate(ordered, start=1)
    )
    return AssessmentReport(
        job_title=job.title,
        candidate_count=len(ranked),
        results=ranked,
    )


def report_as_dict(report: AssessmentReport) -> dict[str, object]:
    """Return a JSON-serializable report."""
    return asdict(report)
