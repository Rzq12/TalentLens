"""enable_rls_on_all_tenant_scoped_tables

Revision ID: g7h8i9j0k1l2
Revises: f6a7b8c9d0e1
Create Date: 2026-08-09

Enables Row-Level Security on every table carrying a ``tenant_id`` column
and creates a policy that filters reads/writes to the tenant set by the
application via ``current_setting('app.current_tenant_id')``.

Plan Phase 0 gate: "two tenants cannot see each other's data, verified
by automated test."
"""

from typing import Sequence, Union

from alembic import op


revision: str = "g7h8i9j0k1l2"
down_revision: Union[str, None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

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
    for table in TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY tenant_isolation_{table}
            ON {table}
            FOR ALL
            USING (tenant_id = current_setting('app.current_tenant_id')::uuid)
            WITH CHECK (tenant_id = current_setting('app.current_tenant_id')::uuid)
            """
        )


def downgrade() -> None:
    for table in TENANT_TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation_{table} ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
