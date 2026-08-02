"""add screening_runs, candidate_scores, requirement_verdicts, evidence_spans

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-08-02 09:40:00.000000+00:00

candidate_scores.candidate_id / .profile_id and screening_runs.triggered_by are
plain uuid columns rather than foreign keys: the candidates, candidate_profiles
and users tables described in ARCHITECTURE.md 6.3-6.4 are not built in this
repo, and declaring the constraints would make this revision unrunnable.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c3d4e5f6a7b8"
down_revision: str | None = "b2c3d4e5f6a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply this revision."""
    op.create_table(
        "screening_runs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("job_id", sa.UUID(), nullable=False),
        sa.Column("rubric_version_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("mode", sa.String(length=32), nullable=False),
        sa.Column("candidate_count", sa.Integer(), nullable=False),
        sa.Column("funnel_stage_counts", postgresql.JSONB(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("workflow_id", sa.String(length=128), nullable=True),
        sa.Column("triggered_by", sa.UUID(), nullable=True),
        sa.Column("cost_usd", sa.Numeric(precision=10, scale=4), nullable=False),
        sa.Column("total_input_tokens", sa.BigInteger(), nullable=False),
        sa.Column("total_output_tokens", sa.BigInteger(), nullable=False),
        sa.Column("cache_read_tokens", sa.BigInteger(), nullable=False),
        sa.Column("cache_write_tokens", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        # RESTRICT: a run is the record of which criteria produced a ranking, so
        # the rubric version it cites must not be deletable out from under it.
        sa.ForeignKeyConstraint(
            ["rubric_version_id"], ["rubric_versions.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_screening_runs_tenant_id", "screening_runs", ["tenant_id"], unique=False
    )
    op.create_index(
        "ix_screening_runs_tenant_job",
        "screening_runs",
        ["tenant_id", "job_id"],
        unique=False,
    )

    op.create_table(
        "candidate_scores",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("candidate_id", sa.UUID(), nullable=False),
        sa.Column("profile_id", sa.UUID(), nullable=True),
        # Two decimals for the reported score, four for the pre-rounding
        # weighted sum, so a score stays replayable.
        sa.Column("overall_score", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("raw_weighted", sa.Numeric(precision=5, scale=4), nullable=False),
        sa.Column("cap_applied", sa.Integer(), nullable=True),
        sa.Column("rank", sa.Integer(), nullable=True),
        sa.Column("retrieval_score", sa.Float(), nullable=True),
        sa.Column("rerank_score", sa.Float(), nullable=True),
        sa.Column("recommendation", sa.String(length=32), nullable=True),
        sa.Column("recommendation_confidence", sa.Float(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("aggregation_formula_version", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["run_id"], ["screening_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "run_id", "candidate_id", name="uq_candidate_scores_run_candidate"
        ),
    )
    op.create_index(
        "ix_candidate_scores_tenant_id", "candidate_scores", ["tenant_id"], unique=False
    )
    op.create_index(
        "ix_candidate_scores_tenant_run",
        "candidate_scores",
        ["tenant_id", "run_id"],
        unique=False,
    )
    op.create_index(
        "ix_candidate_scores_run_rank",
        "candidate_scores",
        ["run_id", "rank"],
        unique=False,
    )

    op.create_table(
        "requirement_verdicts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("score_id", sa.UUID(), nullable=False),
        sa.Column("requirement_id", sa.UUID(), nullable=False),
        sa.Column("verdict", sa.String(length=16), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        # Stored, not derived: the rubric can mint a new version with different
        # weights, and a verdict must stay explainable against the weights that
        # actually produced it.
        sa.Column("weight_at_scoring", sa.Numeric(precision=5, scale=4), nullable=False),
        sa.Column("contribution", sa.Numeric(precision=6, scale=4), nullable=False),
        sa.Column("reasoning", sa.Text(), nullable=True),
        sa.Column("judge_model", sa.String(length=128), nullable=True),
        sa.Column("judge_prompt_version", sa.String(length=32), nullable=True),
        sa.Column("judge_effort", sa.String(length=32), nullable=True),
        sa.Column("cache_hit", sa.Boolean(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        # The exposure record: exactly what the judge saw. Without it a
        # "missing" verdict is indistinguishable from a retrieval failure.
        sa.Column("retrieved_chunk_ids", postgresql.ARRAY(sa.UUID()), nullable=True),
        sa.Column("result_cache_key", sa.String(length=64), nullable=True),
        sa.Column("overridden_by", sa.UUID(), nullable=True),
        sa.Column("override_verdict", sa.String(length=16), nullable=True),
        sa.Column("override_reason", sa.Text(), nullable=True),
        sa.Column("overridden_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["score_id"], ["candidate_scores.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["requirement_id"], ["requirements.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "score_id", "requirement_id", name="uq_requirement_verdicts_score_req"
        ),
    )
    op.create_index(
        "ix_requirement_verdicts_tenant_id",
        "requirement_verdicts",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        "ix_requirement_verdicts_tenant_score",
        "requirement_verdicts",
        ["tenant_id", "score_id"],
        unique=False,
    )
    op.create_index(
        "ix_requirement_verdicts_cache_key",
        "requirement_verdicts",
        ["result_cache_key"],
        unique=False,
    )

    op.create_table(
        "evidence_spans",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("verdict_id", sa.UUID(), nullable=True),
        sa.Column("resume_version_id", sa.UUID(), nullable=False),
        sa.Column("chunk_id", sa.UUID(), nullable=True),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("start_char", sa.Integer(), nullable=False),
        sa.Column("end_char", sa.Integer(), nullable=False),
        sa.Column("quoted_text", sa.Text(), nullable=False),
        # Set by the automated check that re-slices the resume at
        # [start_char, end_char) and compares: the anti-hallucination gate.
        sa.Column("verbatim_verified", sa.Boolean(), nullable=False),
        sa.Column("relevance", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["verdict_id"], ["requirement_verdicts.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["resume_version_id"], ["resume_versions.id"], ondelete="RESTRICT"
        ),
        # SET NULL: re-indexing a resume replaces its chunks, and the citation
        # survives that because resume_version_id plus the character offsets
        # locate the quote independently of any chunk row.
        sa.ForeignKeyConstraint(["chunk_id"], ["resume_chunks.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_evidence_spans_tenant_id", "evidence_spans", ["tenant_id"], unique=False
    )
    op.create_index(
        "ix_evidence_spans_tenant_verdict",
        "evidence_spans",
        ["tenant_id", "verdict_id"],
        unique=False,
    )


def downgrade() -> None:
    """Revert this revision."""
    op.drop_index("ix_evidence_spans_tenant_verdict", table_name="evidence_spans")
    op.drop_index("ix_evidence_spans_tenant_id", table_name="evidence_spans")
    op.drop_table("evidence_spans")

    op.drop_index(
        "ix_requirement_verdicts_cache_key", table_name="requirement_verdicts"
    )
    op.drop_index(
        "ix_requirement_verdicts_tenant_score", table_name="requirement_verdicts"
    )
    op.drop_index(
        "ix_requirement_verdicts_tenant_id", table_name="requirement_verdicts"
    )
    op.drop_table("requirement_verdicts")

    op.drop_index("ix_candidate_scores_run_rank", table_name="candidate_scores")
    op.drop_index("ix_candidate_scores_tenant_run", table_name="candidate_scores")
    op.drop_index("ix_candidate_scores_tenant_id", table_name="candidate_scores")
    op.drop_table("candidate_scores")

    op.drop_index("ix_screening_runs_tenant_job", table_name="screening_runs")
    op.drop_index("ix_screening_runs_tenant_id", table_name="screening_runs")
    op.drop_table("screening_runs")
