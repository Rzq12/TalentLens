"""Semantic and hybrid talent search endpoints.

Two endpoints per ARCHITECTURE.md §7.2:
- ``POST /api/v1/search/candidates`` — hybrid talent search
- ``POST /api/v1/search/similar`` — "more like this"

No LLM in this path. Sub-second. Tenant-scoped via ``ReadPrincipal``.
"""

from __future__ import annotations

from fastapi import APIRouter, status

from app.db import DbSession
from app.schemas.search import (
    CandidateSearchHitResponse,
    EvidenceSpanResponse,
    SearchRequest,
    SearchResponse,
    SimilarRequest,
)
from app.security import ReadPrincipal
from app.services.embedding import get_embedding_service
from app.services.reranker import get_reranker_service
from app.services.search import SearchMode as ServiceSearchMode
from app.services.search import search_candidates, search_similar

router = APIRouter(prefix="/search", tags=["search"])


def _to_response(result: object) -> SearchResponse:
    """Convert a service-layer SearchResult to an API response.

    Args:
        result: The SearchResult from the search service.

    Returns:
        The API-shaped response.
    """
    from app.services.search import SearchResult

    assert isinstance(result, SearchResult)  # noqa: S101

    return SearchResponse(
        items=[
            CandidateSearchHitResponse(
                document_id=hit.document_id,
                score=hit.score,
                spans=[
                    EvidenceSpanResponse(
                        chunk_id=span.chunk_id,
                        content=span.content,
                        section=span.section,
                        page_from=span.page_from,
                        page_to=span.page_to,
                        start_char=span.start_char,
                        end_char=span.end_char,
                        score=span.score,
                    )
                    for span in hit.spans
                ],
            )
            for hit in result.items
        ],
        count=result.count,
        query=result.query,
        mode=result.mode,
    )


@router.post(
    "/candidates",
    response_model=SearchResponse,
    status_code=status.HTTP_200_OK,
    summary="Search candidates",
    description=(
        "Natural-language search across the tenant's candidate pool. "
        "Returns ranked candidates with evidence-cited results. "
        "Supports hybrid (default), semantic-only, and lexical-only modes. "
        "No LLM in this path."
    ),
)
async def search_candidates_endpoint(
    body: SearchRequest,
    principal: ReadPrincipal,
    session: DbSession,
) -> SearchResponse:
    """Execute a talent search.

    Args:
        body: Search parameters.
        principal: Verified caller.
        session: Database session.

    Returns:
        Ranked candidates with supporting evidence spans.
    """
    embedder = get_embedding_service()
    reranker = get_reranker_service()

    # Map schema enum to service enum
    mode_map = {
        "hybrid": ServiceSearchMode.HYBRID,
        "semantic": ServiceSearchMode.SEMANTIC,
        "lexical": ServiceSearchMode.LEXICAL,
    }
    service_mode = mode_map.get(body.mode.value, ServiceSearchMode.HYBRID)

    result = await search_candidates(
        session=session,
        embedder=embedder,
        reranker=reranker,
        tenant_id=principal.tenant_id,
        query=body.query,
        top_k=body.top_k,
        mode=service_mode,
    )
    return _to_response(result)


@router.post(
    "/similar",
    response_model=SearchResponse,
    status_code=status.HTTP_200_OK,
    summary="Find similar candidates",
    description=(
        '"More like this" — find candidates similar to a given resume. '
        "Uses the source document's embeddings to search across the corpus."
    ),
)
async def search_similar_endpoint(
    body: SimilarRequest,
    principal: ReadPrincipal,
    session: DbSession,
) -> SearchResponse:
    """Find candidates similar to a given document.

    Args:
        body: The source document ID and result count.
        principal: Verified caller.
        session: Database session.

    Returns:
        Ranked similar candidates with evidence spans.
    """
    embedder = get_embedding_service()
    reranker = get_reranker_service()

    result = await search_similar(
        session=session,
        embedder=embedder,
        reranker=reranker,
        tenant_id=principal.tenant_id,
        document_id=body.document_id,
        top_k=body.top_k,
    )
    return _to_response(result)
