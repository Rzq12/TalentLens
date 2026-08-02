"""Tests for the Phase 4 screening-run ORM models.

These four tables are the audit trail of a hiring decision, so their column
shapes are part of the contract rather than an implementation detail. The
schema is specified in ARCHITECTURE.md section 6.6, and three properties in it
are load-bearing:

* ``unique(run_id, candidate_id)`` — a candidate is scored once per run. Without
  it, a retried task silently produces two scores and the ranking becomes
  ambiguous.
* ``unique(score_id, requirement_id)`` — one verdict per requirement per score.
  The aggregator already rejects duplicate verdicts; this is the same invariant
  enforced one layer down, where a retry actually happens.
* ``retrieved_chunk_ids`` and ``verbatim_verified`` — the exposure record and
  the anti-hallucination gate. "Why did the model say that?" is unanswerable
  without the first, and a citation nobody checked is worse than no citation.

Money and score columns are ``numeric`` rather than float for the same reason
``Requirement.weight`` is: a stored score that does not reproduce exactly on
replay is not defensible in a hiring decision.

Every case reads table metadata or constructs objects in memory — no database.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import Boolean, Integer, Numeric, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

import app.models as models


def _unique_column_sets(table: object) -> set[tuple[str, ...]]:
    """Return the column-name tuples covered by each unique constraint."""
    return {
        tuple(sorted(column.name for column in constraint.columns))
        for constraint in table.constraints  # type: ignore[attr-defined]
        if isinstance(constraint, UniqueConstraint)
    }


# --- screening_runs ---------------------------------------------------------


def test_screening_run_table_is_named_and_tenant_scoped() -> None:
    """The table must exist and carry `tenant_id` as a non-null filter column."""
    table = models.ScreeningRun.__table__

    assert table.name == "screening_runs"
    assert table.columns["tenant_id"].nullable is False
    assert table.columns["tenant_id"].index is True


def test_screening_run_starts_queued() -> None:
    """A run is accepted before it executes, so `queued` is the only safe default.

    The admission endpoint answers 202 the moment the row exists. Defaulting to
    `running` would make a crashed-before-start run indistinguishable from one
    that is genuinely mid-flight.
    """
    column = models.ScreeningRun.__table__.columns["status"]

    assert column.default is not None
    assert column.default.arg == "queued"
    assert column.nullable is False


def test_screening_run_references_the_job_it_screens_for() -> None:
    """A run without its job cannot be resolved back to what was screened."""
    fk = next(iter(models.ScreeningRun.__table__.columns["job_id"].foreign_keys))

    assert fk.column.table.name == "jobs"
    assert fk.ondelete == "CASCADE"


def test_screening_run_pins_the_rubric_version_it_was_scored_against() -> None:
    """Scores are only interpretable against the criteria that produced them.

    The FK does not cascade: deleting a rubric version that scores reference
    would erase the basis of a decision already communicated to a candidate.
    """
    column = models.ScreeningRun.__table__.columns["rubric_version_id"]
    fk = next(iter(column.foreign_keys))

    assert fk.column.table.name == "rubric_versions"
    assert fk.ondelete == "RESTRICT"
    assert column.nullable is False


def test_screening_run_records_the_funnel_stage_counts_as_jsonb() -> None:
    """The funnel's call-reduction claim is unverifiable without per-stage counts."""
    column = models.ScreeningRun.__table__.columns["funnel_stage_counts"]

    assert isinstance(column.type, JSONB)


def test_screening_run_cost_is_an_exact_decimal() -> None:
    """Spend is money; `numeric(10,4)` per section 6.6, never a float."""
    column = models.ScreeningRun.__table__.columns["cost_usd"]

    assert isinstance(column.type, Numeric)
    assert column.type.precision == 10
    assert column.type.scale == 4


def test_screening_run_token_counters_are_bigint_and_start_at_zero() -> None:
    """A run that has spent nothing must read zero, not NULL.

    NULL would force every consumer of the ledger to special-case "not yet
    started" before summing, and one that forgets produces a NULL total.
    """
    table = models.ScreeningRun.__table__

    for name in (
        "total_input_tokens",
        "total_output_tokens",
        "cache_read_tokens",
        "cache_write_tokens",
    ):
        column = table.columns[name]
        assert column.nullable is False, name
        assert column.default is not None, name
        assert column.default.arg == 0, name


def test_screening_run_completion_columns_are_null_until_it_finishes() -> None:
    """A queued run has not started and has not completed."""
    table = models.ScreeningRun.__table__

    assert table.columns["started_at"].nullable is True
    assert table.columns["completed_at"].nullable is True


# --- candidate_scores ------------------------------------------------------


def test_candidate_score_table_is_named_and_tenant_scoped() -> None:
    """The table must exist and carry `tenant_id` as a non-null filter column."""
    table = models.CandidateScore.__table__

    assert table.name == "candidate_scores"
    assert table.columns["tenant_id"].nullable is False
    assert table.columns["tenant_id"].index is True


