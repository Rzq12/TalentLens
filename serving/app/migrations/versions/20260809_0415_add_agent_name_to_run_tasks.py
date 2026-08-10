"""add_agent_name_to_run_tasks

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-08-09

The orchestrator needs ``agent_name`` on ``run_tasks`` to resolve which
agent class handles each task. Added as nullable with default empty string
for backward compatibility with existing rows.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f6a7b8c9d0e1"
down_revision: str | None = "e5f6a7b8c9d0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "run_tasks",
        sa.Column(
            "agent_name",
            sa.String(64),
            nullable=False,
            server_default="",
        ),
    )


def downgrade() -> None:
    op.drop_column("run_tasks", "agent_name")
