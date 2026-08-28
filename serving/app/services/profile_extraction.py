"""Persist the shared LLM profile extraction for an ingested resume."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import FailoverChain
from app.agents.extraction import (
    EXTRACTION_PROMPT_VERSION,
    build_extraction_request,
    parse_extraction_response,
)
from app.models import CandidateProfile, ResumeVersion


def _object_list(value: object) -> list[dict[str, object]]:
    """Retain only object entries from a model response."""
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


async def extract_candidate_profile(
    *,
    session: AsyncSession,
    profile_id: UUID,
    tenant_id: UUID,
    chain: FailoverChain,
) -> bool:
    """Extract and persist one profile; return whether extraction succeeded."""
    result = await session.execute(
        select(CandidateProfile, ResumeVersion)
        .join(ResumeVersion, CandidateProfile.resume_version_id == ResumeVersion.id)
        .where(
            CandidateProfile.id == profile_id,
            CandidateProfile.tenant_id == tenant_id,
            ResumeVersion.tenant_id == tenant_id,
            ResumeVersion.quarantined.is_(False),
        )
    )
    row = result.one_or_none()
    if row is None:
        return False

    profile, version = row
    try:
        request = build_extraction_request(
            resume_text=version.extracted_text,
            resume_version_id=str(version.id),
        )
        response = await chain.generate(request)
        raw = parse_extraction_response(response.text)
        if not _object_list(raw.get("skills")):
            raise ValueError("Extraction returned no usable skills.")
    except Exception:
        profile.extraction_status = "failed"
        return False

    profile.skills = {"items": _object_list(raw.get("skills"))}
    profile.education = {
        "items": _object_list(raw.get("education")),
        "certifications": _object_list(raw.get("certifications")),
    }
    profile.languages = {"items": _object_list(raw.get("languages"))}
    profile.total_experience_months = _optional_int(raw.get("total_experience_months"))
    profile.latest_role = _optional_string(raw.get("latest_role"))
    profile.extraction_status = "completed"
    profile.extraction_model = response.model
    profile.extraction_prompt_version = EXTRACTION_PROMPT_VERSION
    return True


def _optional_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _optional_string(value: Any) -> str | None:
    return value if isinstance(value, str) and value.strip() else None