def test_candidate_score_is_unique_per_run_and_candidate() -> None:
    """A candidate is scored once per run.

    A retried run task that inserted a second row would leave two different
    ranks for one person, and the shortlist would depend on read order.
    """
    assert ("candidate_id", "run_id") in _unique_column_sets(
        models.CandidateScore.__table__
    )


def test_candidate_score_cascades_from_its_run() -> None:
    """A score has no meaning apart from the run that produced it."""
    fk = next(iter(models.CandidateScore.__table__.columns["run_id"].foreign_keys))

    assert fk.column.table.name == "screening_runs"
    assert fk.ondelete == "CASCADE"


def test_candidate_score_overall_is_numeric_five_two() -> None:
    """`numeric(5,2)` per section 6.6 — a replayed run must reproduce the digits."""
    column = models.CandidateScore.__table__.columns["overall_score"]

    assert isinstance(column.type, Numeric)
    assert column.type.precision == 5
    assert column.type.scale == 2


def test_candidate_score_raw_weighted_keeps_four_decimals() -> None:
    """The pre-cap weighted sum is what makes a capped score explainable."""
    column = models.CandidateScore.__table__.columns["raw_weighted"]

    assert isinstance(column.type, Numeric)
    assert column.type.precision == 5
    assert column.type.scale == 4


def test_candidate_score_cap_applied_is_null_when_no_cap_fired() -> None:
    """`cap_applied` distinguishes "capped to 40" from "genuinely scored 40".

    `aggregate_score()` already reports the cap separately from the must-have
    failure; storing NULL rather than 0 preserves that distinction on disk.
    """
    column = models.CandidateScore.__table__.columns["cap_applied"]

    assert column.nullable is True
    assert isinstance(column.type, Integer)


def test_candidate_score_records_the_formula_that_produced_it() -> None:
    """Provenance for replay: the same inputs must be re-derivable."""
    column = models.CandidateScore.__table__.columns["aggregation_formula_version"]

    assert column.nullable is False


def test_candidate_score_candidate_id_is_a_plain_uuid() -> None:
    """There is no `candidates` table in this repository yet.

    ARCHITECTURE.md section 6.6 declares `candidate_id` as a foreign key, but
    the `candidates` table it points at is unbuilt — the same situation as
    `Requirement.skill_id` and the ESCO taxonomy. Declaring the FK here would
    make the migration unrunnable, so the column is a plain uuid until the
    table exists.
    """
    column = models.CandidateScore.__table__.columns["candidate_id"]

    assert column.nullable is False
    assert not column.foreign_keys


# --- requirement_verdicts --------------------------------------------------


def test_requirement_verdict_table_is_named_and_tenant_scoped() -> None:
    """The table must exist and carry `tenant_id` as a non-null filter column."""
    table = models.RequirementVerdict.__table__

    assert table.name == "requirement_verdicts"
    assert table.columns["tenant_id"].nullable is False
    assert table.columns["tenant_id"].index is True


def test_requirement_verdict_is_unique_per_score_and_requirement() -> None:
    """One verdict per requirement per score.

    `aggregate_score()` raises on duplicate verdicts; this is the same
    invariant at the storage layer, which is where a retry actually races.
    """
    assert ("requirement_id", "score_id") in _unique_column_sets(
        models.RequirementVerdict.__table__
    )


def test_requirement_verdict_cascades_from_its_score() -> None:
    """A verdict is a component of one score and cannot outlive it."""
    fk = next(iter(models.RequirementVerdict.__table__.columns["score_id"].foreign_keys))

    assert fk.column.table.name == "candidate_scores"
    assert fk.ondelete == "CASCADE"


def test_requirement_verdict_pins_the_requirement_it_judged() -> None:
    """A verdict detached from its requirement text explains nothing."""
    fk = next(
        iter(models.RequirementVerdict.__table__.columns["requirement_id"].foreign_keys)
    )

    assert fk.column.table.name == "requirements"
    assert fk.ondelete == "RESTRICT"


def test_requirement_verdict_stores_the_chunks_the_judge_actually_saw() -> None:
    """`retrieved_chunk_ids` is the exposure record.

    Section 6.6: it is precisely the context the judge saw. Without it, "why
    did the model say that?" cannot be answered after the fact.
    """
    column = models.RequirementVerdict.__table__.columns["retrieved_chunk_ids"]

    assert isinstance(column.type, ARRAY)


def test_requirement_verdict_weight_and_contribution_are_exact_decimals() -> None:
    """The verdict's arithmetic must reproduce the score exactly."""
    table = models.RequirementVerdict.__table__

    weight = table.columns["weight_at_scoring"]
    assert isinstance(weight.type, Numeric)
    assert (weight.type.precision, weight.type.scale) == (5, 4)

    contribution = table.columns["contribution"]
    assert isinstance(contribution.type, Numeric)
    assert (contribution.type.precision, contribution.type.scale) == (6, 4)


