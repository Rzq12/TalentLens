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
    BigInteger,
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
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR
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


class ScreeningRun(TimestampMixin, Base):
    """One execution of the scoring pipeline over a job's candidate pool.

    ``rubric_version_id`` is RESTRICT rather than CASCADE: a run is the record
    of which criteria produced a ranking, so the rubric it cites must not be
    deletable out from under it. The job itself CASCADEs — deleting a job is a
    deliberate purge of everything scoped to it.

    ``triggered_by`` is a plain uuid, not a foreign key: the ``users`` table
    described in ARCHITECTURE.md §6.4 does not exist in this repo yet, and
    declaring the constraint would make the migration unrunnable.
    """

    __tablename__ = "screening_runs"
    __table_args__ = (Index("ix_screening_runs_tenant_job", "tenant_id", "job_id"),)

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
    rubric_version_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("rubric_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )

    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    mode: Mapped[str] = mapped_column(String(32), nullable=False, default="interactive")
    candidate_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Per-stage survivor counts for the retrieval funnel, so a shortlist can be
    # explained as "N of M candidates reached the judge" without re-running it.
    funnel_stage_counts: Mapped[dict[str, object] | None] = mapped_column(
        JSONB, nullable=True
    )

    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    workflow_id: Mapped[str | None] = mapped_column(String(128), nullable=True)

    triggered_by: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )

    cost_usd: Mapped[Decimal] = mapped_column(
        Numeric(10, 4), nullable=False, default=Decimal("0")
    )
    total_input_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    total_output_tokens: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0
    )
    cache_read_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    cache_write_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)

    scores: Mapped[list[CandidateScore]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        lazy="noload",
    )


class CandidateScore(TimestampMixin, Base):
    """One candidate's aggregated result within a run.

    ``raw_weighted`` keeps four decimal places while ``overall_score`` keeps
    two: the weighted sum is the input to capping and rounding, and storing it
    pre-rounding is what makes a score replayable. ``cap_applied`` is NULL when
    no must-have cap fired, so "was this candidate capped" is answerable without
    recomputing the rubric.

    ``candidate_id`` and ``profile_id`` are plain uuids rather than foreign
    keys: the ``candidates`` and ``candidate_profiles`` tables described in
    ARCHITECTURE.md §6.3 are not built in this repo, and declaring the
    constraints would make the migration unrunnable.
    """

    __tablename__ = "candidate_scores"
    __table_args__ = (
        UniqueConstraint(
            "run_id", "candidate_id", name="uq_candidate_scores_run_candidate"
        ),
        Index("ix_candidate_scores_run_rank", "run_id", "rank"),
        Index("ix_candidate_scores_tenant_run", "tenant_id", "run_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, index=True
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("screening_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False
    )
    profile_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )

    overall_score: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    raw_weighted: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    cap_applied: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Assigned in a second pass once every candidate in the run is scored, so a
    # partially-completed run has scores without ranks rather than wrong ranks.
    rank: Mapped[int | None] = mapped_column(Integer, nullable=True)

    retrieval_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    rerank_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    recommendation: Mapped[str | None] = mapped_column(String(32), nullable=True)
    recommendation_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Provenance for replay: which aggregation formula produced this number.
    aggregation_formula_version: Mapped[str] = mapped_column(
        String(32), nullable=False, default="v1"
    )

    run: Mapped[ScreeningRun] = relationship(back_populates="scores")
    verdicts: Mapped[list[RequirementVerdict]] = relationship(
        back_populates="score",
        cascade="all, delete-orphan",
        lazy="noload",
    )


class RequirementVerdict(TimestampMixin, Base):
    """The judge's call on one requirement for one candidate.

    ``weight_at_scoring`` and ``contribution`` are stored rather than derived:
    the rubric can mint a new version with different weights, and a verdict must
    stay explainable against the weights that actually produced it.

    ``retrieved_chunk_ids`` is the exposure record — exactly what the judge saw.
    Without it a "missing" verdict is indistinguishable from a retrieval failure.

    ``requirement_id`` is RESTRICT: a verdict cites a criterion, so the
    criterion must outlive it. Override columns are all nullable and set
    together when a human corrects the judge.
    """

    __tablename__ = "requirement_verdicts"
    __table_args__ = (
        UniqueConstraint(
            "score_id", "requirement_id", name="uq_requirement_verdicts_score_req"
        ),
        Index("ix_requirement_verdicts_tenant_score", "tenant_id", "score_id"),
        Index("ix_requirement_verdicts_cache_key", "result_cache_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, index=True
    )
    score_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("candidate_scores.id", ondelete="CASCADE"),
        nullable=False,
    )
    requirement_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("requirements.id", ondelete="RESTRICT"),
        nullable=False,
    )

    verdict: Mapped[str] = mapped_column(String(16), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    weight_at_scoring: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    contribution: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False)
    reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)

    judge_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    judge_prompt_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    judge_effort: Mapped[str | None] = mapped_column(String(32), nullable=True)

    cache_hit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    retrieved_chunk_ids: Mapped[list[uuid.UUID] | None] = mapped_column(
        ARRAY(PG_UUID(as_uuid=True)), nullable=True
    )
    result_cache_key: Mapped[str | None] = mapped_column(String(64), nullable=True)

    overridden_by: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    override_verdict: Mapped[str | None] = mapped_column(String(16), nullable=True)
    override_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    overridden_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    score: Mapped[CandidateScore] = relationship(back_populates="verdicts")
    evidence_spans: Mapped[list[EvidenceSpanRecord]] = relationship(
        back_populates="verdict",
        cascade="all, delete-orphan",
        lazy="noload",
    )


