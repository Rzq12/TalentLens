"""Tests for the indexing service that bridges ingestion and search.

Phase 2 shipped chunking, embedding, and search, but nothing wired them to
ingestion — uploading a resume created a document and a version and stopped
there, so `resume_chunks` stayed empty and every search returned zero results.

These tests pin the missing link: a resume version must be chunked, embedded,
and persisted so search can find it.
"""

from __future__ import annotations

import uuid

import pytest

from app.models import ResumeVersion
from app.services.embedding import MockEmbeddingService


class _FakeChunkRepository:
    """Records what the indexer persists, without a database.

    Attributes:
        upserted: Chunks handed to `upsert_chunks`, in call order.
        deleted: (tenant_id, document_id) pairs passed to `delete_by_document`.
    """

    def __init__(self) -> None:
        """Start with no recorded calls."""
        self.upserted: list[object] = []
        self.deleted: list[tuple[uuid.UUID, uuid.UUID]] = []

    async def upsert_chunks(self, chunks: list[object]) -> None:
        """Record a batch of chunks.

        Args:
            chunks: Chunks the indexer wants to persist.
        """
        self.upserted.extend(chunks)

    async def delete_by_document(
        self, tenant_id: uuid.UUID, document_id: uuid.UUID
    ) -> int:
        """Record a delete request.

        Args:
            tenant_id: Owning tenant.
            document_id: Document being cleared.

        Returns:
            Number of rows notionally deleted.
        """
        self.deleted.append((tenant_id, document_id))
        return 0


def _version(text: str) -> ResumeVersion:
    """Build an unsaved `ResumeVersion` carrying `text`.

    Args:
        text: Extracted resume text.

    Returns:
        A `ResumeVersion` with valid identifiers and no database row.
    """
    return ResumeVersion(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        version=1,
        extracted_text=text,
        text_sha256="0" * 64,
        page_offsets=[],
        parser_version="test-1",
        sanitization_report={},
        injection_risk_score=0.0,
        quarantined=False,
    )


_RESUME_TEXT = """Professional Summary
Senior backend engineer with eight years building distributed systems.

Experience
Staff Engineer at Acme Corp, 2019 to 2025. Led the migration of a monolith to
event-driven services on Kubernetes. Cut p99 latency from 1200ms to 180ms.

Skills
Python, Go, PostgreSQL, Kafka, Kubernetes, Terraform.
"""


@pytest.mark.asyncio
async def test_index_resume_version_persists_chunks() -> None:
    """Indexing a version must persist chunks, or search can never match it."""
    from app.services.indexing import index_resume_version

    repo = _FakeChunkRepository()
    version = _version(_RESUME_TEXT)

    result = await index_resume_version(
        version=version,
        chunk_repo=repo,
        embedder=MockEmbeddingService(dimension=8),
    )

    assert repo.upserted, "no chunks were persisted — search will return nothing"
    assert result.chunks_created == len(repo.upserted)


@pytest.mark.asyncio
async def test_index_resume_version_embeds_only_child_chunks() -> None:
    """Children carry embeddings; parents are context-only and stay unembedded.

    Dense retrieval filters on `is_parent = false`, so embedding parents would
    waste vector budget without ever being searched.
    """
    from app.services.indexing import index_resume_version

    repo = _FakeChunkRepository()

    await index_resume_version(
        version=_version(_RESUME_TEXT),
        chunk_repo=repo,
        embedder=MockEmbeddingService(dimension=8),
    )

    children = [c for c in repo.upserted if not c.is_parent]  # type: ignore[attr-defined]
    parents = [c for c in repo.upserted if c.is_parent]  # type: ignore[attr-defined]

    assert children, "chunking produced no children to embed"
    assert parents, "chunking produced no parents for LLM context"
    assert all(c.embedding is not None for c in children), (
        "some child chunks have no embedding — dense search cannot reach them"
    )
    assert all(c.embedding is None for c in parents), (
        "parent chunks were embedded, but dense search filters them out"
    )


@pytest.mark.asyncio
async def test_index_resume_version_stamps_embedding_provenance() -> None:
    """Every chunk records the model and version that produced its vector.

    Without provenance an embedding-model upgrade cannot be a background
    backfill — you cannot tell which rows are stale.
    """
    from app.services.indexing import index_resume_version

    repo = _FakeChunkRepository()
    embedder = MockEmbeddingService(dimension=8)

    await index_resume_version(
        version=_version(_RESUME_TEXT), chunk_repo=repo, embedder=embedder
    )

    children = [c for c in repo.upserted if not c.is_parent]  # type: ignore[attr-defined]
    assert all(c.embedding_model == embedder.model_name for c in children)
    assert all(c.embedding_version == embedder.model_version for c in children)


@pytest.mark.asyncio
async def test_index_resume_version_carries_tenant_and_document_scope() -> None:
    """Chunks inherit tenant and document IDs, or tenant isolation breaks."""
    from app.services.indexing import index_resume_version

    repo = _FakeChunkRepository()
    version = _version(_RESUME_TEXT)

    await index_resume_version(
        version=version,
        chunk_repo=repo,
        embedder=MockEmbeddingService(dimension=8),
    )

    assert all(c.tenant_id == version.tenant_id for c in repo.upserted)  # type: ignore[attr-defined]
    assert all(c.document_id == version.document_id for c in repo.upserted)  # type: ignore[attr-defined]
    assert all(c.resume_version_id == version.id for c in repo.upserted)  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_index_resume_version_skips_quarantined_documents() -> None:
    """A quarantined resume must not be indexed until a human clears it.

    Its text is suspected of steering a downstream model. Indexing it would put
    that text into search results and, later, into an LLM context.
    """
    from app.services.indexing import index_resume_version

    repo = _FakeChunkRepository()
    version = _version(_RESUME_TEXT)
    version.quarantined = True

    result = await index_resume_version(
        version=version,
        chunk_repo=repo,
        embedder=MockEmbeddingService(dimension=8),
    )

    assert result.chunks_created == 0
    assert result.skipped_reason == "quarantined"
    assert not repo.upserted, "quarantined text reached the search index"


