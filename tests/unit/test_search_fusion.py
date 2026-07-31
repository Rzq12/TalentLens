"""Tests for RRF fusion and candidate grouping.

Reciprocal rank fusion is what merges dense and lexical results without paying
for a cross-encoder on every candidate. If its arithmetic drifts, or if grouping
drops chunks, search silently returns the wrong people.

Fusion identity is the ``ResumeChunk`` primary key, so these fixtures pass ``id``
explicitly rather than letting each call mint a fresh UUID.
"""

from __future__ import annotations

import uuid

from app.models import ResumeChunk
from app.repositories.search import ChunkWithScore
from app.services.search import group_by_candidate, reciprocal_rank_fusion


def _chunk(
    document_id: uuid.UUID,
    content: str,
    *,
    chunk_id: uuid.UUID | None = None,
    section: str = "experience",
) -> ResumeChunk:
    """Build a minimal in-memory ResumeChunk for fusion tests."""
    return ResumeChunk(
        id=chunk_id or uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        resume_version_id=uuid.uuid4(),
        document_id=document_id,
        chunk_index=0,
        parent_chunk_id=None,
        section=section,
        content=content,
        page_from=0,
        page_to=0,
        start_char=0,
        end_char=len(content),
        token_count=len(content.split()),
        embedding_model="mock-embedder",
        embedding_version="test-v1",
        is_parent=False,
    )


def test_rrf_ranks_a_chunk_found_by_both_retrievers_first():
    """Agreement between dense and lexical is the strongest signal RRF has."""
    doc_a, doc_b, doc_c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    only_dense = _chunk(doc_a, "Senior Python engineer")
    in_both = _chunk(doc_b, "Backend developer, Kubernetes")
    only_lexical = _chunk(doc_c, "Full-stack engineer")

    fused = reciprocal_rank_fusion(
        [
            [ChunkWithScore(only_dense, 0.95), ChunkWithScore(in_both, 0.88)],
            [ChunkWithScore(in_both, 12.3), ChunkWithScore(only_lexical, 9.7)],
        ],
        weights=[1.0, 1.0],
        k=60,
    )

    assert fused[0].chunk.id == in_both.id
    assert len(fused) == 3


def test_rrf_weights_shift_the_winner():
    """Weights are the tuning knob for dense-vs-lexical balance."""
    doc_a, doc_b = uuid.uuid4(), uuid.uuid4()
    dense_hit = _chunk(doc_a, "Python")
    lexical_hit = _chunk(doc_b, "Java")

    dense = [ChunkWithScore(dense_hit, 0.9)]
    lexical = [ChunkWithScore(lexical_hit, 10.0)]

    dense_favored = reciprocal_rank_fusion([dense, lexical], weights=[3.0, 1.0])
    lexical_favored = reciprocal_rank_fusion([dense, lexical], weights=[1.0, 3.0])

    assert dense_favored[0].chunk.id == dense_hit.id
    assert lexical_favored[0].chunk.id == lexical_hit.id


def test_rrf_returns_scores_in_descending_order():
    doc_a, doc_b, doc_c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    dense = [
        ChunkWithScore(_chunk(doc_a, "first"), 0.9),
        ChunkWithScore(_chunk(doc_b, "second"), 0.8),
        ChunkWithScore(_chunk(doc_c, "third"), 0.7),
    ]

    fused = reciprocal_rank_fusion([dense], weights=[1.0])
    scores = [item.score for item in fused]

    assert scores == sorted(scores, reverse=True)


def test_rrf_score_reflects_rank_not_raw_score():
    """RRF exists precisely because cosine and ts_rank are not comparable."""
    doc_a, doc_b = uuid.uuid4(), uuid.uuid4()
    top = _chunk(doc_a, "top ranked")
    second = _chunk(doc_b, "second ranked")

    # Raw scores are near-identical; only the rank differs.
    fused = reciprocal_rank_fusion(
        [[ChunkWithScore(top, 0.9001), ChunkWithScore(second, 0.9000)]],
        weights=[1.0],
        k=60,
    )

    assert fused[0].chunk.id == top.id
    assert fused[0].score == 1.0 / 61
    assert fused[1].score == 1.0 / 62


def test_rrf_with_no_lists_returns_empty():
    assert reciprocal_rank_fusion([], weights=[]) == []


def test_rrf_with_one_empty_list_returns_the_other():
    """A retriever returning nothing must not zero out the whole result set."""
    doc_a = uuid.uuid4()
    hit = _chunk(doc_a, "content")

    fused = reciprocal_rank_fusion([[ChunkWithScore(hit, 0.9)], []], weights=[1.0, 1.0])

    assert len(fused) == 1
    assert fused[0].chunk.id == hit.id


def test_rrf_emits_a_chunk_once_even_when_both_retrievers_return_it():
    """A duplicated chunk would double-count as evidence during grouping."""
    doc_a = uuid.uuid4()
    shared = _chunk(doc_a, "Python engineer")

    fused = reciprocal_rank_fusion(
        [[ChunkWithScore(shared, 0.9)], [ChunkWithScore(shared, 12.0)]],
        weights=[1.0, 1.0],
    )

    assert len(fused) == 1


