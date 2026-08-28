"""Durable screening worker, independent of the FastAPI request process."""

from __future__ import annotations

import asyncio

from app.db import get_sessionmaker
from app.routers.screening import _drain_run
from app.services.workflow_runner import InProcessWorkflowRunner


async def drain_ready_screening_runs(limit: int = 100) -> int:
    """Recover abandoned claims and execute every ready screening task once."""
    runner = InProcessWorkflowRunner(get_sessionmaker())
    await runner.recover_claimed()
    runs = await runner.ready_runs(limit=limit)
    for run_id, tenant_id in runs:
        await _drain_run(run_id, tenant_id)
    return len(runs)


def main() -> None:
    """Run one worker pass for a scheduler, container command, or cron job."""
    asyncio.run(drain_ready_screening_runs())


if __name__ == "__main__":
    main()
