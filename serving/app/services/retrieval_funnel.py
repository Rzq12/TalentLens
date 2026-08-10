"""Retrieval funnel — multi-stage candidate reduction.

Stage 1: Hybrid recall (pgvector HNSW + GIN tsvector → RRF fuse) — 1000 → 200
Stage 2: Cross-encoder rerank (CPU ONNX or noop) — 200 → 60
Stage 3: LLM judge (SemanticMatchingAgent) — only stage that spends tokens

94% reduction from naive 12,000 calls to 180 calls on 1000-candidate pool.
Free-tier operation depends on this funnel; without it, 12,000 judge calls
would take ~73 minutes on a single Groq key.

ARCHITECTURE-AGENTS.md §2.7 — funnel math, unchanged from original draft.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.logging import get_logger
from app.repositories.search import ChunkRepository, ChunkWithScore
from app.services.embedding import EmbeddingService
from app.services.reranker import RerankerService
from app.services.search import (
    reciprocal_rank_fusion,
)

logger = get_logger(__name__)

# Funnel cutoffs — configurable, measured via recall@K eval harness.
STAGE1_RECALL_K = 200  # dense + lexical → RRF fuse, select top-200
STAGE2_RERANK_TOPK = 60  # cross-encoder rerank to top-60
JUDGE_TOP_K = 60  # final candidates sent to LLM judge


@dataclass
class FunnelResult:
    """Survivor counts at each stage, for explainability."""

    initial_pool: int = 0
    after_recall: int = 0
    after_rerank: int = 0
    final_pool: int = 0


async def run_retrieval_funnel(
    *,
    session: AsyncSession,
    embedder: EmbeddingService,
    reranker: RerankerService,
    tenant_id: uuid.UUID,
    query: str,
    settings: Settings | None = None,
) -> tuple[list[ChunkWithScore], FunnelResult]:
    """Run the full retrieval funnel: dense + lexical → RRF → rerank → top-K.

    Args:
        session: Database session.
        embedder: Embedding service.
        reranker: Reranker service.
        tenant_id: Owning tenant for RLS.
        query: Natural-language search query.
        settings: Optional config override.

    Returns:
        Tuple of (top-K chunks for judge, funnel counts per stage).
    """
    cfg = settings or get_settings()
    repo = ChunkRepository(session)

    # Stage 1: Hybrid recall
    query_embedding = await embedder.embed_query(query)
    dense = await repo.search_dense(tenant_id, query_embedding, STAGE1_RECALL_K)
    lexical = await repo.search_lexical(tenant_id, query, STAGE1_RECALL_K)
    fused = reciprocal_rank_fusion(
        [dense, lexical],
        [cfg.search_dense_weight, cfg.search_lexical_weight],
    )

    funnel = FunnelResult(initial_pool=STAGE1_RECALL_K, after_recall=len(fused))

    if not fused:
        return [], funnel

    # Stage 2: Cross-encoder rerank
    rerank_input = [c.chunk.content for c in fused[:STAGE2_RERANK_TOPK * 2]]
    rerank_results = await reranker.rerank(query, rerank_input, STAGE2_RERANK_TOPK)

    reranked: list[ChunkWithScore] = []
    for rr in rerank_results:
        if rr.index < len(fused):
            reranked.append(
                ChunkWithScore(chunk=fused[rr.index].chunk, score=rr.score)
            )

    funnel.after_rerank = len(reranked)

    # Stage 3: Trim to judge pool
    final = reranked[:JUDGE_TOP_K] if reranked else fused[:JUDGE_TOP_K]
    funnel.final_pool = len(final)

    logger.info(
        "funnel_complete",
        tenant_id=str(tenant_id),
        query_length=len(query),
        initial=funnel.initial_pool,
        after_recall=funnel.after_recall,
        after_rerank=funnel.after_rerank,
        final=funnel.final_pool,
    )

    return final, funnel
