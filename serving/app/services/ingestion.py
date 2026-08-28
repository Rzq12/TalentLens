"""Ingestion orchestration: validate, store, parse, persist.

Validation happens twice on purpose — the schema layer constrains shape, and
this layer re-checks size and real content type before any parser touches the
bytes. Defense in depth, per the project's design principles.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.agents.ocr_agent import OcrAgent
from app.config import Settings, get_settings
from app.exceptions import (
    EmptyDocumentError,
    PayloadTooLargeError,
    UnsupportedMediaTypeError,
)
from app.logging import get_logger
from app.models import Candidate, CandidateProfile, Job, ResumeDocument, ResumeVersion
from app.repositories.ingestion import JobRepository, ResumeRepository
from app.repositories.search import ChunkRepository
from app.security import Principal
from app.services.embedding import get_embedding_service
from app.services.indexing import index_resume_version
from app.services.ocr_fallback import apply_ocr_fallback
from app.services.parser import parse_document
from app.services.sanitize import sanitize_document
from app.services.storage import ObjectStore, build_storage_key
from app.utils.parsing import content_sha256, detect_media_type, sanitize_filename

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class IngestionOutcome:
    """The result of ingesting one resume.

    Attributes:
        document: The stored (or previously stored) document row.
        candidate: Candidate linked to the resume.
        profile: Candidate profile for the resume version.
        deduplicated: True when identical bytes already existed for this tenant.
    """

    document: ResumeDocument
    candidate: Candidate
    profile: CandidateProfile
    deduplicated: bool
    injection_risk_score: float = 0.0
    quarantined: bool = False


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
    candidate_name: str,
    candidate_email: str | None,
    consent_granted: bool,
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
        candidate_name: Candidate name supplied by the recruiter.
        candidate_email: Optional tenant-scoped candidate email for deduplication.
        consent_granted: Explicit permission to use the CV for screening.
        settings: Optional configuration override.

    Returns:
        The ingestion outcome.

    Raises:
        EmptyDocumentError: If the upload is empty.
        PayloadTooLargeError: If the upload is too large.
        UnsupportedMediaTypeError: If the bytes are not PDF or DOCX.
        DocumentParseError: If the document is structurally unreadable.
    """
    normalized_name = candidate_name.strip()
    if not normalized_name:
        raise ValueError("candidate_name must not be blank")

    media_type = validate_upload(content, settings)
    digest = content_sha256(content)
    repo = ResumeRepository(session)

    existing = await repo.find_by_hash(principal.tenant_id, digest)
    if existing is not None:
        prior = await repo.latest_version(principal.tenant_id, existing.id)
        if prior is None:
            raise RuntimeError("Deduplicated resume has no parsed version.")
        profile = await repo.find_profile_by_resume_version(principal.tenant_id, prior.id)
        if profile is None:
            raise RuntimeError("Deduplicated resume is not linked to a candidate.")
        candidate = await session.get(Candidate, profile.candidate_id)
        if candidate is None:
            raise RuntimeError("Resume profile references a missing candidate.")
        logger.info(
            "resume_deduplicated",
            document_id=str(existing.id),
            tenant_id=str(principal.tenant_id),
            sha256=digest,
        )
        return IngestionOutcome(
            document=existing,
            candidate=candidate,
            profile=profile,
            deduplicated=True,
            injection_risk_score=prior.injection_risk_score,
            quarantined=prior.quarantined,
        )

    # PDF/DOCX parsing is CPU-bound. Running it inline would pin the event
    # loop for the duration and stall every concurrent request — a failure
    # mode this project has already paid for once.
    parsed = await run_in_threadpool(parse_document, content, media_type)
    parsed = await apply_ocr_fallback(
        parsed=parsed,
        content=content,
        document_id=uuid.uuid4(),
        tenant_id=principal.tenant_id,
        ocr=OcrAgent(),
    )

    # Resume text is hostile input. Strip what is provably invisible before any
    # of it is stored, and quarantine the document if what remains looks like an
    # attempt to steer a downstream model.
    sanitized = sanitize_document(parsed)

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
        extracted_text=sanitized.text,
        text_sha256=content_sha256(sanitized.text.encode("utf-8")),
        page_offsets=[
            {
                "page": page.page,
                "start_char": page.start_char,
                "end_char": page.end_char,
            }
            for page in parsed.pages
        ],
        parser_version=parsed.parser_version,
        sanitization_report=sanitized.to_report(),
        injection_risk_score=sanitized.injection_risk_score,
        quarantined=sanitized.should_quarantine,
    )

    await repo.add(document, version)

    normalized_email = candidate_email.strip().lower() if candidate_email else None
    existing_candidate = (
        await repo.find_candidate_by_email(principal.tenant_id, normalized_email)
        if normalized_email
        else None
    )
    candidate = existing_candidate or Candidate(
        tenant_id=principal.tenant_id,
        name=normalized_name,
        email=normalized_email,
        consent_granted_at=datetime.now(UTC) if consent_granted else None,
    )
    profile = CandidateProfile(
        tenant_id=principal.tenant_id,
        candidate_id=candidate.id,
        resume_version_id=version.id,
        extraction_status="pending",
    )
    if existing_candidate is None:
        await repo.add_candidate_profile(candidate, profile)
    else:
        session.add(profile)
        await session.flush()

    # Bridge to Phase 2: chunk, embed, and persist so search can find this resume.
    # Quarantined versions are skipped inside index_resume_version.
    chunk_repo = ChunkRepository(session)
    embedder = get_embedding_service()
    indexing_result = await index_resume_version(
        version=version,
        chunk_repo=chunk_repo,
        embedder=embedder,
    )

    logger.info(
        "resume_ingested",
        document_id=str(document.id),
        tenant_id=str(principal.tenant_id),
        media_type=media_type,
        size_bytes=len(content),
        parse_status=parsed.parse_status,
        needs_ocr=parsed.needs_ocr,
        injection_risk_score=sanitized.injection_risk_score,
        quarantined=sanitized.should_quarantine,
        chunks_created=indexing_result.chunks_created,
        child_chunks=indexing_result.child_chunks,
        parent_chunks=indexing_result.parent_chunks,
    )
    return IngestionOutcome(
        document=document,
        candidate=candidate,
        profile=profile,
        deduplicated=False,
        injection_risk_score=sanitized.injection_risk_score,
        quarantined=sanitized.should_quarantine,
    )


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
    parsed = await run_in_threadpool(parse_document, content, media_type)

    return await create_job_from_text(
        session=session,
        principal=principal,
        title=title,
        description_raw=parsed.text,
        source="upload",
    )
