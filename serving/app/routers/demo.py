"""Demo assessment endpoints — unauthenticated sample for the hiring exercise.

Exposes the deterministic Junior Architect assessment without requiring
a database or LLM keys, so reviewers can verify the pipeline from /docs.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.demo.assessment import load_assessment_case, report_as_dict, run_assessment

router = APIRouter(prefix="/demo", tags=["demo"])


@router.get(
    "/assessment/sample",
    summary="Assessment sample input",
    description=(
        "Returns the sample job and five synthetic CV texts used in the hiring exercise."
    ),
)
async def get_assessment_sample() -> dict[str, object]:
    """Return the raw sample case that the demo scores against."""
    job, candidates = load_assessment_case()
    return {
        "job_title": job.title,
        "criteria": [
            {
                "key": criterion.key,
                "label": criterion.label,
                "weight": criterion.weight,
                "terms": list(criterion.terms),
                "minimum_matches": criterion.minimum_matches,
                "minimum_years": criterion.minimum_years,
                "gap_message": criterion.gap_message,
            }
            for criterion in job.criteria
        ],
        "candidates": [
            {"name": candidate.name, "text": candidate.text} for candidate in candidates
        ],
    }


@router.get(
    "/assessment/run",
    summary="Run the sample assessment",
    description=(
        "Scores the five sample CVs against the Junior Architect criteria "
        "with a deterministic weighted rubric, then returns ranked results "
        "with per-criterion evidence and gaps. No database or LLM call."
    ),
)
async def run_assessment_sample() -> dict[str, object]:
    """Score the five sample CVs and return the ranked report."""
    job, candidates = load_assessment_case()
    report = run_assessment(job=job, candidates=candidates)
    return report_as_dict(report)
