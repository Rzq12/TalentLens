"""Focused durability checks for the Postgres workflow runner."""

from __future__ import annotations

import uuid
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.services.workflow_runner import InProcessWorkflowRunner, _advisory_lock_key


class _Result:
    """Minimal result object for a checkpoint query."""

    def all(self) -> list[tuple[uuid.UUID]]:
        """Return one stale run id."""
        return [(uuid.UUID("12345678-1234-5678-1234-567812345678"),)]


class _Session:
    """Captures the stale-run query issued by the runner."""

    statement: Any | None = None

    async def execute(self, statement: Any) -> _Result:
        """Capture the query and return a fixed row."""
        self.statement = statement
        return _Result()


class _SessionContext(AbstractAsyncContextManager[_Session]):
    """Async context manager around a test session."""

    def __init__(self, session: _Session) -> None:
        """Store the provided session."""
        self.session = session

    async def __aenter__(self) -> _Session:
        """Return the wrapped session."""
        return self.session

    async def __aexit__(self, *args: object) -> None:
        """No test cleanup is required."""


def test_advisory_lock_key_is_stable_and_signed_64_bit() -> None:
    """Workers independently derive the same PostgreSQL lock key for a run."""
    run_id = uuid.UUID("ffffffff-ffff-ffff-0000-000000000000")

    key = _advisory_lock_key(run_id)

    assert key == _advisory_lock_key(run_id)
    assert -(1 << 63) <= key < (1 << 63)


@pytest.mark.asyncio
async def test_resume_stale_honors_threshold_and_active_run_status() -> None:
    """Only old queued/running checkpoints qualify for recovery."""
    session = _Session()
    runner = InProcessWorkflowRunner(lambda: _SessionContext(session))
    before = datetime.now(UTC)

    run_ids = await runner.resume_stale(older_than_seconds=300)

    assert run_ids == [uuid.UUID("12345678-1234-5678-1234-567812345678")]
    compiled = session.statement.compile()
    assert "screening_runs" in str(compiled)
    assert "screening_runs.status IN" in str(compiled)
    cutoff = next(
        value
        for value in compiled.params.values()
        if isinstance(value, datetime)
    )
    assert before - timedelta(seconds=302) < cutoff < before - timedelta(seconds=298)
