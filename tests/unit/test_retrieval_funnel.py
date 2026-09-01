"""Candidate-scoped retrieval funnel regressions."""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.repositories.search import ChunkRepository, ChunkWithScore
from app.services.retrieval_funnel import run_resume_version_retrieval_funnel


class _Embedder:
    async def embed_query(self, query: str) -> list[float]:
        return [0.1]


class _Reranker:
    async def rerank(self, query: str, documents: list[str], top_k: int) -> list[Any]:
        return []


@pytest.mark.asyncio
async def test_resume_version_funnel_scopes_both_retrievers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = uuid.uuid4()
    resume_version_id = uuid.uuid4()
    calls: list[dict[str, object]] = []

    async def dense(self: Any, *args: Any, **kwargs: object) -> list[ChunkWithScore]:
        calls.append(kwargs)
        return []

    async def lexical(self: Any, *args: Any, **kwargs: object) -> list[ChunkWithScore]:
        calls.append(kwargs)
        return []

    monkeypatch.setattr(ChunkRepository, "search_dense", dense)
    monkeypatch.setattr(ChunkRepository, "search_lexical", lexical)

    chunks, funnel = await run_resume_version_retrieval_funnel(
        session=object(),
        embedder=_Embedder(),
        reranker=_Reranker(),
        tenant_id=tenant_id,
        resume_version_id=resume_version_id,
        query="Python engineer",
    )

    assert chunks == []
    assert funnel.initial_pool == 0
    assert [call["resume_version_id"] for call in calls] == [resume_version_id, resume_version_id]
