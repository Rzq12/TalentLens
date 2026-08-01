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

RequirementCategory = Literal[
    "skill",
    "experience",
    "education",
    "certification",
    "language",
    "other",
]
RubricSource = Literal["manual", "extracted", "template"]


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
    min_seniority: str | None = Field(
        default=None,
        max_length=32,
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
        description="The replacement criteria, in display order.",
    )


class RequirementResponse(BaseModel):
    """One stored criterion, with the weight the rubric will actually use."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    ordinal: int = Field(description="Display order within the rubric, from 0.")
    text: str
    category: str
    is_must_have: bool
    weight: Decimal = Field(description="Normalized weight; the set sums to exactly 1.0000.")
    min_years: Decimal | None = None
    min_seniority: str | None = None


class RubricResponse(BaseModel):
    """A rubric version together with its criteria.

    The requirements are always included. ``RubricVersion.requirements`` is
    ``lazy="noload"``, so a response that omitted them would be
    indistinguishable from a rubric that has none.
    """

    rubric_version_id: uuid.UUID
    job_id: uuid.UUID
    version: int = Field(description="Monotonic per job, starting at 1.")
    status: str = Field(description='"draft", "approved", or "superseded".')
    content_hash: str | None = Field(
        default=None,
        description="Fingerprint of the frozen criteria. Null while the rubric is a draft.",
    )
    must_have_fail_cap: int = Field(
        description="Ceiling applied to a candidate who fails any must-have.",
    )
    aggregation_formula_version: str
    source: str
    requirements: list[RequirementResponse] = Field(default_factory=list)
