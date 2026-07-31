"""Tests for the rubric persistence layer.

`app.services.rubric` declares a `RubricRepository` Protocol and never imports a
session-bound class. This module tests the concrete implementation that has to
satisfy that Protocol, and it does so without a database: a recording session
captures every statement, and each statement is compiled against the PostgreSQL
dialect so the emitted SQL can be inspected directly.

Compiling rather than executing is what makes the tenant-isolation guarantee
testable here. CLAUDE.md puts every rubric read behind `tenant_id`, and README
records the rule that a foreign row is reported as missing rather than
forbidden. Both properties live in the WHERE clause, so asserting on the
compiled clause proves them without needing rows to exist.
"""

from __future__ import annotations

import ast
import inspect
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy.dialects import postgresql

_TENANT = uuid.UUID("11111111-1111-1111-1111-111111111111")
_OTHER_TENANT = uuid.UUID("22222222-2222-2222-2222-222222222222")
_JOB = uuid.UUID("44444444-4444-4444-4444-444444444444")
_VERSION_ID = uuid.UUID("55555555-5555-5555-5555-555555555555")


class _Result:
    """Stands in for a SQLAlchemy `Result` without a database behind it."""

    def __init__(self, rows: list[Any] | None = None, scalar: Any = None) -> None:
        """Store what the fake result should yield.

        Args:
            rows: Rows returned by `scalars().all()`.
            scalar: Value returned by `scalar()` and `scalar_one_or_none()`.
        """
        self._rows = [] if rows is None else rows
        self._scalar = scalar

    def scalar_one_or_none(self) -> Any:
        """Return the single scalar, or None."""
        return self._scalar

    def scalar(self) -> Any:
        """Return the single scalar, or None."""
        return self._scalar

    def scalars(self) -> _Result:
        """Return self so `.all()` can be chained, as SQLAlchemy allows."""
        return self

    def all(self) -> list[Any]:
        """Return every row."""
        return self._rows


class _RecordingSession:
    """Captures statements and instances instead of talking to PostgreSQL.

    `calls` preserves the order operations arrived in, which is what lets a test
    assert that a delete precedes the inserts that replace it.
    """

    def __init__(self, *results: _Result) -> None:
        """Queue the results `execute` should hand back, in order.

        Args:
            results: One result per expected `execute` call. An exhausted queue
                yields an empty result rather than raising, so a test that only
                cares about the emitted SQL need not supply one.
        """
        self._results = list(results)
        self.statements: list[Any] = []
        self.added: list[Any] = []
        self.calls: list[str] = []
        self.flushes = 0

    async def execute(self, statement: Any) -> _Result:
        """Record a statement and return the next queued result.

        Args:
            statement: The Core or ORM statement being executed.

        Returns:
            The next queued result, or an empty one.
        """
        self.statements.append(statement)
        self.calls.append("execute")
        return self._results.pop(0) if self._results else _Result()

    def add(self, instance: Any) -> None:
        """Record a pending insert.

        Args:
            instance: The ORM object handed to the session.
        """
        self.added.append(instance)
        self.calls.append("add")

    def add_all(self, instances: Any) -> None:
        """Record a batch of pending inserts.

        Args:
            instances: The ORM objects handed to the session.
        """
        for instance in instances:
            self.add(instance)

    async def flush(self) -> None:
        """Record a flush."""
        self.flushes += 1
        self.calls.append("flush")


def _sql(statement: Any) -> str:
    """Compile a statement to PostgreSQL SQL text.

    The PostgreSQL dialect is required rather than the default one because the
    requirement rows carry a `halfvec` column, which only that dialect renders.

    Args:
        statement: The statement to compile.

    Returns:
        The compiled SQL string.
    """
    return str(statement.compile(dialect=postgresql.dialect()))


