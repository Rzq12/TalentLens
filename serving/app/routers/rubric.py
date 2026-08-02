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
from app.exceptions import CoreStageFailedError, ValidationFailedError
from app.models import Requirement, RubricVersion
from app.repositories.rubric import RubricRepository
from app.schemas.rubric import (
    ContributionResponse,
    RequirementInput,
    RequirementReplaceRequest,
    RequirementResponse,
    RubricCreateRequest,
    RubricResponse,
    ScorePreviewRequest,
    ScorePreviewResponse,
    TemplateDetailResponse,
    TemplateInstantiateRequest,
    TemplateListResponse,
    TemplateSummary,
)
from app.security import ReadPrincipal, WritePrincipal
from app.services.rubric import (
    approve_rubric,
    create_draft_rubric,
    mint_next_version,
    update_draft_requirements,
)
from app.services.rubric import read_rubric as read_rubric_version
from app.services.rubric_templates import get_template, list_templates
from app.services.scoring import Verdict, aggregate_score

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


# --------------------------------------------------------------------------- #
# Starter templates                                                            #
#                                                                              #
# These three routes are declared before `/{rubric_version_id}` deliberately.   #
# FastAPI matches in declaration order, so with the parameterized route first,  #
# a GET of `/rubrics/templates` binds "templates" to `rubric_version_id`, fails #
# UUID coercion, and answers 422 — the catalogue would be unreachable.          #
# --------------------------------------------------------------------------- #


@router.get(
    "/templates",
    response_model=TemplateListResponse,
    summary="List the starter rubric templates",
    description=(
        "Returns every shipped template, ordered by display name. Templates are "
        "application data rather than tenant data — the catalogue is identical "
        "for every caller. The criteria themselves are omitted here; fetch one "
        "template to see them."
    ),
)
async def list_rubric_templates(principal: ReadPrincipal) -> TemplateListResponse:
    """List the shipped rubric templates.

    Read access is sufficient: nothing is written and no tenant data is exposed.

    Args:
        principal: Verified caller. The catalogue does not vary by tenant, but
            the route stays behind a token — an open endpoint here would be a
            free enumeration of the product's scoring vocabulary.

    Returns:
        Every template, ordered by display name.
    """
    return TemplateListResponse(
        templates=[
            TemplateSummary(
                key=template.key,
                name=template.name,
                role_family=template.role_family,
                requirement_count=len(template.requirements),
            )
            for template in list_templates()
        ]
    )


@router.get(
    "/templates/{template_key}",
    response_model=TemplateDetailResponse,
    summary="Read one starter rubric template",
    description=(
        "Returns a template with the criteria it would seed a draft with. The "
        "weights are relative, exactly as a caller would submit them — they are "
        "normalized when a draft is actually created. An unknown key answers 404."
    ),
)
async def read_rubric_template(
    template_key: str,
    principal: ReadPrincipal,
) -> TemplateDetailResponse:
    """Read one template and the criteria it carries.

    Args:
        template_key: The template slug, exactly as listed. Matching is
            case-sensitive.
        principal: Verified caller.

    Returns:
        The template and its criteria, in presentation order.

    Raises:
        ResourceNotFoundError: If no template carries this key. The message
            names no key — this argument arrives from the URL and reaches the
            response body, so echoing it back would make the route a reflection
            primitive.
    """
    template = get_template(template_key)
    return TemplateDetailResponse(
        key=template.key,
        name=template.name,
        role_family=template.role_family,
        requirements=list(template.requirements),
    )


