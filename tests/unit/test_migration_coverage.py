"""Migration coverage for the ORM models, without a database.

`tests/integration/test_migrations.py` already proves the schema and the models
agree — by running `compare_metadata` against a live PostgreSQL. That is the
stronger check and it stays authoritative. It is also unavailable on a machine
with no database, which is exactly where a model gets added and its migration
forgotten.

These tests close that window. They read `Base.metadata` and the Alembic
revision scripts as text, so they run anywhere and fail the moment a table is
declared in code without a revision that creates it.
"""

from __future__ import annotations

import re
from pathlib import Path

_VERSIONS = Path(__file__).resolve().parents[2] / "serving" / "app" / "migrations" / "versions"


def _revision_sources() -> dict[Path, str]:
    """Return every revision script keyed by path, excluding caches."""
    return {path: path.read_text(encoding="utf-8") for path in sorted(_VERSIONS.glob("*.py"))}


def _declared_tables() -> set[str]:
    """Return the table names the ORM declares."""
    import app.models  # noqa: F401  — importing registers every table on Base
    from app.db import Base

    return set(Base.metadata.tables)


def test_revision_scripts_exist() -> None:
    """Anti-vacuous guard: the checks below are meaningless with no scripts."""
    assert _revision_sources(), f"no Alembic revision scripts found under {_VERSIONS}"


def test_every_orm_table_is_created_by_some_migration() -> None:
    """A table in the models with no migration is a deployment that cannot boot.

    The models are the schema the code queries; the migrations are the schema a
    deployment actually gets. When they diverge the failure surfaces as an
    UndefinedTable error in production rather than a test failure here.
    """
    sources = _revision_sources()
    declared = _declared_tables()
    assert declared, "Base.metadata is empty — models did not import"

    missing = sorted(
        table
        for table in declared
        if not any(
            re.search(rf"""create_table\(\s*["']{re.escape(table)}["']""", source)
            or re.search(rf"""CREATE TABLE (?:IF NOT EXISTS )?{re.escape(table)}\b""", source)
            for source in sources.values()
        )
    )

    assert not missing, (
        f"tables declared in app.models with no migration creating them: {missing} — "
        "add an Alembic revision before merging"
    )


def test_the_revision_graph_has_a_single_head() -> None:
    """Two heads make `upgrade head` ambiguous and the deployment order undefined.

    Parsed from source rather than via `ScriptDirectory` so this needs no
    database URL and no Alembic config to resolve.
    """
    sources = _revision_sources()

    revisions: set[str] = set()
    parents: set[str] = set()
    for source in sources.values():
        found = re.search(r"""^revision:\s*str\s*=\s*["']([^"']+)["']""", source, re.MULTILINE)
        if found:
            revisions.add(found.group(1))
        down = re.search(r"""^down_revision:[^=]*=\s*["']([^"']+)["']""", source, re.MULTILINE)
        if down:
            parents.add(down.group(1))

    heads = sorted(revisions - parents)

    assert len(heads) == 1, f"expected exactly one migration head, found {heads}"


def test_every_declared_parent_revision_exists() -> None:
    """A `down_revision` naming a deleted script breaks `upgrade` on a fresh database."""
    sources = _revision_sources()

    revisions: set[str] = set()
    parents: dict[str, str] = {}
    for path, source in sources.items():
        found = re.search(r"""^revision:\s*str\s*=\s*["']([^"']+)["']""", source, re.MULTILINE)
        if found:
            revisions.add(found.group(1))
        down = re.search(r"""^down_revision:[^=]*=\s*["']([^"']+)["']""", source, re.MULTILINE)
        if down:
            parents[path.name] = down.group(1)

    dangling = sorted(
        f"{name} -> {parent}" for name, parent in parents.items() if parent not in revisions
    )

    assert not dangling, f"down_revision points at a revision that does not exist: {dangling}"


def test_tenant_scoped_tables_are_indexed_on_tenant_id() -> None:
    """Tenant isolation that costs a sequential scan does not survive real data.

    Every repository filters on `tenant_id`, so an unindexed tenant column turns
    each read into a full-table scan. Checked against the ORM metadata, which is
    what the integration suite verifies against the live schema.
    """
    declared_tables = _declared_tables()
    from app.db import Base

    assert declared_tables, "Base.metadata is empty — models did not import"

    unindexed: list[str] = []
    for name, table in Base.metadata.tables.items():
        if "tenant_id" not in table.columns:
            continue
        indexed = {column.name for index in table.indexes for column in index.columns} | {
            column.name
            for constraint in table.constraints
            for column in getattr(constraint, "columns", [])
        }
        if "tenant_id" not in indexed:
            unindexed.append(name)

    assert not unindexed, (
        f"tables carrying tenant_id with no index covering it: {sorted(unindexed)}"
    )
