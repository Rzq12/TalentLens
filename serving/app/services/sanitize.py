"""Prompt-injection sanitization for untrusted document text.

Resume text is hostile input. Candidates embed instructions aimed at an LLM in
places a human reviewer never sees: white-on-white runs, one-point fonts, text
positioned off the page, and document metadata. This module removes what is
provably invisible and flags what merely looks like an instruction.

Two deliberate asymmetries:

* **Invisible content is removed; visible content is only flagged.** Text a
  recruiter can read is evidence, and deleting it would both corrupt the record
  and break the character offsets the citation layer depends on.
* **Detection is deterministic.** No model is consulted, so the same document
  always yields the same report and the decision can be defended after the fact.

This is Layer 1-2 of the defense described in `ARCHITECTURE.md` §15.2. It runs on
100% of ingested text, unconditionally.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from app.logging import get_logger
from app.services.parser import ParsedDocument, TextSpan

logger = get_logger(__name__)

FindingKind = Literal[
    "invisible_text",
    "tiny_font",
    "off_canvas",
    "metadata",
    "instruction_pattern",
]

# A span at or below this point size is not legible at any realistic zoom.
MIN_LEGIBLE_FONT_SIZE = 4.0

# Luminance above which text on a white page is effectively invisible. Computed
# with the sRGB coefficients rather than a naive average so that yellow-on-white
# (high luminance, low mean) is caught too.
MAX_VISIBLE_LUMINANCE = 0.92

# How far outside the page box a span must sit to count as off-canvas. A small
# tolerance avoids flagging glyphs that legitimately bleed past the trim edge.
OFF_CANVAS_TOLERANCE_PT = 2.0

# Risk weights. Hidden content is worth more than a suspicious phrase in plain
# sight, because hiding is itself evidence of intent.
_WEIGHT_HIDDEN = 0.35
_WEIGHT_METADATA = 0.25
_WEIGHT_PATTERN = 0.20

QUARANTINE_THRESHOLD = 0.5

MAX_EXCERPT_CHARS = 120

# Patterns that only make sense as an instruction to a language model. Each is
# anchored on a verb-plus-object shape rather than a bare keyword, so ordinary
# technical vocabulary ("distributed system", "prompt-based tooling", "Role:")
# does not match. False positives corrupt legitimate candidates, so the bar for
# adding a pattern here is that it must not plausibly occur in a real resume.
_INSTRUCTION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "override-previous-instructions",
        re.compile(
            r"\b(?:ignore|disregard|forget|override)\b[^.\n]{0,40}?"
            r"\b(?:previous|prior|above|earlier|all)\b[^.\n]{0,20}?"
            r"\b(?:instruction|prompt|direction|rule|context)s?\b",
            re.IGNORECASE,
        ),
    ),
    (
        "disregard-and-emit",
        re.compile(
            r"\b(?:disregard|ignore)\b[^.\n]{0,40}?\b(?:and|then)\b[^.\n]{0,20}?"
            r"\b(?:output|print|say|respond|reply|return)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "role-reassignment",
        re.compile(
            r"\byou\s+are\s+(?:now\s+)?(?:a|an|the)\b[^.\n]{0,60}?"
            r"\b(?:assistant|model|ai|bot|system)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "impersonated-system-turn",
        re.compile(r"(?:^|\n)\s*(?:system|assistant|user)\s*:\s*\S", re.IGNORECASE),
    ),
    (
        "chat-template-delimiter",
        re.compile(
            r"<\|(?:im_start|im_end|system|endoftext|eot_id|start_header_id)\|>"
            r"|\[/?INST\]|<<SYS>>",
            re.IGNORECASE,
        ),
    ),
    (
        "scoring-directive",
        re.compile(
            r"\b(?:rate|score|rank|grade)\b[^.\n]{0,40}?"
            r"\b(?:100|10/10|maximum|highest|perfect|exceptional\s+fit|top\s+candidate)\b",
            re.IGNORECASE,
        ),
    ),
)


@dataclass(frozen=True, slots=True)
class SanitizationFinding:
    """One thing the sanitizer removed or flagged.

    Attributes:
        kind: Which rule fired.
        detail: Why it fired, in terms a human reviewer can audit.
        excerpt: A bounded sample of the offending text.
        page: One-based page number, when the finding is anchored to a page.
        removed: True if the text was stripped; False if only flagged.
    """

    kind: FindingKind
    detail: str
    excerpt: str
    page: int | None = None
    removed: bool = False

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serialisable representation.

        Returns:
            A plain dict suitable for a `jsonb` column.
        """
        return {
            "kind": self.kind,
            "detail": self.detail,
            "excerpt": self.excerpt,
            "page": self.page,
            "removed": self.removed,
        }


