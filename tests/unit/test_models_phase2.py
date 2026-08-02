"""Regression tests for the Phase 2 `ResumeChunk` ORM model.

Two defects made the model unusable and are pinned here:

* ``embedding`` was annotated ``Mapped[list[float] | None]`` with no Core type,
  so importing ``app.models`` raised ``MappedAnnotationError`` and the whole
  application failed to start.
* ``is_parent`` was created by the migration but never declared on the model,
  so every query filtering on it (dense retrieval does) hit a column the ORM
  did not know about.

These cases construct objects in memory only — no database is required.
"""

from __future__ import annotations

import uuid

from pgvector.sqlalchemy import Vector

from app.models import ResumeChunk


def _chunk(**overrides: object) -> ResumeChunk:
    """Build a `ResumeChunk` with valid defaults, overriding named fields.

    Args:
        **overrides: Column values to replace in the baseline row.

    Returns:
        An unsaved `ResumeChunk` instance.
    """
    fields: dict[str, object] = {
        "tenant_id": uuid.uuid4(),
        "resume_version_id": uuid.uuid4(),
        "document_id": uuid.uuid4(),
        "chunk_index": 0,
        "section": "experience",
        "content": "Senior Backend Engineer — Python, Kubernetes, PostgreSQL",
        "page_from": 0,
        "page_to": 0,
        "start_char": 0,
        "end_char": 56,
        "token_count": 8,
        "embedding_model": "BAAI/bge-m3",
        "embedding_version": "1",
        "is_parent": False,
    }
    fields.update(overrides)
    return ResumeChunk(**fields)


def test_resume_chunk_embedding_column_uses_pgvector_type() -> None:
    """`embedding` must map to `vector(1024)`, not an unresolvable Python type."""
    column = ResumeChunk.__table__.columns["embedding"]

    assert isinstance(column.type, Vector)
    assert column.type.dim == 1024
    assert column.nullable is True


def test_resume_chunk_declares_is_parent_matching_the_migration() -> None:
    """`is_parent` must exist on the model, non-nullable, defaulting to false."""
    column = ResumeChunk.__table__.columns["is_parent"]

    assert column.nullable is False
    assert _chunk().is_parent is False


def test_resume_chunk_accepts_an_embedding_vector() -> None:
    """A 1024-dimension vector round-trips onto the instance unchanged."""
    embedding = [0.01] * 1024

    chunk = _chunk(embedding=embedding)

    assert chunk.embedding == embedding


def test_resume_chunk_embedding_defaults_to_none_before_backfill() -> None:
    """Chunks are insertable before embeddings exist, so the column stays optional."""
    assert _chunk().embedding is None


def test_resume_chunk_parent_and_child_are_distinguishable() -> None:
    """Parents carry `is_parent`; children point back through `parent_chunk_id`."""
    parent_id = uuid.uuid4()

    parent = _chunk(id=parent_id, is_parent=True)
    child = _chunk(chunk_index=1, parent_chunk_id=parent_id, is_parent=False)

    assert parent.is_parent is True
    assert parent.parent_chunk_id is None
    assert child.is_parent is False
    assert child.parent_chunk_id == parent_id


def test_resume_chunk_content_tsv_column_uses_tsvector_type() -> None:
    """`content_tsv` must be TSVECTOR to match the migration's generated column.

    The migration creates `content_tsv` as a PostgreSQL tsvector GENERATED column.
    If the model declares it as Text, `Base.metadata.create_all()` will build
    a TEXT column instead, and queries like `content_tsv @@ plainto_tsquery(...)`
    will fail at runtime.
    """
    from sqlalchemy.dialects.postgresql import TSVECTOR

    column = ResumeChunk.__table__.columns["content_tsv"]

    assert isinstance(column.type, TSVECTOR), (
        f"content_tsv type is {type(column.type).__name__}, not TSVECTOR — "
        "this breaks lexical search with the @@ operator"
    )
    assert column.nullable is True
