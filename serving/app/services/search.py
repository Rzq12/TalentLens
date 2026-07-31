"""Hybrid semantic and lexical talent search.

Orchestrates the retrieval pipeline described in ARCHITECTURE.md §12.4:
query → embed → hybrid recall (dense + lexical) → RRF fusion → rerank →
group by candidate → aggregate → return ranked results with evidence spans.

No LLM in this path — search is sub-second and free.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.logging import get_logger
from app.repositories.search import ChunkRepository, ChunkWithScore
from app.services.embedding import EmbeddingService
from app.services.reranker import RerankerService

logger = get_logger(__name__)


class SearchMode(str, Enum):
    """Search retrieval strategy."""

    HYBRID = "hybrid"
    SEMANTIC = "semantic"
    LEXICAL = "lexical"


@dataclass(frozen=True, slots=True)
class EvidenceSpan:
    """One piece of supporting evidence from a search result.

    Attributes:
        chunk_id: The chunk this evidence comes from.
        content: The chunk text.
        section: Resume section (experience, skills, etc.).
        page_from: Starting page (0-based).
        page_to: Ending page (0-based).
        start_char: Starting character offset in the full document.
        end_char: Ending character offset in the full document.
        score: Retrieval score for this chunk.
    """

    chunk_id: uuid.UUID
    content: str
    section: str
    page_from: int
    page_to: int
    start_char: int
    end_char: int
    score: float


@dataclass(frozen=True, slots=True)
class CandidateSearchHit:
    """One candidate in search results.

    Attributes:
        document_id: The resume document ID.
        score: Aggregated relevance score across all matching chunks.
        spans: The best supporting evidence spans.
    """

    document_id: uuid.UUID
    score: float
    spans: list[EvidenceSpan] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class SearchResult:
    """Complete search result set.

    Attributes:
        items: Ranked candidate hits.
        count: Total number of candidates returned.
        query: The original query text.
        mode: The search mode used.
    """

    items: list[CandidateSearchHit]
    count: int
    query: str
    mode: str


def reciprocal_rank_fusion(
    ranked_lists: list[list[ChunkWithScore]],
    weights: list[float],
    k: int = 60,
) -> list[ChunkWithScore]:
    """Fuse multiple ranked lists using Reciprocal Rank Fusion.

    RRF score for a document d = sum(weight_i / (k + rank_i(d))) across lists.

    Args:
        ranked_lists: Lists of ranked chunks from different retrieval methods.
        weights: Weight for each list (must sum to ~1.0).
        k: RRF constant (default 60, standard value).

    Returns:
        A single fused list sorted by descending RRF score.
    """
    scores: dict[uuid.UUID, float] = defaultdict(float)
    chunk_map: dict[uuid.UUID, ChunkWithScore] = {}

    for ranked_list, weight in zip(ranked_lists, weights, strict=False):
        for rank, item in enumerate(ranked_list):
            rrf_score = weight / (k + rank + 1)
            scores[item.chunk.id] += rrf_score
            # Keep the chunk with the highest individual score
            if item.chunk.id not in chunk_map or item.score > chunk_map[item.chunk.id].score:
                chunk_map[item.chunk.id] = item

    # Build fused results
    fused = [
        ChunkWithScore(chunk=chunk_map[chunk_id].chunk, score=score)
        for chunk_id, score in scores.items()
    ]
    fused.sort(key=lambda x: x.score, reverse=True)
    return fused


def group_by_candidate(
    chunks: list[ChunkWithScore],
    max_spans_per_candidate: int = 5,
) -> list[CandidateSearchHit]:
    """Group chunks by candidate (document_id) and aggregate scores.

    Per-candidate score is the sum of the best chunk scores (not mean, so
    candidates with more matching evidence rank higher).

    Args:
        chunks: Scored chunks from retrieval.
        max_spans_per_candidate: Maximum evidence spans to include per candidate.

    Returns:
        Candidates sorted by descending aggregate score.
    """
    by_document: dict[uuid.UUID, list[ChunkWithScore]] = defaultdict(list)
    for chunk in chunks:
        by_document[chunk.chunk.document_id].append(chunk)

    hits: list[CandidateSearchHit] = []
    for doc_id, doc_chunks in by_document.items():
        # Sort chunks by score descending
        doc_chunks.sort(key=lambda c: c.score, reverse=True)
        best = doc_chunks[:max_spans_per_candidate]

        # Aggregate score: sum of best chunk scores
        total_score = sum(c.score for c in best)

        spans = [
            EvidenceSpan(
                chunk_id=c.chunk.id,
                content=c.chunk.content,
                section=c.chunk.section,
                page_from=c.chunk.page_from,
                page_to=c.chunk.page_to,
                start_char=c.chunk.start_char,
                end_char=c.chunk.end_char,
                score=c.score,
            )
            for c in best
        ]
        hits.append(CandidateSearchHit(
            document_id=doc_id,
            score=total_score,
            spans=spans,
        ))

    hits.sort(key=lambda h: h.score, reverse=True)
    return hits


async def search_candidates(
    *,
    session: AsyncSession,
    embedder: EmbeddingService,
    reranker: RerankerService,
    tenant_id: uuid.UUID,
    query: str,
    top_k: int = 10,
    mode: SearchMode = SearchMode.HYBRID,
    settings: Settings | None = None,
) -> SearchResult:
    """Execute a hybrid talent search across the candidate pool.

    Pipeline:
    1. Embed query
    2. Dense retrieval (pgvector HNSW cosine)
    3. Lexical retrieval (GIN tsvector ts_rank_cd)
    4. RRF fusion (configurable weights)
    5. Cross-encoder rerank
    6. Group by candidate, aggregate scores
    7. Return ranked results with evidence spans

    Args:
        session: Database session.
        embedder: Embedding service.
        reranker: Reranker service.
        tenant_id: Owning tenant.
        query: Natural-language search query.
        top_k: Maximum candidates to return.
        mode: Retrieval strategy.
        settings: Optional configuration override.

    Returns:
        Ranked search results with evidence spans.
    """
    cfg = settings or get_settings()
    repo = ChunkRepository(session)

    recall_k = cfg.search_top_k_recall

    # Step 1: Retrieve
    if mode == SearchMode.HYBRID:
        query_embedding = await embedder.embed_query(query)
        dense_results = await repo.search_dense(tenant_id, query_embedding, recall_k)
        lexical_results = await repo.search_lexical(tenant_id, query, recall_k)

        # Step 2: RRF fusion
        fused = reciprocal_rank_fusion(
            [dense_results, lexical_results],
            [cfg.search_dense_weight, cfg.search_lexical_weight],
        )
    elif mode == SearchMode.SEMANTIC:
        query_embedding = await embedder.embed_query(query)
        fused = await repo.search_dense(tenant_id, query_embedding, recall_k)
    else:  # LEXICAL
        fused = await repo.search_lexical(tenant_id, query, recall_k)

    if not fused:
        return SearchResult(items=[], count=0, query=query, mode=mode.value)

    # Step 3: Rerank
    rerank_input = [c.chunk.content for c in fused]
    rerank_results = await reranker.rerank(
        query, rerank_input, cfg.search_rerank_top_k
    )

    # Map rerank results back to chunks
    reranked: list[ChunkWithScore] = []
    for rr in rerank_results:
        if rr.index < len(fused):
            reranked.append(
                ChunkWithScore(chunk=fused[rr.index].chunk, score=rr.score)
            )

    # Step 4: Group by candidate
    candidates = group_by_candidate(reranked or fused)

    # Step 5: Trim to top_k
    candidates = candidates[:top_k]

    logger.info(
        "search_completed",
        tenant_id=str(tenant_id),
        query_length=len(query),
        mode=mode.value,
        candidates_returned=len(candidates),
        total_chunks_recalled=len(fused),
    )

    return SearchResult(
        items=candidates,
        count=len(candidates),
        query=query,
        mode=mode.value,
    )


async def search_similar(
    *,
    session: AsyncSession,
    embedder: EmbeddingService,
    reranker: RerankerService,
    tenant_id: uuid.UUID,
    document_id: uuid.UUID,
    top_k: int = 10,
    settings: Settings | None = None,
) -> SearchResult:
    """Find candidates similar to a given document ("more like this").

    Embeds the candidate's chunks, aggregates them, and searches for similar
    chunks across the corpus — excluding the source document itself.

    Args:
        session: Database session.
        embedder: Embedding service.
        reranker: Reranker service.
        tenant_id: Owning tenant.
        document_id: Source document to find similar candidates for.
        top_k: Maximum candidates to return.
        settings: Optional configuration override.

    Returns:
        Ranked search results for similar candidates.
    """
    cfg = settings or get_settings()
    repo = ChunkRepository(session)

    # Get the source document's chunks
    source_chunks = await repo.get_by_document(
        tenant_id, document_id, children_only=True
    )

    if not source_chunks:
        return SearchResult(
            items=[], count=0, query=f"similar:{document_id}", mode="similar"
        )

    # Use the source chunks' content to build a representative query
    # Take the first few chunks to avoid exceeding embedding limits
    representative_texts = [c.content for c in source_chunks[:5]]
    query_text = " ".join(representative_texts)[:2000]

    query_embedding = await embedder.embed_query(query_text)

    # Search across all chunks, then filter out the source document
    all_results = await repo.search_dense(
        tenant_id, query_embedding, cfg.search_top_k_recall * 2
    )

    # Filter out chunks from the source document
    filtered = [r for r in all_results if r.chunk.document_id != document_id]

    # Group by candidate
    candidates = group_by_candidate(filtered)[:top_k]

    logger.info(
        "similar_search_completed",
        tenant_id=str(tenant_id),
        source_document_id=str(document_id),
        candidates_returned=len(candidates),
    )

    return SearchResult(
        items=candidates,
        count=len(candidates),
        query=f"similar:{document_id}",
        mode="similar",
    )