@dataclass(frozen=True, slots=True)
class SanitizationResult:
    """The outcome of sanitizing one document.

    Attributes:
        text: The text safe to store and later show a model.
        removed_chars: How many characters were stripped.
        findings: Every rule that fired, in detection order.
        injection_risk_score: Aggregate risk in [0.0, 1.0].
        should_quarantine: True when the document must not be processed further
            without human review.
    """

    text: str
    removed_chars: int = 0
    findings: tuple[SanitizationFinding, ...] = field(default=())
    injection_risk_score: float = 0.0
    should_quarantine: bool = False

    def to_report(self) -> dict[str, object]:
        """Return a JSON-serialisable report for persistence.

        Returns:
            A dict matching the `sanitization_report` column's shape.
        """
        return {
            "removed_chars": self.removed_chars,
            "injection_risk_score": round(self.injection_risk_score, 4),
            "should_quarantine": self.should_quarantine,
            "findings": [f.to_dict() for f in self.findings],
        }


def _excerpt(text: str) -> str:
    """Collapse whitespace and truncate text for safe inclusion in a report.

    Args:
        text: The raw offending text.

    Returns:
        A single-line excerpt of at most `MAX_EXCERPT_CHARS` characters.
    """
    flattened = " ".join(text.split())
    if len(flattened) <= MAX_EXCERPT_CHARS:
        return flattened
    return flattened[: MAX_EXCERPT_CHARS - 1] + "..."


def _luminance(packed_color: int) -> float:
    """Return the relative luminance of a packed sRGB integer.

    Args:
        packed_color: Colour as ``0xRRGGBB``.

    Returns:
        Luminance in [0.0, 1.0], where 1.0 is white.
    """
    red = ((packed_color >> 16) & 0xFF) / 255.0
    green = ((packed_color >> 8) & 0xFF) / 255.0
    blue = (packed_color & 0xFF) / 255.0
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def _is_off_canvas(span: TextSpan) -> bool:
    """Report whether a span sits outside its page's visible area.

    Args:
        span: The span to test.

    Returns:
        True when the span's box falls beyond the page rectangle.
    """
    if span.bbox is None or span.page_rect is None:
        return False
    x0, y0, x1, y1 = span.bbox
    px0, py0, px1, py1 = span.page_rect
    tolerance = OFF_CANVAS_TOLERANCE_PT
    return (
        x1 < px0 - tolerance
        or y1 < py0 - tolerance
        or x0 > px1 + tolerance
        or y0 > py1 + tolerance
    )


def classify_span(span: TextSpan) -> tuple[FindingKind, str] | None:
    """Decide whether a span is invisible, and if so why.

    Args:
        span: The span to classify.

    Returns:
        The finding kind and a human-readable reason, or None if the span is
        legitimately visible.
    """
    if 0.0 < span.size <= MIN_LEGIBLE_FONT_SIZE:
        return (
            "tiny_font",
            f"font size {span.size:.2f}pt is below {MIN_LEGIBLE_FONT_SIZE}pt",
        )
    if _is_off_canvas(span):
        return "off_canvas", "span is positioned outside the page rectangle"
    if span.color is not None:
        luminance = _luminance(span.color)
        if luminance >= MAX_VISIBLE_LUMINANCE:
            return (
                "invisible_text",
                f"text luminance {luminance:.3f} is indistinguishable from a white page",
            )
    return None