@pytest.mark.asyncio
async def test_index_resume_version_handles_empty_text() -> None:
    """An empty parse indexes nothing rather than raising."""
    from app.services.indexing import index_resume_version

    repo = _FakeChunkRepository()

    result = await index_resume_version(
        version=_version("   "),
        chunk_repo=repo,
        embedder=MockEmbeddingService(dimension=8),
    )

    assert result.chunks_created == 0
    assert not repo.upserted


@pytest.mark.asyncio
async def test_index_resume_version_clears_prior_chunks_when_reindexing() -> None:
    """Re-indexing replaces prior chunks instead of duplicating them."""
    from app.services.indexing import index_resume_version

    repo = _FakeChunkRepository()
    version = _version(_RESUME_TEXT)

    await index_resume_version(
        version=version,
        chunk_repo=repo,
        embedder=MockEmbeddingService(dimension=8),
        replace_existing=True,
    )

    assert (version.tenant_id, version.document_id) in repo.deleted


@pytest.mark.asyncio
async def test_index_resume_version_caps_children_at_the_configured_limit() -> None:
    """An oversized document must not embed without bound.

    Embedding runs inline while the request holds a pooled connection, so an
    unbounded document would starve the connection pool for other tenants.
    """
    from app.services.indexing import index_resume_version

    repo = _FakeChunkRepository()
    long_text = "Engineered scalable distributed systems at scale. " * 2000

    result = await index_resume_version(
        version=_version(long_text),
        chunk_repo=repo,
        embedder=MockEmbeddingService(dimension=8),
        child_words=20,
        parent_words=60,
        max_child_chunks=5,
    )

    assert result.child_chunks == 5
    assert result.truncated_children > 0


@pytest.mark.asyncio
async def test_index_resume_version_persists_only_the_capped_children() -> None:
    """Dropped children must not reach the database unembedded.

    A child row with a NULL embedding is invisible to dense search but still
    occupies storage and would inflate chunk counts.
    """
    from app.services.indexing import index_resume_version

    repo = _FakeChunkRepository()
    long_text = "Engineered scalable distributed systems at scale. " * 2000

    await index_resume_version(
        version=_version(long_text),
        chunk_repo=repo,
        embedder=MockEmbeddingService(dimension=8),
        child_words=20,
        parent_words=60,
        max_child_chunks=5,
    )

    persisted_children = [c for c in repo.upserted if not c.is_parent]  # type: ignore[attr-defined]
    assert len(persisted_children) == 5
    assert all(c.embedding is not None for c in persisted_children)


@pytest.mark.asyncio
async def test_index_resume_version_keeps_every_child_pointing_at_a_stored_parent() -> None:
    """Truncation must not orphan a child, or parent expansion breaks in Phase 4."""
    from app.services.indexing import index_resume_version

    repo = _FakeChunkRepository()
    long_text = "Engineered scalable distributed systems at scale. " * 2000

    await index_resume_version(
        version=_version(long_text),
        chunk_repo=repo,
        embedder=MockEmbeddingService(dimension=8),
        child_words=20,
        parent_words=60,
        max_child_chunks=5,
    )

    parent_ids = {c.id for c in repo.upserted if c.is_parent}  # type: ignore[attr-defined]
    children = [c for c in repo.upserted if not c.is_parent]  # type: ignore[attr-defined]

    assert children
    for child in children:
        assert child.parent_chunk_id in parent_ids


@pytest.mark.asyncio
async def test_index_resume_version_reports_no_truncation_for_a_normal_resume() -> None:
    """The cap must be inert for documents that fit under it."""
    from app.services.indexing import index_resume_version

    repo = _FakeChunkRepository()

    result = await index_resume_version(
        version=_version(_RESUME_TEXT),
        chunk_repo=repo,
        embedder=MockEmbeddingService(dimension=8),
    )

    assert result.truncated_children == 0


@pytest.mark.asyncio
async def test_index_resume_version_rejects_a_misaligned_embedding_response() -> None:
    """A short vector batch would silently attach the wrong vector to a chunk.

    Positional alignment between `children` and `vectors` is what maps a chunk to
    its embedding, so a count mismatch has to fail loudly rather than zip short.
    """
    from app.services.indexing import index_resume_version

    class _ShortEmbedder:
        """Returns one fewer vector than requested."""

        model_name = "broken-embedder"
        model_version = "test-v1"
        dimension = 8

        async def embed_texts(self, texts: list[str]) -> list[list[float]]:
            """Drop the last vector to simulate a truncated backend response.

            Args:
                texts: Texts to embed.

            Returns:
                One vector fewer than ``texts``.
            """
            return [[0.0] * 8 for _ in texts[:-1]]

        async def embed_query(self, text: str) -> list[float]:
            """Return a zero vector.

            Args:
                text: Query text.

            Returns:
                A zero vector.
            """
            return [0.0] * 8

    repo = _FakeChunkRepository()

    with pytest.raises(ValueError, match="vectors"):
        await index_resume_version(
            version=_version(_RESUME_TEXT),
            chunk_repo=repo,
            embedder=_ShortEmbedder(),  # type: ignore[arg-type]
        )

    assert not repo.upserted, "chunks were persisted despite a misaligned batch"