@router.post(
    "/templates/{template_key}:instantiate",
    response_model=RubricResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Seed a new draft rubric from a template",
    description=(
        "Creates the next rubric version for a job from a shipped template, in "
        "`draft` status and with `source` recorded as `template`. The result is "
        "an ordinary draft: the criteria are editable and a human still has to "
        "approve it before anything is scored against it. An unknown template "
        "key, or a job the caller cannot see, answers 404."
    ),
)
async def instantiate_rubric_template(
    template_key: str,
    payload: TemplateInstantiateRequest,
    principal: WritePrincipal,
    session: DbSession,
) -> RubricResponse:
    """Create a draft rubric seeded from a template.

    The template is resolved before the job is touched, so an unknown key costs
    no database work. Everything after that is the ordinary authoring path —
    weight normalization, the job-visibility check, and the version number all
    come from `create_draft_rubric` rather than being reimplemented here.

    Args:
        template_key: The template slug to seed from.
        payload: The job the new draft is authored against.
        principal: Verified caller; supplies the owning tenant.
        session: Database session.

    Returns:
        The new draft and its normalized criteria.

    Raises:
        ResourceNotFoundError: If no template carries this key, or if the job
            does not exist for this tenant.
    """
    template = get_template(template_key)
    repository = RubricRepository(session)
    version = await create_draft_rubric(
        rubric_repo=repository,
        principal=principal,
        job_id=payload.job_id,
        requirements=_to_models(list(template.requirements)),
        source="template",
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


@router.post(
    "/{rubric_version_id}/score:preview",
    response_model=ScorePreviewResponse,
    summary="Preview how a rubric would score under hypothetical verdicts",
    description=(
        "An authoring aid: supply synthetic verdicts and see what the rubric "
        "would produce. No resume is involved and no score is persisted. The "
        "rubric must be approved — a draft or superseded version answers 409, "
        "because a score attributed to an unapproved rubric is not defensible. "
        "A verdict naming an unknown or duplicated requirement answers 422."
    ),
)
async def score_preview(
    rubric_version_id: uuid.UUID,
    payload: ScorePreviewRequest,
    principal: ReadPrincipal,
    session: DbSession,
) -> ScorePreviewResponse:
    """Preview a rubric's scoring behaviour under caller-supplied verdicts.

    Read access is sufficient: nothing is written, and the verdicts are the
    caller's hypothesis rather than a judgement about any real candidate.

    Args:
        rubric_version_id: Approved rubric to preview against.
        payload: Hypothetical verdicts, one per requirement.
        principal: Verified caller.
        session: Database session.

    Returns:
        The score, the pre-cap raw score, and the per-requirement breakdown.

    Raises:
        ResourceNotFoundError: If no such version exists for this tenant.
        ResourceConflictError: If the rubric is not approved.
        ValidationFailedError: If the verdict set does not correspond to this
            rubric's requirements.
    """
    repository = RubricRepository(session)
    version = await read_rubric_version(
        rubric_repo=repository,
        principal=principal,
        rubric_version_id=rubric_version_id,
    )
    requirements = await repository.list_requirements(principal.tenant_id, version.id)

    verdicts = [
        Verdict(requirement_id=item.requirement_id, verdict=item.verdict)
        for item in payload.verdicts
    ]

    try:
        result = aggregate_score(rubric=version, requirements=requirements, verdicts=verdicts)
    except CoreStageFailedError as exc:
        # `aggregate_score` reports an unusable verdict set as a failed stage,
        # which is a 500 — correct when a judge produced it, wrong here. At this
        # endpoint the verdicts are caller input, so the same condition is a
        # client error.
        raise ValidationFailedError(str(exc)) from exc

    return ScorePreviewResponse(
        score=result.score,
        raw_score=result.raw_score,
        formula_version=result.formula_version,
        must_have_failed=result.must_have_failed,
        cap_applied=result.cap_applied,
        failed_must_have_ids=list(result.failed_must_have_ids),
        contributions=[
            ContributionResponse(
                requirement_id=contribution.requirement_id,
                ordinal=contribution.ordinal,
                text=contribution.text,
                weight=contribution.weight,
                is_must_have=contribution.is_must_have,
                verdict=contribution.verdict,  # type: ignore[arg-type]
                points=contribution.points,
            )
            for contribution in result.contributions
        ],
    )
