"""enable_rls_on_all_tenant_scoped_tables (SUPERSEDED — see 20260812_0120)

Revision ID: g7h8i9j0k1l2
Revises: f6a7b8c9d0e1
Create Date: 2026-08-09

HISTORY FIX: this revision originally enabled RLS on every tenant-scoped
table, but most of those tables (candidates, audit_events, chat_sessions,
decisions, user_roles, ...) are only CREATED by the NEXT revision
(h8i9j0k1l2m3). Running `alembic upgrade head` on a fresh database failed
with "relation does not exist". The suite never noticed because tests build
the schema from ORM metadata, not from the migration chain.

The RLS statements now live in 20260812_0120, which runs after every table
exists. This revision is kept as a no-op so existing `alembic_version` rows
remain valid.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "g7h8i9j0k1l2"
down_revision: str | None = "h8i9j0k1l2m3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Kept for reference; the authoritative list now lives in 20260812_0120.
TENANT_TABLES = [
    "resume_documents",
    "resume_versions",
    "resume_chunks",
    "jobs",
    "rubric_versions",
    "requirements",
    "screening_runs",
    "candidate_scores",
    "requirement_verdicts",
    "evidence_spans",
    "run_tasks",
    "agent_result_cache",
    "ats_compliance_reports",
    "fraud_flags",
    "bias_flags",
    "api_keys",
    "audit_events",
    "candidates",
    "candidate_profiles",
    "chat_sessions",
    "decisions",
    "fairness_snapshots",
    "interview_kits",
    "skill_gaps",
    "user_roles",
]


def upgrade() -> None:
    # No-op: RLS enablement moved to 20260812_0120 (after h8i9j0k1l2m3
    # creates the tables this list references). See module docstring.
    pass


def downgrade() -> None:
    # No-op for the same reason; 20260812_0120.downgrade drops the policies.
    pass
