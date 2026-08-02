"""Tests for the reranker port and its no-op adapter.

The no-op reranker is the CPU fallback: when no cross-encoder endpoint is
configured, search still has to return results in a sane order. It must preserve
the RRF-fused ranking rather than shuffling or dropping it.
"""

from __future__ import annotations

import pytest

from app.services.reranker import (
    NoOpRerankerService,
    RerankResult,
    get_reranker_service,
    reset_reranker_service,
    set_reranker_service,
)

_DOCS = [
    "Senior Python engineer with Kubernetes experience.",
    "Frontend developer specializing in React and TypeScript.",
    "Data engineer building Kafka pipelines on AWS.",
]


def test_rerank_result_carries_index_and_score():
    result = RerankResult(index=2, score=0.87)

    assert result.index == 2
    assert result.score == 0.87


@pytest.mark.asyncio
async def test_noop_reranker_returns_input_order():
    """The fused order is already meaningful — the no-op must not disturb it."""
    reranker = NoOpRerankerService()

    results = await reranker.rerank("python engineer", _DOCS, top_k=3)

    assert [r.index for r in results] == [0, 1, 2]


@pytest.mark.asyncio
async def test_noop_reranker_scores_decrease_with_position():
    """Descending scores let downstream code sort without special-casing."""
    reranker = NoOpRerankerService()

    results = await reranker.rerank("python engineer", _DOCS, top_k=3)
    scores = [r.score for r in results]

    assert scores == sorted(scores, reverse=True)


@pytest.mark.asyncio
async def test_noop_reranker_honors_top_k():
    reranker = NoOpRerankerService()

    results = await reranker.rerank("python", _DOCS, top_k=2)

    assert len(results) == 2


@pytest.mark.asyncio
async def test_noop_reranker_top_k_larger_than_input_returns_all():
    """Asking for more than exists must not pad with phantom indices."""
    reranker = NoOpRerankerService()

    results = await reranker.rerank("python", _DOCS, top_k=99)

    assert len(results) == len(_DOCS)


@pytest.mark.asyncio
async def test_noop_reranker_empty_documents_returns_empty():
    reranker = NoOpRerankerService()

    results = await reranker.rerank("python", [], top_k=5)

    assert results == []


@pytest.mark.asyncio
async def test_noop_reranker_indices_stay_within_bounds():
    """An out-of-range index would raise when used to look up the chunk."""
    reranker = NoOpRerankerService()

    results = await reranker.rerank("python", _DOCS, top_k=3)

    assert all(0 <= r.index < len(_DOCS) for r in results)


@pytest.mark.asyncio
async def test_noop_reranker_ignores_the_query():
    """It cannot score relevance, so the query must not change its output."""
    reranker = NoOpRerankerService()

    first = await reranker.rerank("python engineer", _DOCS, top_k=3)
    second = await reranker.rerank("completely unrelated text", _DOCS, top_k=3)

    assert [r.index for r in first] == [r.index for r in second]
    assert [r.score for r in first] == [r.score for r in second]


def test_singleton_returns_a_reranker_service():
    reset_reranker_service()

    service = get_reranker_service()

    assert hasattr(service, "rerank")


def test_singleton_returns_the_same_instance_on_repeated_calls():
    reset_reranker_service()

    first = get_reranker_service()
    second = get_reranker_service()

    assert first is second


def test_set_reranker_service_overrides_the_singleton():
    reset_reranker_service()
    stub = NoOpRerankerService()

    set_reranker_service(stub)

    assert get_reranker_service() is stub


def test_singleton_falls_back_to_noop_without_an_endpoint():
    """No configured endpoint must degrade gracefully, not crash startup."""
    reset_reranker_service()

    service = get_reranker_service()

    # The test environment configures no reranker endpoint.
    assert isinstance(service, NoOpRerankerService)
