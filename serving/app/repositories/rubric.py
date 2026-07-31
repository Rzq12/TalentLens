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

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Requirement, RubricVersion


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
        """
        self._session.add(version)
        await self._session.flush()
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
