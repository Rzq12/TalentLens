"""Rubric authoring, approval, and versioning endpoints.

Every mutation is a POST. The project targets a POST/GET-only surface for the
MVP, and the operations here are not PUTs in spirit anyway: approving is a state
transition, and minting the next version creates a row rather than replacing
one.

The router reads the requirement set back explicitly after every call.
``RubricVersion.requirements`` is ``lazy="noload"``, so touching the
relationship would yield an empty list rather than the rows just written — a
response indistinguishable from a rubric that genuinely has no criteria.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status

from app.db import DbSession
from app.models import Requirement, RubricVersion
from app.repositories.rubric import RubricRepository
from app.schemas.rubric import (
    RequirementInput,
    RequirementReplaceRequest,
    RequirementResponse,
    RubricCreateRequest,
    RubricResponse,
)
from app.security import ReadPrincipal, WritePrincipal
from app.services.rubric import (
    approve_rubric,
    create_draft_rubric,
    mint_next_version,
    update_draft_requirements,
)
from app.services.rubric import read_rubric as read_rubric_version

router = APIRouter(prefix="/rubrics", tags=["rubrics"])


def _to_models(requirements: list[RequirementInput]) -> list[Requirement]:
    """Convert validated input into unsaved ORM rows.

    Identifiers are assigned here rather than left to the column default: the
    default is applied by the database on insert, and the response is built from
    these same objects before the transaction commits.

    Args:
        requirements: Validated criteria, in display order.

    Returns:
        Unsaved requirement rows. `tenant_id`, `rubric_version_id`, `ordinal`,
        and the normalized `weight` are all set by the service.
    """
    return [
        Requirement(
            id=uuid.uuid4(),
            text=item.text,
            category=item.category,
            is_must_have=item.is_must_have,
            weight=item.weight,
            min_years=item.min_years,
            min_seniority=item.min_seniority,
        )
        for item in requirements
    ]


def _to_response(version: RubricVersion, requirements: list[Requirement]) -> RubricResponse:
    """Assemble the wire representation of a rubric.

    Args:
        version: The rubric version.
        requirements: Its criteria, in display order.

    Returns:
        The response body.
    """
    return RubricResponse(
        rubric_version_id=version.id,
        job_id=version.job_id,
        version=version.version,
        status=version.status,
        content_hash=version.content_hash,
        must_have_fail_cap=version.must_have_fail_cap,
        aggregation_formula_version=version.aggregation_formula_version,
        source=version.source,
        requirements=[RequirementResponse.model_validate(row) for row in requirements],
    )


@router.post(
    "",
    response_model=RubricResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a draft rubric",
    description=(
        "Creates the next rubric version for a job, in `draft` status. Weights "
        "are supplied as relative importance and normalized to sum to exactly "
        "1.0000. The rubric cannot score anything until it is approved."
    ),
)
async def create_rubric(
    payload: RubricCreateRequest,
    principal: WritePrincipal,
    session: DbSession,
) -> RubricResponse:
    """Create a draft rubric for a job.

    Args:
        payload: Validated job reference and criteria.
        principal: Verified caller; supplies the owning tenant.
        session: Database session.

    Returns:
        The new draft and its normalized criteria.
    """
    repository = RubricRepository(session)
    version = await create_draft_rubric(
        rubric_repo=repository,
        principal=principal,
        job_id=payload.job_id,
        requirements=_to_models(payload.requirements),
        source=payload.source,
    )
    requirements = await repository.list_requirements(principal.tenant_id, version.id)
    return _to_response(version, requirements)


@router.get(
    "/{rubric_version_id}",
    response_model=RubricResponse,
    summary="Read a rubric version",
    description=(
        "Returns one rubric version with its criteria. Read-only roles may call "
        "this: auditing a score requires seeing the criteria that produced it. "
        "Versions belonging to another tenant are reported as not found."
    ),
)
async def read_rubric(
    rubric_version_id: uuid.UUID,
    principal: ReadPrincipal,
    session: DbSession,
) -> RubricResponse:
    """Read one rubric version.

    Args:
        rubric_version_id: Version to read.
        principal: Verified caller.
        session: Database session.

    Returns:
        The rubric version and its criteria.

    Raises:
        ResourceNotFoundError: If no such version exists for this tenant.
    """
    repository = RubricRepository(session)
    version = await read_rubric_version(
        rubric_repo=repository,
        principal=principal,
        rubric_version_id=rubric_version_id,
    )
    requirements = await repository.list_requirements(principal.tenant_id, version.id)
    return _to_response(version, requirements)


@router.post(
    "/{rubric_version_id}/requirements",
    response_model=RubricResponse,
    summary="Replace the criteria of a draft",
    description=(
        "Replaces the whole requirement set of a draft rubric and renormalizes "
        "the weights. Approved rubrics are immutable and answer 409 — mint a "
        "new version instead."
    ),
)
async def replace_requirements(
    rubric_version_id: uuid.UUID,
    payload: RequirementReplaceRequest,
    principal: WritePrincipal,
    session: DbSession,
) -> RubricResponse:
    """Replace the criteria of a draft rubric.

    Args:
        rubric_version_id: Draft to edit.
        payload: The replacement criteria, in display order.
        principal: Verified caller.
        session: Database session.

    Returns:
        The rubric version and its new criteria.

    Raises:
        ResourceNotFoundError: If no such version exists for this tenant.
        ResourceConflictError: If the version is no longer a draft.
    """
    repository = RubricRepository(session)
    version = await update_draft_requirements(
        rubric_repo=repository,
        principal=principal,
        rubric_version_id=rubric_version_id,
        requirements=_to_models(payload.requirements),
    )
    requirements = await repository.list_requirements(principal.tenant_id, version.id)
    return _to_response(version, requirements)


@router.post(
    "/{rubric_version_id}/approve",
    response_model=RubricResponse,
    summary="Approve a draft rubric",
    description=(
        "Freezes the criteria, records the approver, and stamps the content "
        "hash that every score computed against this rubric is attributed to. "
        "Approving a rubric that is not a draft answers 409."
    ),
)
async def approve(
    rubric_version_id: uuid.UUID,
    principal: WritePrincipal,
    session: DbSession,
) -> RubricResponse:
    """Approve a draft rubric.

    Args:
        rubric_version_id: Draft to approve.
        principal: Verified caller; recorded as the approver.
        session: Database session.

    Returns:
        The approved version and its frozen criteria.

    Raises:
        ResourceNotFoundError: If no such version exists for this tenant.
        ResourceConflictError: If the version is not a draft.
    """
    repository = RubricRepository(session)
    version = await approve_rubric(
        rubric_repo=repository,
        principal=principal,
        rubric_version_id=rubric_version_id,
    )
    requirements = await repository.list_requirements(principal.tenant_id, version.id)
    return _to_response(version, requirements)


@router.post(
    "/{rubric_version_id}/versions",
    response_model=RubricResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Mint the next rubric version",
    description=(
        "Forks an approved rubric into an editable successor and retires the "
        "predecessor as `superseded`. Scores already computed stay attributable "
        "to the version that produced them. Minting from a draft answers 409."
    ),
)
async def mint_version(
    rubric_version_id: uuid.UUID,
    principal: WritePrincipal,
    session: DbSession,
) -> RubricResponse:
    """Fork an approved rubric into a new draft.

    Args:
        rubric_version_id: Approved version to supersede.
        principal: Verified caller.
        session: Database session.

    Returns:
        The new draft and a copy of the predecessor's criteria.

    Raises:
        ResourceNotFoundError: If no such version exists for this tenant.
        ResourceConflictError: If the version has not been approved.
    """
    repository = RubricRepository(session)
    version = await mint_next_version(
        rubric_repo=repository,
        principal=principal,
        rubric_version_id=rubric_version_id,
    )
    requirements = await repository.list_requirements(principal.tenant_id, version.id)
    return _to_response(version, requirements)
