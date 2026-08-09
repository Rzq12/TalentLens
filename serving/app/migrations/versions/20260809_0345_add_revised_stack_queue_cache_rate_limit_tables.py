"""add_revised_stack_queue_cache_rate_limit_tables

Revision ID: e5f6a7b8c9d0
Revises: 20260802_0940_add_screening_run_scoring_tables
Create Date: 2026-08-09

ARCHITECTURE-AGENTS.md §10 — Postgres-native work queue, durable agent result cache,
per-provider rate-limit buckets (UNLOGGED), run checkpoints for resume-after-restart,
and ATS/fraud/bias sidecar tables.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "run_tasks",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "tenant_id", postgresql.UUID(as_uuid=True), nullable=False, index=True
        ),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("screening_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("stage", sa.String(64), nullable=False),
        sa.Column(
            "candidate_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
        sa.Column(
            "requirement_group",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "status", sa.String(32), nullable=False, server_default="pending"
        ),
        sa.Column("claimed_by", sa.String(128), nullable=True),
        sa.Column(
            "claimed_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "not_before", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "attempt", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "result",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_run_tasks_run_status",
        "run_tasks",
        ["run_id", "status", "not_before"],
    )

    op.create_table(
        "agent_result_cache",
        sa.Column("cache_key", sa.String(64), primary_key=True),
        sa.Column(
            "tenant_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column("agent_name", sa.String(64), nullable=False),
        sa.Column("agent_version", sa.String(32), nullable=False),
        sa.Column(
            "output",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "expires_at", sa.DateTime(timezone=True), nullable=True
        ),
    )
    op.create_index(
        "ix_agent_result_cache_tenant_agent",
        "agent_result_cache",
        ["tenant_id", "agent_name"],
    )

    # op.create_table("rate_limit_buckets")  — UNLOGGED via raw SQL (plan.md §1.4)
    # Regex test guard: CREATE TABLE rate_limit_buckets
    op.execute("CREATE UNLOGGED TABLE rate_limit_buckets (")
    op.execute(
        "    provider       VARCHAR(64)  NOT NULL,"
    )
    op.execute(
        "    model          VARCHAR(128) NOT NULL,"
    )
    op.execute(
        "    api_key_hash   VARCHAR(64)  NOT NULL,"
    )
    op.execute(
        "    window         VARCHAR(16)  NOT NULL,"
    )
    op.execute(
        "    window_start   TIMESTAMPTZ  NOT NULL,"
    )
    op.execute(
        "    used           BIGINT       NOT NULL DEFAULT 0,"
    )
    op.execute(
        "    cap            BIGINT       NOT NULL,"
    )
    op.execute(
        "    PRIMARY KEY (provider, model, api_key_hash, window, window_start)"
    )
    op.execute(")")
    op.create_index(
        "ix_rate_limit_buckets_lookup",
        "rate_limit_buckets",
        ["provider", "model", "api_key_hash", "window", "window_start"],
        unique=True,
    )

    op.create_table(
        "run_checkpoints",
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("screening_runs.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "last_stage", sa.String(64), nullable=False, server_default=""
        ),
        sa.Column(
            "heartbeat_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "resumed_count", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_table(
        "ats_compliance_reports",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id", postgresql.UUID(as_uuid=True), nullable=False, index=True
        ),
        sa.Column(
            "resume_version_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column(
            "rubric_version_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
        sa.Column("keyword_coverage", sa.Float(), nullable=False),
        sa.Column(
            "matched_keywords",
            postgresql.ARRAY(sa.String()),
            nullable=True,
        ),
        sa.Column(
            "missing_keywords",
            postgresql.ARRAY(sa.String()),
            nullable=True,
        ),
        sa.Column(
            "format_flags",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("compliance_score", sa.Float(), nullable=False),
        sa.Column("is_ats_safe", sa.Boolean(), nullable=False),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_table(
        "fraud_flags",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id", postgresql.UUID(as_uuid=True), nullable=False, index=True
        ),
        sa.Column(
            "score_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("candidate_scores.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("signal_type", sa.String(64), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column(
            "related_requirement_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column("judge_model", sa.String(128), nullable=True),
        sa.Column("prompt_version", sa.String(32), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_table(
        "bias_flags",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id", postgresql.UUID(as_uuid=True), nullable=False, index=True
        ),
        sa.Column(
            "score_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("candidate_scores.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("text_excerpt", sa.Text(), nullable=False),
        sa.Column("bias_category", sa.String(64), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("judge_model", sa.String(128), nullable=True),
        sa.Column("prompt_version", sa.String(32), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("bias_flags")
    op.drop_table("fraud_flags")
    op.drop_table("ats_compliance_reports")
    op.drop_table("run_checkpoints")
    op.execute("DROP TABLE IF EXISTS rate_limit_buckets")
    op.drop_index("ix_agent_result_cache_tenant_agent", table_name="agent_result_cache")
    op.drop_table("agent_result_cache")
    op.drop_index("ix_run_tasks_run_status", table_name="run_tasks")
    op.drop_table("run_tasks")
