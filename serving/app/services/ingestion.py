"""Ingestion orchestration: validate, store, parse, persist.

Validation happens twice on purpose — the schema layer constrains shape, and
this layer re-checks size and real content type before any parser touches the
bytes. Defense in depth, per the project's design principles.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.exceptions import (
    EmptyDocumentError,
    PayloadTooLargeError,
    UnsupportedMediaTypeError,
)
from app.logging import get_logger
from app.models import Job, ResumeDocument, ResumeVersion
from app.repositories.ingestion import JobRepository, ResumeRepository
from app.security import Principal
from app.services.parser import parse_document
from app.services.storage import ObjectStore, build_storage_key
from app.utils.parsing import content_sha256, detect_media_type, sanitize_filename

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class IngestionOutcome:
    """The result of ingesting one resume.

    Attributes:
        document: The stored (or previously stored) document row.
        deduplicated: True when identical bytes already existed for this tenant.
    """

    document: ResumeDocument
    deduplicated: bool


def validate_upload(content: bytes, settings: Settings | None = None) -> str:
    """Validate an uploaded file and return its real media type.

    Size is checked before anything else so an oversized payload is rejected
    without being parsed. Content type is decided from the bytes, never from the
    client's filename or `Content-Type` header.

    Args:
        content: Raw uploaded bytes.
        settings: Optional configuration override.

    Returns:
        The detected media type.

    Raises:
        EmptyDocumentError: If the upload is empty.
        PayloadTooLargeError: If the upload exceeds the configured ceiling.
        UnsupportedMediaTypeError: If the bytes are not a supported document.
    """
    cfg = settings or get_settings()
    if not content:
        raise EmptyDocumentError()
    if len(content) > cfg.max_upload_bytes:
        raise PayloadTooLargeError()

    media_type = detect_media_type(content)
    if media_type is None or media_type not in cfg.allowed_upload_mime_types:
        raise UnsupportedMediaTypeError()
    return media_type


async def ingest_resume(
    *,
    session: AsyncSession,
    store: ObjectStore,
    principal: Principal,
    content: bytes,
    filename: str,
    settings: Settings | None = None,
) -> IngestionOutcome:
    """Validate, store, parse, and persist one resume.

    Identical bytes within a tenant resolve to the existing document rather than
    creating a duplicate — the same resume commonly arrives through several
    channels, and re-parsing it would waste work and fragment the candidate.

    Args:
        session: Active database session.
        store: Object store adapter.
        principal: The verified caller; supplies tenancy and attribution.
        content: Raw uploaded bytes.
        filename: Client-supplied filename, sanitized before storage.
        settings: Optional configuration override.

    Returns:
        The ingestion outcome.

    Raises:
        EmptyDocumentError: If the upload is empty.
        PayloadTooLargeError: If the upload is too large.
        UnsupportedMediaTypeError: If the bytes are not PDF or DOCX.
        DocumentParseError: If the document is structurally unreadable.
    """
    media_type = validate_upload(content, settings)
    digest = content_sha256(content)
    repo = ResumeRepository(session)

    existing = await repo.find_by_hash(principal.tenant_id, digest)
    if existing is not None:
        logger.info(
            "resume_deduplicated",
            document_id=str(existing.id),
            tenant_id=str(principal.tenant_id),
            sha256=digest,
        )
        return IngestionOutcome(document=existing, deduplicated=True)

    parsed = parse_document(content, media_type)
    safe_name = sanitize_filename(filename)
    storage_key = build_storage_key(principal.tenant_id, digest, safe_name)
    await store.put(storage_key, content, media_type)

    document = ResumeDocument(
        id=uuid.uuid4(),
        tenant_id=principal.tenant_id,
        uploaded_by=principal.user_id,
        storage_key=storage_key,
        filename_sanitized=safe_name,
        media_type=media_type,
        size_bytes=len(content),
        sha256=digest,
        page_count=parsed.page_count,
        parse_status=parsed.parse_status,
        parser_version=parsed.parser_version,
        needs_ocr=parsed.needs_ocr,
    )
    version = ResumeVersion(
        id=uuid.uuid4(),
        tenant_id=principal.tenant_id,
        document_id=document.id,
        version=1,
        extracted_text=parsed.text,
        text_sha256=content_sha256(parsed.text.encode("utf-8")),
        page_offsets=[
            {
                "page": page.page,
                "start_char": page.start_char,
                "end_char": page.end_char,
            }
            for page in parsed.pages
        ],
        parser_version=parsed.parser_version,
    )

    await repo.add(document, version)
    logger.info(
        "resume_ingested",
        document_id=str(document.id),
        tenant_id=str(principal.tenant_id),
        media_type=media_type,
        size_bytes=len(content),
        parse_status=parsed.parse_status,
        needs_ocr=parsed.needs_ocr,
    )
    return IngestionOutcome(document=document, deduplicated=False)


async def create_job_from_text(
    *,
    session: AsyncSession,
    principal: Principal,
    title: str,
    description_raw: str,
    department: str | None = None,
    location: str | None = None,
    employment_type: str | None = None,
    seniority: str | None = None,
    source: str = "manual",
) -> Job:
    """Persist a job description supplied as text.

    Args:
        session: Active database session.
        principal: The verified caller.
        title: Job title.
        description_raw: The full job description text.
        department: Optional department.
        location: Optional location.
        employment_type: Optional employment type.
        seniority: Optional seniority band.
        source: How the description arrived ("manual" or "upload").

    Returns:
        The persisted job.
    """
    job = Job(
        id=uuid.uuid4(),
        tenant_id=principal.tenant_id,
        created_by=principal.user_id,
        title=title,
        description_raw=description_raw,
        department=department,
        location=location,
        employment_type=employment_type,
        seniority=seniority,
        source=source,
        status="draft",
    )
    return await JobRepository(session).add(job)


async def create_job_from_upload(
    *,
    session: AsyncSession,
    principal: Principal,
    content: bytes,
    title: str,
    settings: Settings | None = None,
) -> Job:
    """Parse an uploaded job description and persist it.

    Args:
        session: Active database session.
        principal: The verified caller.
        content: Raw uploaded bytes.
        title: Job title supplied alongside the file.
        settings: Optional configuration override.

    Returns:
        The persisted job.

    Raises:
        UnsupportedMediaTypeError: If the bytes are not PDF or DOCX.
        DocumentParseError: If the document is structurally unreadable.
    """
    media_type = validate_upload(content, settings)
    parsed = parse_document(content, media_type)
    return await create_job_from_text(
        session=session,
        principal=principal,
        title=title,
        description_raw=parsed.text,
        source="upload",
    )