class EvidenceSpanRecord(TimestampMixin, Base):
    """A verbatim quote from a resume backing one verdict.

    Named ``EvidenceSpanRecord`` rather than ``EvidenceSpan`` because
    ``app.services.search`` already exposes an ``EvidenceSpan`` dataclass for
    in-flight search results; this is the persisted form.

    ``verbatim_verified`` is set by the automated check that re-slices the
    resume text at ``[start_char, end_char)`` and compares it to
    ``quoted_text`` — the anti-hallucination gate. A row with it False is a
    quote the judge produced that the source does not contain.

    ``chunk_id`` is SET NULL on delete: re-indexing a resume replaces its
    chunks, and the citation survives that because ``resume_version_id`` plus
    the character offsets locate the quote independently of any chunk row.
    """

    __tablename__ = "evidence_spans"
    __table_args__ = (
        Index("ix_evidence_spans_tenant_verdict", "tenant_id", "verdict_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, index=True
    )
    # Nullable so a span can be recorded while its verdict is still being built.
    verdict_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("requirement_verdicts.id", ondelete="CASCADE"),
        nullable=True,
    )
    resume_version_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("resume_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    chunk_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("resume_chunks.id", ondelete="SET NULL"),
        nullable=True,
    )

    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    start_char: Mapped[int] = mapped_column(Integer, nullable=False)
    end_char: Mapped[int] = mapped_column(Integer, nullable=False)
    quoted_text: Mapped[str] = mapped_column(Text, nullable=False)
    verbatim_verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    relevance: Mapped[float | None] = mapped_column(Float, nullable=True)

    verdict: Mapped[RequirementVerdict | None] = relationship(
        back_populates="evidence_spans"
    )


# ---------------------------------------------------------------------------
# Revised-stack tables (ARCHITECTURE-AGENTS.md §10)
# ---------------------------------------------------------------------------


