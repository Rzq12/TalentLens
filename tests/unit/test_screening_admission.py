"""Admission checks for POST /screening/jobs/{job_id}/runs.

``task.md`` Phase 4 specifies this endpoint precisely: "endpoint POST admission
screening-run yang menjawab ``202`` saat diterima dan ``409`` saat rubric belum
approved". The 409 is the contract a caller polls against — it says *this job is
not ready yet, approve a rubric and retry*, which is a different instruction
from 422 *your request was malformed*. A client that retries on 409 and gives up
on 422 behaves wrongly if the two are swapped.

These tests stub the session, so they assert the admission contract without a
database.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest


class _NoRubricResult:
    """Mimics the ``Result`` of the approved-rubric lookup, finding nothing."""

    def scalar_one_or_none(self) -> None:
        return None


class _NoRubricSession:
    """A session whose rubric lookup returns no approved rubric.

    Only the surface ``start_screening_run`` touches is implemented. Anything
    else raises ``AssertionError`` rather than silently succeeding, so the test
    fails loudly if the handler starts doing more work before admission.
    """

    async def execute(self, *args: Any, **kwargs: Any) -> _NoRubricResult:
        return _NoRubricResult()

    def add(self, obj: Any) -> None:
        raise AssertionError(
            "a screening run was created despite no approved rubric existing"
        )

    async def flush(self) -> None:
        raise AssertionError("the handler flushed despite failing admission")


@pytest.fixture
async def client_without_rubric() -> Any:
    """Yield an httpx client whose database has no approved rubric."""
    import httpx

    from app.db import get_session
    from app.main import create_app

    app = create_app()
    app.dependency_overrides[get_session] = lambda: _NoRubricSession()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_start_run_without_approved_rubric_returns_409(
    client_without_rubric: Any, auth_headers: dict[str, str]
) -> None:
    """An unapprovable job is a state conflict (409), not a bad request (422).

    ``task.md`` Phase 4 fixes 409 for this case. 422 tells the caller its
    payload was wrong, so a client that stops retrying on 422 would abandon a
    job that merely needs its rubric approved.
    """
    response = await client_without_rubric.post(
        f"/api/v1/screening/jobs/{uuid.uuid4()}/runs",
        headers=auth_headers,
    )

    assert response.status_code == 409, (
        f"expected 409 Conflict for a job with no approved rubric, got "
        f"{response.status_code}: {response.text}"
    )


@pytest.mark.asyncio
async def test_rubric_conflict_message_names_the_remedy(
    client_without_rubric: Any, auth_headers: dict[str, str]
) -> None:
    """The error must tell the recruiter what to do, not just that it failed."""
    response = await client_without_rubric.post(
        f"/api/v1/screening/jobs/{uuid.uuid4()}/runs",
        headers=auth_headers,
    )

    body = response.text.lower()
    assert "rubric" in body, f"error does not mention the rubric: {response.text}"
