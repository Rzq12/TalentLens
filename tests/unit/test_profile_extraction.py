"""Unit tests for optional CandidateProfile extraction persistence."""

from __future__ import annotations

import uuid

import pytest

from app.agents.base import LLMResponse
from app.models import CandidateProfile, ResumeVersion
from app.services.profile_extraction import extract_candidate_profile


class _Result:
    def __init__(self, row: tuple[CandidateProfile, ResumeVersion] | None) -> None:
        self.row = row

    def one_or_none(self) -> tuple[CandidateProfile, ResumeVersion] | None:
        return self.row


class _Session:
    def __init__(self, row: tuple[CandidateProfile, ResumeVersion] | None) -> None:
        self.row = row

    async def execute(self, statement: object) -> _Result:  # noqa: ARG002
        return _Result(self.row)


class _Chain:
    def __init__(self, response: str | Exception) -> None:
        self.response = response

    async def generate(self, request: object) -> LLMResponse:  # noqa: ARG002
        if isinstance(self.response, Exception):
            raise self.response
        return LLMResponse(text=self.response, model="test-model", provider="test")


def _profile_and_version() -> tuple[CandidateProfile, ResumeVersion]:
    tenant_id = uuid.uuid4()
    version = ResumeVersion(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        document_id=uuid.uuid4(),
        version=1,
        extracted_text="Ada has eight years of Python experience.",
        text_sha256="hash",
        quarantined=False,
    )
    profile = CandidateProfile(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        candidate_id=uuid.uuid4(),
        resume_version_id=version.id,
        extraction_status="pending",
    )
    return profile, version


@pytest.mark.anyio
async def test_extract_candidate_profile_persists_valid_response() -> None:
    profile, version = _profile_and_version()
    chain = _Chain(
        '{"skills":[{"name":"Python","category":"programming_language"}],'
        '"experience":[],"education":[],"certifications":[],"languages":[], '
        '"total_experience_months":96,"latest_role":"Engineer"}'
    )

    extracted = await extract_candidate_profile(
        session=_Session((profile, version)),  # type: ignore[arg-type]
        profile_id=profile.id,
        tenant_id=profile.tenant_id,
        chain=chain,  # type: ignore[arg-type]
    )

    assert extracted is True
    assert profile.extraction_status == "completed"
    assert profile.skills == {"items": [{"name": "Python", "category": "programming_language"}]}
    assert profile.total_experience_months == 96
    assert profile.latest_role == "Engineer"
    assert profile.extraction_model == "test-model"


@pytest.mark.anyio
async def test_extract_candidate_profile_marks_provider_failure() -> None:
    profile, version = _profile_and_version()

    extracted = await extract_candidate_profile(
        session=_Session((profile, version)),  # type: ignore[arg-type]
        profile_id=profile.id,
        tenant_id=profile.tenant_id,
        chain=_Chain(RuntimeError("provider unavailable")),  # type: ignore[arg-type]
    )

    assert extracted is False
    assert profile.extraction_status == "failed"