def test_requirement_verdict_cache_key_holds_a_sha256_digest() -> None:
    """`result_cache_key` is the 64-hex key `verdict_cache_key()` derives."""
    column = models.RequirementVerdict.__table__.columns["result_cache_key"]

    assert column.type.length == 64


def test_requirement_verdict_records_whether_the_cache_was_hit() -> None:
    """The "re-run costs ~0 tokens" claim is measured from this column."""
    column = models.RequirementVerdict.__table__.columns["cache_hit"]

    assert isinstance(column.type, Boolean)
    assert column.nullable is False


def test_requirement_verdict_override_columns_are_null_until_a_human_acts() -> None:
    """A human override is recorded beside the model's verdict, never over it.

    The system never rejects a candidate; a recruiter can overrule any verdict.
    Overwriting `verdict` in place would destroy the evidence that the model and
    the human disagreed, which is exactly what an audit needs to see.
    """
    table = models.RequirementVerdict.__table__

    for name in ("overridden_by", "override_verdict", "override_reason", "overridden_at"):
        assert table.columns[name].nullable is True, name


# --- evidence_spans --------------------------------------------------------


def test_evidence_span_table_is_named_and_tenant_scoped() -> None:
    """The table must exist and carry `tenant_id` as a non-null filter column."""
    table = models.EvidenceSpanRecord.__table__

    assert table.name == "evidence_spans"
    assert table.columns["tenant_id"].nullable is False
    assert table.columns["tenant_id"].index is True


def test_evidence_span_verdict_id_is_nullable() -> None:
    """A span can be retrieved and verified before any verdict cites it.

    Section 6.6 declares `verdict_id fk null`. Requiring it would force the
    pipeline to invent a verdict before it has judged anything.
    """
    assert models.EvidenceSpanRecord.__table__.columns["verdict_id"].nullable is True


def test_evidence_span_cascades_from_its_verdict() -> None:
    """Deleting a verdict must not leave orphan citations behind."""
    fk = next(iter(models.EvidenceSpanRecord.__table__.columns["verdict_id"].foreign_keys))

    assert fk.column.table.name == "requirement_verdicts"
    assert fk.ondelete == "CASCADE"


def test_evidence_span_anchors_to_the_parse_that_produced_the_offsets() -> None:
    """Offsets are only valid against the resume version they were taken from.

    A re-parse under a newer parser is a new `resume_versions` row precisely so
    that older offsets stay attributable. The FK restricts deletion for the same
    reason: the span would silently point into a different text.
    """
    column = models.EvidenceSpanRecord.__table__.columns["resume_version_id"]
    fk = next(iter(column.foreign_keys))

    assert fk.column.table.name == "resume_versions"
    assert fk.ondelete == "RESTRICT"
    assert column.nullable is False


def test_evidence_span_carries_exact_character_offsets() -> None:
    """`text[start_char:end_char]` is the check `verify_evidence_span()` runs.

    Both offsets are required: a span with only a start is not checkable, and an
    unverifiable citation is the failure mode this column set exists to prevent.
    """
    table = models.EvidenceSpanRecord.__table__

    assert table.columns["start_char"].nullable is False
    assert table.columns["end_char"].nullable is False
    assert isinstance(table.columns["start_char"].type, Integer)
    assert isinstance(table.columns["end_char"].type, Integer)


def test_evidence_span_verbatim_flag_defaults_to_unverified() -> None:
    """An unchecked citation must never read as verified.

    Defaulting to True would mean a span inserted before the check ran claims a
    guarantee nobody established — the anti-hallucination gate held open.
    """
    column = models.EvidenceSpanRecord.__table__.columns["verbatim_verified"]

    assert isinstance(column.type, Boolean)
    assert column.nullable is False
    assert column.default is not None
    assert column.default.arg is False


# --- construction ----------------------------------------------------------


def test_a_screening_run_accepts_the_fields_the_admission_endpoint_supplies() -> None:
    """The row the endpoint inserts round-trips onto the instance."""
    run = models.ScreeningRun(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        job_id=uuid.uuid4(),
        rubric_version_id=uuid.uuid4(),
        triggered_by=uuid.uuid4(),
        mode="interactive",
        candidate_count=3,
    )

    assert run.mode == "interactive"
    assert run.candidate_count == 3


def test_a_candidate_score_accepts_exact_decimals() -> None:
    """Score and pre-cap weighted sum round-trip as exact Decimals."""
    score = models.CandidateScore(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        candidate_id=uuid.uuid4(),
        overall_score=Decimal("40.00"),
        raw_weighted=Decimal("0.8125"),
        cap_applied=40,
        rank=1,
        aggregation_formula_version="v1",
    )

    assert score.overall_score == Decimal("40.00")
    assert score.raw_weighted == Decimal("0.8125")
    assert score.cap_applied == 40
