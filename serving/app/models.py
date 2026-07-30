"""ORM models for Phase 0-1.

Every tenant-scoped table carries `tenant_id` as the first filter column and is
indexed on it. Content-addressed uniqueness on `(tenant_id, sha256)` is what
makes the same resume arriving through three channels resolve to one document.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
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
        back_populates="document", cascade="all, delete-orphan", lazy="selectin"
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

    document: Mapped[ResumeDocument] = relationship(back_populates="versions")


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
