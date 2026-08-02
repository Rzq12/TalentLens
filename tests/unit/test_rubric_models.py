"""Tests for the Phase 3 rubric ORM models.

A rubric is the artifact a human approves, and every later score is attributed
to the version it was computed against. That makes the column shapes here part
of the audit contract, not an implementation detail:

* ``weight`` must be ``numeric(5,4)`` — normalized weights sum to exactly 1.0,
  so the scale has to hold four decimal places without silent rounding.
* ``content_hash`` is the verdict cache key, so it must be a fixed 64-character
  column matching a SHA-256 hex digest.
* ``unique(job_id, version)`` is what makes "mint version N+1" well defined.

Every case constructs objects or reads table metadata in memory — no database.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import Numeric, UniqueConstraint

import app.models as models


def test_rubric_version_table_is_named_and_tenant_scoped() -> None:
    """The table must exist and carry `tenant_id` as a non-null filter column."""
    table = models.RubricVersion.__table__

    assert table.name == "rubric_versions"
    assert table.columns["tenant_id"].nullable is False


def test_rubric_version_is_unique_per_job_and_version() -> None:
    """`unique(job_id, version)` is what makes minting version N+1 well defined.

    Without it, two concurrent approvals could both create version 2 and a
    prior score would become ambiguous about which criteria produced it.
    """
    constraints = [
        c
        for c in models.RubricVersion.__table__.constraints
        if isinstance(c, UniqueConstraint)
    ]
    column_sets = {tuple(sorted(col.name for col in con.columns)) for con in constraints}

    assert ("job_id", "version") in column_sets


def test_rubric_version_content_hash_holds_a_sha256_digest() -> None:
    """`content_hash` is the verdict cache key, so it must fit 64 hex chars."""
    column = models.RubricVersion.__table__.columns["content_hash"]

    assert column.type.length == 64


def test_rubric_version_defaults_to_draft_status() -> None:
    """A new rubric starts unapproved — scoring is blocked until a human acts."""
    column = models.RubricVersion.__table__.columns["status"]

    assert column.default is not None
    assert column.default.arg == "draft"
    assert column.nullable is False


def test_rubric_version_must_have_fail_cap_defaults_to_forty() -> None:
    """The cap is the documented default from ARCHITECTURE.md section 6.5."""
    column = models.RubricVersion.__table__.columns["must_have_fail_cap"]

    assert column.default is not None
    assert column.default.arg == 40
    assert column.nullable is False


def test_rubric_version_approval_columns_are_null_until_approved() -> None:
    """A draft has no approver, so these must be nullable rather than defaulted."""
    table = models.RubricVersion.__table__

    assert table.columns["approved_by"].nullable is True
    assert table.columns["approved_at"].nullable is True


def test_rubric_version_records_its_aggregation_formula() -> None:
    """A stored score is only reproducible if the formula version is recorded."""
    column = models.RubricVersion.__table__.columns["aggregation_formula_version"]

    assert column.nullable is False


def test_requirement_weight_is_numeric_five_four() -> None:
    """Weights are exact decimals, not floats.

    Binary floats cannot represent 0.1 exactly, so weights entered as tenths
    would fail an equality check against 1.0 after summing. `numeric` keeps the
    arithmetic exact.
    """
    column = models.Requirement.__table__.columns["weight"]

    assert isinstance(column.type, Numeric)
    assert column.type.precision == 5
    assert column.type.scale == 4


def test_requirement_min_years_allows_half_year_granularity() -> None:
    """`min_years` is numeric(4,1) per section 6.5, and optional."""
    column = models.Requirement.__table__.columns["min_years"]

    assert isinstance(column.type, Numeric)
    assert column.type.precision == 4
    assert column.type.scale == 1
    assert column.nullable is True


def test_requirement_embedding_uses_halfvec_1024() -> None:
    """Requirement embeddings match the retrieval dimension at half precision."""
    from pgvector.sqlalchemy import HALFVEC

    column = models.Requirement.__table__.columns["embedding"]

    assert isinstance(column.type, HALFVEC)
    assert column.type.dim == 1024
    assert column.nullable is True


def test_requirement_skill_id_is_nullable_pending_the_taxonomy() -> None:
    """Taxonomy linking is unbuilt, so `skill_id` must be optional.

    ARCHITECTURE.md lists the ESCO skill taxonomy as a Phase 1 deliverable that
    was never built. Requiring `skill_id` would make every requirement
    uninsertable until it exists.
    """
    assert models.Requirement.__table__.columns["skill_id"].nullable is True


def test_requirement_cascades_from_its_rubric_version() -> None:
    """Requirements have no meaning apart from the version that owns them."""
    fk = next(iter(models.Requirement.__table__.columns["rubric_version_id"].foreign_keys))

    assert fk.column.table.name == "rubric_versions"
    assert fk.ondelete == "CASCADE"


def test_requirement_accepts_an_exact_decimal_weight() -> None:
    """A weight round-trips onto the instance as an exact Decimal."""
    requirement = models.Requirement(
        id=uuid.uuid4(),
        rubric_version_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        ordinal=0,
        text="Five years of production Python",
        category="skill",
        is_must_have=True,
        weight=Decimal("0.3333"),
    )

    assert requirement.weight == Decimal("0.3333")
    assert requirement.is_must_have is True
