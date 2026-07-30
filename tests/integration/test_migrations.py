"""Alembic migration correctness.

A migration suite that drifts from the ORM models is worse than no migration
suite: the schema a deployment creates silently stops matching the schema the
code queries. These tests pin the properties that prevent that drift.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration

EXPECTED_TABLES = {"resume_documents", "resume_versions", "jobs"}


def test_alembic_config_is_discoverable():
    """`alembic.ini` must exist and name the migration script location."""
    from app.migrations import get_alembic_config

    config = get_alembic_config()

    assert config.get_main_option("script_location")


def test_migration_head_is_single():
    """Multiple heads mean an unmerged branch — deployments become ambiguous."""
    from alembic.script import ScriptDirectory

    from app.migrations import get_alembic_config

    script = ScriptDirectory.from_config(get_alembic_config())

    assert len(script.get_heads()) == 1


async def test_upgrade_head_creates_every_expected_table(clean_database):
    """Upgrading from empty must produce the full schema the code queries."""
    from sqlalchemy import inspect

    from app.migrations import run_upgrade

    await run_upgrade("head")

    tables = set(await clean_database.run_sync(lambda c: inspect(c).get_table_names()))

    assert tables >= EXPECTED_TABLES
    assert "alembic_version" in tables


async def test_migrations_match_the_orm_models(clean_database):
    """Autogenerate must find nothing left to do.

    This is the regression guard: if a model changes without a matching
    migration, this fails and names the drift.
    """
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    from app.db import Base
    from app.migrations import run_upgrade

    await run_upgrade("head")

    def _diff(connection: object) -> list[object]:
        context = MigrationContext.configure(connection)
        return compare_metadata(context, Base.metadata)

    diff = await clean_database.run_sync(_diff)

    assert diff == [], f"models and migrations have drifted: {diff}"


async def test_downgrade_then_upgrade_is_reversible(clean_database):
    """A migration that cannot be rolled back is not a safe deployment unit."""
    from sqlalchemy import inspect

    from app.migrations import run_downgrade, run_upgrade

    await run_upgrade("head")
    await run_downgrade("base")

    after_downgrade = set(
        await clean_database.run_sync(lambda c: inspect(c).get_table_names())
    )
    assert not (EXPECTED_TABLES & after_downgrade)

    await run_upgrade("head")

    after_reupgrade = set(
        await clean_database.run_sync(lambda c: inspect(c).get_table_names())
    )
    assert after_reupgrade >= EXPECTED_TABLES


async def test_upgrade_is_idempotent(clean_database):
    """Re-running an already-applied upgrade must be a no-op, not an error."""
    from app.migrations import run_upgrade

    await run_upgrade("head")
    await run_upgrade("head")


async def test_tenant_scoped_tables_are_indexed_on_tenant_id(clean_database):
    """Every tenant-scoped query filters on tenant_id; it must be indexed.

    Without this the isolation guarantee is correct but performs a sequential
    scan on every read, which does not survive a realistic candidate pool.
    """
    from sqlalchemy import inspect

    from app.migrations import run_upgrade

    await run_upgrade("head")

    def _indexed_columns(connection: object, table: str) -> set[str]:
        inspector = inspect(connection)
        columns: set[str] = set()
        for index in inspector.get_indexes(table):
            columns.update(index["column_names"] or [])
        return columns

    for table in EXPECTED_TABLES:
        columns = await clean_database.run_sync(_indexed_columns, table)
        assert "tenant_id" in columns, f"{table}.tenant_id is not indexed"


async def test_content_hash_uniqueness_is_enforced_by_the_database(clean_database):
    """Deduplication must be a database constraint, not application politeness."""
    from sqlalchemy import inspect

    from app.migrations import run_upgrade

    await run_upgrade("head")

    def _unique_constraint_columns(connection: object) -> list[list[str]]:
        inspector = inspect(connection)
        return [
            list(c["column_names"])
            for c in inspector.get_unique_constraints("resume_documents")
        ]

    constraints = await clean_database.run_sync(_unique_constraint_columns)

    assert ["tenant_id", "sha256"] in constraints
