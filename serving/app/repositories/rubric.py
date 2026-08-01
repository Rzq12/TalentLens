"""Persistence for rubric versions and their requirements.

This is the only layer permitted to query the rubric tables. Every read and
write is scoped by `tenant_id` at the query level, so a caller cannot ask for a
row belonging to another tenant — a foreign row and a missing row are
indistinguishable from outside, which is what lets the service answer 404 rather
than 403 and avoid confirming that an identifier exists elsewhere.

The class satisfies the `RubricRepository` Protocol declared in
`app.services.rubric`. It is deliberately not imported there: the service stays
free of session-bound types so its logic remains testable without a database.
"""

from __future__ import annotations

import uuid

from sqlalchemy import delete, func, literal, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import ResourceConflictError
from app.models import Job, Requirement, RubricVersion


def _violates(error: IntegrityError, constraint: str) -> bool:
    """Report whether an integrity error came from a named constraint.

    asyncpg exposes the constraint name on the wrapped driver error, but the
    attribute is absent on other drivers and on errors raised before the
    statement reached the server. The string fallback keeps this honest on
    SQLite and on any driver that only renders the name into the message.

    Args:
        error: The integrity error raised by the flush.
        constraint: Constraint name to test for.

    Returns:
        True if the error is attributable to that constraint.
    """
    name = getattr(error.orig, "constraint_name", None)
    return name == constraint or constraint in str(error.orig)


class RubricRepository:
    """Reads and writes rubric versions and requirements for one session."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to a session.

        Args:
            session: Active async session; the caller owns the transaction.
        """
        self._session = session

    async def add_version(self, version: RubricVersion) -> RubricVersion:
        """Persist a rubric version and return the same instance.

        The flush is required rather than cosmetic: the caller immediately uses
        `version.id` to scope the requirements, and those rows carry a foreign
        key PostgreSQL cannot check against an unsent insert.

        Args:
            version: The rubric version to persist.

        Returns:
            The same instance, now flushed.

        Raises:
            ResourceConflictError: If another transaction already minted this
                version number for the job. The version comes from a
                `max(version) + 1` read, so two concurrent authors compute the
                same successor and `uq_rubric_versions_job_version` rejects the
                loser. That is the constraint doing its job, but it surfaces as
                a driver error, and an unhandled one becomes a 500 for what is
                really a retryable conflict.
        """
        self._session.add(version)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            if _violates(exc, "uq_rubric_versions_job_version"):
                raise ResourceConflictError(
                    f"Version {version.version} of this rubric already exists. "
                    "Another author minted it concurrently; retry the request."
                ) from exc
            raise
        return version

    async def get_version(
        self, tenant_id: uuid.UUID, rubric_version_id: uuid.UUID
    ) -> RubricVersion | None:
        """Return one rubric version scoped to a tenant.

        Args:
            tenant_id: Owning tenant.
            rubric_version_id: Version to load.

        Returns:
            The version, or None if it does not exist for this tenant.
        """
        stmt = select(RubricVersion).where(
            RubricVersion.tenant_id == tenant_id,
            RubricVersion.id == rubric_version_id,
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def max_version_for_job(self, tenant_id: uuid.UUID, job_id: uuid.UUID) -> int:
        """Return the highest version number minted for a job.

        Aggregating in the database rather than loading rows keeps this constant
        work as a job accumulates rubric versions. A job with no rubric yields
        SQL NULL, which is normalized to 0 so the caller's `+ 1` produces
        version 1 instead of raising.

        Args:
            tenant_id: Owning tenant.
            job_id: Job whose versions are counted.

        Returns:
            The highest version number, or 0 if the job has no rubric.
        """
        stmt = select(func.max(RubricVersion.version)).where(
            RubricVersion.tenant_id == tenant_id,
            RubricVersion.job_id == job_id,
        )
        return (await self._session.execute(stmt)).scalar() or 0

    async def job_exists(self, tenant_id: uuid.UUID, job_id: uuid.UUID) -> bool:
        """Report whether this tenant owns a job with this identifier.

        Selects the literal 1 rather than the row: the caller only needs to know
        whether authoring against this job is permitted, and a job description
        carries a full text body nothing here reads.

        Args:
            tenant_id: Owning tenant.
            job_id: Job to look for.

        Returns:
            True if the job exists and belongs to this tenant.
        """
        stmt = (
            select(literal(1))
            .select_from(Job)
            .where(Job.tenant_id == tenant_id, Job.id == job_id)
            .limit(1)
        )
        return (await self._session.execute(stmt)).scalar() is not None

    async def replace_requirements(
        self,
        tenant_id: uuid.UUID,
        rubric_version_id: uuid.UUID,
        requirements: list[Requirement],
    ) -> None:
        """Replace the whole requirement set of one rubric version.

        Delete-then-insert rather than an upsert: editing a draft may drop a
        criterion, and a merge would leave the removed requirement scoring
        candidates. An empty list is accepted and clears the set — the service
        decides whether an empty rubric is legal, and duplicating that judgement
        here would make "clear everything" impossible to express.

        Args:
            tenant_id: Owning tenant.
            rubric_version_id: Version whose requirements are replaced.
            requirements: The replacement rows, in display order.
        """
        clear = delete(Requirement).where(
            Requirement.tenant_id == tenant_id,
            Requirement.rubric_version_id == rubric_version_id,
        )
        await self._session.execute(clear)

        for requirement in requirements:
            self._session.add(requirement)
        await self._session.flush()

    async def list_requirements(
        self, tenant_id: uuid.UUID, rubric_version_id: uuid.UUID
    ) -> list[Requirement]:
        """Return the requirements of one rubric version, in display order.

        Args:
            tenant_id: Owning tenant.
            rubric_version_id: Version whose requirements are read.

        Returns:
            The requirements ordered by `ordinal`, empty if there are none.
        """
        stmt = (
            select(Requirement)
            .where(
                Requirement.tenant_id == tenant_id,
                Requirement.rubric_version_id == rubric_version_id,
            )
            .order_by(Requirement.ordinal)
        )
        return list((await self._session.execute(stmt)).scalars().all())
