"""SSE (Server-Sent Events) progress streaming.

Single endpoint: GET /screening/runs/{id}/events — streams run progress
as SSE. The orchestrator pushes events through an asyncio.Queue per run.

Events: run.started, stage.started, stage.progress, stage.complete,
verdict.ready, run.complete, run.failed, run.cancelled.

ARCHITECTURE-AGENTS.md §2.4 — SSE is how the orchestrator reports to
the caller without polling.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from enum import Enum
from typing import Any


class EventType(str, Enum):
    RUN_STARTED = "run.started"
    RUN_COMPLETE = "run.complete"
    RUN_FAILED = "run.failed"
    RUN_CANCELLED = "run.cancelled"
    STAGE_STARTED = "stage.started"
    STAGE_PROGRESS = "stage.progress"
    STAGE_COMPLETE = "stage.complete"
    VERDICT_READY = "verdict.ready"
    HEARTBEAT = "heartbeat"


class SSEManager:
    """In-process SSE event broker. One queue per active run."""

    def __init__(self) -> None:
        self._queues: dict[uuid.UUID, asyncio.Queue[dict]] = {}
        # Periodic heartbeat for all active runs
        self._heartbeat_task: asyncio.Task | None = None

    def _ensure_queue(self, run_id: uuid.UUID) -> asyncio.Queue[dict]:
        if run_id not in self._queues:
            self._queues[run_id] = asyncio.Queue(maxsize=1000)
        return self._queues[run_id]

    async def publish(self, run_id: uuid.UUID, event_type: EventType, data: Any = None) -> None:
        """Push an event to a run's queue."""
        queue = self._ensure_queue(run_id)
        await queue.put({
            "event": event_type.value,
            "data": data or {},
            "timestamp": time.time(),
        })

    async def subscribe(self, run_id: uuid.UUID, cancel_event: asyncio.Event):
        """Async generator yielding SSE-formatted bytes for a run.

        Yields until the run completes/fails/cancels or the connection
        is closed (cancel_event is set).
        """
        queue = self._ensure_queue(run_id)
        heartbeat_interval = 15  # seconds

        while True:
            try:
                # Wait for next event with heartbeat timeout
                event = await asyncio.wait_for(queue.get(), timeout=heartbeat_interval)
                yield _format_sse(event["event"], event["data"], event["timestamp"])
                # Terminal events close the stream
                if event["event"] in {
                    EventType.RUN_COMPLETE.value,
                    EventType.RUN_FAILED.value,
                    EventType.RUN_CANCELLED.value,
                }:
                    break
            except asyncio.TimeoutError:
                # Send heartbeat
                yield _format_sse(EventType.HEARTBEAT.value, {}, time.time())

            if cancel_event.is_set():
                break

    def remove(self, run_id: uuid.UUID) -> None:
        """Clean up a completed run's queue."""
        self._queues.pop(run_id, None)


def _format_sse(event: str, data: Any, timestamp: float) -> bytes:
    """Format an SSE event as bytes."""
    payload = json.dumps({"timestamp": timestamp, **data} if isinstance(data, dict) else data)
    return f"event: {event}\ndata: {payload}\n\n".encode("utf-8")


# Process-wide singleton
_sse_manager = SSEManager()


def get_sse_manager() -> SSEManager:
    return _sse_manager
