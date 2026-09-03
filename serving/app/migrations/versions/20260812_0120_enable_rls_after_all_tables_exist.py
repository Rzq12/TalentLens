"""enable RLS on all tenant-scoped tables (moved from g7h8i9j0k1l2)

Revision ID: 20260812_0120
Revises: 20260811_0115
Create Date: 2026-08-12

Row-Level Security originally shipped in g7h8i9j0k1l2, which runs BEFORE
h8i9j0k1l2m3 creates most of the tables it references — a fresh
`alembic upgrade head` failed with "relation does not exist". This revision
replays the same enablement after every tenant-scoped table exists.

Two hardening changes over the original statements:

* ``current_setting(..., true)`` (missing_ok) instead of a bare
  ``current_setting(...)`` — a connection without a tenant context must see
  zero rows (default-deny), not raise.
* ``NULLIF(..., '')`` because the app resets the context to the empty string
  on connection release; the empty string is not a valid uuid and would
  otherwise make every policy evaluation an error.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260812_0120"
down_revision: str | None = "20260811_0115"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Every table carrying a tenant_id column. Must match the ORM models.
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


def _table_exists(conn: sa.Connection, table: str) -> bool:
    return (
        conn.execute(
            sa.text("SELECT to_regclass(:t) IS NOT NULL"),
            {"t": f"public.{table}"},
        ).scalar()
        or False
    )


def upgrade() -> None:
    conn = op.get_bind()
    for table in TENANT_TABLES:
        if not _table_exists(conn, table):
            # Defensive: a table missing here is an ordering bug elsewhere in
            # the chain, but disabling RLS on the tables that DO exist would
            # be the worse failure. Surface it loudly instead.
            raise RuntimeError(
                f"RLS migration: table '{table}' does not exist. The migration "
                "chain is inconsistent — every tenant-scoped table must be "
                "created before this revision."
            )
        conn.execute(sa.text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))
        conn.execute(
            sa.text(
                f"""
                CREATE POLICY tenant_isolation_{table}
                ON {table}
                FOR ALL
                USING (
                    tenant_id
                      = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
                )
                WITH CHECK (
                    tenant_id
                      = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
                )
                """
            )
        )


def downgrade() -> None:
    conn = op.get_bind()
    for table in TENANT_TABLES:
        if not _table_exists(conn, table):
            continue
        conn.execute(
            sa.text(f"DROP POLICY IF EXISTS tenant_isolation_{table} ON {table}")
        )
        conn.execute(sa.text(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY"))
