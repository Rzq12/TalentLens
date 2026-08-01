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


def test_normalize_weights_rejects_a_positive_weight_too_small_to_store() -> None:
    """A criterion the author weighted cannot silently end up worth nothing.

    `numeric(5,4)` holds 10,000 quanta. A weight whose share rounds below one
    quantum floors to `0.0000`, and the rubric would then be approved carrying a
    criterion that contributes to no score — with nothing in the response saying
    so. Refusing is the only outcome that keeps the stored rubric a faithful
    record of what the author asked for.
    """
    from app.services.rubric import normalize_weights

    with pytest.raises(ValidationFailedError):
        normalize_weights([Decimal("1000"), Decimal("0.00000001")])


def test_normalize_weights_rejects_a_set_too_large_to_weight() -> None:
    """Past 10,000 criteria the quanta run out however the weights are spread.

    An equal-weight set of 20,000 previously stored 10,000 criteria at
    `0.0000`. The failure is starvation, not drift: the surviving weights still
    summed to exactly one, which is why nothing downstream could detect it.
    """
    from app.services.rubric import normalize_weights

    with pytest.raises(ValidationFailedError):
        normalize_weights([Decimal("1")] * 20_000)


def test_normalize_weights_allows_a_weight_the_author_set_to_zero() -> None:
    """An explicit zero is a request for an unscored criterion, not an error.

    The starvation guard must distinguish "too small to store" from "asked for
    nothing", or a rubric could not carry an informational criterion.
    """
    from app.services.rubric import normalize_weights

    assert normalize_weights([Decimal("3"), Decimal("0")]) == [
        Decimal("1.0000"),
        Decimal("0.0000"),
    ]


