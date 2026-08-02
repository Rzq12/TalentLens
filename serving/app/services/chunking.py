"""Parent-child chunking with offset preservation.

Implements the chunking strategy from ARCHITECTURE.md §6.4:
- **Child chunks:** ~180 words for embedding precision
- **Parent chunks:** ~700 words fed to the LLM for context (Phase 4)

Each child carries ``parent_chunk_id`` referencing its parent, enabling the
retrieve-on-children, expand-to-parents pattern.

Section detection is heuristic: common resume headings are matched
case-insensitively and mapped to one of the standard categories.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from app.logging import get_logger

logger = get_logger(__name__)

# Target sizes in words
CHILD_CHUNK_WORDS = 180
PARENT_CHUNK_WORDS = 700

# Approximate token-to-word ratio (words × factor ≈ tokens)
_WORD_TO_TOKEN_RATIO = 1.33

# Section heading patterns (case-insensitive)
_SECTION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "experience",
        re.compile(r"(?i)^\s*(work\s+)?experience|employment|career|professional\s+history"),
    ),
    ("education", re.compile(r"(?i)^\s*education|academic|qualifications|degrees?")),
    ("skills", re.compile(r"(?i)^\s*(technical\s+)?skills|competenc|technologies|proficienc")),
    (
        "summary",
        re.compile(r"(?i)^\s*(professional\s+)?(summary|profile|objective|about\s+me|overview)"),
    ),
    ("certifications", re.compile(r"(?i)^\s*certifications?|licens|credentials?")),
    ("projects", re.compile(r"(?i)^\s*projects?|portfolio")),
    ("languages", re.compile(r"(?i)^\s*languages?")),
    ("awards", re.compile(r"(?i)^\s*awards?|honors?|achievements?")),
    ("publications", re.compile(r"(?i)^\s*publications?|papers?|research")),
    ("references", re.compile(r"(?i)^\s*references?")),
]


@dataclass(frozen=True, slots=True)
class ChunkInfo:
    """One chunk produced by the chunking pipeline.

    Attributes:
        chunk_id: Pre-assigned UUID for the chunk.
        parent_chunk_id: UUID of the parent chunk, or None for parents.
        chunk_index: Zero-based position in the document's chunk sequence.
        content: The chunk text.
        section: Detected resume section.
        page_from: Starting page (0-based).
        page_to: Ending page (0-based).
        start_char: Starting character offset in the full text.
        end_char: Ending character offset in the full text.
        token_count: Estimated token count.
        is_parent: True for parent chunks, False for children.
    """

    chunk_id: uuid.UUID
    parent_chunk_id: uuid.UUID | None
    chunk_index: int
    content: str
    section: str
    page_from: int
    page_to: int
    start_char: int
    end_char: int
    token_count: int
    is_parent: bool


@dataclass
class _Section:
    """An intermediate section detected during segmentation."""

    label: str
    text: str
    start_char: int
    end_char: int


def _detect_section(line: str) -> str | None:
    """Match a line against known section headings.

    Args:
        line: A single line of text.

    Returns:
        The section label if matched, else None.
    """
    stripped = line.strip()
    if not stripped or len(stripped) > 80:
        return None
    for label, pattern in _SECTION_PATTERNS:
        if pattern.match(stripped):
            return label
    return None


def _estimate_tokens(text: str) -> int:
    """Estimate token count from word count.

    Args:
        text: The text to estimate.

    Returns:
        Approximate token count.
    """
    words = len(text.split())
    return max(1, round(words * _WORD_TO_TOKEN_RATIO))


def _resolve_page(
    char_offset: int,
    page_offsets: list[dict[str, int]],
) -> int:
    """Resolve a character offset to a page number.

    Args:
        char_offset: Character offset in the full text.
        page_offsets: Page boundary list from the parser.

    Returns:
        The 0-based page number, or 0 if offsets are empty.
    """
    if not page_offsets:
        return 0
    for page_info in reversed(page_offsets):
        if char_offset >= page_info.get("start_char", 0):
            return int(page_info.get("page", 0))
    return 0


def _segment_into_sections(text: str) -> list[_Section]:
    """Split text into sections based on heading detection.

    Args:
        text: The full document text.

    Returns:
        A list of sections with their character offsets.
    """
    lines = text.split("\n")
    sections: list[_Section] = []
    current_label = "summary"
    current_lines: list[str] = []
    current_start = 0
    char_pos = 0

    for line in lines:
        detected = _detect_section(line)
        if detected is not None and current_lines:
            section_text = "\n".join(current_lines).strip()
            if section_text:
                sections.append(_Section(
                    label=current_label,
                    text=section_text,
                    start_char=current_start,
                    end_char=current_start + len(section_text),
                ))
            current_label = detected
            current_lines = []
            current_start = char_pos
        else:
            current_lines.append(line)
        char_pos += len(line) + 1  # +1 for the newline

    # Flush last section
    section_text = "\n".join(current_lines).strip()
    if section_text:
        sections.append(_Section(
            label=current_label,
            text=section_text,
            start_char=current_start,
            end_char=current_start + len(section_text),
        ))

    # If no sections detected, wrap the entire text as "other"
    if not sections:
        sections.append(_Section(
            label="other",
            text=text.strip(),
            start_char=0,
            end_char=len(text.strip()),
        ))

    return sections


def _split_into_word_chunks(
    text: str,
    target_words: int,
    base_start_char: int,
) -> list[tuple[str, int, int]]:
    """Split text into chunks of approximately ``target_words`` words.

    Splits on sentence boundaries when possible, falling back to word
    boundaries.

    Args:
        text: Text to split.
        target_words: Target word count per chunk.
        base_start_char: Character offset of ``text`` within the full document.

    Returns:
        List of (chunk_text, start_char, end_char) tuples.
    """
    if not text.strip():
        return []

    words = text.split()
    if len(words) <= target_words:
        return [(text.strip(), base_start_char, base_start_char + len(text.strip()))]

    # Try sentence splitting first
    sentences = re.split(r"(?<=[.!?])\s+", text)
    chunks: list[tuple[str, int, int]] = []
    current_words: list[str] = []
    current_start = base_start_char

    for sentence in sentences:
        sentence_words = sentence.split()
        if current_words and len(current_words) + len(sentence_words) > target_words:
            chunk_text = " ".join(current_words).strip()
            if chunk_text:
                chunks.append((
                    chunk_text,
                    current_start,
                    current_start + len(chunk_text),
                ))
            current_start = current_start + len(chunk_text) + 1
            current_words = sentence_words
        else:
            current_words.extend(sentence_words)

    # Flush remaining
    if current_words:
        chunk_text = " ".join(current_words).strip()
        if chunk_text:
            chunks.append((
                chunk_text,
                current_start,
                current_start + len(chunk_text),
            ))

    return chunks


def chunk_document(
    text: str,
    page_offsets: list[dict[str, int]] | None = None,
    child_words: int = CHILD_CHUNK_WORDS,
    parent_words: int = PARENT_CHUNK_WORDS,
) -> list[ChunkInfo]:
    """Chunk a document into parent-child chunks with offset preservation.

    The strategy is:
    1. Segment text into resume sections (experience, skills, etc.)
    2. Within each section, create parent chunks (~700 words)
    3. Within each parent, create child chunks (~180 words)
    4. Children carry ``parent_chunk_id``; parents carry ``is_parent=True``

    Args:
        text: The full document text.
        page_offsets: Page boundary data from the parser.
        child_words: Target words per child chunk.
        parent_words: Target words per parent chunk.

    Returns:
        All chunks (parents and children), ordered by chunk_index.
    """
    if not text or not text.strip():
        return []

    offsets = page_offsets or []
    sections = _segment_into_sections(text)

    all_chunks: list[ChunkInfo] = []
    chunk_index = 0

    for section in sections:
        # Create parent chunks from the section
        parent_spans = _split_into_word_chunks(
            section.text, parent_words, section.start_char
        )

        for parent_text, parent_start, parent_end in parent_spans:
            parent_id = uuid.uuid4()

            # Create the parent chunk
            parent_chunk = ChunkInfo(
                chunk_id=parent_id,
                parent_chunk_id=None,
                chunk_index=chunk_index,
                content=parent_text,
                section=section.label,
                page_from=_resolve_page(parent_start, offsets),
                page_to=_resolve_page(parent_end, offsets),
                start_char=parent_start,
                end_char=parent_end,
                token_count=_estimate_tokens(parent_text),
                is_parent=True,
            )
            all_chunks.append(parent_chunk)
            chunk_index += 1

            # Create child chunks within this parent
            child_spans = _split_into_word_chunks(
                parent_text, child_words, parent_start
            )

            # If the parent is small enough, it serves as its own child
            if len(child_spans) <= 1:
                child_chunk = ChunkInfo(
                    chunk_id=uuid.uuid4(),
                    parent_chunk_id=parent_id,
                    chunk_index=chunk_index,
                    content=parent_text,
                    section=section.label,
                    page_from=parent_chunk.page_from,
                    page_to=parent_chunk.page_to,
                    start_char=parent_start,
                    end_char=parent_end,
                    token_count=parent_chunk.token_count,
                    is_parent=False,
                )
                all_chunks.append(child_chunk)
                chunk_index += 1
            else:
                for child_text, child_start, child_end in child_spans:
                    child_chunk = ChunkInfo(
                        chunk_id=uuid.uuid4(),
                        parent_chunk_id=parent_id,
                        chunk_index=chunk_index,
                        content=child_text,
                        section=section.label,
                        page_from=_resolve_page(child_start, offsets),
                        page_to=_resolve_page(child_end, offsets),
                        start_char=child_start,
                        end_char=child_end,
                        token_count=_estimate_tokens(child_text),
                        is_parent=False,
                    )
                    all_chunks.append(child_chunk)
                    chunk_index += 1

    logger.info(
        "document_chunked",
        total_chunks=len(all_chunks),
        parent_chunks=sum(1 for c in all_chunks if c.is_parent),
        child_chunks=sum(1 for c in all_chunks if not c.is_parent),
        sections=len(sections),
    )
    return all_chunks
