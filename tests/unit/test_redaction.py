"""Blind-screening redaction tests (FR-12).

The critical property is not "redaction happens" but "no identity signal
survives serialization". The leakage test therefore inspects the payload the
way a provider would see it: fully serialized, after any JSON encoding.
"""

from __future__ import annotations

import json

import pytest

from app.services.redaction import (
    PLACEHOLDER_AGE,
    PLACEHOLDER_CONTACT,
    PLACEHOLDER_IDENTITY,
    PLACEHOLDER_LOCATION,
    PLACEHOLDER_NAME,
    assert_no_identity_leakage,
    redact_for_blind_screening,
)

CANDIDATE = "Budi Santoso"

SAMPLE_RESUME = (
    "Budi Santoso\n"
    "budi.santoso@gmail.com | +62 812-3456-7890\n"
    "Jl. Jend. Sudirman No. 45, Jakarta\n"
    "Age: 29 | Indonesian | Male\n"
    "Education: Universitas Indonesia, BSc Computer Science\n"
    "Experience: Senior Backend Engineer at Tokopedia (2019 - 2023)\n"
    "Skills: Python, FastAPI, PostgreSQL, Redis\n"
)


def test_name_is_redacted_everywhere_it_appears():
    result = redact_for_blind_screening(SAMPLE_RESUME, candidate_name=CANDIDATE)
    assert CANDIDATE.lower() not in result.text.lower()
    assert PLACEHOLDER_NAME in result.text


def test_email_and_phone_are_redacted():
    result = redact_for_blind_screening(SAMPLE_RESUME, candidate_name=CANDIDATE)
    assert "budi.santoso@gmail.com" not in result.text
    assert "+62 812-3456-7890" not in result.text
    assert PLACEHOLDER_CONTACT in result.text


def test_address_is_redacted():
    result = redact_for_blind_screening(SAMPLE_RESUME, candidate_name=CANDIDATE)
    assert "Jl. Jend. Sudirman No. 45" not in result.text
    assert PLACEHOLDER_LOCATION in result.text


def test_age_nationality_and_gender_are_redacted():
    result = redact_for_blind_screening(SAMPLE_RESUME, candidate_name=CANDIDATE)
    assert "Age: 29" not in result.text
    assert "Indonesian" not in result.text
    assert "Male" not in result.text
    assert PLACEHOLDER_AGE in result.text
    assert PLACEHOLDER_IDENTITY in result.text


def test_prestige_school_is_redacted():
    result = redact_for_blind_screening(SAMPLE_RESUME, candidate_name=CANDIDATE)
    assert "Universitas Indonesia" not in result.text


def test_employment_dates_and_skills_survive():
    """Over-redaction destroys evidence — these must survive."""
    result = redact_for_blind_screening(SAMPLE_RESUME, candidate_name=CANDIDATE)
    assert "2019 - 2023" in result.text
    assert "Senior Backend Engineer" in result.text
    assert "Python, FastAPI, PostgreSQL" in result.text


def test_offsets_remain_valid_after_redaction():
    """Placeholders are same-length, so offsets computed on the redacted text
    index back into it exactly — the contract the evidence layer relies on."""
    result = redact_for_blind_screening(SAMPLE_RESUME, candidate_name=CANDIDATE)
    assert len(result.text) == len(SAMPLE_RESUME)
    # The skills line is untouched; its offset must be identical in both.
    assert result.text.find("Skills:") == SAMPLE_RESUME.find("Skills:")


def test_findings_report_is_serializable():
    result = redact_for_blind_screening(SAMPLE_RESUME, candidate_name=CANDIDATE)
    report = result.to_report()
    encoded = json.dumps(report)
    assert report["redacted_chars"] > 0
    kinds = {f["kind"] for f in report["findings"]}
    assert {"candidate_name", "email", "phone", "age"} <= kinds


def test_clean_text_is_returned_unchanged():
    clean = "Built a FastAPI service with PostgreSQL and Redis."
    result = redact_for_blind_screening(clean, candidate_name=CANDIDATE)
    assert result.text == clean
    assert result.redacted_chars == 0
    assert result.findings == ()


def test_empty_text_is_a_no_op():
    result = redact_for_blind_screening("", candidate_name=CANDIDATE)
    assert result.text == ""
    assert result.redacted_chars == 0


def test_leakage_guard_accepts_redacted_payload():
    """The serialized payload of a redacted result must pass the guard."""
    result = redact_for_blind_screening(SAMPLE_RESUME, candidate_name=CANDIDATE)
    payload = json.dumps({"resume_text": result.text})
    assert_no_identity_leakage(payload, candidate_name=CANDIDATE)  # must not raise


def test_leakage_guard_rejects_raw_payload():
    """The guard is the enforcement point: raw PII in a serialized payload
    must fail loudly, not silently reach a provider."""
    payload = json.dumps({"resume_text": SAMPLE_RESUME})
    with pytest.raises(ValueError, match="candidate_name"):
        assert_no_identity_leakage(payload, candidate_name=CANDIDATE)


def test_leakage_guard_rejects_email_in_payload():
    payload = json.dumps({"contact": "someone@company.com"})
    with pytest.raises(ValueError, match="email"):
        assert_no_identity_leakage(payload)


def test_leakage_guard_rejects_age_marker_in_payload():
    payload = json.dumps({"profile": "Age: 34, 10 years experience"})
    with pytest.raises(ValueError, match="age_marker"):
        assert_no_identity_leakage(payload)


def test_leakage_guard_ignores_non_pii_content():
    payload = json.dumps({"skills": ["Python", "FastAPI"], "score": 82})
    assert_no_identity_leakage(payload)  # must not raise
