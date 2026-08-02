"""add rubric_versions and requirements tables

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-08-01 10:20:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b2c3d4e5f6a7"
down_revision: str | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply this revision."""
    op.create_table(
        "rubric_versions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("job_id", sa.UUID(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("must_have_fail_cap", sa.Integer(), nullable=False),
        sa.Column("aggregation_formula_version", sa.String(length=32), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("approved_by", sa.UUID(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", "version", name="uq_rubric_versions_job_version"),
    )
    op.create_index(
        "ix_rubric_versions_tenant_id", "rubric_versions", ["tenant_id"], unique=False
    )
    op.create_index(
        "ix_rubric_versions_tenant_job",
        "rubric_versions",
        ["tenant_id", "job_id"],
        unique=False,
    )

    op.create_table(
        "requirements",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("rubric_version_id", sa.UUID(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("is_must_have", sa.Boolean(), nullable=False),
        # numeric, not float: normalized weights must sum to exactly 1.0, and a
        # binary float cannot represent tenths exactly.
        sa.Column("weight", sa.Numeric(precision=5, scale=4), nullable=False),
        sa.Column("min_years", sa.Numeric(precision=4, scale=1), nullable=True),
        sa.Column("min_seniority", sa.String(length=32), nullable=True),
        sa.Column("skill_id", sa.UUID(), nullable=True),
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
            ["rubric_version_id"], ["rubric_versions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_requirements_tenant_id", "requirements", ["tenant_id"], unique=False)
    op.create_index(
        "ix_requirements_tenant_version",
        "requirements",
        ["tenant_id", "rubric_version_id"],
        unique=False,
    )

    # Alembic cannot render pgvector types, so the embedding column goes in as
    # raw SQL. The extension is already installed by revision a1b2c3d4e5f6.
    op.execute("ALTER TABLE requirements ADD COLUMN embedding halfvec(1024)")


def downgrade() -> None:
    """Revert this revision."""
    op.drop_index("ix_requirements_tenant_version", table_name="requirements")
    op.drop_index("ix_requirements_tenant_id", table_name="requirements")
    op.drop_table("requirements")

    op.drop_index("ix_rubric_versions_tenant_job", table_name="rubric_versions")
    op.drop_index("ix_rubric_versions_tenant_id", table_name="rubric_versions")
    op.drop_table("rubric_versions")
