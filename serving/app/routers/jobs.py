"""Job description endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, File, Form, Query, UploadFile, status

from app.db import DbSession
from app.exceptions import ResourceNotFoundError, ValidationFailedError
from app.repositories.ingestion import JobRepository
from app.schemas.ingestion import (
    JobCreateRequest,
    JobListResponse,
    JobResponse,
    JobSummary,
)
from app.security import ReadPrincipal, WritePrincipal
from app.services.ingestion import create_job_from_text, create_job_from_upload
from app.utils.upload import read_upload_bounded

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post(
    "",
    response_model=JobResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a job description",
    description="Creates a job from pasted text. The job starts in `draft` status.",
)
async def create_job(
    payload: JobCreateRequest,
    principal: WritePrincipal,
    session: DbSession,
) -> JobResponse:
    """Create a job from pasted text.

    Args:
        payload: Validated job fields.
        principal: Verified caller.
        session: Database session.

    Returns:
        The persisted job.
    """
    job = await create_job_from_text(
        session=session,
        principal=principal,
        title=payload.title,
        description_raw=payload.description_raw,
        department=payload.department,
        location=payload.location,
        employment_type=payload.employment_type,
        seniority=payload.seniority,
    )
    return JobResponse.model_validate(job)


@router.post(
    "/upload",
    response_model=JobResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a job description document",
    description=(
        "Creates a job by extracting text from an uploaded PDF or DOCX. The "
        "media type is determined from the file's bytes, not its name."
    ),
)
async def upload_job(
    principal: WritePrincipal,
    session: DbSession,
    title: Annotated[str, Form()],
    file: Annotated[UploadFile, File()],
) -> JobResponse:
    """Create a job from an uploaded document.

    Args:
        principal: Verified caller.
        session: Database session.
        title: Job title supplied alongside the file.
        file: The uploaded job description.

    Returns:
        The persisted job.

    Raises:
        ValidationFailedError: If the title is blank.
    """
    if not title.strip():
        raise ValidationFailedError("Title must not be blank.")
    content = await read_upload_bounded(file)
    job = await create_job_from_upload(
        session=session,
        principal=principal,
        content=content,
        title=title.strip(),
    )
    return JobResponse.model_validate(job)


@router.get(
    "",
    response_model=JobListResponse,
    summary="List job descriptions",
    description=(
        "Returns the tenant's jobs, newest first. Rows omit the full "
        "description — read a single job for that. Page by passing the "
        "returned `next_cursor` back as `before`."
    ),
)
async def list_jobs(
    principal: ReadPrincipal,
    session: DbSession,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    before: Annotated[
        datetime | None,
        Query(description="Cursor: return jobs created before this ISO 8601 timestamp."),
    ] = None,
) -> JobListResponse:
    """List the tenant's jobs.

    Args:
        principal: Verified caller.
        session: Database session.
        limit: Maximum rows to return.
        before: Cursor from a previous page.

    Returns:
        A page of job summaries. `next_cursor` is null once the listing is
        exhausted, which is the case whenever fewer rows come back than were
        asked for.
    """
    items = await JobRepository(session).list_for_tenant(
        principal.tenant_id, limit, before=before
    )
    exhausted = len(items) < limit
    next_cursor = None if exhausted or not items else items[-1].created_at.isoformat()
    return JobListResponse(
        items=[JobSummary.model_validate(job) for job in items],
        count=len(items),
        next_cursor=next_cursor,
    )


@router.get(
    "/{job_id}",
    response_model=JobResponse,
    summary="Read a job description",
    description="Jobs belonging to another tenant are reported as not found.",
)
async def read_job(
    job_id: uuid.UUID,
    principal: ReadPrincipal,
    session: DbSession,
) -> JobResponse:
    """Read one job.

    Args:
        job_id: Job identifier.
        principal: Verified caller.
        session: Database session.

    Returns:
        The job.

    Raises:
        ResourceNotFoundError: If no such job exists for this tenant.
    """
    job = await JobRepository(session).get(principal.tenant_id, job_id)
    if job is None:
        raise ResourceNotFoundError()
    return JobResponse.model_validate(job)
