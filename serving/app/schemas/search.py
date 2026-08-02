"""Request and response schemas for semantic and hybrid talent search."""

from __future__ import annotations

import uuid
from enum import Enum

from pydantic import BaseModel, Field


class SearchMode(str, Enum):
    """Search retrieval strategy."""

    HYBRID = "hybrid"
    SEMANTIC = "semantic"
    LEXICAL = "lexical"


class SearchFilters(BaseModel):
    """Optional filters to narrow search results."""

    sections: list[str] | None = Field(
        default=None,
        description="Restrict search to specific resume sections (e.g. experience, skills).",
    )


class SearchRequest(BaseModel):
    """Payload for ``POST /api/v1/search/candidates``."""

    query: str = Field(
        min_length=1,
        max_length=2000,
        description="Natural-language search query.",
    )
    filters: SearchFilters | None = Field(
        default=None,
        description="Optional search filters.",
    )
    top_k: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Maximum number of candidates to return.",
    )
    mode: SearchMode = Field(
        default=SearchMode.HYBRID,
        description="Retrieval strategy: hybrid, semantic, or lexical.",
    )


class EvidenceSpanResponse(BaseModel):
    """One piece of evidence supporting a search result."""

    chunk_id: uuid.UUID = Field(description="Identifier of the source chunk.")
    content: str = Field(description="The matching chunk text.")
    section: str = Field(description="Resume section this chunk belongs to.")
    page_from: int = Field(description="Starting page (0-based).")
    page_to: int = Field(description="Ending page (0-based).")
    start_char: int = Field(description="Starting character offset in the full document.")
    end_char: int = Field(description="Ending character offset in the full document.")
    score: float = Field(description="Retrieval score for this chunk.")


class CandidateSearchHitResponse(BaseModel):
    """One candidate in search results."""

    document_id: uuid.UUID = Field(description="The resume document ID.")
    score: float = Field(description="Aggregated relevance score.")
    spans: list[EvidenceSpanResponse] = Field(
        default_factory=list,
        description="Best supporting evidence spans.",
    )


class SearchResponse(BaseModel):
    """Complete search result set."""

    items: list[CandidateSearchHitResponse] = Field(
        default_factory=list,
        description="Ranked candidate hits.",
    )
    count: int = Field(description="Number of candidates returned.")
    query: str = Field(description="The original query text.")
    mode: str = Field(description="The search mode used.")


class SimilarRequest(BaseModel):
    """Payload for ``POST /api/v1/search/similar``."""

    document_id: uuid.UUID = Field(
        description="Source document to find similar candidates for.",
    )
    top_k: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Maximum number of candidates to return.",
    )
