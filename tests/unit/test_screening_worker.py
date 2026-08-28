"""Focused lifecycle tests for the post-response screening worker."""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.exceptions import LLMProviderError
from app.models import Job, RubricVersion, ScreeningRun
from app.routers import screening
from app.services.sse import EventType


class _Session:
    def __init__(self, run: ScreeningRun, rubric: RubricVersion, job: Job) -> None:
        self._items = {
            (ScreeningRun, run.id): run,
            (RubricVersion, rubric.id): rubric,
            (Job, job.id): job,
        }
        self.commits = 0
        self.rollbacks = 0

    async def get(self, model: type[Any], item_id: uuid.UUID) -> Any:
        return self._items.get((model, item_id))

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


class _SessionContext:
    def __init__(self, session: _Session) -> None:
        self.session = session

    async def __aenter__(self) -> _Session:
        return self.session

    async def __aexit__(self, *args: Any) -> None:
        return None


@pytest.fixture
def run_dependencies() -> tuple[ScreeningRun, RubricVersion, Job]:
    tenant_id = uuid.uuid4()
    job = Job(id=uuid.uuid4(), tenant_id=tenant_id, title="Backend Engineer")
    rubric = RubricVersion(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        job_id=job.id,
        version=1,
        status="approved",
        source="manual",
        must_have_fail_cap=40,
        aggregation_formula_version="v1",
    )
    run = ScreeningRun(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        job_id=job.id,
        rubric_version_id=rubric.id,
        status="queued",
        mode="interactive",
    )
    return run, rubric, job


@pytest.mark.asyncio
async def test_execute_run_commits_and_publishes_terminal_events(
    monkeypatch: pytest.MonkeyPatch,
    run_dependencies: tuple[ScreeningRun, RubricVersion, Job],
) -> None:
    run, rubric, job = run_dependencies
    session = _Session(run, rubric, job)
    events: list[tuple[uuid.UUID, EventType, dict[str, Any]]] = []

    monkeypatch.setattr(screening, "get_sessionmaker", lambda: lambda: _SessionContext(session))
    monkeypatch.setattr(screening, "set_tenant_context", lambda tenant_id: None)
    monkeypatch.setattr(screening._registry, "resolve", lambda name: object())

    async def fake_execute(**kwargs: Any) -> list[object]:
        assert kwargs["run"] is run
        assert kwargs["rubric"] is rubric
        assert kwargs["job_title"] == job.title
        return [object(), object()]

    async def capture_event(
        event_run_id: uuid.UUID, event_type: EventType, data: dict[str, Any]
    ) -> None:
        events.append((event_run_id, event_type, data))

    monkeypatch.setattr(screening, "execute_screening_run", fake_execute)
    monkeypatch.setattr(screening._sse, "publish", capture_event)

    insight_scores: list[object] = []

    async def fake_persist_insights(**kwargs: Any) -> None:
        insight_scores.append(kwargs["score"])

    monkeypatch.setattr(screening, "persist_score_insights", fake_persist_insights)

    await screening._execute_run(run.id, run.tenant_id)

    assert len(insight_scores) == 2
    assert session.commits == 1
    assert session.rollbacks == 0
    assert [event_type for _, event_type, _ in events] == [
        EventType.STAGE_STARTED,
        EventType.STAGE_STARTED,
        EventType.STAGE_COMPLETE,
        EventType.STAGE_COMPLETE,
        EventType.RUN_COMPLETE,
    ]
    assert events[-1][2]["candidate_count"] == 2


@pytest.mark.asyncio
async def test_execute_run_rolls_back_hides_error_and_emits_failed_event(
    monkeypatch: pytest.MonkeyPatch,
    run_dependencies: tuple[ScreeningRun, RubricVersion, Job],
) -> None:
    run, rubric, job = run_dependencies
    session = _Session(run, rubric, job)
    events: list[tuple[uuid.UUID, EventType, dict[str, Any]]] = []

    monkeypatch.setattr(screening, "get_sessionmaker", lambda: lambda: _SessionContext(session))
    monkeypatch.setattr(screening, "set_tenant_context", lambda tenant_id: None)
    monkeypatch.setattr(screening._registry, "resolve", lambda name: object())

    async def raise_provider_error(**kwargs: Any) -> list[object]:
        raise RuntimeError("provider key leaked")

    async def capture_event(
        event_run_id: uuid.UUID, event_type: EventType, data: dict[str, Any]
    ) -> None:
        events.append((event_run_id, event_type, data))

    monkeypatch.setattr(screening, "execute_screening_run", raise_provider_error)
    monkeypatch.setattr(screening._sse, "publish", capture_event)

    await screening._execute_run(run.id, run.tenant_id)

    assert session.rollbacks == 1
    assert session.commits == 1
    assert run.status == "failed"
    assert [event_type for _, event_type, _ in events] == [
        EventType.STAGE_STARTED,
        EventType.RUN_FAILED,
    ]
    assert events[-1][2]["message"] == "Screening run failed. Please retry later."
    assert "provider key leaked" not in str(events[-1][2])


@pytest.mark.asyncio
async def test_execute_run_preserves_a_provider_failure_for_durable_retry(
    monkeypatch: pytest.MonkeyPatch,
    run_dependencies: tuple[ScreeningRun, RubricVersion, Job],
) -> None:
    run, rubric, job = run_dependencies
    session = _Session(run, rubric, job)

    monkeypatch.setattr(screening, "get_sessionmaker", lambda: lambda: _SessionContext(session))
    monkeypatch.setattr(screening, "set_tenant_context", lambda tenant_id: None)
    monkeypatch.setattr(screening._registry, "resolve", lambda name: object())

    async def raise_provider_error(**kwargs: Any) -> list[object]:
        raise LLMProviderError("rate limited", kind="rate_limit", provider="gemini")

    async def ignore_event(*args: Any, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr(screening, "execute_screening_run", raise_provider_error)
    monkeypatch.setattr(screening._sse, "publish", ignore_event)

    outcome = await screening._execute_run(run.id, run.tenant_id)

    assert outcome.success is False
    assert outcome.error_code == "rate_limit"
    assert run.status == "queued"
    assert session.rollbacks == 1
    assert session.commits == 1
