"""Request and response schemas for rubric authoring.

Validation here is the first of two layers. The service validates again, but a
rejection at this boundary means no session work and no partial write was ever
attempted — the request never reached business logic.

Two constraints are worth naming. ``category`` and ``source`` are literals
rather than free text because both drive downstream behaviour: the category
groups a criterion in the score breakdown, and the source records how the
criteria were produced. And ``weight`` is bounded but *relative* — the caller
expresses "this matters three times as much", and the service normalizes the
set to sum to exactly 1.0000 before storing it.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# The `requirements.min_years` column is numeric(4,1): three integer digits and
# one decimal. 99 is a career ceiling that fits it with room to spare.
MAX_MIN_YEARS = 99
# Weights are relative, not percentages, so the ceiling only has to stop absurd
# input from reaching the normalizer. numeric(5,4) holds the normalized result.
MAX_WEIGHT = 1000
# A rubric a human is expected to read and sign off on does not run to hundreds
# of criteria. The ceiling exists because the list drives one INSERT per element
# plus a sort, so an unbounded list is a write-amplification lever on a shared
# database. It also keeps the set well clear of the 10,000 weight quanta
# available: past that, criteria cannot all carry a non-zero normalized weight.
MAX_REQUIREMENTS = 200

RequirementCategory = Literal[
    "skill",
    "experience",
    "education",
    "certification",
    "language",
    "other",
]
RubricSource = Literal["manual", "extracted", "template"]
RubricStatus = Literal["draft", "approved", "superseded"]
# A floor only means something if both sides read it the same way. Free text
# would let "Sr." and "senior" express the same requirement while comparing
# unequal, which makes the floor unenforceable by anything downstream.
SeniorityLevel = Literal[
    "intern",
    "junior",
    "mid",
    "senior",
    "staff",
    "principal",
    "lead",
    "manager",
    "director",
]
# The verdict vocabulary a caller may submit to the score preview. It mirrors
# `app.services.scoring.VERDICTS` deliberately rather than importing it: this is
# the wire contract, and pinning it here means a change to the internal
# vocabulary shows up as a failing test rather than as a silently widened API.
PreviewVerdict = Literal["met", "partial", "missing", "unclear"]


class RequirementInput(BaseModel):
    """One criterion as supplied by the author."""

    text: str = Field(
        min_length=1,
        max_length=2000,
        description="What is being assessed, in the recruiter's own words.",
    )
    category: RequirementCategory = Field(
        default="skill",
        description="Groups the criterion in the score breakdown.",
    )
    is_must_have: bool = Field(
        default=False,
        description="A candidate failing this cannot score above the fail cap.",
    )
    weight: Decimal = Field(
        default=Decimal(1),
        ge=0,
        le=MAX_WEIGHT,
        description="Relative importance. Normalized server-side to sum to 1.0000.",
    )
    min_years: Decimal | None = Field(
        default=None,
        ge=0,
        le=MAX_MIN_YEARS,
        description="Minimum years of relevant experience, if this criterion has a floor.",
    )
    min_seniority: SeniorityLevel | None = Field(
        default=None,
        description="Minimum seniority level, if this criterion has a floor.",
    )

    @field_validator("text")
    @classmethod
    def _reject_whitespace_only(cls, value: str) -> str:
        """Reject text that is only whitespace.

        Args:
            value: The criterion text as supplied.

        Returns:
            The text with surrounding whitespace removed.

        Raises:
            ValueError: If nothing remains after stripping. A blank criterion
                would be weighted and scored against like any other, silently
                diluting every real criterion in the set.
        """
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped


class RubricCreateRequest(BaseModel):
    """Payload for creating the next draft rubric for a job."""

    job_id: uuid.UUID = Field(description="Job the rubric is authored against.")
    requirements: list[RequirementInput] = Field(
        min_length=1,
        max_length=MAX_REQUIREMENTS,
        description="The criteria, in display order. A rubric with none cannot score.",
    )
    source: RubricSource = Field(
        default="manual",
        description="How the criteria were produced.",
    )


class RequirementReplaceRequest(BaseModel):
    """Payload for replacing the whole requirement set of a draft."""

    requirements: list[RequirementInput] = Field(
        min_length=1,
        max_length=MAX_REQUIREMENTS,
        description="The replacement criteria, in display order.",
    )


class RequirementResponse(BaseModel):
    """One stored criterion, with the weight the rubric will actually use."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    ordinal: int = Field(description="Display order within the rubric, from 0.")
    text: str
    category: RequirementCategory
    is_must_have: bool
    weight: Decimal = Field(description="Normalized weight; the set sums to exactly 1.0000.")
    min_years: Decimal | None = None
    # Narrowed to match `RequirementInput`. Publishing `str` here would tell a
    # client the field is arbitrary text and leave it unable to branch on the
    # value exhaustively, even though nothing can store anything else: the column
    # is only ever written from a validated `RequirementInput`, and the copy made
    # by minting a successor carries values that already passed that check.
    min_seniority: SeniorityLevel | None = None


