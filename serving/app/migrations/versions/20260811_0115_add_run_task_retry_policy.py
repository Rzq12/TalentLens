"""Add durable retry policy fields to workflow tasks.

Revision ID: 20260811_0115
Revises: 20260810_0100
Create Date: 2026-08-11 01:15:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260811_0115"
down_revision = "20260810_0100"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "run_tasks",
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
    )
    op.add_column("run_tasks", sa.Column("error_code", sa.String(64), nullable=True))
    op.create_index("ix_run_tasks_ready", "run_tasks", ["stage", "status", "not_before"])


def downgrade() -> None:
    op.drop_index("ix_run_tasks_ready", table_name="run_tasks")
    op.drop_column("run_tasks", "error_code")
    op.drop_column("run_tasks", "max_attempts")
