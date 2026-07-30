"""Programmatic access to the Alembic migration suite.

Migrations are exposed as functions rather than only as a CLI so that startup
checks, tests, and deployment scripts all drive the same code path. Alembic's
own API is synchronous, so each entry point bridges to it through the async
engine's `run_sync`.
"""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy.engine import Connection

from app.config import get_settings
from app.db import get_engine
from app.logging import get_logger

logger = get_logger(__name__)

_PACKAGE_ROOT = Path(__file__).resolve().parent
_PROJECT_ROOT = _PACKAGE_ROOT.parents[2]
ALEMBIC_INI = _PROJECT_ROOT / "alembic.ini"


def get_alembic_config() -> Config:
    """Build an Alembic config wired to this project's settings.

    The database URL is injected from `Settings` rather than read from
    `alembic.ini`, so migrations always target the same database the
    application does and no credential is ever written to a tracked file.

    Returns:
        A configured Alembic `Config`.

    Raises:
        FileNotFoundError: If `alembic.ini` is missing from the project root.
    """
    if not ALEMBIC_INI.is_file():
        msg = f"alembic.ini not found at {ALEMBIC_INI}"
        raise FileNotFoundError(msg)

    config = Config(str(ALEMBIC_INI))
    config.set_main_option("script_location", str(_PACKAGE_ROOT))
    config.set_main_option("sqlalchemy.url", get_settings().database_url.replace("%", "%%"))
    return config


def _upgrade(connection: Connection, revision: str) -> None:
    """Run an upgrade on an already-open synchronous connection.

    Args:
        connection: A synchronous connection supplied by `run_sync`.
        revision: Target revision, e.g. ``"head"``.
    """
    config = get_alembic_config()
    config.attributes["connection"] = connection
    command.upgrade(config, revision)


def _downgrade(connection: Connection, revision: str) -> None:
    """Run a downgrade on an already-open synchronous connection.

    Args:
        connection: A synchronous connection supplied by `run_sync`.
        revision: Target revision, e.g. ``"base"``.
    """
    config = get_alembic_config()
    config.attributes["connection"] = connection
    command.downgrade(config, revision)


async def run_upgrade(revision: str = "head") -> None:
    """Apply migrations up to `revision`.

    Idempotent: applying an already-current revision is a no-op.

    Args:
        revision: Target revision. Defaults to the latest.
    """
    engine = get_engine()
    async with engine.begin() as connection:
        await connection.run_sync(_upgrade, revision)
    logger.info("migrations_applied", revision=revision)


async def run_downgrade(revision: str) -> None:
    """Roll migrations back to `revision`.

    Args:
        revision: Target revision, e.g. ``"base"`` to unwind everything.
    """
    engine = get_engine()
    async with engine.begin() as connection:
        await connection.run_sync(_downgrade, revision)
    logger.warning("migrations_rolled_back", revision=revision)
