"""Starter rubric templates, one per role family.

A recruiter opening an empty rubric editor has to invent a scoring scheme from
nothing, and what they invent under time pressure is where accidental bias gets
in. A template gives them a defensible starting point they then edit.

These are **application data, not tenant data**. They are constructed at import
time as validated :class:`~app.schemas.rubric.RequirementInput` instances, so a
malformed template is a startup failure rather than a 500 on the first request
that touches it. Nothing here is persisted: instantiating a template produces a
*draft* rubric through the ordinary authoring path, and a human still approves it
before any candidate is scored against it.

Two rules govern what may be written here.

* **No criterion may reference a protected characteristic.** A rubric drives an
  automated ranking, so a term shipped here would be applied to every job that
  started from this template. A test enumerates the prohibited terms.
* **No template is entirely must-haves.** A rubric where everything is mandatory
  degenerates into a pass/fail gate, because the fail cap applies to every
  imperfect candidate and the weights stop discriminating.

Whether a template's criteria are the *right* ones for a role is a recruiting
judgement that no test can settle. That is precisely why the result is editable.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from app.exceptions import ResourceNotFoundError
from app.logging import get_logger
from app.schemas.rubric import RequirementInput

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class RubricTemplate:
    """A named starting point for a rubric.

    Attributes:
        key: URL-safe slug. It becomes a path segment, so it stays lowercase and
            hyphenated rather than anything needing escaping.
        name: Display label, unique across the catalogue.
        role_family: Broad grouping used to organize the picker.
        requirements: The criteria, in presentation order. A tuple rather than a
            list because the catalogue is process-wide: a mutable sequence here
            would let one request's edit leak into every later request, and
            across tenants.
    """

    key: str
    name: str
    role_family: str
    requirements: tuple[RequirementInput, ...]


_BACKEND_ENGINEER = RubricTemplate(
    key="backend-engineer",
    name="Backend Engineer",
    role_family="Engineering",
    requirements=(
        RequirementInput(
            text="3+ years building and operating production HTTP services",
            category="experience",
            is_must_have=True,
            weight=5,
            min_years=3,
            min_seniority="mid",
        ),
        RequirementInput(
            text="Proficient in at least one strongly typed server-side ecosystem",
            category="skill",
            is_must_have=True,
            weight=4,
        ),
        RequirementInput(
            text="Designs relational schemas and writes efficient SQL, including index selection",
            category="skill",
            weight=4,
        ),
        RequirementInput(
            text="Writes automated tests as part of normal delivery, not as an afterthought",
            category="skill",
            weight=3,
        ),
        RequirementInput(
            text="Instruments services with structured logs and metrics for production debugging",
            category="skill",
            weight=3,
        ),
        RequirementInput(
            text="Familiar with containerized deployment and CI pipelines",
            category="skill",
            weight=2,
        ),
        RequirementInput(
            text="Degree in computer science, or equivalent demonstrated practical work",
            category="education",
            weight=1,
        ),
    ),
)

_DATA_SCIENTIST = RubricTemplate(
    key="data-scientist",
    name="Data Scientist",
    role_family="Data and Analytics",
    requirements=(
        RequirementInput(
            text="2+ years delivering models that reached production use",
            category="experience",
            is_must_have=True,
            weight=5,
            min_years=2,
        ),
        RequirementInput(
            text="Fluent in Python and its numerical and modelling libraries",
            category="skill",
            is_must_have=True,
            weight=4,
        ),
        RequirementInput(
            text="Frames a business question as a measurable modelling problem",
            category="skill",
            weight=4,
        ),
        RequirementInput(
            text="Chooses and defends evaluation metrics appropriate to the decision at hand",
            category="skill",
            weight=4,
        ),
        RequirementInput(
            text="Writes SQL against large analytical tables",
            category="skill",
            weight=3,
        ),
        RequirementInput(
            text="Communicates uncertainty and limitations to non-specialist readers",
            category="skill",
            weight=3,
        ),
        RequirementInput(
            text="Quantitative degree, or a portfolio of equivalent applied work",
            category="education",
            weight=2,
        ),
    ),
)

_PRODUCT_MANAGER = RubricTemplate(
    key="product-manager",
    name="Product Manager",
    role_family="Product",
    requirements=(
        RequirementInput(
            text="3+ years owning a product area end to end, from discovery through launch",
            category="experience",
            is_must_have=True,
            weight=5,
            min_years=3,
            min_seniority="mid",
        ),
        RequirementInput(
            text="Turns qualitative user research into a prioritized, defensible roadmap",
            category="skill",
            is_must_have=True,
            weight=4,
        ),
        RequirementInput(
            text="Defines success metrics before a launch and reports against them after",
            category="skill",
            weight=4,
        ),
        RequirementInput(
            text="Writes specifications engineers can build from without re-interviewing them",
            category="skill",
            weight=4,
        ),
        RequirementInput(
            text="Negotiates scope with engineering and design without escalating every trade-off",
            category="skill",
            weight=3,
        ),
        RequirementInput(
            text="Comfortable querying product analytics directly rather than requesting every cut",
            category="skill",
            weight=2,
        ),
    ),
)

_DEVOPS_ENGINEER = RubricTemplate(
    key="devops-engineer",
    name="DevOps Engineer",
    role_family="Engineering",
    requirements=(
        RequirementInput(
            text="3+ years operating production infrastructure with an on-call responsibility",
            category="experience",
            is_must_have=True,
            weight=5,
            min_years=3,
            min_seniority="mid",
        ),
        RequirementInput(
            text="Provisions infrastructure declaratively rather than by console clicks",
            category="skill",
            is_must_have=True,
            weight=4,
        ),
        RequirementInput(
            text="Builds and maintains CI/CD pipelines including rollback paths",
            category="skill",
            weight=4,
        ),
        RequirementInput(
            text="Operates container orchestration in production, not only in a local cluster",
            category="skill",
            weight=4,
        ),
        RequirementInput(
            text="Designs alerting that distinguishes a page from a ticket",
            category="skill",
            weight=3,
        ),
        RequirementInput(
            text="Applies least-privilege access and secret management as a default",
            category="skill",
            weight=3,
        ),
        RequirementInput(
            text="Scripts routine operational work instead of repeating it by hand",
            category="skill",
            weight=2,
        ),
    ),
)

_UX_DESIGNER = RubricTemplate(
    key="ux-designer",
    name="UX Designer",
    role_family="Design",
    requirements=(
        RequirementInput(
            text="Portfolio showing shipped work with the reasoning behind each decision",
            category="experience",
            is_must_have=True,
            weight=5,
        ),
        RequirementInput(
            text="Plans and runs user research, then acts on what it says over what was hoped",
            category="skill",
            is_must_have=True,
            weight=4,
        ),
        RequirementInput(
            text="Works fluently in a collaborative interface design tool",
            category="skill",
            weight=3,
        ),
        RequirementInput(
            text="Builds and maintains a component library rather than one-off screens",
            category="skill",
            weight=3,
        ),
        RequirementInput(
            text="Designs to accessibility guidelines as a requirement, not a later pass",
            category="skill",
            weight=4,
        ),
        RequirementInput(
            text="Hands off to engineering with states, edge cases, and empty views specified",
            category="skill",
            weight=3,
        ),
    ),
)

_SALES_REPRESENTATIVE = RubricTemplate(
    key="sales-representative",
    name="Sales Representative",
    role_family="Go to Market",
    requirements=(
        RequirementInput(
            text="2+ years carrying and meeting an individual revenue quota",
            category="experience",
            is_must_have=True,
            weight=5,
            min_years=2,
        ),
        RequirementInput(
            text="Runs a consultative discovery conversation rather than a feature recital",
            category="skill",
            is_must_have=True,
            weight=4,
        ),
        RequirementInput(
            text="Maintains an accurate pipeline in a CRM without being chased for it",
            category="skill",
            weight=3,
        ),
        RequirementInput(
            text="Negotiates commercial terms and closes without discounting reflexively",
            category="skill",
            weight=4,
        ),
        RequirementInput(
            text="Coordinates a multi-stakeholder buying process across a long cycle",
            category="skill",
            weight=3,
        ),
        RequirementInput(
            text="Writes follow-up correspondence that advances the deal on its own",
            category="skill",
            weight=2,
        ),
    ),
)

_CUSTOMER_SUPPORT = RubricTemplate(
    key="customer-support-specialist",
    name="Customer Support Specialist",
    role_family="Customer Operations",
    requirements=(
        RequirementInput(
            text="1+ years in a customer-facing support role with a resolution target",
            category="experience",
            is_must_have=True,
            weight=4,
            min_years=1,
        ),
        RequirementInput(
            text="Writes clearly and calmly to a frustrated correspondent",
            category="skill",
            is_must_have=True,
            weight=4,
        ),
        RequirementInput(
            text="Reproduces a reported problem before escalating it",
            category="skill",
            weight=4,
        ),
        RequirementInput(
            text="Works a ticketing system to an SLA without losing the thread of a case",
            category="skill",
            weight=3,
        ),
        RequirementInput(
            text="Turns repeated questions into documentation instead of repeated answers",
            category="skill",
            weight=3,
        ),
        RequirementInput(
            text="Communicates fluently in the language the support queue is served in",
            category="language",
            weight=3,
        ),
    ),
)

#: The shipped catalogue, keyed by slug. Wrapped in a ``MappingProxyType`` so a
#: caller cannot add, replace, or delete an entry at runtime — the mapping is
#: process-wide, and a mutation would outlive the request that made it.
RUBRIC_TEMPLATES: Mapping[str, RubricTemplate] = MappingProxyType(
    {
        template.key: template
        for template in (
            _BACKEND_ENGINEER,
            _CUSTOMER_SUPPORT,
            _DATA_SCIENTIST,
            _DEVOPS_ENGINEER,
            _PRODUCT_MANAGER,
            _SALES_REPRESENTATIVE,
            _UX_DESIGNER,
        )
    }
)


def get_template(key: str) -> RubricTemplate:
    """Look up one template by its slug.

    Args:
        key: The template slug, exactly as listed. Matching is case-sensitive so
            that one key names one template and a listing cannot show two
            entries that resolve to the same place.

    Returns:
        The matching template.

    Raises:
        ResourceNotFoundError: If no template carries this key. The message
            names no key: this argument arrives from the URL and the message
            reaches both the logs and the response body, so echoing it back
            would make the endpoint a reflection primitive.
    """
    try:
        return RUBRIC_TEMPLATES[key]
    except KeyError as exc:
        logger.info("rubric_template_not_found", known_count=len(RUBRIC_TEMPLATES))
        raise ResourceNotFoundError("No rubric template exists with that key.") from exc


def list_templates() -> tuple[RubricTemplate, ...]:
    """Return every shipped template, ordered by display name.

    Sorting here rather than relying on definition order means adding a template
    mid-file cannot silently reorder an existing picker.

    Returns:
        All templates, sorted by ``name``.
    """
    return tuple(sorted(RUBRIC_TEMPLATES.values(), key=lambda template: template.name))


__all__ = [
    "RUBRIC_TEMPLATES",
    "RubricTemplate",
    "get_template",
    "list_templates",
]