def score_injection_risk(text: str) -> float:
    """Score text for language that only makes sense as a model instruction.

    Args:
        text: The text to inspect.

    Returns:
        Risk in [0.0, 1.0]. Zero means no pattern matched.
    """
    matched = {name for name, pattern in _INSTRUCTION_PATTERNS if pattern.search(text)}
    if not matched:
        return 0.0
    return min(1.0, len(matched) * _WEIGHT_PATTERN)


def _pattern_findings(
    text: str, source: FindingKind, page: int | None
) -> list[SanitizationFinding]:
    """Build findings for every instruction pattern matching `text`.

    Args:
        text: The text to inspect.
        source: The finding kind to record.
        page: Page number, when known.

    Returns:
        One finding per distinct pattern that matched.
    """
    findings: list[SanitizationFinding] = []
    for name, pattern in _INSTRUCTION_PATTERNS:
        match = pattern.search(text)
        if match:
            findings.append(
                SanitizationFinding(
                    kind=source,
                    detail=f"matched instruction pattern '{name}'",
                    excerpt=_excerpt(match.group(0)),
                    page=page,
                )
            )
    return findings


def _collapse_blank_runs(text: str) -> str:
    """Tidy the whitespace left behind by removing spans.

    Args:
        text: Text with holes where spans were stripped.

    Returns:
        The same text with runs of blank lines collapsed to two newlines.
    """
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def sanitize_document(parsed: ParsedDocument) -> SanitizationResult:
    """Strip invisible content from a parsed document and score what remains.

    Args:
        parsed: The document as produced by `app.services.parser.parse_document`.

    Returns:
        The sanitized text plus a full, auditable report of every action taken.
    """
    findings: list[SanitizationFinding] = []
    removed_chars = 0
    text = parsed.text

    # Layer 1 - remove spans that are provably invisible.
    hidden_kinds: set[FindingKind] = set()
    for span in parsed.spans:
        classification = classify_span(span)
        if classification is None:
            continue
        kind, detail = classification
        stripped = span.text.strip()
        if not stripped:
            continue
        if stripped in text:
            text = text.replace(stripped, "")
            removed_chars += len(stripped)
        hidden_kinds.add(kind)
        findings.append(
            SanitizationFinding(
                kind=kind,
                detail=detail,
                excerpt=_excerpt(span.text),
                page=span.page,
                removed=True,
            )
        )

    # Layer 1b - metadata never enters the text, but is still an attack surface.
    metadata_hit = False
    for key, value in parsed.metadata.items():
        if score_injection_risk(value) > 0:
            metadata_hit = True
            findings.append(
                SanitizationFinding(
                    kind="metadata",
                    detail=f"instruction-like content in metadata field '{key}'",
                    excerpt=_excerpt(value),
                )
            )

    # Layer 2 - flag, but never remove, instruction-like visible text.
    pattern_findings = _pattern_findings(text, "instruction_pattern", None)
    findings.extend(pattern_findings)

    score = _WEIGHT_HIDDEN * len(hidden_kinds)
    score += _WEIGHT_METADATA if metadata_hit else 0.0
    score += _WEIGHT_PATTERN * len(pattern_findings)
    score = min(1.0, score)

    result = SanitizationResult(
        text=_collapse_blank_runs(text),
        removed_chars=removed_chars,
        findings=tuple(findings),
        injection_risk_score=score,
        should_quarantine=score >= QUARANTINE_THRESHOLD,
    )

    if findings:
        logger.warning(
            "document_sanitized",
            removed_chars=removed_chars,
            finding_count=len(findings),
            kinds=sorted({f.kind for f in findings}),
            injection_risk_score=round(score, 4),
            should_quarantine=result.should_quarantine,
        )

    return result
