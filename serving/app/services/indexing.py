"""Bridges ingestion and search by turning a resume version into search rows.

Phase 2 shipped chunking, embedding, and retrieval as separate pieces, but
nothing joined them: uploading a resume wrote a ``resume_documents`` row and a
``resume_versions`` row and stopped. ``resume_chunks`` stayed empty, so every
search returned zero results no matter how many resumes had been uploaded.

This module is that join. Given a parsed version, it chunks the text, embeds
the child chunks, and persists both parents and children.

Only children are embedded. Dense retrieval filters on ``is_parent = false``
(see :mod:`app.repositories.search`), so a parent vector could never be
returned — computing one would spend embedding budget and vector storage on a
row no query can reach. Parents exist to be expanded into LLM context after
their children match.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.config import get_settings
from app.logging import get_logger
from app.models import ResumeChunk, ResumeVersion
from app.repositories.search import ChunkRepositoryProtocol
from app.services.chunking import (
    CHILD_CHUNK_WORDS,
    PARENT_CHUNK_WORDS,
    ChunkInfo,
    chunk_document,
)
from app.services.embedding import EmbeddingService

logger = get_logger(__name__)

# Chunks are embedded in batches so one oversized resume cannot build a single
# request large enough for the embedding backend to reject.
EMBED_BATCH_SIZE = 32


@dataclass(frozen=True, slots=True)
class IndexingResult:
    """Outcome of indexing one resume version.

    Attributes:
        chunks_created: Total chunks persisted (parents plus children).
        parent_chunks: Number of parent chunks persisted.
        child_chunks: Number of child chunks persisted and embedded.
        skipped_reason: Why nothing was indexed, or None if indexing ran.
        truncated_children: Children dropped for exceeding the per-document cap.
            Non-zero means part of this resume is not searchable.
    """

    chunks_created: int
    parent_chunks: int
    child_chunks: int
    skipped_reason: str | None = None
    truncated_children: int = 0


def _normalize_page_offsets(
    page_offsets: list[dict[str, object]] | None,
) -> list[dict[str, int]]:
    """Coerce JSONB page offsets into the integer shape chunking expects.

    ``ResumeVersion.page_offsets`` is JSONB, so its values arrive typed as
    ``object``. Chunking resolves character offsets to page numbers and needs
    integers.

    Args:
        page_offsets: Raw page boundary records from the parser.

    Returns:
        Page records with integer ``page``, ``start_char``, and ``end_char``.
        Malformed records are dropped rather than raising — a bad offset costs
        page attribution on a citation, which is not worth failing an upload.
    """
    if not page_offsets:
        return []

    normalized: list[dict[str, int]] = []
    for entry in page_offsets:
        if not isinstance(entry, dict):
            continue
        try:
            normalized.append(
                {
                    "page": int(entry.get("page", 0)),  # type: ignore[arg-type]
                    "start_char": int(entry.get("start_char", 0)),  # type: ignore[arg-type]
                    "end_char": int(entry.get("end_char", 0)),  # type: ignore[arg-type]
                }
            )
        except (TypeError, ValueError):
            continue
    return normalized


def _to_orm_chunk(
    info: ChunkInfo,
    version: ResumeVersion,
    *,
    embedding: list[float] | None,
    embedding_model: str,
    embedding_version: str,
) -> ResumeChunk:
    """Build a persistable chunk row from a chunking result.

    Args:
        info: The chunk produced by :func:`chunk_document`.
        version: The resume version the chunk belongs to.
        embedding: Vector for this chunk, or None for parents.
        embedding_model: Model identifier to stamp on the row.
        embedding_version: Model version to stamp on the row.

    Returns:
        An unsaved `ResumeChunk` carrying tenant and document scope.
    """
    return ResumeChunk(
        id=info.chunk_id,
        tenant_id=version.tenant_id,
        resume_version_id=version.id,
        document_id=version.document_id,
        chunk_index=info.chunk_index,
        parent_chunk_id=info.parent_chunk_id,
        section=info.section,
        content=info.content,
        page_from=info.page_from,
        page_to=info.page_to,
        start_char=info.start_char,
        end_char=info.end_char,
        token_count=info.token_count,
        embedding=embedding,
        embedding_model=embedding_model,
        embedding_version=embedding_version,
        is_parent=info.is_parent,
    )


async def index_resume_version(
    *,
    version: ResumeVersion,
    chunk_repo: ChunkRepositoryProtocol,
    embedder: EmbeddingService,
    replace_existing: bool = False,
    child_words: int = CHILD_CHUNK_WORDS,
    parent_words: int = PARENT_CHUNK_WORDS,
    max_child_chunks: int | None = None,
) -> IndexingResult:
    """Chunk, embed, and persist a resume version so search can find it.

    Args:
        version: The parsed version to index.
        chunk_repo: Repository exposing ``upsert_chunks`` and
            ``delete_by_document``.
        embedder: Embedding service used for child chunks.
        replace_existing: If True, delete the document's existing chunks first.
            Set this when re-parsing or re-embedding; leaving it False on a
            re-run would duplicate every chunk.
        child_words: Target words per child chunk.
        parent_words: Target words per parent chunk.
        max_child_chunks: Ceiling on children embedded for this document.
            Defaults to ``settings.indexing_max_child_chunks``. Children beyond
            the cap are dropped, and the document is indexed with what fits
            rather than failing the upload.

    Returns:
        An `IndexingResult` describing what was written, or why nothing was.
    """
    if max_child_chunks is None:
        max_child_chunks = get_settings().indexing_max_child_chunks

    if version.quarantined:
        # Quarantined text is suspected of steering a downstream model.
        # Indexing it would put it into search results and, in Phase 4, into an
        # LLM context — the exact reach quarantine exists to deny.
        logger.warning(
            "indexing_skipped_quarantined",
            tenant_id=str(version.tenant_id),
            document_id=str(version.document_id),
            resume_version_id=str(version.id),
            injection_risk_score=version.injection_risk_score,
        )
        return IndexingResult(
            chunks_created=0,
            parent_chunks=0,
            child_chunks=0,
            skipped_reason="quarantined",
        )

    chunk_infos = chunk_document(
        version.extracted_text,
        page_offsets=_normalize_page_offsets(version.page_offsets),
        child_words=child_words,
        parent_words=parent_words,
    )

    if not chunk_infos:
        logger.info(
            "indexing_skipped_empty_text",
            tenant_id=str(version.tenant_id),
            document_id=str(version.document_id),
            resume_version_id=str(version.id),
        )
        return IndexingResult(
            chunks_created=0,
            parent_chunks=0,
            child_chunks=0,
            skipped_reason="empty_text",
        )

    if replace_existing:
        deleted = await chunk_repo.delete_by_document(
            version.tenant_id, version.document_id
        )
        logger.info(
            "indexing_cleared_prior_chunks",
            tenant_id=str(version.tenant_id),
            document_id=str(version.document_id),
            deleted=deleted,
        )

    children = [info for info in chunk_infos if not info.is_parent]

    # Cap the embedded set. Embedding is a sequential run of awaited HTTP calls
    # made while this request holds a pooled connection, so an unbounded document
    # would hold that connection long enough to starve the pool for every other
    # tenant. Parents are kept regardless: they cost no embedding calls and are
    # only reachable through a child, so dropping children never orphans one.
    truncated_children = max(0, len(children) - max_child_chunks)
    if truncated_children:
        children = children[:max_child_chunks]
        child_ids = {info.chunk_id for info in children}
        chunk_infos = [
            info for info in chunk_infos if info.is_parent or info.chunk_id in child_ids
        ]
        logger.warning(
            "indexing_truncated_child_chunks",
            tenant_id=str(version.tenant_id),
            document_id=str(version.document_id),
            resume_version_id=str(version.id),
            embedded=len(children),
            dropped=truncated_children,
            max_child_chunks=max_child_chunks,
        )

    # Embed children in batches, keeping the result aligned with `children` by
    # position. A mismatch would silently attach the wrong vector to a chunk,
    # so the alignment is checked below rather than assumed.
    vectors: list[list[float]] = []
    for start in range(0, len(children), EMBED_BATCH_SIZE):
        batch = children[start : start + EMBED_BATCH_SIZE]
        vectors.extend(await embedder.embed_texts([info.content for info in batch]))

    if len(vectors) != len(children):
        raise ValueError(
            f"embedding service returned {len(vectors)} vectors for "
            f"{len(children)} child chunks"
        )

    embedding_by_chunk_id = {
        info.chunk_id: vector for info, vector in zip(children, vectors, strict=True)
    }

    rows = [
        _to_orm_chunk(
            info,
            version,
            embedding=embedding_by_chunk_id.get(info.chunk_id),
            embedding_model=embedder.model_name,
            embedding_version=embedder.model_version,
        )
        for info in chunk_infos
    ]

    await chunk_repo.upsert_chunks(rows)

    parent_count = sum(1 for info in chunk_infos if info.is_parent)
    logger.info(
        "resume_version_indexed",
        tenant_id=str(version.tenant_id),
        document_id=str(version.document_id),
        resume_version_id=str(version.id),
        chunks_created=len(rows),
        parent_chunks=parent_count,
        child_chunks=len(children),
        truncated_children=truncated_children,
        embedding_model=embedder.model_name,
        embedding_version=embedder.model_version,
    )

    return IndexingResult(
        chunks_created=len(rows),
        parent_chunks=parent_count,
        child_chunks=len(children),
        skipped_reason=None,
        truncated_children=truncated_children,
    )
