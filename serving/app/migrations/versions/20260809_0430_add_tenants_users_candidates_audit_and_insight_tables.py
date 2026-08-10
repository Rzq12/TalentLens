"""Phase 0 completion — tenants, users, candidates, audit events, chat, insights.

Adds the foundation tables required by ARCHITECTURE.md §6 and referenced
by existing foreign-key-placeholder columns (screening_runs.triggered_by,
candidate_scores.candidate_id, etc.). Also includes chat sessions
(stateful RAG), skill gaps, interview kits, decisions, and fairness
snapshots for future phase agents.

Revision ID: h8i9j0k1l2m3
Revises: g7h8i9j0k1l2
Create Date: 2026-08-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "h8i9j0k1l2m3"
down_revision: str | None = "g7h8i9j0k1l2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- tenants ---
    op.create_table(
        "tenants",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("name", sa.String(255), nullable=False, unique=True),
        sa.Column("slug", sa.String(64), nullable=False, unique=True),
        sa.Column("plan", sa.String(32), nullable=False, server_default="free"),
        sa.Column("retention_days", sa.Integer(), nullable=False, server_default="365"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # --- users (cross-tenant) ---
    op.create_table(
        "users",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # --- user_roles (per-tenant membership) ---
    op.create_table(
        "user_roles",
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "tenant_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("role", sa.String(32), nullable=False, primary_key=True),
    )
    op.create_index("ix_user_roles_tenant", "user_roles", ["tenant_id"])

    # --- api_keys ---
    op.create_table(
        "api_keys",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False, index=True,
        ),
        sa.Column("key_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("key_prefix", sa.String(12), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # --- audit_events (tamper-evident hash-chained) ---
    op.create_table(
        "audit_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column(
            "tenant_id", postgresql.UUID(as_uuid=True), nullable=False, index=True,
        ),
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=True), nullable=True,
        ),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("resource_type", sa.String(64), nullable=False),
        sa.Column("resource_id", sa.String(64), nullable=False),
        sa.Column(
            "details", postgresql.JSONB(astext_type=sa.Text()), nullable=True,
        ),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("request_id", sa.String(36), nullable=True),
        sa.Column(
            "occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False,
        ),
        # Hash chain: links to previous event for tamper evidence
        sa.Column("prev_hash", sa.String(64), nullable=True),
        sa.Column("chain_hash", sa.String(64), nullable=False),
    )
    op.create_index("ix_audit_events_tenant_time", "audit_events",
                    ["tenant_id", "occurred_at"])
    op.create_index("ix_audit_events_resource", "audit_events",
                    ["resource_type", "resource_id"])

    # --- candidates ---
    op.create_table(
        "candidates",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id", postgresql.UUID(as_uuid=True), nullable=False, index=True,
        ),
        sa.Column("external_id", sa.String(255), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("phone", sa.String(64), nullable=True),
        sa.Column(
            "consent_purpose", sa.String(64), nullable=False,
            server_default="candidate_screening",
        ),
        sa.Column("consent_granted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_unique_constraint(
        "uq_candidates_tenant_email",
        "candidates",
        ["tenant_id", "email"],
    )

    # --- candidate_profiles (parsed structured data) ---
    op.create_table(
        "candidate_profiles",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id", postgresql.UUID(as_uuid=True), nullable=False, index=True,
        ),
        sa.Column(
            "candidate_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("candidates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "resume_version_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("resume_versions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("extraction_status", sa.String(32), nullable=False,
                  server_default="pending"),
        sa.Column("total_experience_months", sa.Integer(), nullable=True),
        sa.Column("skills", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("education", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("languages", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("latest_role", sa.String(255), nullable=True),
        sa.Column(
            "extraction_model", sa.String(128), nullable=True,
        ),
        sa.Column(
            "extraction_prompt_version", sa.String(32), nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # --- skill_gaps ---
    op.create_table(
        "skill_gaps",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id", postgresql.UUID(as_uuid=True), nullable=False, index=True,
        ),
        sa.Column(
            "score_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("candidate_scores.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("requirement_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("gap_type", sa.String(32), nullable=False),
        sa.Column("suggested_probe", sa.Text(), nullable=True),
        sa.Column("weight", sa.Float(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # --- interview_kits (one per score) ---
    op.create_table(
        "interview_kits",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id", postgresql.UUID(as_uuid=True), nullable=False, index=True,
        ),
        sa.Column(
            "score_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("candidate_scores.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # --- interview_questions ---
    op.create_table(
        "interview_questions",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column(
            "targets_requirement_id", postgresql.UUID(as_uuid=True), nullable=True,
        ),
        sa.Column("difficulty", sa.String(16), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("expected_signal", sa.Text(), nullable=True),
        sa.Column("follow_ups", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "kit_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("interview_kits.id", ondelete="CASCADE"),
            nullable=False,
        ),
    )

    # --- decisions ---
    op.create_table(
        "decisions",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id", postgresql.UUID(as_uuid=True), nullable=False, index=True,
        ),
        sa.Column(
            "score_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("candidate_scores.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "decided_by", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("agreed_with_ai", sa.Boolean(), nullable=False),
        sa.Column(
            "decided_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # --- fairness_snapshots ---
    op.create_table(
        "fairness_snapshots",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id", postgresql.UUID(as_uuid=True), nullable=False, index=True,
        ),
        sa.Column("computed_for_date", sa.Date(), nullable=False),
        sa.Column(
            "metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=False,
        ),
        sa.Column(
            "computed_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_unique_constraint(
        "uq_fairness_snapshots_tenant_date",
        "fairness_snapshots",
        ["tenant_id", "computed_for_date"],
    )

    # --- chat_sessions ---
    op.create_table(
        "chat_sessions",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id", postgresql.UUID(as_uuid=True), nullable=False, index=True,
        ),
        sa.Column(
            "job_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("jobs.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("candidate_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_by", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("last_active_at", sa.DateTime(timezone=True), nullable=True),
    )

    # --- chat_messages ---
    op.create_table(
        "chat_messages",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column(
            "session_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("chat_sessions.id", ondelete="CASCADE"),
            nullable=False, index=True,
        ),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "citations", postgresql.JSONB(astext_type=sa.Text()), nullable=True,
        ),
        sa.Column(
            "tool_calls", postgresql.JSONB(astext_type=sa.Text()), nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # Now add FK constraints to existing columns that were placeholder uuids
    op.create_foreign_key(
        "fk_screening_runs_triggered_by",
        "screening_runs", "users",
        ["triggered_by"], ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_candidate_scores_candidate_id",
        "candidate_scores", "candidates",
        ["candidate_id"], ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_candidate_scores_profile_id",
        "candidate_scores", "candidate_profiles",
        ["profile_id"], ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_candidate_scores_profile_id", "candidate_scores",
                       type_="foreignkey")
    op.drop_constraint("fk_candidate_scores_candidate_id", "candidate_scores",
                       type_="foreignkey")
    op.drop_constraint("fk_screening_runs_triggered_by", "screening_runs",
                       type_="foreignkey")
    op.drop_table("chat_messages")
    op.drop_table("chat_sessions")
    op.drop_table("fairness_snapshots")
    op.drop_table("decisions")
    op.drop_table("interview_questions")
    op.drop_table("interview_kits")
    op.drop_table("skill_gaps")
    op.drop_table("candidate_profiles")
    op.drop_table("candidates")
    op.drop_table("audit_events")
    op.drop_table("api_keys")
    op.drop_table("user_roles")
    op.drop_table("users")
    op.drop_table("tenants")