class RunTask(TimestampMixin, Base):
    """One unit of work in the screening pipeline queue.

    Replaces a Celery/Arq broker. Claimed via ``SELECT ... FOR UPDATE
    SKIP LOCKED``. A rate-limit reschedule sets ``not_before`` and resets
    ``status='pending'`` without consuming a retry attempt — distinct
    from a genuine failure (status='failed', attempt incremented).
    """

    __tablename__ = "run_tasks"
    __table_args__ = (
        Index("ix_run_tasks_run_status", "run_id", "status", "not_before"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, index=True
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("screening_runs.id", ondelete="CASCADE"),
        nullable=False,
    )

    stage: Mapped[str] = mapped_column(String(64), nullable=False)
    agent_name: Mapped[str] = mapped_column(
        String(64), nullable=False, default=""
    )
    candidate_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    requirement_group: Mapped[dict[str, object] | None] = mapped_column(
        JSONB, nullable=True
    )

    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    claimed_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    not_before: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    payload: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    result: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class AgentResultCache(TimestampMixin, Base):
    """Durable agent result cache — the reproducibility mechanism.

    A cache hit skips an LLM call entirely, so a re-run with an unchanged
    rubric costs ~zero tokens and produces an identical score.
    """

    __tablename__ = "agent_result_cache"
    __table_args__ = (
        Index("ix_agent_result_cache_tenant_agent", "tenant_id", "agent_name"),
    )

    cache_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False
    )
    agent_name: Mapped[str] = mapped_column(String(64), nullable=False)
    agent_version: Mapped[str] = mapped_column(String(32), nullable=False)
    output: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class RateLimitBucket(Base):
    """Per-provider token-bucket state. UNLOGGED — losing it on crash
    is an accepted degradation (bucket resets, worst case: burst of
    provider 429s absorbed by the rate-limit classifier).
    """

    __tablename__ = "rate_limit_buckets"
    __table_args__ = (
        Index(
            "ix_rate_limit_buckets_lookup",
            "provider",
            "model",
            "api_key_hash",
            "window",
            "window_start",
            unique=True,
        ),
        {"prefixes": ["UNLOGGED"]},
    )

    provider: Mapped[str] = mapped_column(String(64), primary_key=True)
    model: Mapped[str] = mapped_column(String(128), primary_key=True)
    api_key_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    window: Mapped[str] = mapped_column(
        String(16), primary_key=True
    )  # 'rpm' | 'tpm' | 'rpd'
    window_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True
    )
    used: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    cap: Mapped[int] = mapped_column(BigInteger, nullable=False)


class RunCheckpoint(TimestampMixin, Base):
    """Heartbeat for resume-after-restart. One row per run."""

    __tablename__ = "run_checkpoints"

    run_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("screening_runs.id", ondelete="CASCADE"),
        primary_key=True,
    )
    last_stage: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    heartbeat_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=func.now
    )
    resumed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class AtsComplianceReport(TimestampMixin, Base):
    """ATS keyword/format compliance sidecar — never blended into overall_score."""

    __tablename__ = "ats_compliance_reports"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, index=True
    )
    resume_version_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False
    )
    rubric_version_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )

    keyword_coverage: Mapped[float] = mapped_column(Float, nullable=False)
    matched_keywords: Mapped[list[str] | None] = mapped_column(
        ARRAY(String), nullable=True
    )
    missing_keywords: Mapped[list[str] | None] = mapped_column(
        ARRAY(String), nullable=True
    )
    format_flags: Mapped[dict[str, object] | None] = mapped_column(
        JSONB, nullable=True
    )
    compliance_score: Mapped[float] = mapped_column(Float, nullable=False)
    is_ats_safe: Mapped[bool] = mapped_column(Boolean, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=func.now
    )


class FraudFlag(TimestampMixin, Base):
    """Deception signals — distinct from verdicts, never scored."""

    __tablename__ = "fraud_flags"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, index=True
    )
    score_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("candidate_scores.id", ondelete="CASCADE"),
        nullable=False,
    )

    signal_type: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    related_requirement_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    judge_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(32), nullable=True)


class BiasFlag(TimestampMixin, Base):
    """Language-bias findings in generated text — distinct from verdicts."""

    __tablename__ = "bias_flags"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, index=True
    )
    score_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("candidate_scores.id", ondelete="CASCADE"),
        nullable=False,
    )

    source: Mapped[str] = mapped_column(String(32), nullable=False)
    text_excerpt: Mapped[str] = mapped_column(Text, nullable=False)
    bias_category: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    judge_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(32), nullable=True)

