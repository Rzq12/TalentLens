"""Data access for resume chunks and vector search.

This is the only layer permitted to query the ``resume_chunks`` table.
Hybrid retrieval (dense + lexical) is implemented here because the query
construction is tightly coupled to the pgvector and tsvector index structure.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ResumeChunk


@dataclass(frozen=True, slots=True)
class ChunkWithScore:
    """A chunk paired with a retrieval score.

    Attributes:
        chunk: The retrieved chunk.
        score: Retrieval score (cosine similarity, ts_rank, or fused).
    """

    chunk: ResumeChunk
    score: float


class ChunkRepositoryProtocol(Protocol):
    """Interface required by indexing and search services."""

    async def upsert_chunks(self, chunks: list[ResumeChunk]) -> None:
        """Persist a batch of chunks."""
        ...

    async def delete_by_document(
        self, tenant_id: uuid.UUID, document_id: uuid.UUID
    ) -> int:
        """Delete all chunks for a document."""
        ...


class ChunkRepository:
    """Persistence and retrieval for resume chunks with embeddings."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the repository.

        Args:
            session: An active async session.
        """
        self._session = session

    async def upsert_chunks(self, chunks: list[ResumeChunk]) -> None:
        """Persist a batch of chunks.

        Args:
            chunks: Chunks to insert.
        """
        for chunk in chunks:
            self._session.add(chunk)
        await self._session.flush()

    async def delete_by_document(
        self, tenant_id: uuid.UUID, document_id: uuid.UUID
    ) -> int:
        """Delete all chunks for a document.

        Used when re-embedding or re-parsing a document.

        Args:
            tenant_id: Owning tenant.
            document_id: Document to clear.

        Returns:
            Number of rows deleted.
        """
        stmt = delete(ResumeChunk).where(
            ResumeChunk.tenant_id == tenant_id,
            ResumeChunk.document_id == document_id,
        )
        result = await self._session.execute(stmt)
        return result.rowcount  # type: ignore[return-value]

    async def search_dense(
        self,
        tenant_id: uuid.UUID,
        embedding: list[float],
        top_k: int = 20,
        *,
        document_id: uuid.UUID | None = None,
    ) -> list[ChunkWithScore]:
        """Dense vector search using pgvector cosine distance.

        Args:
            tenant_id: Owning tenant (isolation filter).
            embedding: Query embedding vector.
            top_k: Maximum results.
            document_id: Optional filter to scope results to one document.

        Returns:
            Chunks ordered by descending cosine similarity.
        """
        # Use raw SQL for pgvector operator support
        vec_str = "[" + ",".join(str(v) for v in embedding) + "]"

        params: dict[str, object] = {
            "tenant_id": str(tenant_id),
            "top_k": top_k,
            "embedding": vec_str,
        }

        if document_id is not None:
            params["document_id"] = str(document_id)
            query = text("""
                SELECT id, tenant_id, resume_version_id, document_id,
                       chunk_index, parent_chunk_id, section, content,
                       page_from, page_to, start_char, end_char,
                       token_count, embedding_model, embedding_version,
                       1 - (embedding <=> :embedding::vector) AS score
                FROM resume_chunks
                WHERE tenant_id = :tenant_id
                  AND embedding IS NOT NULL
                  AND is_parent = false
                  AND document_id = :document_id
                ORDER BY embedding <=> :embedding::vector
                LIMIT :top_k
            """)
        else:
            query = text("""
                SELECT id, tenant_id, resume_version_id, document_id,
                       chunk_index, parent_chunk_id, section, content,
                       page_from, page_to, start_char, end_char,
                       token_count, embedding_model, embedding_version,
                       1 - (embedding <=> :embedding::vector) AS score
                FROM resume_chunks
                WHERE tenant_id = :tenant_id
                  AND embedding IS NOT NULL
                  AND is_parent = false
                ORDER BY embedding <=> :embedding::vector
                LIMIT :top_k
            """)

        result = await self._session.execute(query, params)
        rows = result.fetchall()

        chunks: list[ChunkWithScore] = []
        for row in rows:
            chunk = ResumeChunk(
                id=uuid.UUID(str(row.id)),
                tenant_id=uuid.UUID(str(row.tenant_id)),
                resume_version_id=uuid.UUID(str(row.resume_version_id)),
                document_id=uuid.UUID(str(row.document_id)),
                chunk_index=row.chunk_index,
                parent_chunk_id=(
                    uuid.UUID(str(row.parent_chunk_id))
                    if row.parent_chunk_id
                    else None
                ),
                section=row.section,
                content=row.content,
                page_from=row.page_from,
                page_to=row.page_to,
                start_char=row.start_char,
                end_char=row.end_char,
                token_count=row.token_count,
                embedding_model=row.embedding_model,
                embedding_version=row.embedding_version,
            )
            chunks.append(ChunkWithScore(chunk=chunk, score=float(row.score)))
        return chunks

    async def search_lexical(
        self,
        tenant_id: uuid.UUID,
        query: str,
        top_k: int = 20,
        *,
        document_id: uuid.UUID | None = None,
    ) -> list[ChunkWithScore]:
        """Lexical search using PostgreSQL tsvector and ts_rank_cd.

        Args:
            tenant_id: Owning tenant.
            query: Raw search query text.
            top_k: Maximum results.
            document_id: Optional filter to scope results to one document.

        Returns:
            Chunks ordered by descending ts_rank_cd score.
        """
        params: dict[str, object] = {
            "tenant_id": str(tenant_id),
            "query": query,
            "top_k": top_k,
        }

        if document_id is not None:
            params["document_id"] = str(document_id)
            sql = text("""
                SELECT id, tenant_id, resume_version_id, document_id,
                       chunk_index, parent_chunk_id, section, content,
                       page_from, page_to, start_char, end_char,
                       token_count, embedding_model, embedding_version,
                       ts_rank_cd(content_tsv, plainto_tsquery('english', :query)) AS score
                FROM resume_chunks
                WHERE tenant_id = :tenant_id
                  AND content_tsv IS NOT NULL
                  AND content_tsv @@ plainto_tsquery('english', :query)
                  AND document_id = :document_id
                ORDER BY score DESC
                LIMIT :top_k
            """)
        else:
            sql = text("""
                SELECT id, tenant_id, resume_version_id, document_id,
                       chunk_index, parent_chunk_id, section, content,
                       page_from, page_to, start_char, end_char,
                       token_count, embedding_model, embedding_version,
                       ts_rank_cd(content_tsv, plainto_tsquery('english', :query)) AS score
                FROM resume_chunks
                WHERE tenant_id = :tenant_id
                  AND content_tsv IS NOT NULL
                  AND content_tsv @@ plainto_tsquery('english', :query)
                ORDER BY score DESC
                LIMIT :top_k
            """)

        result = await self._session.execute(sql, params)
        rows = result.fetchall()

        chunks: list[ChunkWithScore] = []
        for row in rows:
            chunk = ResumeChunk(
                id=uuid.UUID(str(row.id)),
                tenant_id=uuid.UUID(str(row.tenant_id)),
                resume_version_id=uuid.UUID(str(row.resume_version_id)),
                document_id=uuid.UUID(str(row.document_id)),
                chunk_index=row.chunk_index,
                parent_chunk_id=(
                    uuid.UUID(str(row.parent_chunk_id))
                    if row.parent_chunk_id
                    else None
                ),
                section=row.section,
                content=row.content,
                page_from=row.page_from,
                page_to=row.page_to,
                start_char=row.start_char,
                end_char=row.end_char,
                token_count=row.token_count,
                embedding_model=row.embedding_model,
                embedding_version=row.embedding_version,
            )
            chunks.append(ChunkWithScore(chunk=chunk, score=float(row.score)))
        return chunks

    async def get_parents(
        self,
        tenant_id: uuid.UUID,
        chunk_ids: list[uuid.UUID],
    ) -> list[ResumeChunk]:
        """Retrieve parent chunks by their IDs, scoped to one tenant.

        Used for parent expansion after child retrieval. ``tenant_id`` is required
        rather than optional: the expanded text feeds LLM context, so isolation must
        be enforced by the query itself and not left to caller discipline.

        Args:
            tenant_id: Owning tenant. Chunks belonging to any other tenant are
                excluded even if their IDs appear in ``chunk_ids``.
            chunk_ids: Parent chunk IDs to fetch.

        Returns:
            The parent chunks owned by ``tenant_id``.
        """
        if not chunk_ids:
            return []
        stmt = select(ResumeChunk).where(
            ResumeChunk.tenant_id == tenant_id,
            ResumeChunk.id.in_(chunk_ids),
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_document(
        self,
        tenant_id: uuid.UUID,
        document_id: uuid.UUID,
        *,
        children_only: bool = False,
    ) -> Sequence[ResumeChunk]:
        """Return all chunks for a document.

        Args:
            tenant_id: Owning tenant.
            document_id: Document identifier.
            children_only: If True, exclude parent chunks.

        Returns:
            Chunks ordered by chunk_index.
        """
        stmt = (
            select(ResumeChunk)
            .where(
                ResumeChunk.tenant_id == tenant_id,
                ResumeChunk.document_id == document_id,
            )
            .order_by(ResumeChunk.chunk_index)
        )
        if children_only:
            stmt = stmt.where(ResumeChunk.parent_chunk_id.isnot(None))
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def count_by_tenant(self, tenant_id: uuid.UUID) -> int:
        """Count total chunks for a tenant.

        Args:
            tenant_id: Owning tenant.

        Returns:
            Total chunk count.
        """
        stmt = (
            select(func.count())
            .select_from(ResumeChunk)
            .where(ResumeChunk.tenant_id == tenant_id)
        )
        result = await self._session.execute(stmt)
        return int(result.scalar() or 0)
