"""Tests for embedding service and mock adapter.

The mock embedder is what lets unit tests run without a live TEI instance. If it
silently produces the wrong dimension or fails to honor the protocol, every test
using it becomes unreliable.
"""

from __future__ import annotations

import pytest

from app.services.embedding import (
    MockEmbeddingService,
    get_embedding_service,
    reset_embedding_service,
    set_embedding_service,
)


@pytest.mark.asyncio
async def test_mock_embedding_service_returns_correct_dimension():
    embedder = MockEmbeddingService(dimension=512)

    vector = await embedder.embed_query("test query")

    assert len(vector) == 512


@pytest.mark.asyncio
async def test_mock_embedding_service_batch_returns_one_vector_per_text():
    embedder = MockEmbeddingService(dimension=128)

    vectors = await embedder.embed_texts(["first", "second", "third"])

    assert len(vectors) == 3
    assert all(len(v) == 128 for v in vectors)


@pytest.mark.asyncio
async def test_mock_embedding_service_empty_batch_returns_empty_list():
    embedder = MockEmbeddingService(dimension=128)

    vectors = await embedder.embed_texts([])

    assert vectors == []


def test_mock_embedding_service_exposes_model_name():
    embedder = MockEmbeddingService(dimension=64)

    assert embedder.model_name == "mock-embedder"


def test_mock_embedding_service_exposes_model_version():
    embedder = MockEmbeddingService(dimension=64)

    assert embedder.model_version == "test-v1"


def test_mock_embedding_service_exposes_dimension():
    embedder = MockEmbeddingService(dimension=256)

    assert embedder.dimension == 256


@pytest.mark.asyncio
async def test_mock_embedding_service_embed_texts_is_awaitable():
    """The protocol requires async, so the mock must match."""
    embedder = MockEmbeddingService(dimension=64)

    vectors = await embedder.embed_texts(["async test"])

    assert len(vectors) == 1
    assert len(vectors[0]) == 64


@pytest.mark.asyncio
async def test_mock_embedding_service_embed_query_is_awaitable():
    embedder = MockEmbeddingService(dimension=64)

    vector = await embedder.embed_query("async query")

    assert len(vector) == 64


def test_singleton_returns_an_embedding_service():
    """The singleton must return something that satisfies the protocol."""
    reset_embedding_service()

    service = get_embedding_service()

    assert hasattr(service, "model_name")
    assert hasattr(service, "model_version")
    assert hasattr(service, "dimension")
    assert hasattr(service, "embed_texts")
    assert hasattr(service, "embed_query")


def test_singleton_returns_the_same_instance_on_repeated_calls():
    reset_embedding_service()

    first = get_embedding_service()
    second = get_embedding_service()

    assert first is second


def test_set_embedding_service_overrides_the_singleton():
    """Tests need to inject a mock without network calls."""
    reset_embedding_service()
    mock = MockEmbeddingService(dimension=32)

    set_embedding_service(mock)
    retrieved = get_embedding_service()

    assert retrieved is mock


def test_reset_embedding_service_clears_the_singleton():
    set_embedding_service(MockEmbeddingService(dimension=16))

    reset_embedding_service()
    after_reset = get_embedding_service()

    # After reset, the singleton rebuilds from config, so it's a new instance
    assert after_reset is not None
