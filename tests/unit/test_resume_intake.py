"""Integration coverage for resume-to-candidate intake mapping."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select

from app.models import Candidate, CandidateProfile

RESUMES = "/api/v1/resumes"


async def _model_count(model: type[object]) -> int:
    from app.db import get_sessionmaker

    async with get_sessionmaker()() as session:
        return int(await session.scalar(select(func.count()).select_from(model)) or 0)


@pytest.mark.anyio
async def test_resume_upload_creates_and_deduplicates_candidate_profile(
    db_client: object,
    auth_headers: dict[str, str],
    minimal_pdf_bytes: bytes,
) -> None:
    """A document intake creates one candidate/profile mapping and preserves it on retry."""
    client = db_client
    upload = {
        "file": ("jane-doe.pdf", minimal_pdf_bytes, "application/pdf"),
        "candidate_name": (None, "Jane Doe"),
        "candidate_email": (None, "jane@example.com"),
        "consent_granted": (None, "true"),
    }

    first = await client.post(RESUMES, files=upload, headers=auth_headers)

    assert first.status_code == 202
    first_body = first.json()
    assert first_body["deduplicated"] is False
    candidate_id = uuid.UUID(first_body["candidate_id"])
    profile_id = uuid.UUID(first_body["profile_id"])
    assert await _model_count(Candidate) == 1
    assert await _model_count(CandidateProfile) == 1

    retry = await client.post(RESUMES, files=upload, headers=auth_headers)

    assert retry.status_code == 202
    retry_body = retry.json()
    assert retry_body["deduplicated"] is True
    assert uuid.UUID(retry_body["candidate_id"]) == candidate_id
    assert uuid.UUID(retry_body["profile_id"]) == profile_id
    assert await _model_count(Candidate) == 1
    assert await _model_count(CandidateProfile) == 1
