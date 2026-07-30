"""Resume ingestion endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, File, Query, UploadFile, status

from app.db import DbSession
from app.exceptions import ResourceNotFoundError
from app.repositories.ingestion import ResumeRepository
from app.schemas.ingestion import (
    ResumeDetailResponse,
    ResumeListResponse,
    ResumeSummary,
    ResumeUploadResponse,
)
from app.security import CurrentPrincipal
from app.services.ingestion import ingest_resume
from app.services.storage import get_object_store
from app.utils.upload import read_upload_bounded

router = APIRouter(prefix="/resumes", tags=["resumes"])


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
    principal: CurrentPrincipal,
    session: DbSession,
    file: Annotated[UploadFile, File()],
) -> ResumeUploadResponse:
    """Ingest one resume.

    Args:
        principal: Verified caller.
        session: Database session.
        file: The uploaded document.

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
    )
    document = outcome.document
    return ResumeUploadResponse(
        document_id=document.id,
        filename=document.filename_sanitized,
        media_type=document.media_type,
        size_bytes=document.size_bytes,
        sha256=document.sha256,
        page_count=document.page_count,
        parse_status=document.parse_status,
        needs_ocr=document.needs_ocr,
        deduplicated=outcome.deduplicated,
    )


@router.get(
    "",
    response_model=ResumeListResponse,
    summary="List resumes",
    description="Returns the calling tenant's most recent resumes, newest first.",
)
async def list_resumes(
    principal: CurrentPrincipal,
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
    next_cursor = items[-1].created_at.isoformat() if items else None
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
    principal: CurrentPrincipal,
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
        text=version.extracted_text if version else "",
        created_at=document.created_at,
    )
