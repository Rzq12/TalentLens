"""The deterministic core of rubric versioning.

Three invariants make a score defensible, and they all live here:

* Normalized weights sum to **exactly** 1.0000. Naive division does not achieve
  this — three equal weights quantized to four decimal places sum to 0.9999 —
  so the rounding remainder is distributed rather than discarded.
* ``content_hash`` changes when and only when the criteria change. It is part of
  every verdict cache key, so reordering rows in the editor must not evict a
  cached verdict, while reweighting must.
* An approved rubric is immutable. Editing one mints version N+1 and marks the
  predecessor ``superseded``, leaving prior scores attributable to the criteria
  that produced them.

Persistence is reached only through an injected repository, following the
``index_resume_version`` precedent, so every function here is testable without a
database.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Protocol

from app.exceptions import (
    ResourceConflictError,
    ResourceNotFoundError,
    ValidationFailedError,
)
from app.logging import get_logger
from app.models import Requirement, RubricVersion

if TYPE_CHECKING:
    from app.security import Principal

logger = get_logger(__name__)

# The scale of the `requirements.weight` column, numeric(5,4). Weights are
# reasoned about as integer counts of this quantum so the sum-to-one invariant is
# exact arithmetic rather than a rounding hope.
WEIGHT_QUANTUM = Decimal("0.0001")
WEIGHT_UNITS = 10_000

DEFAULT_MUST_HAVE_FAIL_CAP = 40
DEFAULT_AGGREGATION_FORMULA_VERSION = "v1"

EDITABLE_STATUS = "draft"
APPROVED_STATUS = "approved"
SUPERSEDED_STATUS = "superseded"


class RubricRepository(Protocol):
    """Persistence contract the rubric service depends on.

    Declared as a Protocol so the service never imports a session-bound class,
    which is what lets these functions be tested against an in-memory double.
    """

    async def add_version(self, version: RubricVersion) -> RubricVersion:
        """Persist a rubric version and return it."""
        ...

    async def get_version(
        self, tenant_id: uuid.UUID, rubric_version_id: uuid.UUID
    ) -> RubricVersion | None:
        """Return one version scoped to the tenant, or None."""
        ...

    async def max_version_for_job(self, tenant_id: uuid.UUID, job_id: uuid.UUID) -> int:
        """Return the highest version number minted for a job, or 0."""
        ...

    async def replace_requirements(
        self,
        tenant_id: uuid.UUID,
        rubric_version_id: uuid.UUID,
        requirements: list[Requirement],
    ) -> None:
        """Replace the whole requirement set for one version."""
        ...

    async def list_requirements(
        self, tenant_id: uuid.UUID, rubric_version_id: uuid.UUID
    ) -> list[Requirement]:
        """Return the stored requirements for one version, in order."""
        ...


# ---------------------------------------------------------------------------
# pure functions
# ---------------------------------------------------------------------------


def normalize_weights(weights: list[Decimal]) -> list[Decimal]:
    """Scale relative weights so they sum to exactly ``Decimal("1.0000")``.

    Callers submit weights as relative importance — ``[3, 1]`` means "the first
    matters three times as much". Storage holds the normalized form so two
    readers of the same row cannot disagree about what the rubric weighs.

    The arithmetic is done in integer units of 0.0001 to keep the invariant
    exact. Dividing 1 by 3 and quantizing gives 0.3333, and three of those sum
    to 0.9999 — a candidate scoring full marks everywhere would total 99.99. The
    leftover units are handed to the largest weights (ties broken by position),
    so the shortfall lands where it distorts the proportions least.

    Args:
        weights: Non-empty list of non-negative relative weights.

    Returns:
        Weights quantized to four decimal places, summing to exactly 1.0000,
        in the same order as the input.

    Raises:
        ValidationFailedError: If the list is empty, any weight is negative, or
            the total is zero.
    """
    if not weights:
        raise ValidationFailedError("A rubric must have at least one requirement.")
    if any(w < 0 for w in weights):
        raise ValidationFailedError("Requirement weights cannot be negative.")

    total = sum(weights, Decimal(0))
    if total == 0:
        raise ValidationFailedError("Requirement weights cannot all be zero.")

    # Floor each share to a whole quantum, then hand the remaining units out.
    # Flooring first guarantees the remainder is non-negative and smaller than
    # the number of weights, so a single pass distributes it.
    exact_units = [(w * WEIGHT_UNITS) / total for w in weights]
    floored = [int(u) for u in exact_units]
    remainder = WEIGHT_UNITS - sum(floored)

    # Largest fractional part first — standard largest-remainder apportionment.
    # `index` is the tiebreaker so the result is deterministic for equal weights,
    # which matters because `content_hash` is computed from these numbers.
    order = sorted(
        range(len(weights)),
        key=lambda i: (-(exact_units[i] - floored[i]), i),
    )
    for i in order[:remainder]:
        floored[i] += 1

    return [Decimal(units) * WEIGHT_QUANTUM for units in floored]


def compute_content_hash(requirements: list[Requirement]) -> str:
    """Fingerprint a requirement set for use as a verdict cache key.

    The digest covers what is being assessed and how heavily — text, weight,
    must-have flag, category, and the seniority and experience floors. It
    deliberately excludes ``ordinal``, ``id``, and timestamps: dragging a row in
    the editor changes the display order, not the criteria, and evicting every
    cached verdict for a cosmetic move would force a full re-score.

    Args:
        requirements: The requirements to fingerprint, in any order.

    Returns:
        A 64-character lowercase hex SHA-256 digest.
    """
    fingerprints = sorted(
        json.dumps(
            {
                "text": requirement.text.strip(),
                "category": requirement.category,
                "is_must_have": bool(requirement.is_must_have),
                "weight": str(Decimal(requirement.weight).quantize(WEIGHT_QUANTUM)),
                "min_years": None if requirement.min_years is None else str(requirement.min_years),
                "min_seniority": requirement.min_seniority,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        for requirement in requirements
    )
    payload = "\n".join(fingerprints).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def ensure_editable(version: RubricVersion) -> None:
    """Raise unless the rubric is still a draft.

    Args:
        version: The rubric version being edited.

    Raises:
        ResourceConflictError: If the rubric is approved or superseded. An
            approved rubric is the record of a decision; rewriting it in place
            would change what past candidates were judged by.
    """
    if version.status != EDITABLE_STATUS:
        raise ResourceConflictError(
            f"Rubric version {version.version} is {version.status} and cannot be edited. "
            "Create a new version instead."
        )


def ensure_approved_for_scoring(version: RubricVersion) -> None:
    """Raise unless the rubric is approved.

    Args:
        version: The rubric version scoring would run against.

    Raises:
        ResourceConflictError: If the rubric is a draft or superseded. Scoring
            against unreviewed criteria, or against retired ones, produces a
            verdict nobody signed off on.
    """
    if version.status != APPROVED_STATUS:
        raise ResourceConflictError(
            f"Rubric version {version.version} is {version.status}; "
            "scoring requires an approved rubric."
        )


# ---------------------------------------------------------------------------
# orchestration
# ---------------------------------------------------------------------------


async def _load_version(
    rubric_repo: RubricRepository, principal: Principal, rubric_version_id: uuid.UUID
) -> RubricVersion:
    """Load a rubric version scoped to the caller's tenant.

    Args:
        rubric_repo: Rubric persistence.
        principal: The authenticated caller.
        rubric_version_id: Version to load.

    Returns:
        The rubric version.

    Raises:
        ResourceNotFoundError: If no such version exists for this tenant. A
            cross-tenant id yields the same 404 as an unknown one — a 403 would
            confirm the rubric exists, leaking that another tenant holds that
            identifier.
    """
    version = await rubric_repo.get_version(principal.tenant_id, rubric_version_id)
    if version is None:
        raise ResourceNotFoundError("Rubric version not found.")
    return version


def _rescope(
    requirements: list[Requirement],
    *,
    tenant_id: uuid.UUID,
    rubric_version_id: uuid.UUID,
) -> list[Requirement]:
    """Attach a requirement set to one tenant and version, with normalized weights.

    Args:
        requirements: Requirements as supplied by the caller, in display order.
        tenant_id: Tenant the requirements must belong to.
        rubric_version_id: Version the requirements must belong to.

    Returns:
        The same requirement objects, renumbered from 0 and reweighted to sum to
        exactly 1.0000.

    Raises:
        ValidationFailedError: If the set is empty or its weights are invalid.
    """
    normalized = normalize_weights([Decimal(r.weight) for r in requirements])
    for ordinal, (requirement, weight) in enumerate(zip(requirements, normalized, strict=True)):
        requirement.tenant_id = tenant_id
        requirement.rubric_version_id = rubric_version_id
        requirement.ordinal = ordinal
        requirement.weight = weight
    return requirements


async def create_draft_rubric(
    *,
    rubric_repo: RubricRepository,
    principal: Principal,
    job_id: uuid.UUID,
    requirements: list[Requirement],
    source: str = "manual",
) -> RubricVersion:
    """Create the next draft rubric for a job.

    Args:
        rubric_repo: Rubric persistence.
        principal: The authenticated caller; supplies the owning tenant.
        job_id: Job the rubric belongs to.
        requirements: The criteria, in display order, with relative weights.
        source: How the criteria were produced — ``extracted``, ``manual``, or
            ``template``.

    Returns:
        The persisted draft rubric version.

    Raises:
        ValidationFailedError: If the requirement set is empty or its weights
            are invalid.
    """
    if not requirements:
        raise ValidationFailedError("A rubric must have at least one requirement.")

    next_version = await rubric_repo.max_version_for_job(principal.tenant_id, job_id) + 1
    version = RubricVersion(
        id=uuid.uuid4(),
        tenant_id=principal.tenant_id,
        job_id=job_id,
        version=next_version,
        status=EDITABLE_STATUS,
        must_have_fail_cap=DEFAULT_MUST_HAVE_FAIL_CAP,
        aggregation_formula_version=DEFAULT_AGGREGATION_FORMULA_VERSION,
        source=source,
    )
    await rubric_repo.add_version(version)
    await rubric_repo.replace_requirements(
        principal.tenant_id,
        version.id,
        _rescope(requirements, tenant_id=principal.tenant_id, rubric_version_id=version.id),
    )

    logger.info(
        "rubric_draft_created",
        tenant_id=str(principal.tenant_id),
        job_id=str(job_id),
        rubric_version_id=str(version.id),
        version=next_version,
        requirement_count=len(requirements),
        source=source,
    )
    return version


async def update_draft_requirements(
    *,
    rubric_repo: RubricRepository,
    principal: Principal,
    rubric_version_id: uuid.UUID,
    requirements: list[Requirement],
) -> RubricVersion:
    """Replace the requirement set of a draft rubric.

    Args:
        rubric_repo: Rubric persistence.
        principal: The authenticated caller.
        rubric_version_id: Draft to edit.
        requirements: The replacement criteria, in display order.

    Returns:
        The rubric version that was edited.

    Raises:
        ResourceNotFoundError: If the version does not exist for this tenant.
        ResourceConflictError: If the version is no longer a draft.
        ValidationFailedError: If the requirement set is empty or its weights
            are invalid.
    """
    version = await _load_version(rubric_repo, principal, rubric_version_id)
    ensure_editable(version)

    if not requirements:
        raise ValidationFailedError("A rubric must have at least one requirement.")

    await rubric_repo.replace_requirements(
        principal.tenant_id,
        version.id,
        _rescope(requirements, tenant_id=principal.tenant_id, rubric_version_id=version.id),
    )

    logger.info(
        "rubric_draft_updated",
        tenant_id=str(principal.tenant_id),
        rubric_version_id=str(version.id),
        requirement_count=len(requirements),
    )
    return version


async def approve_rubric(
    *,
    rubric_repo: RubricRepository,
    principal: Principal,
    rubric_version_id: uuid.UUID,
) -> RubricVersion:
    """Freeze a draft rubric and record who signed off on it.

    The content hash is computed here, at the moment the criteria stop changing,
    because it is the verdict cache key — deriving it lazily at score time would
    let a later read disagree with an earlier one.

    Args:
        rubric_repo: Rubric persistence.
        principal: The authenticated caller; recorded as the approver.
        rubric_version_id: Draft to approve.

    Returns:
        The approved rubric version.

    Raises:
        ResourceNotFoundError: If the version does not exist for this tenant.
        ResourceConflictError: If the version is not a draft. Re-approving would
            silently rewrite an existing audit record.
        ValidationFailedError: If the rubric has no requirements to freeze.
    """
    version = await _load_version(rubric_repo, principal, rubric_version_id)
    ensure_editable(version)

    requirements = await rubric_repo.list_requirements(principal.tenant_id, version.id)
    if not requirements:
        raise ValidationFailedError("A rubric cannot be approved with no requirements.")

    version.content_hash = compute_content_hash(requirements)
    version.status = APPROVED_STATUS
    version.approved_by = principal.user_id
    version.approved_at = datetime.now(UTC)

    logger.info(
        "rubric_approved",
        tenant_id=str(principal.tenant_id),
        rubric_version_id=str(version.id),
        version=version.version,
        content_hash=version.content_hash,
        requirement_count=len(requirements),
    )
    return version


async def mint_next_version(
    *,
    rubric_repo: RubricRepository,
    principal: Principal,
    rubric_version_id: uuid.UUID,
) -> RubricVersion:
    """Fork an approved rubric into an editable successor.

    This is how an approved rubric is "edited": the predecessor is retired as
    ``superseded`` and a new draft starts from a copy of its criteria, so scores
    already computed stay attributable to the version that produced them.

    Args:
        rubric_repo: Rubric persistence.
        principal: The authenticated caller.
        rubric_version_id: The approved version to fork.

    Returns:
        The new draft rubric version.

    Raises:
        ResourceNotFoundError: If the version does not exist for this tenant.
        ResourceConflictError: If the version is not approved. A draft is
            already editable, and forking it would orphan the work in progress.
        ValidationFailedError: If the predecessor has no requirements to copy.
    """
    predecessor = await _load_version(rubric_repo, principal, rubric_version_id)
    if predecessor.status != APPROVED_STATUS:
        raise ResourceConflictError(
            f"Rubric version {predecessor.version} is {predecessor.status}; "
            "only an approved rubric can be superseded."
        )

    existing = await rubric_repo.list_requirements(principal.tenant_id, predecessor.id)
    if not existing:
        raise ValidationFailedError("The rubric being superseded has no requirements to copy.")

    next_version = (
        await rubric_repo.max_version_for_job(principal.tenant_id, predecessor.job_id) + 1
    )
    successor = RubricVersion(
        id=uuid.uuid4(),
        tenant_id=principal.tenant_id,
        job_id=predecessor.job_id,
        version=next_version,
        status=EDITABLE_STATUS,
        must_have_fail_cap=predecessor.must_have_fail_cap,
        aggregation_formula_version=predecessor.aggregation_formula_version,
        source=predecessor.source,
    )
    await rubric_repo.add_version(successor)
    await rubric_repo.replace_requirements(
        principal.tenant_id,
        successor.id,
        _rescope(
            [_copy_requirement(r) for r in existing],
            tenant_id=principal.tenant_id,
            rubric_version_id=successor.id,
        ),
    )

    # Retire the predecessor only after the successor exists, so a failure part
    # way through cannot leave the job with no editable rubric.
    predecessor.status = SUPERSEDED_STATUS

    logger.info(
        "rubric_version_minted",
        tenant_id=str(principal.tenant_id),
        job_id=str(predecessor.job_id),
        superseded_version_id=str(predecessor.id),
        rubric_version_id=str(successor.id),
        version=next_version,
        requirement_count=len(existing),
    )
    return successor


def _copy_requirement(requirement: Requirement) -> Requirement:
    """Clone a requirement as a new unsaved row.

    Args:
        requirement: The requirement to copy.

    Returns:
        A new `Requirement` with a fresh id and no version binding. Tenant,
        version, ordinal, and weight are set by `_rescope`.
    """
    return Requirement(
        id=uuid.uuid4(),
        tenant_id=requirement.tenant_id,
        rubric_version_id=requirement.rubric_version_id,
        ordinal=requirement.ordinal,
        text=requirement.text,
        category=requirement.category,
        is_must_have=requirement.is_must_have,
        weight=requirement.weight,
        min_years=requirement.min_years,
        min_seniority=requirement.min_seniority,
        skill_id=requirement.skill_id,
        embedding=requirement.embedding,
    )
