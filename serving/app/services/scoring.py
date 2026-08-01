"""Deterministic scoring: aggregation, evidence verification, cache keys.

Everything in this module is a pure function. Given the same verdicts and the
same rubric, ``aggregate_score`` returns the same number forever — no clock, no
database, no model. That is what makes a score defensible six months later when
a rejected candidate asks how it was reached.

The LLM judge that *produces* verdicts lives elsewhere. This module owns what
happens to a verdict once it exists: how it converts to points, how a must-have
failure caps the total, whether the evidence behind it can be trusted, and what
identity it caches under.

Nothing here defaults on missing or malformed input. A stage that cannot be
completed raises :class:`CoreStageFailedError` rather than substituting a
verdict, because a silent default biases the score in a direction nobody chose.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Final

from app.exceptions import CoreStageFailedError, EvidenceSpanMismatchError
from app.models import Requirement, RubricVersion
from app.services.rubric import ensure_approved_for_scoring

# --------------------------------------------------------------------------- #
# Verdict vocabulary                                                           #
# --------------------------------------------------------------------------- #

VERDICT_MET: Final = "met"
VERDICT_PARTIAL: Final = "partial"
VERDICT_MISSING: Final = "missing"
VERDICT_UNCLEAR: Final = "unclear"

#: Credit each verdict earns, as a fraction of the requirement's weight.
#:
#: ``unclear`` earns nothing, deliberately. A judge that could not tell must not
#: hand out the benefit of the doubt, or an unreadable resume would outscore a
#: readable weak one.
VERDICT_CREDIT: Final[Mapping[str, Decimal]] = {
    VERDICT_MET: Decimal("1.0"),
    VERDICT_PARTIAL: Decimal("0.5"),
    VERDICT_MISSING: Decimal("0.0"),
    VERDICT_UNCLEAR: Decimal("0.0"),
}

VERDICTS: Final[tuple[str, ...]] = tuple(VERDICT_CREDIT)

#: Formula versions this build knows how to evaluate. A rubric stamped with
#: anything else was written by a newer deployment; reinterpreting it under an
#: older formula would publish a score the two versions do not agree on.
SUPPORTED_FORMULA_VERSIONS: Final[frozenset[str]] = frozenset({"v1"})

_SCORE_SCALE: Final = Decimal("100")
_SCORE_QUANTUM: Final = Decimal("0.01")
_WEIGHT_SUM_TOLERANCE: Final = Decimal("0.0001")

#: Separator between cache-key components. A record separator cannot occur in a
#: UUID, a hex digest, or a model identifier, so no amount of text shifted
#: between components can forge another component's boundary.
_KEY_SEPARATOR: Final = "\x1e"


# --------------------------------------------------------------------------- #
# Value objects                                                                #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class Verdict:
    """One judged requirement.

    Attributes:
        requirement_id: The requirement this verdict answers.
        verdict: One of :data:`VERDICTS`.
    """

    requirement_id: uuid.UUID
    verdict: str


@dataclass(frozen=True, slots=True)
class Contribution:
    """What one requirement contributed to the raw score.

    Attributes:
        requirement_id: The requirement scored.
        ordinal: Display position within the rubric.
        text: The criterion as written, so a breakdown reads on its own.
        weight: The requirement's normalized weight.
        is_must_have: Whether failing this caps the total.
        verdict: The verdict applied.
        points: Weight times verdict credit, on the 0-100 scale.
    """

    requirement_id: uuid.UUID
    ordinal: int
    text: str
    weight: Decimal
    is_must_have: bool
    verdict: str
    points: Decimal


@dataclass(frozen=True, slots=True)
class ScoreResult:
    """The outcome of aggregating one candidate against one rubric version.

    Attributes:
        score: Final score, 0-100, after any must-have cap.
        raw_score: Score before the cap, kept so a capped result stays
            explainable rather than looking like a weak match.
        formula_version: The formula the rubric was scored under.
        must_have_failed: Whether any must-have was not met.
        cap_applied: Whether the cap actually lowered the score. Distinct from
            ``must_have_failed``: a must-have can fail while the raw score is
            already below the cap.
        failed_must_have_ids: The must-haves that were not met, in rubric order.
        contributions: Per-requirement breakdown, in rubric order.
    """

    score: Decimal
    raw_score: Decimal
    formula_version: str
    must_have_failed: bool
    cap_applied: bool
    failed_must_have_ids: tuple[uuid.UUID, ...]
    contributions: tuple[Contribution, ...]


# --------------------------------------------------------------------------- #
# Aggregation                                                                  #
# --------------------------------------------------------------------------- #


def _index_verdicts(
    requirements: Sequence[Requirement], verdicts: Sequence[Verdict]
) -> dict[uuid.UUID, str]:
    """Map requirement id to verdict, refusing anything ambiguous.

    Args:
        requirements: The rubric's requirements.
        verdicts: Verdicts to apply, in any order.

    Returns:
        One verdict per requirement id.

    Raises:
        CoreStageFailedError: If a verdict is duplicated, names an unknown
            requirement, carries an unrecognized label, or is missing for some
            requirement. Each of these would otherwise resolve to a guess.
    """
    known = {req.id for req in requirements}
    by_requirement: dict[uuid.UUID, str] = {}

    for verdict in verdicts:
        if verdict.verdict not in VERDICT_CREDIT:
            raise CoreStageFailedError(
                f"Unrecognized verdict {verdict.verdict!r} for requirement "
                f"{verdict.requirement_id}."
            )
        if verdict.requirement_id not in known:
            raise CoreStageFailedError(
                f"Verdict names requirement {verdict.requirement_id}, which is not "
                "part of this rubric version."
            )
        if verdict.requirement_id in by_requirement:
            # Last-one-wins would make the score depend on the order the judge
            # happened to answer in.
            raise CoreStageFailedError(
                f"Duplicate verdict for requirement {verdict.requirement_id}."
            )
        by_requirement[verdict.requirement_id] = verdict.verdict

    unjudged = [str(req.id) for req in requirements if req.id not in by_requirement]
    if unjudged:
        raise CoreStageFailedError(
            "No verdict for requirement(s): " + ", ".join(sorted(unjudged)) + "."
        )

    return by_requirement


def _validate_rubric(rubric: RubricVersion, requirements: Sequence[Requirement]) -> None:
    """Check the rubric is scorable at all.

    Args:
        rubric: The rubric version being scored against.
        requirements: Its requirements.

    Raises:
        ResourceConflictError: If the rubric is not approved.
        CoreStageFailedError: If the formula version is unknown, the rubric is
            empty, a requirement belongs to another version, or the weights do
            not sum to one.
    """
    ensure_approved_for_scoring(rubric)

    if rubric.aggregation_formula_version not in SUPPORTED_FORMULA_VERSIONS:
        raise CoreStageFailedError(
            f"Rubric uses aggregation formula {rubric.aggregation_formula_version!r}, "
            "which this build cannot evaluate."
        )

    if not requirements:
        raise CoreStageFailedError("Rubric version has no requirements to score.")

    foreign = [str(req.id) for req in requirements if req.rubric_version_id != rubric.id]
    if foreign:
        # Scoring one version's verdicts against another's weights yields a
        # number attributable to no rubric at all.
        raise CoreStageFailedError(
            "Requirement(s) belong to a different rubric version: "
            + ", ".join(sorted(foreign))
            + "."
        )

    total = sum((req.weight for req in requirements), start=Decimal(0))
    if abs(total - Decimal(1)) > _WEIGHT_SUM_TOLERANCE:
        raise CoreStageFailedError(
            f"Requirement weights sum to {total}, not 1. The rubric was not normalized."
        )


def aggregate_score(
    *,
    rubric: RubricVersion,
    requirements: Sequence[Requirement],
    verdicts: Sequence[Verdict],
) -> ScoreResult:
    """Combine verdicts into a single defensible score.

    The score is the weighted sum of verdict credit on a 0-100 scale. A
    candidate who fails any must-have cannot exceed the rubric's
    ``must_have_fail_cap``, no matter how strong the rest of the match is. The
    cap is a ceiling only: it never lifts a weaker score up to it.

    Only ``met`` satisfies a must-have. Must-haves are binary by design — if
    partial credit were meaningful for a criterion, it would not have been
    marked must-have.

    Args:
        rubric: The approved rubric version to score against. Supplies the cap
            and the formula version, both stored per version so that changing
            them cannot silently re-rank candidates already scored.
        requirements: The rubric's requirements, with normalized weights.
        verdicts: Exactly one verdict per requirement, in any order.

    Returns:
        The final score with the full breakdown behind it.

    Raises:
        ResourceConflictError: If the rubric is not approved.
        CoreStageFailedError: If the rubric or the verdict set is not scorable.
            Nothing is defaulted; an incomplete input fails the run.
    """
    _validate_rubric(rubric, requirements)
    by_requirement = _index_verdicts(requirements, verdicts)

    ordered = sorted(requirements, key=lambda req: (req.ordinal, str(req.id)))

    contributions: list[Contribution] = []
    failed_must_have_ids: list[uuid.UUID] = []
    raw_score = Decimal(0)

    for req in ordered:
        verdict = by_requirement[req.id]
        points = (req.weight * VERDICT_CREDIT[verdict] * _SCORE_SCALE).quantize(
            _SCORE_QUANTUM, rounding=ROUND_HALF_UP
        )
        raw_score += points

        if req.is_must_have and verdict != VERDICT_MET:
            failed_must_have_ids.append(req.id)

        contributions.append(
            Contribution(
                requirement_id=req.id,
                ordinal=req.ordinal,
                text=req.text,
                weight=req.weight,
                is_must_have=req.is_must_have,
                verdict=verdict,
                points=points,
            )
        )

    must_have_failed = bool(failed_must_have_ids)
    cap = Decimal(rubric.must_have_fail_cap)
    cap_applied = must_have_failed and raw_score > cap
    score = cap if cap_applied else raw_score

    return ScoreResult(
        score=score.quantize(_SCORE_QUANTUM, rounding=ROUND_HALF_UP),
        raw_score=raw_score.quantize(_SCORE_QUANTUM, rounding=ROUND_HALF_UP),
        formula_version=rubric.aggregation_formula_version,
        must_have_failed=must_have_failed,
        cap_applied=cap_applied,
        failed_must_have_ids=tuple(failed_must_have_ids),
        contributions=tuple(contributions),
    )


# --------------------------------------------------------------------------- #
# Evidence verification                                                        #
# --------------------------------------------------------------------------- #


def verify_evidence_span(
    *,
    document_text: str,
    start_char: int,
    end_char: int,
    quoted_text: str,
) -> None:
    """Confirm a cited quote sits verbatim at the offsets it claims.

    Matching the quote *somewhere* in the document is not enough. A judge that
    cites the right words at the wrong offset has not shown it read that part
    of the resume, and a reviewer following the citation would land somewhere
    else. The check is therefore an exact slice comparison, not a search.

    Args:
        document_text: The full source text the offsets index into.
        start_char: Inclusive start offset of the claimed span.
        end_char: Exclusive end offset of the claimed span.
        quoted_text: The text the verdict claims to have quoted.

    Raises:
        EvidenceSpanMismatchError: If the span is empty, inverted, out of
            bounds, or does not hold exactly ``quoted_text``. The message
            reports offsets and lengths only — never document content, which
            may carry candidate PII into a log.
    """
    if not quoted_text:
        # An empty quote matches an empty slice anywhere, which would make
        # evidence-free verdicts trivially "verifiable".
        raise EvidenceSpanMismatchError("Cited evidence is empty.")

    if start_char < 0 or end_char < 0:
        raise EvidenceSpanMismatchError(
            f"Cited span has a negative offset ({start_char}, {end_char})."
        )

    if end_char <= start_char:
        raise EvidenceSpanMismatchError(
            f"Cited span is empty or inverted ({start_char}, {end_char})."
        )

    if end_char > len(document_text):
        raise EvidenceSpanMismatchError(
            f"Cited span ends at {end_char}, past the {len(document_text)}-character "
            "document."
        )

    if document_text[start_char:end_char] != quoted_text:
        raise EvidenceSpanMismatchError(
            f"Cited text does not match the document at offsets "
            f"({start_char}, {end_char})."
        )


# --------------------------------------------------------------------------- #
# Cache keys                                                                   #
# --------------------------------------------------------------------------- #


def retrieval_config_hash(config: Mapping[str, object]) -> str:
    """Digest a retrieval configuration, independent of key order.

    Two runs configured identically must share a verdict cache whatever order
    the settings were assembled in, so the mapping is serialized with sorted
    keys. A key present with a null value is distinct from an absent key,
    because the two can resolve to different defaults downstream.

    Args:
        config: Retrieval settings — top-k, reranker, and similar.

    Returns:
        A SHA-256 hex digest.
    """
    canonical = json.dumps(config, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def verdict_cache_key(
    *,
    resume_version_id: uuid.UUID,
    requirement_id: uuid.UUID,
    rubric_content_hash: str | None,
    judge_prompt_version: str,
    judge_model: str,
    judge_effort: str,
    retrieval_config_hash: str,
) -> str:
    """Derive the cache identity of a single judged requirement.

    Every input that can change a verdict is part of the key. Leaving one out
    would let a stale verdict be served after the thing it depended on moved —
    a re-worded criterion, a new prompt, a different model.

    Components are joined with a record separator rather than concatenated, so
    text shifted from one component to the next cannot forge the same key.

    Args:
        resume_version_id: The exact resume revision judged.
        requirement_id: The criterion judged.
        rubric_content_hash: Digest of the rubric's requirement content.
        judge_prompt_version: Version of the judge prompt template.
        judge_model: Model identifier that produced the verdict.
        judge_effort: Reasoning effort the judge ran at.
        retrieval_config_hash: Digest of the retrieval settings that chose the
            evidence the judge saw.

    Returns:
        A SHA-256 hex digest.

    Raises:
        CoreStageFailedError: If any component is missing or blank. In
            particular a draft rubric has no ``content_hash``, and keying on
            null would collide every edit with verdicts computed before it.
    """
    if not rubric_content_hash:
        raise CoreStageFailedError(
            "Rubric has no content hash; only an approved rubric can be cached against."
        )

    components = {
        "judge_prompt_version": judge_prompt_version,
        "judge_model": judge_model,
        "judge_effort": judge_effort,
        "retrieval_config_hash": retrieval_config_hash,
    }
    blank = sorted(name for name, value in components.items() if not value)
    if blank:
        raise CoreStageFailedError(
            "Cache key component(s) missing: " + ", ".join(blank) + "."
        )

    payload = _KEY_SEPARATOR.join(
        (
            str(resume_version_id),
            str(requirement_id),
            rubric_content_hash,
            judge_prompt_version,
            judge_model,
            judge_effort,
            retrieval_config_hash,
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
