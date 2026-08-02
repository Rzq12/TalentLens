"""The starter rubric template catalogue.

A template is a named set of criteria for a role family that a recruiter
instantiates and then edits. It is application-authored data, not tenant data:
the catalogue ships with the build as validated ``RequirementInput`` instances,
so a malformed template is an import-time failure rather than a 500 on the first
request that touches it.

What these tests pin is that the catalogue is well-formed, carries no protected
characteristic, and that instantiating one yields a *draft* a human must still
approve. What they cannot pin is whether a template's criteria are the right
ones for a role — that is a recruiting judgement, and it is the reason the
result is editable rather than authoritative.
"""

from __future__ import annotations

import re
from typing import get_args

import pytest

from app.exceptions import ResourceNotFoundError
from app.schemas.rubric import (
    MAX_REQUIREMENTS,
    RequirementCategory,
    RequirementInput,
    SeniorityLevel,
)
from app.services.rubric_templates import (
    RUBRIC_TEMPLATES,
    RubricTemplate,
    get_template,
    list_templates,
)

#: Patterns that must not match a shipped criterion. A rubric drives an
#: automated ranking, so a template that mentioned any of these would encode a
#: protected characteristic into every job that instantiated it.
#:
#: These are regexes rather than substrings because a bare substring test is
#: wrong in both directions. `"age"` inside `"language"` and `"male"` inside
#: `"female"` are false alarms that would force the catalogue to avoid ordinary
#: vocabulary, whereas `pregnan` and `disab` are deliberate stems that must
#: still catch every inflection. Anchoring each term explicitly keeps the check
#: precise about what it is actually prohibiting.
_PROHIBITED = (
    r"\bages?\b",
    r"\baged\b",
    r"\bmales?\b",
    r"\bfemales?\b",
    r"\bgender",
    r"\bmarried\b",
    r"\bmarital\b",
    r"\breligio",
    r"\bnationalit",
    r"\brace\b",
    r"\bethnic",
    r"\bpregnan",
    r"\bdisab",
    r"\bphotos?\b",
    r"\bphotograph",
    r"\bnative speaker",
)


# --- Catalogue shape --------------------------------------------------------


def test_the_catalogue_is_not_empty_so_a_recruiter_has_somewhere_to_start():
    assert RUBRIC_TEMPLATES


def test_every_template_key_is_a_url_safe_slug():
    # The key becomes a path segment. A key needing escaping would make the
    # route work in a test and fail behind a proxy that normalizes the path.
    for key in RUBRIC_TEMPLATES:
        assert re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", key), key


def test_each_template_key_matches_the_key_recorded_on_the_template():
    # The mapping key and the template's own `key` are two sources of truth for
    # the same identifier; a mismatch would make `get_template` and the listing
    # disagree about what a template is called.
    for key, template in RUBRIC_TEMPLATES.items():
        assert template.key == key


def test_every_template_carries_a_human_readable_name_and_role_family():
    for template in RUBRIC_TEMPLATES.values():
        assert template.name.strip()
        assert template.role_family.strip()


def test_no_two_templates_share_a_display_name():
    names = [t.name for t in RUBRIC_TEMPLATES.values()]

    assert len(names) == len(set(names))


# --- Requirement validity ---------------------------------------------------


def test_every_requirement_in_every_template_is_a_validated_requirement_input():
    # Constructing these at import time is what makes a malformed template a
    # startup failure instead of a 500 on the first request to touch it.
    for template in RUBRIC_TEMPLATES.values():
        for requirement in template.requirements:
            assert isinstance(requirement, RequirementInput)


def test_every_template_has_at_least_one_requirement():
    # `create_draft_rubric` raises on an empty set, so an empty template would
    # be an instantiable catalogue entry that cannot produce a rubric.
    for template in RUBRIC_TEMPLATES.values():
        assert template.requirements


def test_no_template_exceeds_the_schema_requirement_ceiling():
    for template in RUBRIC_TEMPLATES.values():
        assert len(template.requirements) <= MAX_REQUIREMENTS


def test_every_template_has_at_least_one_must_have():
    # A rubric with no must-have can never apply its fail cap, which makes the
    # cap column dead weight and the ranking purely additive.
    for template in RUBRIC_TEMPLATES.values():
        assert any(r.is_must_have for r in template.requirements)


def test_no_template_is_entirely_must_haves():
    # If everything is mandatory, every imperfect candidate is capped and the
    # ranking collapses to a pass/fail gate.
    for template in RUBRIC_TEMPLATES.values():
        assert not all(r.is_must_have for r in template.requirements)


def test_no_two_requirements_within_a_template_repeat_the_same_text():
    # A duplicated criterion is double-weighted without saying so.
    for template in RUBRIC_TEMPLATES.values():
        texts = [r.text.casefold() for r in template.requirements]
        assert len(texts) == len(set(texts)), template.key


def test_every_category_used_is_a_member_of_the_schema_literal():
    allowed = set(get_args(RequirementCategory))

    for template in RUBRIC_TEMPLATES.values():
        for requirement in template.requirements:
            assert requirement.category in allowed


