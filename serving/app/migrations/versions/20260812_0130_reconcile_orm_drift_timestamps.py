"""reconcile ORM drift: timestamps on 0430 tables, run_tasks_ready index

Revision ID: 20260812_0130
Revises: 20260812_0120
Create Date: 2026-08-12

`tests/integration/test_migrations.py::test_migrations_match_the_orm_models`
(alembic `compare_metadata`) reported 19 drift items on a fresh
`upgrade head`:

* 15 missing timestamp columns — revision h8i9j0k1l2m3 created its tables
  without the ``TimestampMixin`` columns (``created_at``/``updated_at``) the
  ORM declares. Any ORM insert into those tables fails with
  ``UndefinedColumn`` on a migrated schema (tests create schema from ORM
  metadata instead, which is why the suite never caught it).
* 3 remove_fk items — revision h8i9j0k1l2m3 added real DB constraints
  (``fk_screening_runs_triggered_by`` → users.id SET NULL,
  ``fk_candidate_scores_candidate_id`` → candidates.id RESTRICT,
  ``fk_candidate_scores_profile_id`` → candidate_profiles.id SET NULL) that
  the ORM never declared. compare_metadata DOES report DB-side FKs missing
  from the models. The constraints are correct referential integrity, so the
  ORM is brought in line (ForeignKey declarations in app/models.py) instead
  of dropping them.
* 1 remove_index — 20260811_0115 created ``ix_run_tasks_ready`` but the ORM
  ``RunTask`` model never declared it. Declared in app/models.py.

The timestamp columns are added idempotently per table because whether a
table already has them depends on which path built the schema.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260812_0130"
down_revision: str | None = "20260812_0120"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Tables created by h8i9j0k1l2m3 whose ORM classes mix in TimestampMixin.
# Verified against app/models.py — keep in sync with that file.
# Which columns each table actually lacks (per the drift report):
#   api_keys, chat_messages, chat_sessions, interview_kits, skill_gaps
#       -> updated_at only (created_at already exists)
#   audit_events, decisions, fairness_snapshots, interview_questions,
#   user_roles -> both created_at and updated_at
_TABLES_MISSING_TIMESTAMPS = [
    "api_keys",
    "audit_events",
    "chat_messages",
    "chat_sessions",
    "decisions",
    "fairness_snapshots",
    "interview_kits",
    "interview_questions",
    "skill_gaps",
    "user_roles",
]


def _column_exists(table: str, column: str) -> bool:
    """True when ``column`` already exists on ``table`` (idempotence guard)."""
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema = current_schema() "
            "AND table_name = :table AND column_name = :column"
        ),
        {"table": table, "column": column},
    )
    return result.scalar() is not None


def upgrade() -> None:
    now = sa.text("now()")

    for table in _TABLES_MISSING_TIMESTAMPS:
        # _column_exists makes each add idempotent: whether a table already
        # has a column depends on which path built the schema.
        if not _column_exists(table, "created_at"):
            op.add_column(
                table,
                sa.Column(
                    "created_at", sa.DateTime(timezone=True),
                    server_default=now, nullable=False,
                ),
            )
        if not _column_exists(table, "updated_at"):
            op.add_column(
                table,
                sa.Column(
                    "updated_at", sa.DateTime(timezone=True),
                    server_default=now, nullable=False,
                ),
            )


def downgrade() -> None:
    for table in _TABLES_MISSING_TIMESTAMPS:
        if _column_exists(table, "updated_at"):
            op.drop_column(table, "updated_at")
        if _column_exists(table, "created_at"):
            op.drop_column(table, "created_at")
