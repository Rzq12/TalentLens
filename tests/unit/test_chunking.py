"""Tests for parent-child chunking.

Chunking decides what dense retrieval can ever match. If a child chunk loses
its parent link, Phase 4 cannot expand a hit into LLM context; if character
offsets drift, a citation points at the wrong part of the resume.
"""

from __future__ import annotations

from app.services.chunking import (
    CHILD_CHUNK_WORDS,
    PARENT_CHUNK_WORDS,
    chunk_document,
)

_SECTIONED_RESUME = """Professional Summary
Senior backend engineer with eight years building distributed systems.

Work Experience
Staff Engineer at Acme Corp, 2019 to 2025. Led the migration of a monolith to
event-driven services on Kubernetes. Cut p99 latency from 1200ms to 180ms.

Education
BSc Computer Science, Institut Teknologi Bandung, 2013 to 2017.

Technical Skills
Python, Go, PostgreSQL, Kafka, Kubernetes, Terraform.
"""


def test_chunk_document_empty_text_returns_no_chunks():
    assert chunk_document("") == []


def test_chunk_document_whitespace_only_returns_no_chunks():
    assert chunk_document("   \n\t  \n  ") == []


def test_chunk_document_produces_both_parents_and_children():
    chunks = chunk_document(_SECTIONED_RESUME)

    parents = [c for c in chunks if c.is_parent]
    children = [c for c in chunks if not c.is_parent]

    assert parents, "no parent chunks — Phase 4 has nothing to expand into"
    assert children, "no child chunks — dense search has nothing to match"


def test_every_child_points_at_an_existing_parent():
    """A dangling parent link breaks retrieve-child-expand-to-parent."""
    chunks = chunk_document(_SECTIONED_RESUME)

    parent_ids = {c.chunk_id for c in chunks if c.is_parent}
    children = [c for c in chunks if not c.is_parent]

    assert children
    for child in children:
        assert child.parent_chunk_id in parent_ids


def test_parents_carry_no_parent_link():
    chunks = chunk_document(_SECTIONED_RESUME)
    parents = [c for c in chunks if c.is_parent]

    assert parents
    assert all(p.parent_chunk_id is None for p in parents)


def test_chunk_index_is_unique_and_contiguous():
    """Index gaps or repeats would make chunk ordering unreliable."""
    chunks = chunk_document(_SECTIONED_RESUME)
    indices = [c.chunk_index for c in chunks]

    assert indices == sorted(indices)
    assert indices == list(range(len(chunks)))


def test_chunk_ids_are_unique():
    chunks = chunk_document(_SECTIONED_RESUME)
    ids = [c.chunk_id for c in chunks]

    assert len(ids) == len(set(ids))


def test_section_headings_are_detected():
    """Section labels drive filtering and explain where evidence came from."""
    chunks = chunk_document(_SECTIONED_RESUME)
    sections = {c.section for c in chunks}

    assert "experience" in sections
    assert "education" in sections
    assert "skills" in sections


def test_text_without_headings_still_chunks():
    """An unstructured resume must not silently produce zero chunks."""
    chunks = chunk_document(
        "Just a paragraph of prose with no headings whatsoever, describing "
        "some work that someone did at some point in their career."
    )

    assert chunks
    assert all(c.section for c in chunks), "every chunk needs a section label"


def test_chunks_carry_non_negative_offsets():
    chunks = chunk_document(_SECTIONED_RESUME)

    for chunk in chunks:
        assert chunk.start_char >= 0
        assert chunk.end_char >= chunk.start_char


def test_token_count_is_positive_for_every_chunk():
    """A zero token count would let a chunk slip past budget accounting."""
    chunks = chunk_document(_SECTIONED_RESUME)

    assert chunks
    assert all(c.token_count > 0 for c in chunks)


def test_children_are_smaller_than_their_parent_budget():
    """Children exist to be precise; one the size of a parent defeats that."""
    long_text = "Engineered scalable systems. " * 400
    chunks = chunk_document(long_text, child_words=20, parent_words=100)

    children = [c for c in chunks if not c.is_parent]
    assert children

    # Allow slack: splitting happens on sentence boundaries, so a chunk can
    # overshoot the target by the length of one sentence.
    for child in children:
        assert len(child.content.split()) <= 20 * 3


def test_long_document_yields_multiple_parents():
    long_text = "Delivered production machine learning services. " * 500
    chunks = chunk_document(long_text, child_words=50, parent_words=150)

    parents = [c for c in chunks if c.is_parent]
    assert len(parents) > 1


def test_small_document_parent_also_serves_as_its_own_child():
    """A short section must still be searchable, not parent-only."""
    chunks = chunk_document("Skills\nPython and PostgreSQL.")

    parents = [c for c in chunks if c.is_parent]
    children = [c for c in chunks if not c.is_parent]

    assert len(parents) == 1
    assert len(children) == 1
    assert children[0].content == parents[0].content


def test_page_offsets_are_resolved_to_page_numbers():
    """Page attribution is what makes a citation clickable in the UI."""
    text = "Page one content here.\n" + ("filler words " * 50) + "\nPage two content."
    page_offsets = [
        {"page": 0, "start_char": 0, "end_char": 30},
        {"page": 1, "start_char": 31, "end_char": len(text)},
    ]

    chunks = chunk_document(text, page_offsets=page_offsets)

    assert chunks
    assert all(c.page_from >= 0 for c in chunks)
    assert all(c.page_to >= c.page_from for c in chunks)


def test_missing_page_offsets_default_to_page_zero():
    chunks = chunk_document(_SECTIONED_RESUME, page_offsets=None)

    assert chunks
    assert all(c.page_from == 0 for c in chunks)


def test_default_chunk_budgets_keep_children_smaller_than_parents():
    assert CHILD_CHUNK_WORDS < PARENT_CHUNK_WORDS


def test_chunk_content_is_never_blank():
    """A blank chunk would be embedded and stored for nothing."""
    chunks = chunk_document(_SECTIONED_RESUME)

    assert chunks
    assert all(c.content.strip() for c in chunks)