def test_rrf_keeps_the_chunk_from_the_higher_scoring_retriever():
    """When the same id arrives twice, the better-scored row wins the tie."""
    doc_a = uuid.uuid4()
    shared_id = uuid.uuid4()
    low = _chunk(doc_a, "low score version", chunk_id=shared_id)
    high = _chunk(doc_a, "high score version", chunk_id=shared_id)

    fused = reciprocal_rank_fusion(
        [[ChunkWithScore(low, 0.1)], [ChunkWithScore(high, 8.2)]],
        weights=[1.0, 1.0],
    )

    assert len(fused) == 1
    assert fused[0].chunk.content == "high score version"


def test_group_by_candidate_collapses_chunks_from_the_same_document():
    """Search returns people, not chunks."""
    doc_a, doc_b = uuid.uuid4(), uuid.uuid4()
    chunks = [
        ChunkWithScore(_chunk(doc_a, "Python", section="experience"), 10.0),
        ChunkWithScore(_chunk(doc_a, "Django", section="experience"), 8.0),
        ChunkWithScore(_chunk(doc_b, "React", section="skills"), 9.0),
    ]

    hits = group_by_candidate(chunks, max_spans_per_candidate=5)

    assert len(hits) == 2
    assert hits[0].document_id == doc_a
    assert len(hits[0].spans) == 2


def test_group_by_candidate_caps_spans_and_keeps_the_best_ones():
    """The UI shows a handful of spans; the cap must drop the weakest."""
    doc_a = uuid.uuid4()
    chunks = [
        ChunkWithScore(_chunk(doc_a, f"chunk {i}"), 10.0 - i) for i in range(10)
    ]

    hits = group_by_candidate(chunks, max_spans_per_candidate=3)

    assert len(hits) == 1
    assert [span.content for span in hits[0].spans] == ["chunk 0", "chunk 1", "chunk 2"]


def test_group_by_candidate_score_is_the_sum_of_retained_spans():
    """Sum, not mean — more corroborating evidence should rank higher."""
    doc_a = uuid.uuid4()
    chunks = [
        ChunkWithScore(_chunk(doc_a, "first"), 5.0),
        ChunkWithScore(_chunk(doc_a, "second"), 3.0),
    ]

    hits = group_by_candidate(chunks, max_spans_per_candidate=5)

    assert hits[0].score == 8.0


def test_group_by_candidate_score_ignores_spans_beyond_the_cap():
    """Otherwise a resume padded with keywords outranks a genuinely strong one."""
    doc_a = uuid.uuid4()
    chunks = [ChunkWithScore(_chunk(doc_a, f"chunk {i}"), 1.0) for i in range(10)]

    hits = group_by_candidate(chunks, max_spans_per_candidate=3)

    assert hits[0].score == 3.0


def test_group_by_candidate_sorts_candidates_by_aggregate_score():
    doc_a, doc_b = uuid.uuid4(), uuid.uuid4()
    chunks = [
        ChunkWithScore(_chunk(doc_a, "one weak match"), 2.0),
        ChunkWithScore(_chunk(doc_b, "strong match"), 10.0),
        ChunkWithScore(_chunk(doc_b, "second strong match"), 8.0),
    ]

    hits = group_by_candidate(chunks, max_spans_per_candidate=5)

    assert [hit.document_id for hit in hits] == [doc_b, doc_a]
    assert hits[0].score == 18.0


def test_group_by_candidate_spans_are_ordered_by_score():
    doc_a = uuid.uuid4()
    chunks = [
        ChunkWithScore(_chunk(doc_a, "weakest"), 1.0),
        ChunkWithScore(_chunk(doc_a, "strongest"), 9.0),
        ChunkWithScore(_chunk(doc_a, "middle"), 5.0),
    ]

    hits = group_by_candidate(chunks, max_spans_per_candidate=5)

    assert [span.content for span in hits[0].spans] == ["strongest", "middle", "weakest"]


def test_group_by_candidate_empty_input_returns_empty():
    assert group_by_candidate([], max_spans_per_candidate=5) == []


def test_group_by_candidate_carries_citation_metadata_into_spans():
    """These offsets are what make a citation point at the right text."""
    doc_a = uuid.uuid4()
    chunk = _chunk(doc_a, "Kubernetes experience", section="experience")
    chunk.page_from = 2
    chunk.page_to = 3
    chunk.start_char = 100
    chunk.end_char = 200

    hits = group_by_candidate([ChunkWithScore(chunk, 9.5)], max_spans_per_candidate=5)
    span = hits[0].spans[0]

    assert span.chunk_id == chunk.id
    assert span.content == "Kubernetes experience"
    assert span.section == "experience"
    assert span.page_from == 2
    assert span.page_to == 3
    assert span.start_char == 100
    assert span.end_char == 200
    assert span.score == 9.5
