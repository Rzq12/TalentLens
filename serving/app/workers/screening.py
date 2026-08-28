"""Durable screening worker, independent of the FastAPI request process."""

from __future__ import annotations

import asyncio
import logging
import os
import time

from app.db import get_sessionmaker
from app.metrics import workflow_worker_cycle_errors_total, workflow_worker_last_success_timestamp
from app.routers.screening import _drain_run
from app.services.workflow_runner import InProcessWorkflowRunner

logger = logging.getLogger(__name__)

async def drain_ready_screening_runs(limit: int = 100) -> int:
    """Recover abandoned claims and execute every ready screening task once."""
    runner = InProcessWorkflowRunner(get_sessionmaker())
    await runner.recover_claimed()
    runs = await runner.ready_runs(limit=limit)
    for run_id, tenant_id in runs:
        await _drain_run(run_id, tenant_id)
    return len(runs)

async def run_forever(interval_seconds: float = 5.0, limit: int = 100) -> None:
    """Continuously drain the durable queue for deployment as a worker service."""
    while True:
        try:
            await drain_ready_screening_runs(limit=limit)
            workflow_worker_last_success_timestamp.set(time.time())
        except Exception:
            logger.exception("Durable screening worker cycle failed")
            workflow_worker_cycle_errors_total.inc()
        await asyncio.sleep(interval_seconds)

def main() -> None:
    """Run a single scheduler pass or a continuous worker process."""
    if os.getenv("WORKER_CONTINUOUS", "false").lower() == "true":
        asyncio.run(run_forever())
    else:
        asyncio.run(drain_ready_screening_runs())


if __name__ == "__main__":
    main()