def _params(statement: Any) -> dict[str, Any]:
    """Return the bind parameters a statement would send.

    Args:
        statement: The statement to compile.

    Returns:
        Mapping of bind parameter name to value.
    """
    return dict(statement.compile(dialect=postgresql.dialect()).params)


def _repository(session: _RecordingSession) -> Any:
    """Build the repository under test against a recording session.

    Args:
        session: The fake session to inject.

    Returns:
        A `RubricRepository` bound to that session.
    """
    from app.repositories.rubric import RubricRepository

    return RubricRepository(session)


def _requirement(text: str, weight: str, *, ordinal: int = 0) -> Any:
    """Build an unsaved requirement.

    Args:
        text: Criterion text.
        weight: Normalized weight as a decimal string.
        ordinal: Display position.

    Returns:
        A `Requirement` instance.
    """
    from app.models import Requirement

    return Requirement(
        id=uuid.uuid4(),
        tenant_id=_TENANT,
        rubric_version_id=_VERSION_ID,
        ordinal=ordinal,
        text=text,
        category="skill",
        is_must_have=False,
        weight=Decimal(weight),
    )


def _version() -> Any:
    """Build an unsaved draft rubric version.

    Returns:
        A `RubricVersion` instance owned by `_TENANT`.
    """
    from app.models import RubricVersion

    return RubricVersion(
        id=_VERSION_ID,
        tenant_id=_TENANT,
        job_id=_JOB,
        version=1,
        status="draft",
    )


# ---------------------------------------------------------------------------
# contract
# ---------------------------------------------------------------------------


def test_repository_satisfies_the_service_protocol() -> None:
    """The concrete class must match the Protocol the service depends on.

    The service calls these methods positionally, so parameter names and order
    are part of the contract, not just the method names. A silent rename here
    would surface as a `TypeError` only at runtime.
    """
    from app.repositories.rubric import RubricRepository as ConcreteRepository
    from app.services.rubric import RubricRepository as RepositoryContract

    declared = [
        name
        for name, _ in inspect.getmembers(RepositoryContract, inspect.isfunction)
        if not name.startswith("_")
    ]
    assert declared, "the Protocol declares no methods — this test would pass vacuously"

    for name in declared:
        implementation = getattr(ConcreteRepository, name, None)
        assert implementation is not None, f"RubricRepository does not implement {name}"
        assert inspect.iscoroutinefunction(implementation), f"{name} must be async"
        assert list(inspect.signature(implementation).parameters) == list(
            inspect.signature(getattr(RepositoryContract, name)).parameters
        ), f"{name} parameters diverge from the Protocol"


def test_module_builds_no_raw_sql() -> None:
    """Rubric persistence has no need for `text()`, so none may appear.

    Raw SQL is where the interpolation defect fixed in `repositories/search.py`
    became possible. If a future rubric query genuinely needs `text()`, replace
    this test with the static-literal AST checks in
    `tests/unit/test_search_repository_security.py` rather than deleting it.
    """
    import app.repositories.rubric as module

    tree = ast.parse(inspect.getsource(module))
    offenders: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
        if name == "text":
            offenders.append(node.lineno)

    assert not offenders, (
        "raw text() SQL found in app.repositories.rubric at line(s) "
        f"{offenders} — use ORM constructs or add static-literal assertions"
    )


# ---------------------------------------------------------------------------
# get_version
# ---------------------------------------------------------------------------


async def test_get_version_filters_on_tenant_and_id() -> None:
    """Isolation lives in the WHERE clause, not in caller discipline."""
    session = _RecordingSession(_Result(scalar=None))

    await _repository(session).get_version(_TENANT, _VERSION_ID)

    statement = session.statements[0]
    sql = _sql(statement)
    assert "rubric_versions.tenant_id = " in sql
    assert "rubric_versions.id = " in sql
    assert set(_params(statement).values()) >= {_TENANT, _VERSION_ID}


