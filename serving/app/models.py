"""ORM models for Phase 0-3.

Every tenant-scoped table carries `tenant_id` as the first filter column and is
indexed on it. Content-addressed uniqueness on `(tenant_id, sha256)` is what
makes the same resume arriving through three channels resolve to one document.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pgvector.sqlalchemy import HALFVEC, Vector
from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class TimestampMixin:
    """Adds server-side creation and update timestamps."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class ResumeDocument(TimestampMixin, Base):
    """An uploaded resume file, deduplicated by content hash within a tenant."""

    __tablename__ = "resume_documents"
    __table_args__ = (
        UniqueConstraint("tenant_id", "sha256", name="uq_resume_documents_tenant_sha256"),
        Index("ix_resume_documents_tenant_created", "tenant_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, index=True
    )
    uploaded_by: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)

    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    filename_sanitized: Mapped[str] = mapped_column(String(255), nullable=False)
    media_type: Mapped[str] = mapped_column(String(128), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)

    page_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    parse_status: Mapped[str] = mapped_column(String(32), nullable=False, default="ok")
    parse_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    parser_version: Mapped[str] = mapped_column(String(64), nullable=False)
    needs_ocr: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    versions: Mapped[list[ResumeVersion]] = relationship(
        back_populates="document", cascade="all, delete-orphan", lazy="noload"
    )


class ResumeVersion(TimestampMixin, Base):
    """Extracted text for one parse of one document.

    Kept separate from the document so a re-parse under a newer parser version
    is a new row rather than a destructive update — prior evidence offsets stay
    attributable to the parse that produced them.
    """

    __tablename__ = "resume_versions"
    __table_args__ = (
        UniqueConstraint(
            "document_id", "version", name="uq_resume_versions_document_version"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, index=True
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("resume_documents.id", ondelete="CASCADE"),
        nullable=False,
    )

    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    extracted_text: Mapped[str] = mapped_column(Text, nullable=False)
    text_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    page_offsets: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    parser_version: Mapped[str] = mapped_column(String(64), nullable=False)

    # Sanitization provenance. Stored per version because a re-parse under a
    # newer sanitizer must not overwrite what an earlier decision was based on.
    sanitization_report: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    injection_risk_score: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0
    )
    quarantined: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    document: Mapped[ResumeDocument] = relationship(back_populates="versions")


class ResumeChunk(TimestampMixin, Base):
    """A chunk of resume text with its embedding vector.

    Parent-child chunking: small children (~180 words) for embedding precision,
    larger parents (~700 words) fed to the LLM for context. Retrieve on children,
    expand to parents.

    ``embedding_version`` on the row is what makes an embedding-model upgrade a
    background backfill instead of a flag day.
    """

    __tablename__ = "resume_chunks"
    # Every index the migration creates is declared here, including the two
    # PostgreSQL-specific ones. Leaving them out of the metadata does not make
    # them optional — it makes `alembic revision --autogenerate` emit a
    # `drop_index` for each on the next run, quietly removing the indexes both
    # halves of hybrid search depend on.
    __table_args__ = (
        Index("ix_resume_chunks_tenant_document", "tenant_id", "document_id"),
        Index("ix_resume_chunks_tenant_id", "tenant_id"),
        Index("ix_resume_chunks_content_tsv", "content_tsv", postgresql_using="gin"),
        Index(
            "ix_resume_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    resume_version_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("resume_versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("resume_documents.id", ondelete="CASCADE"),
        nullable=False,
    )

    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_chunk_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    section: Mapped[str] = mapped_column(
        String(64), nullable=False, default="other"
    )

    content: Mapped[str] = mapped_column(Text, nullable=False)
    # content_tsv is a PostgreSQL tsvector GENERATED column managed by the
    # database. The column exists for GIN indexing and ts_rank_cd queries.
    # We declare it here so SQLAlchemy knows about it but never write to it
    # from Python.
    content_tsv: Mapped[str | None] = mapped_column(
        TSVECTOR, nullable=True, server_default=None
    )

    page_from: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    page_to: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    start_char: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    end_char: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    token_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # pgvector embedding — stored as vector(1024). The HNSW index is created
    # in the Alembic migration rather than here because SQLAlchemy's Index()
    # does not support the pgvector-specific USING/WITH clauses.
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(1024), nullable=True
    )

    embedding_model: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    embedding_version: Mapped[str] = mapped_column(String(64), nullable=False, default="")

    is_parent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class Job(TimestampMixin, Base):
    """A job description, either pasted as text or extracted from an upload."""

    __tablename__ = "jobs"
    __table_args__ = (Index("ix_jobs_tenant_created", "tenant_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, index=True
    )
    created_by: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    department: Mapped[str | None] = mapped_column(String(255), nullable=True)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    employment_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    seniority: Mapped[str | None] = mapped_column(String(64), nullable=True)

    description_raw: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="manual")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    blind_mode: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class RubricVersion(TimestampMixin, Base):
    """One immutable-once-approved snapshot of the criteria for a job.

    A rubric is the artifact a human signs off on, and every score is attributed
    to the version it was computed against. Editing an approved rubric mints
    version N+1 and leaves prior scores attributable to the criteria that
    produced them, so `unique(job_id, version)` is what keeps "which criteria
    was this candidate judged by" answerable.

    ``content_hash`` fingerprints the full requirement set and is part of every
    verdict cache key. It stays NULL while the rubric is a draft — a draft has
    no frozen criteria to fingerprint.
    """

    __tablename__ = "rubric_versions"
    __table_args__ = (
        UniqueConstraint("job_id", "version", name="uq_rubric_versions_job_version"),
        Index("ix_rubric_versions_tenant_job", "tenant_id", "job_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, index=True
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
    )

    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # A candidate failing a must-have cannot score above this, no matter how
    # strong the rest of the match is. Stored per version so tightening the cap
    # does not silently re-rank candidates scored under the old one.
    must_have_fail_cap: Mapped[int] = mapped_column(Integer, nullable=False, default=40)
    aggregation_formula_version: Mapped[str] = mapped_column(
        String(32), nullable=False, default="v1"
    )
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="manual")

    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    requirements: Mapped[list[Requirement]] = relationship(
        back_populates="rubric_version",
        cascade="all, delete-orphan",
        lazy="noload",
    )


class Requirement(TimestampMixin, Base):
    """One weighted criterion within a rubric version.

    ``weight`` is ``numeric(5,4)`` rather than a float because normalized
    weights must sum to exactly 1.0. Binary floats cannot represent tenths
    exactly, so a float column would make that invariant unverifiable.

    ``skill_id`` is nullable: the ESCO skill taxonomy it would point at is not
    built yet, and requiring it would make every requirement uninsertable.
    """

    __tablename__ = "requirements"
    __table_args__ = (
        Index("ix_requirements_tenant_version", "tenant_id", "rubric_version_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, index=True
    )
    rubric_version_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("rubric_versions.id", ondelete="CASCADE"),
        nullable=False,
    )

    ordinal: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False, default="skill")
    is_must_have: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    weight: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)

    min_years: Mapped[Decimal | None] = mapped_column(Numeric(4, 1), nullable=True)
    min_seniority: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # Reserved for taxonomy linking; the ESCO tables do not exist yet.
    skill_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )

    # Half precision because requirement counts are small and the extra recall
    # from full precision is not worth doubling the index footprint. The HNSW
    # index is created in the Alembic migration, not here.
    embedding: Mapped[list[float] | None] = mapped_column(HALFVEC(1024), nullable=True)

    rubric_version: Mapped[RubricVersion] = relationship(back_populates="requirements")
