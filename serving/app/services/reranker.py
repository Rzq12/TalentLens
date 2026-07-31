"""Reranker service port and adapters.

Cross-encoder reranking improves precision by scoring query–document pairs with
a more powerful model after initial recall.  Two adapters:

* ``TEIRerankerService`` — calls HuggingFace TEI rerank endpoint.
* ``NoOpRerankerService`` — passes through scores unchanged (CPU fallback).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import httpx

from app.config import Settings, get_settings
from app.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class RerankResult:
    """One reranked document.

    Attributes:
        index: Original index in the input list.
        score: Relevance score from the reranker.
    """

    index: int
    score: float


# ---------------------------------------------------------------------------
# Port
# ---------------------------------------------------------------------------


@runtime_checkable
class RerankerService(Protocol):
    """Capability: rerank documents by relevance to a query."""

    async def rerank(
        self, query: str, documents: list[str], top_k: int
    ) -> list[RerankResult]:
        """Rerank documents by relevance to the query.

        Args:
            query: The search query.
            documents: Document texts to rerank.
            top_k: Maximum results to return.

        Returns:
            The top-k results sorted by descending score.
        """
        ...


# ---------------------------------------------------------------------------
# TEI adapter (production)
# ---------------------------------------------------------------------------

_TEI_RERANK_PATH = "/rerank"
_TEI_RERANK_TIMEOUT = 30.0


class TEIRerankerService:
    """Calls HuggingFace TEI rerank endpoint.

    Attributes:
        _endpoint: Base URL of the TEI reranker instance.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        """Initialize from settings.

        Args:
            settings: Optional configuration override.
        """
        cfg = settings or get_settings()
        self._endpoint = cfg.reranker_endpoint.rstrip("/")
        self._model = cfg.reranker_model

    async def rerank(
        self, query: str, documents: list[str], top_k: int
    ) -> list[RerankResult]:
        """Rerank via TEI.

        Args:
            query: The search query.
            documents: Document texts.
            top_k: Maximum results.

        Returns:
            Reranked results sorted by descending score.
        """
        if not documents:
            return []

        url = f"{self._endpoint}{_TEI_RERANK_PATH}"
        payload = {
            "query": query,
            "texts": documents,
            "return_text": False,
        }
        try:
            async with httpx.AsyncClient(timeout=_TEI_RERANK_TIMEOUT) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                raw: list[dict[str, object]] = response.json()
                results = [
                    RerankResult(index=int(r["index"]), score=float(r["score"]))
                    for r in raw
                ]
                results.sort(key=lambda r: r.score, reverse=True)
                return results[:top_k]
        except (httpx.HTTPError, Exception) as exc:
            logger.warning(
                "reranker_service_error",
                endpoint=self._endpoint,
                error=str(exc)[:200],
            )
            # Graceful degradation: return original order with default scores
            return [
                RerankResult(index=i, score=1.0 / (i + 1))
                for i in range(min(top_k, len(documents)))
            ]


# ---------------------------------------------------------------------------
# No-op adapter (CPU fallback / dev mode)
# ---------------------------------------------------------------------------


class NoOpRerankerService:
    """Passes through documents without reranking.

    Used when no reranker endpoint is configured.  Returns scores based on
    input order so the RRF-fused ranking is preserved.
    """

    async def rerank(
        self, query: str, documents: list[str], top_k: int
    ) -> list[RerankResult]:
        """Return input-order scores without reranking.

        Args:
            query: Ignored.
            documents: Document texts.
            top_k: Maximum results.

        Returns:
            Results in input order with position-based scores.
        """
        return [
            RerankResult(index=i, score=1.0 / (i + 1))
            for i in range(min(top_k, len(documents)))
        ]


# ---------------------------------------------------------------------------
# Singleton management
# ---------------------------------------------------------------------------

_reranker_service: RerankerService | None = None


def get_reranker_service() -> RerankerService:
    """Return the process-wide reranker service instance.

    Returns a ``NoOpRerankerService`` when no reranker endpoint is configured.

    Returns:
        The reranker service singleton.
    """
    global _reranker_service  # noqa: PLW0603
    if _reranker_service is not None:
        return _reranker_service

    settings = get_settings()
    if settings.reranker_endpoint:
        _reranker_service = TEIRerankerService(settings)
        logger.info(
            "reranker_service_initialized",
            adapter="TEI",
            endpoint=settings.reranker_endpoint,
        )
    else:
        _reranker_service = NoOpRerankerService()
        logger.info("reranker_service_initialized", adapter="NoOp")
    return _reranker_service


def set_reranker_service(service: RerankerService) -> None:
    """Override the reranker service singleton (for tests).

    Args:
        service: The service to install.
    """
    global _reranker_service  # noqa: PLW0603
    _reranker_service = service


def reset_reranker_service() -> None:
    """Clear the reranker service singleton (for tests)."""
    global _reranker_service  # noqa: PLW0603
    _reranker_service = None
