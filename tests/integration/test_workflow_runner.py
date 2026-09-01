"""PostgreSQL behavior checks for the durable workflow runner."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.db import get_sessionmaker
from app.models import Job, RubricVersion, RunTask, ScreeningRun
from app.services.workflow_runner import InProcessWorkflowRunner

pytestmark = pytest.mark.integration


async def _seed_run_parents(tenant_id: uuid.UUID, run_ids: list[uuid.UUID]) -> None:
    job_id = uuid.uuid4()
    rubric_id = uuid.uuid4()
    async with get_sessionmaker()() as session:
        session.add_all(
            [
                Job(
                    id=job_id,
                    tenant_id=tenant_id,
                    created_by=uuid.uuid4(),
                    title="Backend Engineer",
                    description_raw="Role.",
                ),
                RubricVersion(
                    id=rubric_id,
                    tenant_id=tenant_id,
                    job_id=job_id,
                    version=1,
                    status="approved",
                ),
                *(
                    ScreeningRun(
                        id=run_id,
                        tenant_id=tenant_id,
                        job_id=job_id,
                        rubric_version_id=rubric_id,
                    )
                    for run_id in run_ids
                ),
            ]
        )
        await session.commit()


async def test_ready_runs_deduplicates_orders_and_skips_deferred_tasks(db_client, tenant_id):
    runner = InProcessWorkflowRunner(get_sessionmaker())
    first_run_id = uuid.uuid4()
    second_run_id = uuid.uuid4()
    deferred_run_id = uuid.uuid4()
    await _seed_run_parents(tenant_id, [first_run_id, second_run_id, deferred_run_id])

    async with get_sessionmaker()() as session:
        session.add_all(
            [
                RunTask(
                    tenant_id=tenant_id,
                    run_id=first_run_id,
                    stage="screening",
                    status="pending",
                ),
                RunTask(
                    tenant_id=tenant_id,
                    run_id=first_run_id,
                    stage="screening",
                    status="pending",
                ),
                RunTask(
                    tenant_id=tenant_id,
                    run_id=second_run_id,
                    stage="screening",
                    status="pending",
                ),
                RunTask(
                    tenant_id=tenant_id,
                    run_id=deferred_run_id,
                    stage="screening",
                    status="pending",
                    not_before=datetime.now(UTC) + timedelta(minutes=5),
                ),
            ]
        )
        await session.commit()

    assert await runner.ready_runs() == [
        (first_run_id, tenant_id),
        (second_run_id, tenant_id),
    ]


async def _task_by_id(task_id: int) -> RunTask:
    async with get_sessionmaker()() as session:
        return (await session.execute(select(RunTask).where(RunTask.id == task_id))).scalar_one()


async def test_fail_retries_transient_errors_and_stops_at_max_attempts(db_client, tenant_id):
    run_id = uuid.uuid4()
    await _seed_run_parents(tenant_id, [run_id])
    runner = InProcessWorkflowRunner(get_sessionmaker())
    await runner.enqueue(
        run_id=run_id,
        tenant_id=tenant_id,
        stage="screening",
        agent_name="semantic_matching",
        tasks=[{}, {}],
    )

    claimed_tasks = await runner.claim(run_id, "screening")
    first_task, terminal_task = claimed_tasks
    before_retry = datetime.now(UTC)
    await runner.fail(first_task.id, "Provider unavailable.", error_code="network")
    retry_task = await _task_by_id(first_task.id)
    assert retry_task.status == "pending"
    assert retry_task.attempt == 1
    assert retry_task.error_code == "network"
    assert (
        before_retry + timedelta(seconds=1)
        <= retry_task.not_before
        <= before_retry + timedelta(seconds=3)
    )

    terminal_task_id = terminal_task.id
    async with get_sessionmaker()() as session:
        task = await session.get(RunTask, terminal_task_id)
        task.attempt = task.max_attempts
        await session.commit()
    await runner.fail(terminal_task_id, "Provider unavailable.", error_code="network")
    assert (await _task_by_id(terminal_task_id)).status == "failed"


async def test_fail_reschedules_quota_without_consuming_an_attempt(db_client, tenant_id):
    run_id = uuid.uuid4()
    await _seed_run_parents(tenant_id, [run_id])
    runner = InProcessWorkflowRunner(get_sessionmaker())
    task_id = (
        await runner.enqueue(
            run_id=run_id,
            tenant_id=tenant_id,
            stage="screening",
            agent_name="semantic_matching",
            tasks=[{}],
        )
    )[0]

    claimed_task = (await runner.claim(run_id, "screening"))[0]
    before_reschedule = datetime.now(UTC)
    await runner.fail(
        task_id, "Provider quota exhausted.", error_code="quota", retry_after_seconds=30
    )
    quota_task = await _task_by_id(claimed_task.id)
    assert quota_task.status == "pending"
    assert quota_task.attempt == 0
    assert quota_task.error_code == "quota"
    assert (
        before_reschedule + timedelta(seconds=29)
        <= quota_task.not_before
        <= before_reschedule + timedelta(seconds=31)
    )
