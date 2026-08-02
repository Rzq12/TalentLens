"""Rubric score preview — the 409 guard over HTTP and scoring mechanics.

The score-preview endpoint is an authoring aid: it lets a recruiter see how a
rubric would score a hypothetical candidate before any real candidate is run
against it. The verdicts are synthetic — the caller supplies them — so this
endpoint never touches a resume or runs any matcher.

What these tests prove is that the 409 guard (`ensure_approved_for_scoring`)
is reachable over HTTP, and that the scoring service is wired correctly. What
they deliberately do not prove is that the *matching* produces correct verdicts
— that is the concern of the matcher unit tests and the e2e screening suite.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


async def test_preview_score_for_an_approved_rubric_returns_200_with_breakdown(
    db_client, auth_headers
):
    # Create a job
    job_response = await db_client.post(
        "/api/v1/jobs",
        headers=auth_headers,
        json={"title": "Backend Engineer", "description_raw": "A role."},
    )
    assert job_response.status_code == 201
    job_id = job_response.json()["id"]

    # Create a rubric
    rubric_response = await db_client.post(
        "/api/v1/rubrics",
        headers=auth_headers,
        json={
            "job_id": job_id,
            "requirements": [
                {
                    "text": "5+ years Python",
                    "category": "experience",
                    "is_must_have": True,
                    "weight": 5,
                },
                {
                    "text": "Strong PostgreSQL",
                    "category": "skill",
                    "is_must_have": False,
                    "weight": 3,
                },
            ],
        },
    )
    assert rubric_response.status_code == 201
    rubric_id = rubric_response.json()["rubric_version_id"]
    requirements = rubric_response.json()["requirements"]

    # Approve it
    approve_response = await db_client.post(
        f"/api/v1/rubrics/{rubric_id}/approve", headers=auth_headers
    )
    assert approve_response.status_code == 200

    # Preview with synthetic verdicts
    preview_response = await db_client.post(
        f"/api/v1/rubrics/{rubric_id}/score:preview",
        headers=auth_headers,
        json={
            "verdicts": [
                {"requirement_id": requirements[0]["id"], "verdict": "met"},
                {"requirement_id": requirements[1]["id"], "verdict": "partial"},
            ]
        },
    )

    assert preview_response.status_code == 200
    body = preview_response.json()
    assert "score" in body
    assert "raw_score" in body
    assert "formula_version" in body
    assert "must_have_failed" in body
    assert "cap_applied" in body
    assert "contributions" in body
    assert isinstance(body["contributions"], list)


async def test_preview_on_a_draft_rubric_returns_409(db_client, auth_headers):
    """The 409 guard is the reason this endpoint exists in the HTTP layer."""
    # Create a job
    job_response = await db_client.post(
        "/api/v1/jobs",
        headers=auth_headers,
        json={"title": "Backend Engineer", "description_raw": "A role."},
    )
    assert job_response.status_code == 201
    job_id = job_response.json()["id"]

    # Create a rubric but do NOT approve it
    rubric_response = await db_client.post(
        "/api/v1/rubrics",
        headers=auth_headers,
        json={
            "job_id": job_id,
            "requirements": [
                {
                    "text": "5+ years Python",
                    "category": "experience",
                    "is_must_have": True,
                    "weight": 5,
                }
            ],
        },
    )
    assert rubric_response.status_code == 201
    rubric_id = rubric_response.json()["rubric_version_id"]
    requirements = rubric_response.json()["requirements"]

    # Try to preview — should be refused
    preview_response = await db_client.post(
        f"/api/v1/rubrics/{rubric_id}/score:preview",
        headers=auth_headers,
        json={"verdicts": [{"requirement_id": requirements[0]["id"], "verdict": "met"}]},
    )

    assert preview_response.status_code == 409
    assert "draft" in preview_response.json()["message"].lower()


async def test_preview_on_a_superseded_rubric_returns_409(db_client, auth_headers):
    # Create a job
    job_response = await db_client.post(
        "/api/v1/jobs",
        headers=auth_headers,
        json={"title": "Backend Engineer", "description_raw": "A role."},
    )
    assert job_response.status_code == 201
    job_id = job_response.json()["id"]

    # Create and approve a rubric
    rubric_response = await db_client.post(
        "/api/v1/rubrics",
        headers=auth_headers,
        json={
            "job_id": job_id,
            "requirements": [
                {
                    "text": "5+ years Python",
                    "category": "experience",
                    "is_must_have": True,
                    "weight": 5,
                }
            ],
        },
    )
    assert rubric_response.status_code == 201
    rubric_id_v1 = rubric_response.json()["rubric_version_id"]
    await db_client.post(f"/api/v1/rubrics/{rubric_id_v1}/approve", headers=auth_headers)

    # Create a new version — this supersedes v1
    new_version_response = await db_client.post(
        f"/api/v1/rubrics/{rubric_id_v1}/versions",
        headers=auth_headers,
        json={
            "requirements": [
                {
                    "text": "5+ years Python",
                    "category": "experience",
                    "is_must_have": True,
                    "weight": 5,
                },
                {
                    "text": "Strong PostgreSQL",
                    "category": "skill",
                    "is_must_have": False,
                    "weight": 3,
                },
            ]
        },
    )
    assert new_version_response.status_code == 201

    # Now try to preview v1 — it is superseded
    requirements_v1 = rubric_response.json()["requirements"]
    preview_response = await db_client.post(
        f"/api/v1/rubrics/{rubric_id_v1}/score:preview",
        headers=auth_headers,
        json={"verdicts": [{"requirement_id": requirements_v1[0]["id"], "verdict": "met"}]},
    )

    assert preview_response.status_code == 409
    assert "superseded" in preview_response.json()["message"].lower()


async def test_preview_requires_authentication(db_client):
    preview_response = await db_client.post(
        "/api/v1/rubrics/00000000-0000-0000-0000-000000000000/score:preview",
        json={"verdicts": []},
    )

    assert preview_response.status_code == 401


async def test_preview_with_mismatched_requirement_ids_fails_validation(db_client, auth_headers):
    """Verdicts must reference requirement IDs that exist in the rubric."""
    # Create a job
    job_response = await db_client.post(
        "/api/v1/jobs",
        headers=auth_headers,
        json={"title": "Backend Engineer", "description_raw": "A role."},
    )
    assert job_response.status_code == 201
    job_id = job_response.json()["id"]

    # Create and approve a rubric
    rubric_response = await db_client.post(
        "/api/v1/rubrics",
        headers=auth_headers,
        json={
            "job_id": job_id,
            "requirements": [
                {
                    "text": "5+ years Python",
                    "category": "experience",
                    "is_must_have": True,
                    "weight": 5,
                }
            ],
        },
    )
    assert rubric_response.status_code == 201
    rubric_id = rubric_response.json()["rubric_version_id"]
    await db_client.post(f"/api/v1/rubrics/{rubric_id}/approve", headers=auth_headers)

    # Try to preview with a non-existent requirement ID
    preview_response = await db_client.post(
        f"/api/v1/rubrics/{rubric_id}/score:preview",
        headers=auth_headers,
        json={
            "verdicts": [
                {"requirement_id": "00000000-0000-0000-0000-000000000000", "verdict": "met"}
            ]
        },
    )

    assert preview_response.status_code == 422
