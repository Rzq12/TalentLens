"""Resume ingestion endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, File, Form, Query, UploadFile, status

from app.agents.factory import build_failover_chain
from app.db import DbSession, get_sessionmaker, set_tenant_context
from app.exceptions import ResourceNotFoundError
from app.repositories.ingestion import ResumeRepository
from app.schemas.ingestion import (
    ResumeDetailResponse,
    ResumeListResponse,
    ResumeSummary,
    ResumeUploadResponse,
)
from app.security import ReadPrincipal, WritePrincipal
from app.services.ingestion import ingest_resume
from app.services.profile_extraction import extract_candidate_profile
from app.services.storage import get_object_store
from app.utils.upload import read_upload_bounded

router = APIRouter(prefix="/resumes", tags=["resumes"])


async def _extract_profile(profile_id: uuid.UUID, tenant_id: uuid.UUID) -> None:
    """Run optional LLM extraction outside the upload request transaction."""
    set_tenant_context(tenant_id)
    async with get_sessionmaker()() as session:
        await extract_candidate_profile(
            session=session,
            profile_id=profile_id,
            tenant_id=tenant_id,
            chain=build_failover_chain(),
        )
        await session.commit()


@router.post(
    "",
    response_model=ResumeUploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Upload a resume",
    description=(
        "Accepts a PDF or DOCX resume. The media type is determined from the "
        "file's bytes, not its name. Identical content within a tenant "
        "deduplicates to the existing document."
    ),
)
async def upload_resume(
    principal: WritePrincipal,
    session: DbSession,
    background_tasks: BackgroundTasks,
    file: Annotated[UploadFile, File()],
    candidate_name: Annotated[str, Form(min_length=1, max_length=255)],
    candidate_email: Annotated[str | None, Form(max_length=255)] = None,
    consent_granted: Annotated[bool, Form()] = False,
) -> ResumeUploadResponse:
    """Ingest one resume.

    Args:
        principal: Verified caller.
        session: Database session.
        background_tasks: Background tasks.
        file: The uploaded document.
        candidate_name: Candidate name supplied by the recruiter.
        candidate_email: Optional tenant-scoped candidate email.
        consent_granted: Explicit permission to screen the candidate.

    Returns:
        An acknowledgement describing the stored document.
    """
    content = await read_upload_bounded(file)
    outcome = await ingest_resume(
        session=session,
        store=get_object_store(),
        principal=principal,
        content=content,
        filename=file.filename or "unnamed",
        candidate_name=candidate_name,
        candidate_email=candidate_email,
        consent_granted=consent_granted,
    )
    document = outcome.document
    if not outcome.deduplicated and not outcome.quarantined:
        background_tasks.add_task(
            _extract_profile, outcome.profile.id, principal.tenant_id
        )
    return ResumeUploadResponse(
        document_id=document.id,
        candidate_id=outcome.candidate.id,
        profile_id=outcome.profile.id,
        filename=document.filename_sanitized,
        media_type=document.media_type,
        size_bytes=document.size_bytes,
        sha256=document.sha256,
        page_count=document.page_count,
        parse_status=document.parse_status,
        needs_ocr=document.needs_ocr,
        deduplicated=outcome.deduplicated,
        injection_risk_score=outcome.injection_risk_score,
        quarantined=outcome.quarantined,
    )


@router.get(
    "",
    response_model=ResumeListResponse,
    summary="List resumes",
    description="Returns the calling tenant's most recent resumes, newest first.",
)
async def list_resumes(
    principal: ReadPrincipal,
    session: DbSession,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    before: Annotated[
        datetime | None,
        Query(description="Cursor: return items created before this ISO 8601 timestamp."),
    ] = None,
) -> ResumeListResponse:
    """List the caller's resumes.

    Args:
        principal: Verified caller.
        session: Database session.
        limit: Maximum rows to return (1–200).
        before: Cursor for pagination — only return items created before this time.

    Returns:
        A page of resume summaries, scoped to the caller's tenant.
    """
    rows = await ResumeRepository(session).list_for_tenant(
        principal.tenant_id, limit, before=before,
    )
    items = [
        ResumeSummary(
            document_id=row.id,
            filename=row.filename_sanitized,
            media_type=row.media_type,
            page_count=row.page_count,
            parse_status=row.parse_status,
            created_at=row.created_at,
        )
        for row in rows
    ]
    exhausted = len(items) < limit
    next_cursor = None if exhausted or not items else items[-1].created_at.isoformat()
    return ResumeListResponse(items=items, count=len(items), next_cursor=next_cursor)


@router.get(
    "/{document_id}",
    response_model=ResumeDetailResponse,
    summary="Read a resume",
    description=(
        "Returns document metadata and the extracted text of its latest parse. "
        "Documents belonging to another tenant are reported as not found."
    ),
)
async def read_resume(
    document_id: uuid.UUID,
    principal: ReadPrincipal,
    session: DbSession,
) -> ResumeDetailResponse:
    """Read one resume.

    Args:
        document_id: Document identifier.
        principal: Verified caller.
        session: Database session.

    Returns:
        The document detail with extracted text.

    Raises:
        ResourceNotFoundError: If no such document exists for this tenant.
    """
    repo = ResumeRepository(session)
    document = await repo.get(principal.tenant_id, document_id)
    if document is None:
        raise ResourceNotFoundError()

    version = await repo.latest_version(principal.tenant_id, document_id)

    # A quarantined document must not hand its text to any consumer until a
    # human has reviewed the findings.
    visible_text = "" if version is None or version.quarantined else version.extracted_text

    return ResumeDetailResponse(
        document_id=document.id,
        filename=document.filename_sanitized,
        media_type=document.media_type,
        size_bytes=document.size_bytes,
        sha256=document.sha256,
        page_count=document.page_count,
        parse_status=document.parse_status,
        needs_ocr=document.needs_ocr,
        parser_version=document.parser_version,
        text=visible_text,
        injection_risk_score=version.injection_risk_score if version else 0.0,
        quarantined=version.quarantined if version else False,
        sanitization_report=version.sanitization_report if version else {},
        created_at=document.created_at,
    )