def test_every_seniority_floor_used_is_a_member_of_the_schema_literal():
    allowed = set(get_args(SeniorityLevel))

    for template in RUBRIC_TEMPLATES.values():
        for requirement in template.requirements:
            if requirement.min_seniority is not None:
                assert requirement.min_seniority in allowed


def test_every_weight_is_positive_so_no_criterion_ships_unscored():
    # Weight 0 is accepted by the schema but means the criterion cannot affect
    # the score. Shipping one would read as a criterion and behave as decoration.
    for template in RUBRIC_TEMPLATES.values():
        for requirement in template.requirements:
            assert requirement.weight > 0


# --- Fairness ---------------------------------------------------------------


@pytest.mark.parametrize("pattern", _PROHIBITED)
def test_no_shipped_criterion_mentions_a_protected_characteristic(pattern: str):
    for template in RUBRIC_TEMPLATES.values():
        for requirement in template.requirements:
            assert not re.search(
                pattern, requirement.text.casefold()
            ), f"{template.key}: {requirement.text!r}"


@pytest.mark.parametrize(
    "text",
    [
        "Under 30 years of age",
        "Aged 25 to 35",
        "Male candidates only",
        "Female applicants preferred",
        "Gender-balanced team fit",
        "Must be married",
        "Marital status: single",
        "Shares the company religion",
        "Indonesian nationality required",
        "Of the appropriate race",
        "Ethnic background",
        "Not currently pregnant",
        "No disability",
        "Attach a recent photo",
        "Include a photograph",
        "Native speaker of English",
    ],
)
def test_the_fairness_patterns_catch_the_phrasings_they_exist_to_catch(text: str):
    # The prohibition list is only as good as its patterns. Without this, a
    # typo in one regex would silently pass the catalogue forever, and the
    # fairness test above would read as protection it was not providing.
    assert any(re.search(pattern, text.casefold()) for pattern in _PROHIBITED), text


@pytest.mark.parametrize(
    "text",
    [
        "Communicates fluently in the language the support queue is served in",
        "Has managed a small team",
        "Owns the release package end to end",
        "Coverage of the average case",
    ],
)
def test_the_fairness_patterns_do_not_fire_on_ordinary_vocabulary(text: str):
    # `age` inside `language`, `manager`, `package`, and `average` is why the
    # patterns are word-anchored rather than plain substrings.
    assert not any(re.search(pattern, text.casefold()) for pattern in _PROHIBITED), text


# --- Lookup -----------------------------------------------------------------


def test_a_known_key_returns_the_template():
    key = next(iter(RUBRIC_TEMPLATES))

    assert get_template(key).key == key


def test_an_unknown_key_raises_not_found_rather_than_key_error():
    # A bare KeyError would surface as a 500. The catalogue is a lookup over
    # caller-supplied input, so a miss is a 404.
    with pytest.raises(ResourceNotFoundError):
        get_template("no-such-template")


def test_the_not_found_message_does_not_echo_the_requested_key():
    # The key arrives from the URL and the message reaches the logs and the
    # response body. Echoing it back is a reflection primitive.
    with pytest.raises(ResourceNotFoundError) as excinfo:
        get_template("<script>alert(1)</script>")

    assert "<script>" not in str(excinfo.value)


def test_lookup_is_case_sensitive_so_one_key_names_one_template():
    key = next(iter(RUBRIC_TEMPLATES))

    with pytest.raises(ResourceNotFoundError):
        get_template(key.upper())


# --- Listing ----------------------------------------------------------------


def test_the_listing_covers_every_template_in_the_catalogue():
    listed = list_templates()

    assert {t.key for t in listed} == set(RUBRIC_TEMPLATES)


def test_the_listing_is_ordered_by_name_so_the_ui_is_stable():
    # Dict insertion order is an implementation detail; a UI that renders the
    # listing would reorder itself whenever a template was added mid-file.
    listed = list_templates()

    assert [t.name for t in listed] == sorted(t.name for t in listed)


def test_the_listing_returns_the_templates_themselves_not_copies_of_the_requirements():
    # Cheap guard against a listing that rebuilds requirements and drops fields.
    for template in list_templates():
        assert template.requirements == RUBRIC_TEMPLATES[template.key].requirements


# --- Immutability -----------------------------------------------------------


def test_a_template_cannot_be_mutated_after_import():
    # The catalogue is process-wide. If one request could edit a template, the
    # edit would leak into every later request and across tenants.
    template = get_template(next(iter(RUBRIC_TEMPLATES)))

    with pytest.raises((AttributeError, TypeError, ValueError)):
        template.name = "mutated"  # type: ignore[misc]


def test_a_templates_requirement_sequence_cannot_be_appended_to():
    template = get_template(next(iter(RUBRIC_TEMPLATES)))

    with pytest.raises(AttributeError):
        template.requirements.append(  # type: ignore[attr-defined]
            RequirementInput(text="Injected.", category="skill", is_must_have=False, weight=1)
        )


def test_the_template_type_is_exported_for_annotation():
    assert isinstance(get_template(next(iter(RUBRIC_TEMPLATES))), RubricTemplate)