async def test_get_version_returns_none_for_a_foreign_tenant() -> None:
    """A row belonging to another tenant must be indistinguishable from absent.

    The query binds the caller's tenant, so PostgreSQL returns nothing and the
    repository reports None. The router turns that into 404 — a 403 would confirm
    the identifier exists somewhere.
    """
    session = _RecordingSession(_Result(scalar=None))

    result = await _repository(session).get_version(_OTHER_TENANT, _VERSION_ID)

    assert result is None
    assert _OTHER_TENANT in set(_params(session.statements[0]).values())


async def test_get_version_returns_the_row_when_present() -> None:
    """A matching row is handed back unchanged."""
    version = _version()
    session = _RecordingSession(_Result(scalar=version))

    result = await _repository(session).get_version(_TENANT, _VERSION_ID)

    assert result is version


# ---------------------------------------------------------------------------
# max_version_for_job
# ---------------------------------------------------------------------------


async def test_max_version_for_job_returns_zero_when_no_rubric_exists() -> None:
    """The service adds 1 to this, so an unknown job must yield 0, not None.

    `max()` over an empty set is SQL NULL. Returning that unchanged would make
    `create_draft_rubric` compute `None + 1` and raise `TypeError` on the very
    first rubric for a job.
    """
    session = _RecordingSession(_Result(scalar=None))

    assert await _repository(session).max_version_for_job(_TENANT, _JOB) == 0


async def test_max_version_for_job_returns_the_highest_version() -> None:
    """The stored maximum is returned as an int."""
    session = _RecordingSession(_Result(scalar=3))

    assert await _repository(session).max_version_for_job(_TENANT, _JOB) == 3


async def test_max_version_for_job_aggregates_instead_of_loading_rows() -> None:
    """A job with many versions must not be read into memory to find the max."""
    session = _RecordingSession(_Result(scalar=1))

    await _repository(session).max_version_for_job(_TENANT, _JOB)

    assert "max(" in _sql(session.statements[0]).lower()


async def test_max_version_for_job_filters_on_tenant_and_job() -> None:
    """Version numbering is per job and must never span tenants."""
    session = _RecordingSession(_Result(scalar=1))

    await _repository(session).max_version_for_job(_TENANT, _JOB)

    statement = session.statements[0]
    sql = _sql(statement)
    assert "rubric_versions.tenant_id = " in sql
    assert "rubric_versions.job_id = " in sql
    assert set(_params(statement).values()) >= {_TENANT, _JOB}


# ---------------------------------------------------------------------------
# add_version
# ---------------------------------------------------------------------------


async def test_add_version_persists_and_returns_the_row() -> None:
    """The caller keeps its reference, so the same object must come back.

    `create_draft_rubric` reads `version.id` afterwards to scope the
    requirements, so returning a copy would silently attach requirements to the
    wrong version.
    """
    version = _version()
    session = _RecordingSession()

    result = await _repository(session).add_version(version)

    assert result is version
    assert session.added == [version]


async def test_add_version_flushes_so_the_id_is_usable() -> None:
    """Requirements reference the version id, so the insert cannot stay pending.

    Without a flush the foreign key would be checked against a row PostgreSQL
    has not seen yet.
    """
    session = _RecordingSession()

    await _repository(session).add_version(_version())

    assert session.flushes >= 1
    assert session.calls.index("add") < session.calls.index("flush")


# ---------------------------------------------------------------------------
# replace_requirements
# ---------------------------------------------------------------------------


async def test_replace_requirements_deletes_before_inserting() -> None:
    """Replacing means the old set is gone, not merged with the new one.

    Editing a draft to remove a criterion must actually remove it; an
    insert-only implementation would leave the dropped requirement scoring
    candidates.
    """
    session = _RecordingSession()

    await _repository(session).replace_requirements(
        _TENANT, _VERSION_ID, [_requirement("Python", "0.6000")]
    )

    assert "execute" in session.calls, "no statement issued — nothing was deleted"
    assert session.calls.index("execute") < session.calls.index("add")


