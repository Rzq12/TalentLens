"""Allow authenticated external identities to record decisions.

Revision ID: 20260810_0100
Revises: 20260809_0430
Create Date: 2026-08-10 01:00:00
"""

from __future__ import annotations

from alembic import op

revision = "20260810_0100"
down_revision = "g7h8i9j0k1l2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("decisions_decided_by_fkey", "decisions", type_="foreignkey")


def downgrade() -> None:
    op.create_foreign_key(
        "decisions_decided_by_fkey",
        "decisions",
        "users",
        ["decided_by"],
        ["id"],
        ondelete="RESTRICT",
    )
