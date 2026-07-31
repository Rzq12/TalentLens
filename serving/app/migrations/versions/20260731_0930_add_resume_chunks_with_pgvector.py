"""add resume_chunks table with pgvector

Revision ID: a1b2c3d4e5f6
Revises: dd2329f32308
Create Date: 2026-07-31 09:30:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "dd2329f32308"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply this revision."""
    # Enable the pgvector extension — idempotent, safe to re-run
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "resume_chunks",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("resume_version_id", sa.UUID(), nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("parent_chunk_id", sa.UUID(), nullable=True),
        sa.Column("section", sa.String(length=64), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_tsv", sa.Text(), nullable=True),
        sa.Column("page_from", sa.Integer(), nullable=False),
        sa.Column("page_to", sa.Integer(), nullable=False),
        sa.Column("start_char", sa.Integer(), nullable=False),
        sa.Column("end_char", sa.Integer(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("embedding_model", sa.String(length=128), nullable=False),
        sa.Column("embedding_version", sa.String(length=64), nullable=False),
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
            ["resume_version_id"], ["resume_versions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["document_id"], ["resume_documents.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # Add the pgvector embedding column — raw SQL because Alembic/SA don't
    # know about the vector type natively
    op.execute("ALTER TABLE resume_chunks ADD COLUMN embedding vector(1024)")

    # Replace the content_tsv text column with a real tsvector column
    op.execute("ALTER TABLE resume_chunks DROP COLUMN IF EXISTS content_tsv")
    op.execute(
        "ALTER TABLE resume_chunks ADD COLUMN content_tsv tsvector "
        "GENERATED ALWAYS AS (to_tsvector('english', content)) STORED"
    )

    # Add the is_parent column (needed for filtering child-only retrieval)
    op.execute(
        "ALTER TABLE resume_chunks ADD COLUMN is_parent boolean NOT NULL DEFAULT false"
    )

    # --- Indexes ---
    # HNSW index for cosine vector search (pgvector-specific)
    op.execute(
        "CREATE INDEX ix_resume_chunks_embedding_hnsw ON resume_chunks "
        "USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    )

    # GIN index for full-text search
    op.execute(
        "CREATE INDEX ix_resume_chunks_content_tsv ON resume_chunks "
        "USING gin (content_tsv)"
    )

    # Composite index for tenant + document scoped queries
    op.create_index(
        "ix_resume_chunks_tenant_document",
        "resume_chunks",
        ["tenant_id", "document_id"],
        unique=False,
    )

    # Tenant isolation index
    op.create_index(
        "ix_resume_chunks_tenant_id",
        "resume_chunks",
        ["tenant_id"],
        unique=False,
    )


def downgrade() -> None:
    """Revert this revision."""
    op.drop_index("ix_resume_chunks_tenant_id", table_name="resume_chunks")
    op.drop_index("ix_resume_chunks_tenant_document", table_name="resume_chunks")
    op.execute("DROP INDEX IF EXISTS ix_resume_chunks_content_tsv")
    op.execute("DROP INDEX IF EXISTS ix_resume_chunks_embedding_hnsw")
    op.drop_table("resume_chunks")
    # Note: we do NOT drop the vector extension — other tables may use it