async def test_replace_requirements_scopes_the_delete_to_one_version() -> None:
    """An unscoped DELETE would wipe another tenant's or another version's rows."""
    session = _RecordingSession()

    await _repository(session).replace_requirements(
        _TENANT, _VERSION_ID, [_requirement("Python", "1.0000")]
    )

    statement = session.statements[0]
    sql = _sql(statement)
    assert sql.upper().startswith("DELETE"), f"expected a DELETE, got: {sql}"
    assert "requirements.tenant_id = " in sql
    assert "requirements.rubric_version_id = " in sql
    assert set(_params(statement).values()) >= {_TENANT, _VERSION_ID}


async def test_replace_requirements_inserts_every_requirement() -> None:
    """All supplied rows reach the session, in the order given."""
    requirements = [
        _requirement("Python", "0.5000", ordinal=0),
        _requirement("Go", "0.3000", ordinal=1),
        _requirement("Kubernetes", "0.2000", ordinal=2),
    ]
    session = _RecordingSession()

    await _repository(session).replace_requirements(_TENANT, _VERSION_ID, requirements)

    assert session.added == requirements


async def test_replace_requirements_with_an_empty_list_still_clears_the_set() -> None:
    """Clearing is a legitimate operation for this layer.

    The service rejects empty rubrics; the repository must not also guess, or
    "delete everything then insert nothing" would become impossible to express.
    """
    session = _RecordingSession()

    await _repository(session).replace_requirements(_TENANT, _VERSION_ID, [])

    assert _sql(session.statements[0]).upper().startswith("DELETE")
    assert session.added == []


async def test_replace_requirements_flushes_after_inserting() -> None:
    """The rows must be visible to the transaction before the caller continues."""
    session = _RecordingSession()

    await _repository(session).replace_requirements(
        _TENANT, _VERSION_ID, [_requirement("Python", "1.0000")]
    )

    assert session.flushes >= 1
    assert session.calls[-1] == "flush", f"expected a trailing flush, got {session.calls}"


# ---------------------------------------------------------------------------
# list_requirements
# ---------------------------------------------------------------------------


async def test_list_requirements_orders_by_ordinal() -> None:
    """Display order is stored, so it must be restored by the query.

    `compute_content_hash` ignores ordinal deliberately, which means ordering is
    purely a presentation guarantee — and the only place it can be enforced is
    here.
    """
    session = _RecordingSession(_Result(rows=[]))

    await _repository(session).list_requirements(_TENANT, _VERSION_ID)

    assert "ORDER BY requirements.ordinal" in _sql(session.statements[0])


async def test_list_requirements_filters_on_tenant_and_version() -> None:
    """Requirements are read only through their owning version and tenant."""
    session = _RecordingSession(_Result(rows=[]))

    await _repository(session).list_requirements(_TENANT, _VERSION_ID)

    statement = session.statements[0]
    sql = _sql(statement)
    assert "requirements.tenant_id = " in sql
    assert "requirements.rubric_version_id = " in sql
    assert set(_params(statement).values()) >= {_TENANT, _VERSION_ID}


async def test_list_requirements_returns_a_list() -> None:
    """The Protocol promises `list`, and callers index and re-sort the result.

    SQLAlchemy hands back a `Sequence`; leaking that would satisfy iteration but
    break anything that mutates the result.
    """
    rows = [_requirement("Python", "1.0000")]
    session = _RecordingSession(_Result(rows=rows))

    result = await _repository(session).list_requirements(_TENANT, _VERSION_ID)

    assert isinstance(result, list)
    assert result == rows


async def test_list_requirements_returns_empty_for_a_draft_with_no_criteria() -> None:
    """A freshly minted version has no requirements, which is not an error."""
    session = _RecordingSession(_Result(rows=[]))

    assert await _repository(session).list_requirements(_TENANT, _VERSION_ID) == []
