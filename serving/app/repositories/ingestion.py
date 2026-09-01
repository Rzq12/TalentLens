"""Data access for resumes and jobs.

This is the only layer permitted to query the database. Every read and write is
scoped by `tenant_id` at the query level — a caller cannot ask for a row that
belongs to another tenant, so a missing row and a foreign row are
indistinguishable from outside, which is the behaviour we want.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Candidate, CandidateProfile, Job, ResumeDocument, ResumeVersion


class ResumeRepository:
    """Persistence for resume documents and their parsed versions."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the repository.

        Args:
            session: An active async session.
        """
        self._session = session

    async def find_by_hash(self, tenant_id: uuid.UUID, sha256: str) -> ResumeDocument | None:
        """Return the tenant's document with this content hash, if any.

        Args:
            tenant_id: Owning tenant.
            sha256: Content hash to look up.

        Returns:
            The matching document, or None.
        """
        stmt = select(ResumeDocument).where(
            ResumeDocument.tenant_id == tenant_id, ResumeDocument.sha256 == sha256
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get(
        self, tenant_id: uuid.UUID, document_id: uuid.UUID
    ) -> ResumeDocument | None:
        """Return one document scoped to the caller's tenant.

        Args:
            tenant_id: Owning tenant.
            document_id: Document identifier.

        Returns:
            The document, or None if it does not exist for this tenant.
        """
        stmt = (
            select(ResumeDocument)
            .where(ResumeDocument.tenant_id == tenant_id, ResumeDocument.id == document_id)
            .options(selectinload(ResumeDocument.versions))
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_for_tenant(
        self,
        tenant_id: uuid.UUID,
        limit: int = 50,
        *,
        before: datetime | None = None,
    ) -> Sequence[ResumeDocument]:
        """Return the tenant's most recent documents.

        Args:
            tenant_id: Owning tenant.
            limit: Maximum rows to return.
            before: If provided, only return documents created before this time
                (cursor-based pagination).

        Returns:
            Documents ordered newest first.
        """
        stmt = (
            select(ResumeDocument)
            .where(ResumeDocument.tenant_id == tenant_id)
            .order_by(ResumeDocument.created_at.desc())
            .limit(limit)
        )
        if before is not None:
            stmt = stmt.where(ResumeDocument.created_at < before)
        return (await self._session.execute(stmt)).scalars().all()

    async def latest_version(
        self, tenant_id: uuid.UUID, document_id: uuid.UUID
    ) -> ResumeVersion | None:
        """Return the newest parsed version of a document.

        Args:
            tenant_id: Owning tenant.
            document_id: Document identifier.

        Returns:
            The highest-numbered version, or None.
        """
        stmt = (
            select(ResumeVersion)
            .where(
                ResumeVersion.tenant_id == tenant_id,
                ResumeVersion.document_id == document_id,
            )
            .order_by(ResumeVersion.version.desc())
            .limit(1)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def add(
        self, document: ResumeDocument, version: ResumeVersion
    ) -> ResumeDocument:
        """Persist a new document together with its first parsed version.

        Args:
            document: The document row.
            version: Its initial version row.

        Returns:
            The persisted document.
        """
        self._session.add(document)
        await self._session.flush()
        version.document_id = document.id
        self._session.add(version)
        await self._session.flush()
        return document

    async def find_candidate_by_email(
        self, tenant_id: uuid.UUID, email: str
    ) -> Candidate | None:
        """Return a candidate by tenant-scoped email."""
        stmt = select(Candidate).where(
            Candidate.tenant_id == tenant_id,
            Candidate.email == email,
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def find_profile_by_resume_version(
        self, tenant_id: uuid.UUID, resume_version_id: uuid.UUID
    ) -> CandidateProfile | None:
        """Return the profile that links a parsed resume to its candidate."""
        stmt = select(CandidateProfile).where(
            CandidateProfile.tenant_id == tenant_id,
            CandidateProfile.resume_version_id == resume_version_id,
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def add_candidate_profile(
        self, candidate: Candidate, profile: CandidateProfile
    ) -> None:
        """Persist an intake candidate and its resume-linked profile."""
        self._session.add(candidate)
        await self._session.flush()
        profile.candidate_id = candidate.id
        self._session.add(profile)
        await self._session.flush()


class JobRepository:
    """Persistence for job descriptions."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the repository.

        Args:
            session: An active async session.
        """
        self._session = session

    async def add(self, job: Job) -> Job:
        """Persist a new job.

        Args:
            job: The job row.

        Returns:
            The persisted job.
        """
        self._session.add(job)
        await self._session.flush()
        return job

    async def get(self, tenant_id: uuid.UUID, job_id: uuid.UUID) -> Job | None:
        """Return one job scoped to the caller's tenant.

        Args:
            tenant_id: Owning tenant.
            job_id: Job identifier.

        Returns:
            The job, or None if it does not exist for this tenant.
        """
        stmt = select(Job).where(Job.tenant_id == tenant_id, Job.id == job_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_for_tenant(
        self,
        tenant_id: uuid.UUID,
        limit: int = 50,
        *,
        before: datetime | None = None,
    ) -> Sequence[Job]:
        """Return the tenant's most recent jobs.

        Args:
            tenant_id: Owning tenant.
            limit: Maximum rows to return.
            before: If provided, only return jobs created before this time
                (cursor-based pagination).

        Returns:
            Jobs ordered newest first.
        """
        stmt = (
            select(Job)
            .where(Job.tenant_id == tenant_id)
            .order_by(Job.created_at.desc())
            .limit(limit)
        )
        if before is not None:
            stmt = stmt.where(Job.created_at < before)
        return (await self._session.execute(stmt)).scalars().all()
