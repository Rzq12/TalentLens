"""Request and response schemas for resume and job-description ingestion."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

MIN_DESCRIPTION_LENGTH = 1
MAX_DESCRIPTION_LENGTH = 100_000


class ResumeUploadResponse(BaseModel):
    """Acknowledgement returned by `POST /api/v1/resumes`."""

    document_id: uuid.UUID = Field(description="Identifier of the stored document.")
    filename: str = Field(description="Sanitized filename as stored.")
    media_type: str = Field(description="Media type detected from the bytes.")
    size_bytes: int = Field(description="Size of the uploaded file.")
    sha256: str = Field(description="Content hash used for deduplication.")
    page_count: int = Field(description="Pages found by the parser.")
    parse_status: str = Field(description='"ok" or "low_yield".')
    needs_ocr: bool = Field(description="True when the text layer is too thin to trust.")
    deduplicated: bool = Field(
        default=False,
        description="True when identical bytes were already stored for this tenant.",
    )
    injection_risk_score: float = Field(
        default=0.0,
        description="Deterministic prompt-injection risk in [0.0, 1.0].",
    )
    quarantined: bool = Field(
        default=False,
        description="True when the document needs human review before any further use.",
    )


class ResumeDetailResponse(BaseModel):
    """Full document detail, including extracted text."""

    model_config = ConfigDict(from_attributes=True)

    document_id: uuid.UUID
    filename: str
    media_type: str
    size_bytes: int
    sha256: str
    page_count: int
    parse_status: str
    needs_ocr: bool
    parser_version: str
    text: str = Field(
        description=(
            "Sanitized text of the latest parsed version. Empty when the "
            "document is quarantined."
        )
    )
    injection_risk_score: float = 0.0
    quarantined: bool = False
    sanitization_report: dict[str, object] = Field(default_factory=dict)
    created_at: datetime


class ResumeSummary(BaseModel):
    """One row in a resume listing."""

    model_config = ConfigDict(from_attributes=True)

    document_id: uuid.UUID
    filename: str
    media_type: str
    page_count: int
    parse_status: str
    created_at: datetime


class ResumeListResponse(BaseModel):
    """A page of resume summaries."""

    items: list[ResumeSummary] = Field(default_factory=list)
    count: int = 0
    next_cursor: str | None = Field(
        default=None,
        description="Pass as `before` for the next page. Null when exhausted.",
    )


class JobCreateRequest(BaseModel):
    """Payload for creating a job from pasted text."""

    title: str = Field(min_length=1, max_length=255)
    description_raw: str = Field(
        min_length=MIN_DESCRIPTION_LENGTH, max_length=MAX_DESCRIPTION_LENGTH
    )
    department: str | None = Field(default=None, max_length=255)
    location: str | None = Field(default=None, max_length=255)
    employment_type: str | None = Field(default=None, max_length=64)
    seniority: str | None = Field(default=None, max_length=64)

    @field_validator("title", "description_raw")
    @classmethod
    def _reject_whitespace_only(cls, value: str) -> str:
        """Reject values that are only whitespace.

        Args:
            value: The incoming field value.

        Returns:
            The stripped value.

        Raises:
            ValueError: If nothing remains after stripping.
        """
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped


class JobResponse(BaseModel):
    """A persisted job description."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    description_raw: str
    department: str | None = None
    location: str | None = None
    employment_type: str | None = None
    seniority: str | None = None
    source: str
    status: str
    created_at: datetime
