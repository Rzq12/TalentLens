"""Tests for the deterministic rubric core.

These are the guards that make a score defensible: weights that sum to exactly
one, a content hash that changes when and only when the criteria change, and an
approved rubric that cannot be mutated in place.

The pure functions are tested directly and need no database. The orchestration
functions take an injected repository, following the `index_resume_version`
precedent, so they are tested against a recording fake.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest

from app.exceptions import (
    ResourceConflictError,
    ResourceNotFoundError,
    ValidationFailedError,
)
from app.security import Principal

if TYPE_CHECKING:
    from app.models import Requirement, RubricVersion

_TENANT = uuid.UUID("11111111-1111-1111-1111-111111111111")
_OTHER_TENANT = uuid.UUID("22222222-2222-2222-2222-222222222222")
_USER = uuid.UUID("33333333-3333-3333-3333-333333333333")


def _principal(tenant_id: uuid.UUID = _TENANT) -> Principal:
    """Build a recruiter principal.

    Args:
        tenant_id: Owning tenant for the caller.

    Returns:
        A `Principal` holding the `recruiter` role.
    """
    return Principal(user_id=_USER, tenant_id=tenant_id, roles=("recruiter",))


def _draft(**overrides: object) -> RubricVersion:
    """Build an unsaved draft `RubricVersion`.

    Args:
        **overrides: Column values to replace in the baseline row.

    Returns:
        An unsaved `RubricVersion` in `draft` status.
    """
    from app.models import RubricVersion

    fields: dict[str, object] = {
        "id": uuid.uuid4(),
        "tenant_id": uuid.uuid4(),
        "job_id": uuid.uuid4(),
        "version": 1,
        "status": "draft",
        "must_have_fail_cap": 40,
        "aggregation_formula_version": "v1",
        "source": "manual",
    }
    fields.update(overrides)
    return RubricVersion(**fields)


def _requirement(
    text: str, weight: str, *, must_have: bool = False, ordinal: int = 0
) -> Requirement:
    """Build an unsaved `Requirement`.

    Args:
        text: The requirement text.
        weight: Weight as a decimal string.
        must_have: Whether the requirement is a hard gate.
        ordinal: Display order within the rubric.

    Returns:
        An unsaved `Requirement`.
    """
    from app.models import Requirement

    return Requirement(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        rubric_version_id=uuid.uuid4(),
        ordinal=ordinal,
        text=text,
        category="skill",
        is_must_have=must_have,
        weight=Decimal(weight),
    )


# --------------------------------------------------------------------------
# normalize_weights
# --------------------------------------------------------------------------


def test_normalize_weights_scales_arbitrary_positives_to_one() -> None:
    """Raw weights are relative; only their proportions carry meaning."""
    from app.services.rubric import normalize_weights

    result = normalize_weights([Decimal("3"), Decimal("1")])

    assert sum(result) == Decimal("1.0000")
    assert result[0] == Decimal("0.7500")
    assert result[1] == Decimal("0.2500")


def test_normalize_weights_sums_to_exactly_one_for_three_equal_weights() -> None:
    """Three equal weights must still sum to exactly 1.0000.

    This is the case naive division gets wrong: 1/3 quantized to four decimal
    places is 0.3333, and three of those sum to 0.9999. The remainder has to be
    distributed, or a candidate scoring full marks on every requirement would
    total 99.99 instead of 100.
    """
    from app.services.rubric import normalize_weights

    result = normalize_weights([Decimal("1"), Decimal("1"), Decimal("1")])

    assert sum(result) == Decimal("1.0000"), f"weights sum to {sum(result)}, not 1"
    assert all(w.as_tuple().exponent >= -4 for w in result)


def test_normalize_weights_sums_to_exactly_one_for_seven_equal_weights() -> None:
    """A prime count is the harshest rounding case; it must still total one."""
    from app.services.rubric import normalize_weights

    result = normalize_weights([Decimal("1")] * 7)

    assert sum(result) == Decimal("1.0000")


def test_normalize_weights_leaves_already_normalized_weights_alone() -> None:
    """Normalization is idempotent, so re-saving a rubric does not drift."""
    from app.services.rubric import normalize_weights

    once = normalize_weights([Decimal("2"), Decimal("1"), Decimal("1")])
    twice = normalize_weights(once)

    assert once == twice
    assert sum(twice) == Decimal("1.0000")


def test_normalize_weights_rejects_an_empty_requirement_set() -> None:
    """A rubric with no requirements cannot score anything."""
    from app.services.rubric import normalize_weights

    with pytest.raises(ValidationFailedError):
        normalize_weights([])


def test_normalize_weights_rejects_a_zero_total() -> None:
    """An all-zero set has no proportions to preserve and would divide by zero."""
    from app.services.rubric import normalize_weights

    with pytest.raises(ValidationFailedError):
        normalize_weights([Decimal("0"), Decimal("0")])


def test_normalize_weights_rejects_a_negative_weight() -> None:
    """A negative weight would let a matched requirement lower the score."""
    from app.services.rubric import normalize_weights

    with pytest.raises(ValidationFailedError):
        normalize_weights([Decimal("1"), Decimal("-1")])


def test_normalize_weights_preserves_a_single_requirement_as_full_weight() -> None:
    """One requirement carries the whole score."""
    from app.services.rubric import normalize_weights

    assert normalize_weights([Decimal("5")]) == [Decimal("1.0000")]


# --------------------------------------------------------------------------
# compute_content_hash
# --------------------------------------------------------------------------


def test_compute_content_hash_returns_sixty_four_hex_chars() -> None:
    """The hash must fit the `char(64)` column that stores it."""
    from app.services.rubric import compute_content_hash

    digest = compute_content_hash([_requirement("Python", "1.0000")])

    assert len(digest) == 64
    assert all(c in "0123456789abcdef" for c in digest)


def test_compute_content_hash_is_stable_across_calls() -> None:
    """An unchanged rubric must not invalidate its own verdict cache."""
    from app.services.rubric import compute_content_hash

    reqs = [_requirement("Python", "0.6000"), _requirement("Kubernetes", "0.4000")]

    assert compute_content_hash(reqs) == compute_content_hash(reqs)


def test_compute_content_hash_ignores_requirement_ordering() -> None:
    """Reordering the display order does not change what is being assessed.

    If it did, dragging a row in the editor would evict every cached verdict for
    that job and force a full re-score.
    """
    from app.services.rubric import compute_content_hash

    a = _requirement("Python", "0.6000", ordinal=0)
    b = _requirement("Kubernetes", "0.4000", ordinal=1)

    assert compute_content_hash([a, b]) == compute_content_hash([b, a])


def test_compute_content_hash_changes_when_text_changes() -> None:
    """Different criteria must produce a different cache key."""
    from app.services.rubric import compute_content_hash

    before = compute_content_hash([_requirement("Python", "1.0000")])
    after = compute_content_hash([_requirement("Rust", "1.0000")])

    assert before != after


def test_compute_content_hash_changes_when_weight_changes() -> None:
    """Reweighting changes the score, so it must change the cache key."""
    from app.services.rubric import compute_content_hash

    before = compute_content_hash(
        [_requirement("Python", "0.6000"), _requirement("Go", "0.4000")]
    )
    after = compute_content_hash(
        [_requirement("Python", "0.7000"), _requirement("Go", "0.3000")]
    )

    assert before != after


def test_compute_content_hash_changes_when_must_have_flag_flips() -> None:
    """A must-have gate can zero a candidate, so it belongs in the hash."""
    from app.services.rubric import compute_content_hash

    soft = compute_content_hash([_requirement("Python", "1.0000", must_have=False)])
    hard = compute_content_hash([_requirement("Python", "1.0000", must_have=True)])

    assert soft != hard


# --------------------------------------------------------------------------
# immutability and the scoring gate
# --------------------------------------------------------------------------


def test_ensure_editable_allows_a_draft() -> None:
    """A draft is the only editable state."""
    from app.services.rubric import ensure_editable

    ensure_editable(_draft())


def test_ensure_editable_rejects_an_approved_rubric() -> None:
    """An approved rubric is immutable — a past decision cannot be rewritten."""
    from app.services.rubric import ensure_editable

    with pytest.raises(ResourceConflictError):
        ensure_editable(_draft(status="approved"))


def test_ensure_editable_rejects_a_superseded_rubric() -> None:
    """A superseded version is history; edits belong on the current draft."""
    from app.services.rubric import ensure_editable

    with pytest.raises(ResourceConflictError):
        ensure_editable(_draft(status="superseded"))


def test_ensure_approved_for_scoring_rejects_a_draft_with_409() -> None:
    """Scoring against unreviewed criteria is the failure this gate prevents."""
    from app.services.rubric import ensure_approved_for_scoring

    with pytest.raises(ResourceConflictError) as caught:
        ensure_approved_for_scoring(_draft())

    assert caught.value.status_code == 409


def test_ensure_approved_for_scoring_allows_an_approved_rubric() -> None:
    """An approved rubric is what scoring is supposed to run against."""
    from app.services.rubric import ensure_approved_for_scoring

    ensure_approved_for_scoring(_draft(status="approved"))


def test_ensure_approved_for_scoring_rejects_a_superseded_rubric() -> None:
    """New scores must use the current criteria, not a retired version."""
    from app.services.rubric import ensure_approved_for_scoring

    with pytest.raises(ResourceConflictError):
        ensure_approved_for_scoring(_draft(status="superseded"))


# --------------------------------------------------------------------------
# orchestration
# --------------------------------------------------------------------------


class _FakeRubricRepository:
    """Holds rubric rows in memory so the service can be tested without a database.

    Attributes:
        versions: Stored rubric versions keyed by id.
        requirements: Stored requirement lists keyed by rubric version id.
    """

    def __init__(self) -> None:
        """Start with an empty store."""
        self.versions: dict[uuid.UUID, object] = {}
        self.requirements: dict[uuid.UUID, list[object]] = {}

    async def add_version(self, version: object) -> object:
        """Persist a rubric version.

        Args:
            version: The version to store.

        Returns:
            The stored version.
        """
        self.versions[version.id] = version  # type: ignore[attr-defined]
        return version

    async def get_version(
        self, tenant_id: uuid.UUID, rubric_version_id: uuid.UUID
    ) -> object | None:
        """Return one version scoped to the caller's tenant.

        Args:
            tenant_id: Owning tenant.
            rubric_version_id: Version identifier.

        Returns:
            The version, or None if it does not exist for this tenant.
        """
        version = self.versions.get(rubric_version_id)
        if version is None or version.tenant_id != tenant_id:  # type: ignore[attr-defined]
            return None
        return version

    async def max_version_for_job(self, tenant_id: uuid.UUID, job_id: uuid.UUID) -> int:
        """Return the highest version number minted for a job.

        Args:
            tenant_id: Owning tenant.
            job_id: The job the rubric belongs to.

        Returns:
            The highest version number, or 0 when no rubric exists yet.
        """
        return max(
            (
                v.version  # type: ignore[attr-defined]
                for v in self.versions.values()
                if v.tenant_id == tenant_id and v.job_id == job_id  # type: ignore[attr-defined]
            ),
            default=0,
        )

    async def replace_requirements(
        self,
        tenant_id: uuid.UUID,
        rubric_version_id: uuid.UUID,
        requirements: list[object],
    ) -> None:
        """Replace the whole requirement set for one version.

        Args:
            tenant_id: Owning tenant.
            rubric_version_id: Version whose requirements are being written.
            requirements: The replacement requirements.
        """
        self.requirements[rubric_version_id] = list(requirements)

    async def list_requirements(
        self, tenant_id: uuid.UUID, rubric_version_id: uuid.UUID
    ) -> list[object]:
        """Return the stored requirements for one version.

        Args:
            tenant_id: Owning tenant.
            rubric_version_id: Version to read.

        Returns:
            The requirements, in stored order.
        """
        return list(self.requirements.get(rubric_version_id, []))


async def test_create_draft_rubric_mints_version_one_as_a_draft() -> None:
    """A brand-new rubric starts at version 1 and unapproved."""
    from app.services.rubric import create_draft_rubric

    repo = _FakeRubricRepository()

    version = await create_draft_rubric(
        rubric_repo=repo,
        principal=_principal(),
        job_id=uuid.uuid4(),
        requirements=[_requirement("Python", "1")],
    )

    assert version.version == 1
    assert version.status == "draft"
    assert version.tenant_id == _TENANT


async def test_create_draft_rubric_normalizes_weights_on_save() -> None:
    """Callers submit relative weights; storage holds normalized ones.

    If normalization happened only at score time, two readers of the same row
    could disagree about what the rubric weighs.
    """
    from app.services.rubric import create_draft_rubric

    repo = _FakeRubricRepository()

    version = await create_draft_rubric(
        rubric_repo=repo,
        principal=_principal(),
        job_id=uuid.uuid4(),
        requirements=[_requirement("Python", "3"), _requirement("Go", "1")],
    )

    stored = await repo.list_requirements(_TENANT, version.id)
    assert sum(r.weight for r in stored) == Decimal("1.0000")
    assert [r.weight for r in stored] == [Decimal("0.7500"), Decimal("0.2500")]


async def test_create_draft_rubric_scopes_requirements_to_the_new_version() -> None:
    """Requirements inherit the tenant and version, or isolation breaks."""
    from app.services.rubric import create_draft_rubric

    repo = _FakeRubricRepository()

    version = await create_draft_rubric(
        rubric_repo=repo,
        principal=_principal(),
        job_id=uuid.uuid4(),
        requirements=[_requirement("Python", "1"), _requirement("Go", "1")],
    )

    stored = await repo.list_requirements(_TENANT, version.id)
    assert all(r.tenant_id == _TENANT for r in stored)
    assert all(r.rubric_version_id == version.id for r in stored)
    assert [r.ordinal for r in stored] == [0, 1]


async def test_create_draft_rubric_rejects_an_empty_requirement_set() -> None:
    """A rubric with no criteria cannot score anyone."""
    from app.services.rubric import create_draft_rubric

    repo = _FakeRubricRepository()

    with pytest.raises(ValidationFailedError):
        await create_draft_rubric(
            rubric_repo=repo,
            principal=_principal(),
            job_id=uuid.uuid4(),
            requirements=[],
        )


async def test_update_draft_requirements_renormalizes_the_new_set() -> None:
    """Editing a draft re-normalizes, so weights still sum to one afterwards."""
    from app.services.rubric import create_draft_rubric, update_draft_requirements

    repo = _FakeRubricRepository()
    version = await create_draft_rubric(
        rubric_repo=repo,
        principal=_principal(),
        job_id=uuid.uuid4(),
        requirements=[_requirement("Python", "1")],
    )

    await update_draft_requirements(
        rubric_repo=repo,
        principal=_principal(),
        rubric_version_id=version.id,
        requirements=[
            _requirement("Python", "1"),
            _requirement("Go", "1"),
            _requirement("Rust", "1"),
        ],
    )

    stored = await repo.list_requirements(_TENANT, version.id)
    assert len(stored) == 3
    assert sum(r.weight for r in stored) == Decimal("1.0000")


async def test_update_draft_requirements_rejects_an_approved_rubric() -> None:
    """An approved rubric is the record of a decision and cannot be edited."""
    from app.services.rubric import update_draft_requirements

    repo = _FakeRubricRepository()
    approved = _draft(tenant_id=_TENANT, status="approved")
    await repo.add_version(approved)

    with pytest.raises(ResourceConflictError):
        await update_draft_requirements(
            rubric_repo=repo,
            principal=_principal(),
            rubric_version_id=approved.id,
            requirements=[_requirement("Python", "1")],
        )


async def test_approve_rubric_stamps_the_approver_and_content_hash() -> None:
    """Approval records who signed off and freezes the criteria fingerprint.

    The hash is the verdict cache key, so it has to be computed at the moment
    the criteria stop changing — not lazily at score time.
    """
    from app.services.rubric import approve_rubric, create_draft_rubric

    repo = _FakeRubricRepository()
    draft = await create_draft_rubric(
        rubric_repo=repo,
        principal=_principal(),
        job_id=uuid.uuid4(),
        requirements=[_requirement("Python", "1")],
    )

    approved = await approve_rubric(
        rubric_repo=repo, principal=_principal(), rubric_version_id=draft.id
    )

    assert approved.status == "approved"
    assert approved.approved_by == _USER
    assert approved.approved_at is not None
    assert approved.content_hash is not None
    assert len(approved.content_hash) == 64


async def test_approve_rubric_rejects_a_second_approval() -> None:
    """Re-approving would silently rewrite an existing audit record."""
    from app.services.rubric import approve_rubric

    repo = _FakeRubricRepository()
    approved = _draft(tenant_id=_TENANT, status="approved")
    await repo.add_version(approved)

    with pytest.raises(ResourceConflictError):
        await approve_rubric(
            rubric_repo=repo, principal=_principal(), rubric_version_id=approved.id
        )


async def test_approve_rubric_reports_a_missing_rubric_as_not_found() -> None:
    """An unknown id is a 404, not a crash."""
    from app.services.rubric import approve_rubric

    repo = _FakeRubricRepository()

    with pytest.raises(ResourceNotFoundError) as caught:
        await approve_rubric(
            rubric_repo=repo, principal=_principal(), rubric_version_id=uuid.uuid4()
        )

    assert caught.value.status_code == 404


async def test_approve_rubric_reports_another_tenants_rubric_as_not_found() -> None:
    """A cross-tenant id must look absent, not forbidden.

    A 403 would confirm the rubric exists, leaking that another tenant holds
    that identifier.
    """
    from app.services.rubric import approve_rubric

    repo = _FakeRubricRepository()
    foreign = _draft(tenant_id=_OTHER_TENANT)
    await repo.add_version(foreign)

    with pytest.raises(ResourceNotFoundError):
        await approve_rubric(
            rubric_repo=repo, principal=_principal(), rubric_version_id=foreign.id
        )


async def test_mint_next_version_supersedes_the_approved_version() -> None:
    """Editing an approved rubric forks version N+1 and retires the old one."""
    from app.services.rubric import approve_rubric, create_draft_rubric, mint_next_version

    repo = _FakeRubricRepository()
    job_id = uuid.uuid4()
    draft = await create_draft_rubric(
        rubric_repo=repo,
        principal=_principal(),
        job_id=job_id,
        requirements=[_requirement("Python", "1")],
    )
    approved = await approve_rubric(
        rubric_repo=repo, principal=_principal(), rubric_version_id=draft.id
    )

    successor = await mint_next_version(
        rubric_repo=repo, principal=_principal(), rubric_version_id=approved.id
    )

    assert successor.version == 2
    assert successor.status == "draft"
    assert successor.job_id == job_id
    assert approved.status == "superseded"


async def test_mint_next_version_copies_the_requirements_forward() -> None:
    """The successor starts from the approved criteria, not from nothing."""
    from app.services.rubric import approve_rubric, create_draft_rubric, mint_next_version

    repo = _FakeRubricRepository()
    draft = await create_draft_rubric(
        rubric_repo=repo,
        principal=_principal(),
        job_id=uuid.uuid4(),
        requirements=[_requirement("Python", "3"), _requirement("Go", "1")],
    )
    approved = await approve_rubric(
        rubric_repo=repo, principal=_principal(), rubric_version_id=draft.id
    )

    successor = await mint_next_version(
        rubric_repo=repo, principal=_principal(), rubric_version_id=approved.id
    )

    copied = await repo.list_requirements(_TENANT, successor.id)
    assert [r.text for r in copied] == ["Python", "Go"]
    assert all(r.rubric_version_id == successor.id for r in copied)
    assert sum(r.weight for r in copied) == Decimal("1.0000")


async def test_mint_next_version_rejects_a_draft() -> None:
    """A draft is already editable; forking it would orphan the work in progress."""
    from app.services.rubric import mint_next_version

    repo = _FakeRubricRepository()
    draft = _draft(tenant_id=_TENANT)
    await repo.add_version(draft)

    with pytest.raises(ResourceConflictError):
        await mint_next_version(
            rubric_repo=repo, principal=_principal(), rubric_version_id=draft.id
        )
