"""The HTTP surface for rubric authoring, approval, and job listing.

These tests run without PostgreSQL. The session dependency is overridden with
an in-memory double, so what is pinned here is the contract the transport layer
owns: which routes exist, who may call them, which payloads are rejected before
any business logic runs, and which exception maps to which status code.

Persistence behaviour is pinned separately in ``test_rubric_repository.py`` and
the service invariants in ``test_rubric_service.py``. Nothing here asserts that
a row reached a database.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal
from typing import get_args

import httpx
import pytest

RUBRICS = "/api/v1/rubrics"
JOBS = "/api/v1/jobs"

_TENANT = uuid.UUID("11111111-1111-1111-1111-111111111111")
_USER = uuid.UUID("33333333-3333-3333-3333-333333333333")
_JOB = uuid.UUID("44444444-4444-4444-4444-444444444444")
_VERSION_ID = uuid.UUID("55555555-5555-5555-5555-555555555555")

_READ_ONLY_ROLES = ["viewer", "auditor", "hiring_manager"]


# --------------------------------------------------------------------------- #
# Doubles                                                                      #
# --------------------------------------------------------------------------- #


class _Result:
    """A stand-in for SQLAlchemy's ``Result``.

    Each accessor is backed by its own value rather than one shared value, so a
    test does not have to know the order in which the repository calls them.
    """

    def __init__(
        self,
        *,
        one: object = None,
        scalar: object = None,
        rows: Sequence[object] = (),
    ) -> None:
        self._one = one
        self._scalar = scalar
        self._rows = rows

    def scalar_one_or_none(self) -> object:
        return self._one

    def scalar(self) -> object:
        return self._scalar

    def scalars(self) -> _Result:
        return self

    def all(self) -> Sequence[object]:
        return self._rows


class _StubSession:
    """The minimum of ``AsyncSession`` the rubric repository actually touches.

    ``rows`` is what a listing query returns. When left empty it falls through
    to whatever the request itself added, which is what makes a create round
    trip observable without a database.
    """

    def __init__(
        self,
        *,
        one: object = None,
        scalar: object = None,
        rows: Sequence[object] | None = None,
    ) -> None:
        self.one = one
        self.scalar = scalar
        self.seed_rows = rows
        self.added: list[object] = []
        self.flushes = 0

    def add(self, instance: object) -> None:
        self.added.append(instance)

    async def flush(self) -> None:
        self.flushes += 1

    async def delete(self, instance: object) -> None:
        return None

    async def execute(self, statement: object, *args: object, **kwargs: object) -> _Result:
        rows = self.seed_rows if self.seed_rows is not None else self._added_requirements()
        return _Result(one=self.one, scalar=self.scalar, rows=rows)

    def _added_requirements(self) -> Sequence[object]:
        from app.models import Requirement

        return [row for row in self.added if isinstance(row, Requirement)]


@asynccontextmanager
async def _app_client(session: _StubSession) -> AsyncIterator[httpx.AsyncClient]:
    """Yield a client whose database session is the supplied double."""
    from app.db import get_session
    from app.main import create_app

    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


# --------------------------------------------------------------------------- #
# Builders                                                                     #
# --------------------------------------------------------------------------- #


def _requirement_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "text": "Five years of production Python.",
        "category": "skill",
        "is_must_have": True,
        "weight": 1,
    }
    payload.update(overrides)
    return payload


def _create_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "job_id": str(_JOB),
        "requirements": [
            _requirement_payload(),
            _requirement_payload(text="Postgres tuning.", is_must_have=False),
        ],
        "source": "manual",
    }
    payload.update(overrides)
    return payload


def _version(status: str = "draft", *, version: int = 1) -> object:
    from app.models import RubricVersion

    return RubricVersion(
        id=_VERSION_ID,
        tenant_id=_TENANT,
        job_id=_JOB,
        version=version,
        status=status,
        content_hash="a" * 64 if status != "draft" else None,
        must_have_fail_cap=40,
        aggregation_formula_version="v1",
        source="manual",
        approved_by=_USER if status == "approved" else None,
        approved_at=datetime.now(UTC) if status == "approved" else None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _requirement(text: str = "Python.", *, ordinal: int = 0) -> object:
    from app.models import Requirement

    return Requirement(
        id=uuid.uuid4(),
        tenant_id=_TENANT,
        rubric_version_id=_VERSION_ID,
        ordinal=ordinal,
        text=text,
        category="skill",
        is_must_have=True,
        weight=Decimal("1.0000"),
        min_years=None,
        min_seniority=None,
        skill_id=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _job(title: str = "Backend Engineer", *, created: datetime | None = None) -> object:
    from app.models import Job

    return Job(
        id=uuid.uuid4(),
        tenant_id=_TENANT,
        title=title,
        description_raw="Python and Postgres.",
        department=None,
        location=None,
        employment_type=None,
        seniority=None,
        source="manual",
        status="draft",
        blind_mode=False,
        created_at=created or datetime.now(UTC),
        updated_at=created or datetime.now(UTC),
    )


# --------------------------------------------------------------------------- #
# Registration and documentation                                               #
# --------------------------------------------------------------------------- #


def test_the_rubric_router_is_registered_under_the_versioned_prefix() -> None:
    """An unregistered router is invisible: every route would 404 in production.

    Paths are read from the generated schema rather than by scanning
    `app.routes`. FastAPI 0.141 wraps each `include_router` call in an internal
    `_IncludedRouter` that carries no `path` attribute of its own, so filtering
    the top-level route list on `hasattr(route, "path")` discards every mounted
    router and reports a correctly wired app as unregistered.
    """
    from app.config import get_settings
    from app.main import create_app

    prefix = f"{get_settings().api_v1_prefix}/rubrics"
    paths = set(create_app().openapi()["paths"])

    assert any(path.startswith(prefix) for path in paths), (
        f"no route under {prefix} — the rubric router was not included in create_app"
    )


def test_every_rubric_route_documents_itself() -> None:
    """CLAUDE.md requires an explicit summary and description on every endpoint.

    The OpenAPI document is the contract the recruiter-facing UI is built
    against; an undocumented route ships as an unlabelled entry in the schema.
    """
    from app.main import create_app

    schema = create_app().openapi()
    rubric_paths = {
        path: methods
        for path, methods in schema["paths"].items()
        if path.startswith(f"{RUBRICS}")
    }
    assert rubric_paths, "the OpenAPI document contains no rubric paths"

    undocumented = [
        f"{method.upper()} {path}"
        for path, methods in rubric_paths.items()
        for method, operation in methods.items()
        if not operation.get("summary") or not operation.get("description")
    ]

    assert not undocumented, f"routes missing summary or description: {undocumented}"


def test_every_rubric_route_declares_a_response_model() -> None:
    """Without a response_model the endpoint's return type is unenforced.

    A route that leaks an ORM object serializes whatever columns happen to
    exist, which is how internal fields reach an API response by accident.

    The rubric path set is asserted non-empty first: this check is a filter
    over the schema, so an unregistered router would leave nothing to inspect
    and the test would pass without having verified a single route.
    """
    from app.main import create_app

    schema = create_app().openapi()
    rubric_paths = {
        path: methods for path, methods in schema["paths"].items() if path.startswith(RUBRICS)
    }
    assert rubric_paths, "the OpenAPI document contains no rubric paths"

    modelless: list[str] = []
    for path, methods in rubric_paths.items():
        for method, operation in methods.items():
            success = [code for code in operation.get("responses", {}) if code.startswith("2")]
            content = operation["responses"][success[0]].get("content", {}) if success else {}
            if not content.get("application/json", {}).get("schema"):
                modelless.append(f"{method.upper()} {path}")

    assert not modelless, f"routes with no declared success schema: {modelless}"


# --------------------------------------------------------------------------- #
# Authorization                                                                #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("role", _READ_ONLY_ROLES)
async def test_a_read_only_role_cannot_create_a_rubric(client, make_token, role) -> None:
    """Authoring criteria is a write action; read roles must be refused.

    The rubric is the human-oversight surface of the product. A viewer able to
    author criteria would silently become the decision-maker.
    """
    headers = {"Authorization": f"Bearer {make_token(roles=[role])}"}

    response = await client.post(RUBRICS, headers=headers, json=_create_payload())

    assert response.status_code == 403
    assert response.json()["error"] == "FORBIDDEN"


@pytest.mark.parametrize("role", _READ_ONLY_ROLES)
async def test_a_read_only_role_cannot_approve_a_rubric(client, make_token, role) -> None:
    """Approval is the sign-off that unblocks scoring — writers only."""
    headers = {"Authorization": f"Bearer {make_token(roles=[role])}"}

    response = await client.post(f"{RUBRICS}/{_VERSION_ID}/approve", headers=headers)

    assert response.status_code == 403


async def test_an_unauthenticated_caller_cannot_reach_the_rubric_routes(client) -> None:
    """Every route but /health sits behind a verified token."""
    response = await client.post(RUBRICS, json=_create_payload())

    assert response.status_code in (401, 403)


async def test_a_recruiter_may_author_a_rubric(make_token) -> None:
    """The role that runs hiring must not be locked out of its own workflow."""
    session = _StubSession(scalar=0)
    async with _app_client(session) as ac:
        response = await ac.post(
            RUBRICS,
            headers={"Authorization": f"Bearer {make_token(roles=['recruiter'])}"},
            json=_create_payload(),
        )

    assert response.status_code == 201, response.text


# --------------------------------------------------------------------------- #
# Payload validation — rejected before any business logic runs                 #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("label", "overrides"),
    [
        ("blank text", {"requirements": [_requirement_payload(text="   ")]}),
        ("empty requirement list", {"requirements": []}),
        ("negative weight", {"requirements": [_requirement_payload(weight=-1)]}),
        ("absurd weight", {"requirements": [_requirement_payload(weight=10_000)]}),
        ("unknown source", {"source": "telepathy"}),
        ("negative min_years", {"requirements": [_requirement_payload(min_years=-3)]}),
        ("min_years beyond a career", {"requirements": [_requirement_payload(min_years=500)]}),
        ("job_id is not a uuid", {"job_id": "not-a-uuid"}),
    ],
)
async def test_a_malformed_rubric_payload_is_rejected(
    make_token, label, overrides
) -> None:
    """Bad input must fail at the schema boundary, not inside the service.

    Defence in depth: the service also validates, but a 422 here means no
    session work and no partial write was ever attempted.
    """
    session = _StubSession(scalar=0)
    async with _app_client(session) as ac:
        response = await ac.post(
            RUBRICS,
            headers={"Authorization": f"Bearer {make_token()}"},
            json=_create_payload(**overrides),
        )

    assert response.status_code == 422, f"{label} was accepted: {response.text}"
    assert session.added == [], f"{label} reached the session before validation"


async def test_an_unknown_category_is_rejected(make_token) -> None:
    """Categories drive the score breakdown; a free-text value would break it."""
    session = _StubSession(scalar=0)
    async with _app_client(session) as ac:
        response = await ac.post(
            RUBRICS,
            headers={"Authorization": f"Bearer {make_token()}"},
            json=_create_payload(requirements=[_requirement_payload(category="vibes")]),
        )

    assert response.status_code == 422


async def test_a_requirement_list_beyond_the_ceiling_is_rejected(make_token) -> None:
    """An unbounded list is one INSERT per element on a shared database.

    A single 50,000-criterion request was previously accepted with a 201. The
    bound is read from `MAX_REQUIREMENTS` rather than written as a literal, so
    raising the constant cannot leave this test silently checking the old one.
    """
    from app.schemas.rubric import MAX_REQUIREMENTS

    session = _StubSession(scalar=0)
    oversized = [
        _requirement_payload(text=f"Criterion {i}.") for i in range(MAX_REQUIREMENTS + 1)
    ]

    async with _app_client(session) as ac:
        response = await ac.post(
            RUBRICS,
            headers={"Authorization": f"Bearer {make_token()}"},
            json=_create_payload(requirements=oversized),
        )

    assert response.status_code == 422
    assert session.added == [], "an oversized payload reached the session"


async def test_a_requirement_list_at_the_ceiling_is_accepted(make_token) -> None:
    """The bound must be a ceiling, not an off-by-one that rejects the limit.

    It also has to sit inside what `numeric(5,4)` can weight: 200 equal criteria
    are 50 quanta each, well clear of the starvation floor.
    """
    from app.schemas.rubric import MAX_REQUIREMENTS

    session = _StubSession(scalar=0)
    at_limit = [_requirement_payload(text=f"Criterion {i}.") for i in range(MAX_REQUIREMENTS)]

    async with _app_client(session) as ac:
        response = await ac.post(
            RUBRICS,
            headers={"Authorization": f"Bearer {make_token()}"},
            json=_create_payload(requirements=at_limit),
        )

    assert response.status_code == 201, response.text
    weights = [Decimal(str(item["weight"])) for item in response.json()["requirements"]]
    assert sum(weights) == Decimal("1.0000")


@pytest.mark.parametrize(
    "value", ["<script>alert(1)</script>", "Sr.", "very senior", "SENIOR", ""]
)
async def test_a_free_text_seniority_floor_is_rejected(make_token, value) -> None:
    """A floor only means something if both sides read it the same way.

    `min_seniority` was free text bounded only by length, so "Sr." and "senior"
    expressed the same requirement while comparing unequal — which makes the
    floor unenforceable by anything downstream, and let markup through as a
    stored value.
    """
    session = _StubSession(scalar=0)
    async with _app_client(session) as ac:
        response = await ac.post(
            RUBRICS,
            headers={"Authorization": f"Bearer {make_token()}"},
            json=_create_payload(requirements=[_requirement_payload(min_seniority=value)]),
        )

    assert response.status_code == 422, response.text
    assert session.added == []


async def test_a_recognized_seniority_floor_is_accepted(make_token) -> None:
    """Tightening the type must not reject the values the product actually uses."""
    session = _StubSession(scalar=0)
    async with _app_client(session) as ac:
        response = await ac.post(
            RUBRICS,
            headers={"Authorization": f"Bearer {make_token()}"},
            json=_create_payload(requirements=[_requirement_payload(min_seniority="senior")]),
        )

    assert response.status_code == 201, response.text
    assert response.json()["requirements"][0]["min_seniority"] == "senior"


def test_the_seniority_floor_reads_the_same_on_the_way_in_and_out() -> None:
    """A response looser than the request cannot be branched on exhaustively.

    The field is only ever written from a validated `RequirementInput`, so a
    `str` on the response would advertise a freedom the API does not have and
    force every client into a default branch that cannot be reached.
    """
    from app.schemas.rubric import RequirementInput, RequirementResponse

    incoming = RequirementInput.model_fields["min_seniority"].annotation
    outgoing = RequirementResponse.model_fields["min_seniority"].annotation

    assert incoming == outgoing


def test_the_documented_rubric_status_matches_what_the_service_can_set() -> None:
    """The published enum must list every state a rubric can actually be in.

    A status the service assigns but the schema omits fails serialization on the
    response — the mutation succeeds and the caller sees a 500.
    """
    from app.schemas.rubric import RubricResponse
    from app.services.rubric import APPROVED_STATUS, EDITABLE_STATUS, SUPERSEDED_STATUS

    published = set(get_args(RubricResponse.model_fields["status"].annotation))

    assert {EDITABLE_STATUS, APPROVED_STATUS, SUPERSEDED_STATUS} <= published


async def test_a_caller_cannot_choose_the_tenant_a_rubric_belongs_to(make_token) -> None:
    """Tenant comes from the verified token only — never from the payload."""
    session = _StubSession(scalar=0)
    payload = _create_payload()
    payload["tenant_id"] = str(uuid.UUID("22222222-2222-2222-2222-222222222222"))

    async with _app_client(session) as ac:
        response = await ac.post(
            RUBRICS, headers={"Authorization": f"Bearer {make_token()}"}, json=payload
        )

    assert response.status_code in (201, 422)
    if response.status_code == 201:
        from app.models import RubricVersion

        versions = [row for row in session.added if isinstance(row, RubricVersion)]
        assert versions and versions[0].tenant_id == _TENANT


# --------------------------------------------------------------------------- #
# Create                                                                       #
# --------------------------------------------------------------------------- #


async def test_creating_a_rubric_returns_the_draft_and_its_requirements(make_token) -> None:
    """The response must be self-contained.

    ``RubricVersion.requirements`` is ``lazy="noload"``, so the router has to
    read the rows back explicitly. If it forgets, the client gets a version
    with no criteria and no way to tell that they were persisted.
    """
    session = _StubSession(scalar=0)
    async with _app_client(session) as ac:
        response = await ac.post(
            RUBRICS,
            headers={"Authorization": f"Bearer {make_token()}"},
            json=_create_payload(),
        )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "draft"
    assert body["version"] == 1
    assert body["content_hash"] is None
    assert len(body["requirements"]) == 2


async def test_returned_weights_are_normalized_to_sum_to_one(make_token) -> None:
    """Weights are relative on input and a probability mass on output.

    Largest-remainder apportionment is what makes ``numeric(5,4)`` values sum
    to exactly 1.0000 with no drifting cent.
    """
    session = _StubSession(scalar=0)
    async with _app_client(session) as ac:
        response = await ac.post(
            RUBRICS,
            headers={"Authorization": f"Bearer {make_token()}"},
            json=_create_payload(
                requirements=[
                    _requirement_payload(weight=1),
                    _requirement_payload(text="Postgres.", weight=1),
                    _requirement_payload(text="Kafka.", weight=1),
                ]
            ),
        )

    assert response.status_code == 201, response.text
    weights = [Decimal(str(item["weight"])) for item in response.json()["requirements"]]
    assert sum(weights) == Decimal("1.0000"), weights


async def test_each_returned_requirement_carries_its_decision_fields(make_token) -> None:
    """A recruiter cannot audit a score without seeing the gate that produced it."""
    session = _StubSession(scalar=0)
    async with _app_client(session) as ac:
        response = await ac.post(
            RUBRICS,
            headers={"Authorization": f"Bearer {make_token()}"},
            json=_create_payload(
                requirements=[_requirement_payload(is_must_have=True, min_years=5)]
            ),
        )

    assert response.status_code == 201, response.text
    item = response.json()["requirements"][0]
    assert item["is_must_have"] is True
    assert Decimal(str(item["min_years"])) == Decimal("5")
    assert item["category"] == "skill"
    assert item["ordinal"] == 0


# --------------------------------------------------------------------------- #
# Read                                                                         #
# --------------------------------------------------------------------------- #


async def test_reading_a_rubric_returns_its_requirements(make_token) -> None:
    """The detail route is what the rubric editor loads."""
    session = _StubSession(one=_version("draft"), rows=[_requirement("Python.")])
    async with _app_client(session) as ac:
        response = await ac.get(
            f"{RUBRICS}/{_VERSION_ID}", headers={"Authorization": f"Bearer {make_token()}"}
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["rubric_version_id"] == str(_VERSION_ID)
    assert [item["text"] for item in body["requirements"]] == ["Python."]


async def test_reading_an_unknown_rubric_is_a_404(make_token) -> None:
    """A missing row and another tenant's row are indistinguishable to the caller.

    Reporting 404 rather than 403 avoids confirming that an id exists.
    """
    session = _StubSession(one=None)
    async with _app_client(session) as ac:
        response = await ac.get(
            f"{RUBRICS}/{uuid.uuid4()}", headers={"Authorization": f"Bearer {make_token()}"}
        )

    assert response.status_code == 404


async def test_a_missing_rubric_answers_with_the_standard_error_envelope(make_token) -> None:
    """The read route used to raise its own bare error, bypassing the service.

    Every failure on this surface carries the same envelope, and the read path
    has to be in it: a client branches on `error`, and a correlation id is what
    ties a support report to a log line.
    """
    session = _StubSession(one=None)
    async with _app_client(session) as ac:
        response = await ac.get(
            f"{RUBRICS}/{uuid.uuid4()}", headers={"Authorization": f"Bearer {make_token()}"}
        )

    body = response.json()
    assert body["error"] == "NOT_FOUND"
    assert body["status_code"] == 404
    assert uuid.UUID(body["request_id"])
    assert response.headers["X-Request-ID"] == body["request_id"]


@pytest.mark.parametrize("role", _READ_ONLY_ROLES)
async def test_a_read_only_role_may_read_a_rubric(make_token, role) -> None:
    """Oversight requires visibility: auditors must be able to inspect criteria."""
    session = _StubSession(one=_version("approved"), rows=[_requirement()])
    async with _app_client(session) as ac:
        response = await ac.get(
            f"{RUBRICS}/{_VERSION_ID}",
            headers={"Authorization": f"Bearer {make_token(roles=[role])}"},
        )

    assert response.status_code == 200, response.text


# --------------------------------------------------------------------------- #
# Approval and immutability                                                    #
# --------------------------------------------------------------------------- #


async def test_approving_a_draft_stamps_a_content_hash(make_token) -> None:
    """Approval freezes the criteria and mints the verdict cache key.

    Every score is attributed to the exact requirement set that produced it, so
    the hash must exist the moment the rubric becomes usable.
    """
    session = _StubSession(one=_version("draft"), rows=[_requirement()])
    async with _app_client(session) as ac:
        response = await ac.post(
            f"{RUBRICS}/{_VERSION_ID}/approve",
            headers={"Authorization": f"Bearer {make_token()}"},
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "approved"
    assert body["content_hash"] and len(body["content_hash"]) == 64


async def test_approving_an_already_approved_rubric_is_a_conflict(make_token) -> None:
    """An approved rubric is immutable — re-approval would move a frozen artifact."""
    session = _StubSession(one=_version("approved"), rows=[_requirement()])
    async with _app_client(session) as ac:
        response = await ac.post(
            f"{RUBRICS}/{_VERSION_ID}/approve",
            headers={"Authorization": f"Bearer {make_token()}"},
        )

    assert response.status_code == 409


async def test_editing_an_approved_rubric_is_a_conflict(make_token) -> None:
    """Editing in place would retroactively change what past scores meant.

    The only legal way forward is to mint a new version.
    """
    session = _StubSession(one=_version("approved"), rows=[_requirement()])
    async with _app_client(session) as ac:
        response = await ac.post(
            f"{RUBRICS}/{_VERSION_ID}/requirements",
            headers={"Authorization": f"Bearer {make_token()}"},
            json={"requirements": [_requirement_payload(text="Rust.")]},
        )

    assert response.status_code == 409


async def test_replacing_a_drafts_requirements_returns_the_new_set(make_token) -> None:
    """A draft is still being authored, so replacement is allowed."""
    session = _StubSession(one=_version("draft"))
    async with _app_client(session) as ac:
        response = await ac.post(
            f"{RUBRICS}/{_VERSION_ID}/requirements",
            headers={"Authorization": f"Bearer {make_token()}"},
            json={"requirements": [_requirement_payload(text="Rust.", weight=2)]},
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert [item["text"] for item in body["requirements"]] == ["Rust."]
    assert Decimal(str(body["requirements"][0]["weight"])) == Decimal("1.0000")


async def test_replacing_requirements_with_an_empty_set_is_rejected(make_token) -> None:
    """A rubric with no criteria cannot score anything."""
    session = _StubSession(one=_version("draft"))
    async with _app_client(session) as ac:
        response = await ac.post(
            f"{RUBRICS}/{_VERSION_ID}/requirements",
            headers={"Authorization": f"Bearer {make_token()}"},
            json={"requirements": []},
        )

    assert response.status_code == 422


async def test_approving_an_unknown_rubric_is_a_404(make_token) -> None:
    session = _StubSession(one=None)
    async with _app_client(session) as ac:
        response = await ac.post(
            f"{RUBRICS}/{uuid.uuid4()}/approve",
            headers={"Authorization": f"Bearer {make_token()}"},
        )

    assert response.status_code == 404


# --------------------------------------------------------------------------- #
# Minting the next version                                                     #
# --------------------------------------------------------------------------- #


async def test_minting_from_an_approved_rubric_yields_a_new_draft(make_token) -> None:
    """Superseding is how criteria evolve without rewriting history."""
    session = _StubSession(one=_version("approved"), scalar=1, rows=[_requirement()])
    async with _app_client(session) as ac:
        response = await ac.post(
            f"{RUBRICS}/{_VERSION_ID}/versions",
            headers={"Authorization": f"Bearer {make_token()}"},
        )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["version"] == 2
    assert body["status"] == "draft"
    assert body["content_hash"] is None


async def test_minting_from_a_draft_is_a_conflict(make_token) -> None:
    """There is nothing to supersede until a version has been signed off."""
    session = _StubSession(one=_version("draft"), scalar=1, rows=[_requirement()])
    async with _app_client(session) as ac:
        response = await ac.post(
            f"{RUBRICS}/{_VERSION_ID}/versions",
            headers={"Authorization": f"Bearer {make_token()}"},
        )

    assert response.status_code == 409


# --------------------------------------------------------------------------- #
# Job listing                                                                  #
# --------------------------------------------------------------------------- #


async def test_listing_jobs_returns_a_page(make_token) -> None:
    """A rubric is authored against a job, so the job list is the entry point."""
    session = _StubSession(rows=[_job("Backend Engineer"), _job("Data Engineer")])
    async with _app_client(session) as ac:
        response = await ac.get(JOBS, headers={"Authorization": f"Bearer {make_token()}"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["count"] == 2
    assert [item["title"] for item in body["items"]] == ["Backend Engineer", "Data Engineer"]
    assert body["next_cursor"] is None


async def test_a_full_page_of_jobs_reports_a_cursor(make_token) -> None:
    """Without a cursor the client cannot reach the second page."""
    session = _StubSession(rows=[_job(f"Role {index}") for index in range(2)])
    async with _app_client(session) as ac:
        response = await ac.get(
            JOBS, params={"limit": 2}, headers={"Authorization": f"Bearer {make_token()}"}
        )

    assert response.status_code == 200, response.text
    assert response.json()["next_cursor"] is not None


async def test_a_job_summary_omits_the_full_description(make_token) -> None:
    """Listing hundreds of jobs must not ship a full JD body for each one."""
    session = _StubSession(rows=[_job()])
    async with _app_client(session) as ac:
        response = await ac.get(JOBS, headers={"Authorization": f"Bearer {make_token()}"})

    assert response.status_code == 200, response.text
    assert "description_raw" not in response.json()["items"][0]


@pytest.mark.parametrize("limit", [0, -1, 201])
async def test_an_out_of_range_job_page_size_is_rejected(make_token, limit) -> None:
    """An unbounded limit is a denial-of-service lever on a shared database."""
    session = _StubSession(rows=[])
    async with _app_client(session) as ac:
        response = await ac.get(
            JOBS, params={"limit": limit}, headers={"Authorization": f"Bearer {make_token()}"}
        )

    assert response.status_code == 422


async def test_listing_jobs_requires_authentication(client) -> None:
    response = await client.get(JOBS)

    assert response.status_code in (401, 403)


# --------------------------------------------------------------------------- #
# Authoring is bound to a visible job                                          #
# --------------------------------------------------------------------------- #


async def test_authoring_against_an_invisible_job_is_a_404(make_token) -> None:
    """`job_id` comes from the request body and nothing else constrains it.

    With `scalar=None` the existence probe finds no row — the same state a
    nonexistent id and another tenant's id both produce. This previously
    returned 201 and stored a rubric hanging off an id the caller could not see.
    """
    session = _StubSession(scalar=None)
    async with _app_client(session) as ac:
        response = await ac.post(
            RUBRICS,
            headers={"Authorization": f"Bearer {make_token()}"},
            json=_create_payload(job_id=str(uuid.uuid4())),
        )

    assert response.status_code == 404, response.text
    assert response.json()["error"] == "NOT_FOUND"


async def test_a_rejected_job_stores_nothing(make_token) -> None:
    """The refusal has to happen before any row is staged.

    A version staged and then abandoned still consumes a version number and
    leaves the session dirty for whatever commits next.
    """
    from app.models import Requirement, RubricVersion

    session = _StubSession(scalar=None)
    async with _app_client(session) as ac:
        await ac.post(
            RUBRICS,
            headers={"Authorization": f"Bearer {make_token()}"},
            json=_create_payload(job_id=str(uuid.uuid4())),
        )

    assert not [row for row in session.added if isinstance(row, RubricVersion)]
    assert not [row for row in session.added if isinstance(row, Requirement)]


# --------------------------------------------------------------------------- #
# Rate limiting                                                                #
# --------------------------------------------------------------------------- #


async def test_rubric_authoring_is_rate_limited(make_token) -> None:
    """Rubric creation writes one row per criterion and was left unthrottled.

    Every other write surface is covered, so an unlisted prefix is the cheapest
    bulk-write path into the database. The loop runs past the configured budget
    rather than a hard-coded count so the assertion tracks the setting.
    """
    from app.main import _RATE_LIMIT_REQUESTS

    session = _StubSession(scalar=0)
    headers = {"Authorization": f"Bearer {make_token()}"}
    statuses: list[int] = []

    async with _app_client(session) as ac:
        for _ in range(_RATE_LIMIT_REQUESTS + 5):
            response = await ac.post(RUBRICS, headers=headers, json=_create_payload())
            statuses.append(response.status_code)

    assert 429 in statuses, f"no request was throttled: {sorted(set(statuses))}"
    assert statuses[0] == 201, "throttling began before the budget was spent"


async def test_the_rate_limit_refusal_uses_the_standard_error_envelope(make_token) -> None:
    """A throttled caller needs a machine-readable reason, not a bare 429."""
    from app.main import _RATE_LIMIT_REQUESTS

    session = _StubSession(scalar=0)
    headers = {"Authorization": f"Bearer {make_token()}"}

    async with _app_client(session) as ac:
        throttled = None
        for _ in range(_RATE_LIMIT_REQUESTS + 5):
            response = await ac.post(RUBRICS, headers=headers, json=_create_payload())
            if response.status_code == 429:
                throttled = response
                break

    assert throttled is not None, "the limiter never engaged"
    body = throttled.json()
    assert body["status_code"] == 429
    assert uuid.UUID(body["request_id"])