class RubricResponse(BaseModel):
    """A rubric version together with its criteria.

    The requirements are always included. ``RubricVersion.requirements`` is
    ``lazy="noload"``, so a response that omitted them would be
    indistinguishable from a rubric that has none.
    """

    rubric_version_id: uuid.UUID
    job_id: uuid.UUID
    version: int = Field(description="Monotonic per job, starting at 1.")
    status: RubricStatus = Field(description='"draft", "approved", or "superseded".')
    content_hash: str | None = Field(
        default=None,
        description="Fingerprint of the frozen criteria. Null while the rubric is a draft.",
    )
    must_have_fail_cap: int = Field(
        description="Ceiling applied to a candidate who fails any must-have.",
    )
    aggregation_formula_version: str
    source: RubricSource
    requirements: list[RequirementResponse] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Score preview                                                                #
# --------------------------------------------------------------------------- #


class VerdictInput(BaseModel):
    """One hypothetical judgement supplied by the caller.

    These verdicts are synthetic. The preview endpoint exists so a recruiter can
    see how the rubric behaves before any candidate is run against it, so the
    caller states the outcome rather than the system deriving it.
    """

    requirement_id: uuid.UUID
    verdict: PreviewVerdict


class ScorePreviewRequest(BaseModel):
    """Payload for previewing a rubric's score under hypothetical verdicts.

    The list is bounded by ``MAX_REQUIREMENTS`` because a rubric cannot hold
    more criteria than that, so a longer list can only be wrong.
    """

    verdicts: list[VerdictInput] = Field(min_length=1, max_length=MAX_REQUIREMENTS)


class ContributionResponse(BaseModel):
    """What one requirement contributed to the previewed score."""

    requirement_id: uuid.UUID
    ordinal: int
    text: str
    weight: Decimal
    is_must_have: bool
    verdict: PreviewVerdict
    points: Decimal = Field(description="Weight times verdict credit, on the 0-100 scale.")


class ScorePreviewResponse(BaseModel):
    """The previewed score with the full breakdown behind it.

    ``raw_score`` is published alongside ``score`` so a capped result stays
    explainable: without it, a candidate held down by a failed must-have is
    indistinguishable from one who simply matched poorly.
    """

    score: Decimal = Field(description="Final score, 0-100, after any must-have cap.")
    raw_score: Decimal = Field(description="Score before the cap was applied.")
    formula_version: str
    must_have_failed: bool
    cap_applied: bool = Field(
        description="Whether the cap actually lowered the score, not merely whether "
        "a must-have failed.",
    )
    failed_must_have_ids: list[uuid.UUID] = Field(default_factory=list)
    contributions: list[ContributionResponse] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Starter templates                                                            #
# --------------------------------------------------------------------------- #


class TemplateSummary(BaseModel):
    """One catalogue entry, without its criteria.

    The listing omits the requirements deliberately. A picker needs the label and
    the size of what it is offering, not seven paragraphs per entry, and the full
    set is one request away.
    """

    key: str = Field(description="URL-safe slug; the path segment used to fetch the template.")
    name: str
    role_family: str = Field(description="Broad grouping used to organize the picker.")
    requirement_count: int = Field(description="How many criteria instantiating this would add.")


class TemplateListResponse(BaseModel):
    """The whole shipped catalogue, ordered by display name."""

    templates: list[TemplateSummary] = Field(default_factory=list)


class TemplateDetailResponse(BaseModel):
    """One template with the criteria it would seed a draft with.

    The weights published here are the template's *relative* weights, exactly as
    a caller would submit them. They are not normalized: normalization happens
    when a draft is created, and publishing a normalized figure would imply the
    template had already been apportioned against a specific set.
    """

    key: str
    name: str
    role_family: str
    requirements: list[RequirementInput] = Field(default_factory=list)


class TemplateInstantiateRequest(BaseModel):
    """Payload for seeding a new draft rubric from a template."""

    job_id: uuid.UUID = Field(description="Job the new draft is authored against.")
