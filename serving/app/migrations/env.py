"""Alembic environment.

Supports two invocation styles:

* **Programmatic** — `app.migrations.run_upgrade` passes an already-open
  connection via `config.attributes["connection"]`. Used by tests, startup
  checks, and deployment scripts.
* **CLI** — `alembic revision --autogenerate` and friends, where no connection
  is supplied and this module opens its own synchronous one.

The metadata comes from the ORM models, so autogenerate compares against the
same definitions the application queries.
"""

from __future__ import annotations

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.config import get_settings
from app.db import Base
from app.models import Job, ResumeDocument, ResumeVersion  # noqa: F401 - register tables

config = context.config
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Emit SQL to stdout without connecting to a database."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Apply migrations against a live connection."""
    connection = config.attributes.get("connection")

    if connection is not None:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()
        return

    # `alembic.ini` deliberately ships an empty URL so no credential is ever
    # committed. Fall back to Settings, which is the single source of config.
    url = config.get_main_option("sqlalchemy.url") or get_settings().database_url
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = url.replace("+asyncpg", "+psycopg2")
    engine = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)

    with engine.connect() as own_connection:
        context.configure(
            connection=own_connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