def test_normalize_weights_still_sums_to_one_at_the_representable_limit() -> None:
    """The guard must not reject a set that quantization can still represent.

    10,000 equal criteria is exactly one quantum each — the boundary the
    rejection test above sits just past.
    """
    from app.services.rubric import normalize_weights

    normalized = normalize_weights([Decimal("1")] * 10_000)

    assert sum(normalized) == Decimal("1.0000")
    assert all(weight > 0 for weight in normalized)


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
        jobs: `(tenant_id, job_id)` pairs the tenant is allowed to author
            against. A test that authors a rubric must seed the job first, the
            same as production: the service refuses to attach a rubric to a job
            the caller cannot see.
    """

    def __init__(self) -> None:
        """Start with an empty store."""
        self.versions: dict[uuid.UUID, object] = {}
        self.requirements: dict[uuid.UUID, list[object]] = {}
        self.jobs: set[tuple[uuid.UUID, uuid.UUID]] = set()

    def seed_job(self, tenant_id: uuid.UUID, job_id: uuid.UUID) -> None:
        """Register a job as visible to a tenant.

        Args:
            tenant_id: Owning tenant.
            job_id: Job the tenant may author rubrics against.
        """
        self.jobs.add((tenant_id, job_id))

    async def job_exists(self, tenant_id: uuid.UUID, job_id: uuid.UUID) -> bool:
        """Report whether the tenant owns this job.

        Args:
            tenant_id: Owning tenant.
            job_id: Job to look for.

        Returns:
            True if the pair was seeded.
        """
        return (tenant_id, job_id) in self.jobs

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


def _repo_with_job(job_id: uuid.UUID, *, tenant_id: uuid.UUID = _TENANT) -> tuple[
    _FakeRubricRepository, uuid.UUID
]:
    """Return a store in which the tenant already owns `job_id`.

    Authoring a rubric requires a visible job, so a test that does not seed one
    is testing the 404 path whether it means to or not.

    Args:
        job_id: Job the rubric will be authored against.
        tenant_id: Tenant that owns it.

    Returns:
        The store and the job id, for convenient unpacking.
    """
    repo = _FakeRubricRepository()
    repo.seed_job(tenant_id, job_id)
    return repo, job_id


async def test_create_draft_rubric_mints_version_one_as_a_draft() -> None:
    """A brand-new rubric starts at version 1 and unapproved."""
    from app.services.rubric import create_draft_rubric

    repo, job_id = _repo_with_job(uuid.uuid4())

    version = await create_draft_rubric(
        rubric_repo=repo,
        principal=_principal(),
        job_id=job_id,
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

    repo, job_id = _repo_with_job(uuid.uuid4())

    version = await create_draft_rubric(
        rubric_repo=repo,
        principal=_principal(),
        job_id=job_id,
        requirements=[_requirement("Python", "3"), _requirement("Go", "1")],
    )

    stored = await repo.list_requirements(_TENANT, version.id)
    assert sum(r.weight for r in stored) == Decimal("1.0000")
    assert [r.weight for r in stored] == [Decimal("0.7500"), Decimal("0.2500")]


async def test_create_draft_rubric_scopes_requirements_to_the_new_version() -> None:
    """Requirements inherit the tenant and version, or isolation breaks."""
    from app.services.rubric import create_draft_rubric

    repo, job_id = _repo_with_job(uuid.uuid4())

    version = await create_draft_rubric(
        rubric_repo=repo,
        principal=_principal(),
        job_id=job_id,
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

    repo, job_id = _repo_with_job(uuid.uuid4())
    version = await create_draft_rubric(
        rubric_repo=repo,
        principal=_principal(),
        job_id=job_id,
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

    repo, job_id = _repo_with_job(uuid.uuid4())
    draft = await create_draft_rubric(
        rubric_repo=repo,
        principal=_principal(),
        job_id=job_id,
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

    repo, job_id = _repo_with_job(uuid.uuid4())
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

    repo, job_id = _repo_with_job(uuid.uuid4())
    draft = await create_draft_rubric(
        rubric_repo=repo,
        principal=_principal(),
        job_id=job_id,
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


# --------------------------------------------------------------------------
# authoring is bound to a job the caller can see
# --------------------------------------------------------------------------


async def test_create_draft_rubric_rejects_a_job_that_does_not_exist() -> None:
    """`job_id` arrives in the request body and nothing else constrains it.

    The `rubric_versions.job_id` foreign key only requires the row to reference
    *a* job, so an unchecked id produced a rubric attached to nothing findable.
    """
    from app.services.rubric import create_draft_rubric

    repo = _FakeRubricRepository()

    with pytest.raises(ResourceNotFoundError):
        await create_draft_rubric(
            rubric_repo=repo,
            principal=_principal(),
            job_id=uuid.uuid4(),
            requirements=[_requirement("Python", "1")],
        )


async def test_create_draft_rubric_rejects_another_tenants_job() -> None:
    """Cross-tenant grafting is the sharper form of the same hole.

    A caller who learns a competitor's job id could previously author criteria
    against it and receive a 201. The job must be invisible, not merely absent,
    so the check is scoped by tenant and the answer is the same "not found" a
    nonexistent id produces — a distinct error would confirm the id exists.
    """
    from app.services.rubric import create_draft_rubric

    job_id = uuid.uuid4()
    repo = _FakeRubricRepository()
    repo.seed_job(_OTHER_TENANT, job_id)

    with pytest.raises(ResourceNotFoundError):
        await create_draft_rubric(
            rubric_repo=repo,
            principal=_principal(),
            job_id=job_id,
            requirements=[_requirement("Python", "1")],
        )

    assert repo.versions == {}, "a rubric was stored against a foreign tenant's job"


async def test_create_draft_rubric_checks_the_job_before_minting_a_version() -> None:
    """A rejected create must not consume a version number.

    `max_version_for_job` feeds the `version` column; running it for an
    unauthorized job would leak whether that job has rubrics.
    """
    from app.services.rubric import create_draft_rubric

    repo = _FakeRubricRepository()

    with pytest.raises(ResourceNotFoundError):
        await create_draft_rubric(
            rubric_repo=repo,
            principal=_principal(),
            job_id=uuid.uuid4(),
            requirements=[_requirement("Python", "1")],
        )

    assert repo.requirements == {}, "requirements were written for a rejected job"


# --------------------------------------------------------------------------
# read_rubric
# --------------------------------------------------------------------------


async def test_read_rubric_returns_the_version_for_its_owner() -> None:
    """The read path exists so the router never reaches the repository itself."""
    from app.services.rubric import read_rubric

    repo = _FakeRubricRepository()
    draft = _draft(tenant_id=_TENANT)
    await repo.add_version(draft)

    found = await read_rubric(
        rubric_repo=repo, principal=_principal(), rubric_version_id=draft.id
    )

    assert found.id == draft.id


async def test_read_rubric_reports_a_foreign_tenants_rubric_as_missing() -> None:
    """A cross-tenant read is 404, not 403 — 403 would confirm the id exists."""
    from app.services.rubric import read_rubric

    repo = _FakeRubricRepository()
    foreign = _draft(tenant_id=_OTHER_TENANT)
    await repo.add_version(foreign)

    with pytest.raises(ResourceNotFoundError):
        await read_rubric(
            rubric_repo=repo, principal=_principal(), rubric_version_id=foreign.id
        )


async def test_read_rubric_reports_an_unknown_id_as_missing() -> None:
    """An id that was never minted is the same answer as one owned elsewhere."""
    from app.services.rubric import read_rubric

    repo = _FakeRubricRepository()

    with pytest.raises(ResourceNotFoundError):
        await read_rubric(
            rubric_repo=repo, principal=_principal(), rubric_version_id=uuid.uuid4()
        )


async def test_read_rubric_words_a_missing_rubric_the_same_way_every_path_does() -> None:
    """The router used to raise its own bare error, so one path read differently.

    Wording is the contract a client branches on when it renders the failure.
    Comparing against `approve_rubric` pins the two to the same string rather
    than to a literal this test could quietly drift from.
    """
    from app.services.rubric import approve_rubric, read_rubric

    repo = _FakeRubricRepository()
    missing = uuid.uuid4()

    with pytest.raises(ResourceNotFoundError) as read_error:
        await read_rubric(
            rubric_repo=repo, principal=_principal(), rubric_version_id=missing
        )
    with pytest.raises(ResourceNotFoundError) as approve_error:
        await approve_rubric(
            rubric_repo=repo, principal=_principal(), rubric_version_id=missing
        )

    assert str(read_error.value) == str(approve_error.value)


# --------------------------------------------------------------------------
# an empty requirement set is refused on every path that can produce one
# --------------------------------------------------------------------------


async def test_update_draft_requirements_rejects_an_empty_set() -> None:
    """Emptying a draft would leave a rubric that scores everyone identically.

    The create path already refuses this. The edit path can reach the same state
    by replacing the set with nothing, so it needs its own guard rather than
    inheriting one.
    """
    from app.services.rubric import create_draft_rubric, update_draft_requirements

    repo, job_id = _repo_with_job(uuid.uuid4())
    version = await create_draft_rubric(
        rubric_repo=repo,
        principal=_principal(),
        job_id=job_id,
        requirements=[_requirement("Python", "1")],
    )

    with pytest.raises(ValidationFailedError):
        await update_draft_requirements(
            rubric_repo=repo,
            principal=_principal(),
            rubric_version_id=version.id,
            requirements=[],
        )

    assert len(await repo.list_requirements(_TENANT, version.id)) == 1


async def test_approve_rubric_rejects_a_draft_with_no_requirements() -> None:
    """Approval is the sign-off that unblocks scoring, so it needs criteria.

    A draft can reach this state through a route that bypassed the service, or
    through a partially applied edit; approving it would stamp a content hash
    over an empty set and let scoring run against nothing.
    """
    from app.services.rubric import approve_rubric

    repo = _FakeRubricRepository()
    draft = _draft(tenant_id=_TENANT)
    await repo.add_version(draft)

    with pytest.raises(ValidationFailedError):
        await approve_rubric(
            rubric_repo=repo, principal=_principal(), rubric_version_id=draft.id
        )

    assert draft.status == "draft", "a rubric with no criteria was approved"
    assert draft.content_hash is None


async def test_mint_next_version_rejects_a_predecessor_with_no_requirements() -> None:
    """The successor is a copy, and copying nothing yields an unusable draft.

    Failing here is louder than minting an empty version the author then has to
    notice is empty.
    """
    from app.services.rubric import mint_next_version

    repo = _FakeRubricRepository()
    approved = _draft(tenant_id=_TENANT, status="approved")
    await repo.add_version(approved)

    with pytest.raises(ValidationFailedError):
        await mint_next_version(
            rubric_repo=repo, principal=_principal(), rubric_version_id=approved.id
        )

    assert len(repo.versions) == 1, "an empty successor version was minted"
    assert approved.status == "approved", "the predecessor was superseded anyway"
