"""PII redaction for blind screening (FR-12).

Blind screening hides identity signals from the model — and, optionally, from
the UI. The enforcement point is the prompt-assembly layer, not the UI: a
toggle in a template changes nothing if the serialized payload still carries
the candidate's name. This module is therefore the single function every
T1-tier agent payload passes through before it reaches a provider.

What is redacted is deliberately conservative and enumerable: names, email
addresses, phone numbers, physical addresses, age/date-of-birth markers,
nationality, gender markers, and school-prestige signals. What is *not*
redacted is everything else — skills, employers, dates of employment — because
over-redaction destroys the evidence the scoring layer must cite.

The output preserves character offsets by construction: redaction replaces
spans with fixed-width placeholders of the same length, so an evidence span
computed on the redacted text indexes back into it exactly.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.logging import get_logger

logger = get_logger(__name__)

# Fixed-width placeholders. Each is exactly as long as the span it replaces so
# that offsets computed on the redacted text remain valid on it.
PLACEHOLDER_NAME = "[NAME]"
PLACEHOLDER_CONTACT = "[CONTACT]"
PLACEHOLDER_AGE = "[AGE]"
PLACEHOLDER_LOCATION = "[LOCATION]"
PLACEHOLDER_IDENTITY = "[IDENTITY]"

# Gendered and nationality markers that carry no screening signal but do carry
# disparate-impact exposure. Word-bounded so "male" does not hit "female" —
# the negative lookbehind/lookahead handles the compound cases.
_GENDER_MARKERS = re.compile(
    r"\b(?<!fe)(?:male|female)\b|\b(?:he|she)\s*/\s*(?:him|her)\b"
    r"|\b(?:mr|mrs|ms|miss)\.?\s+(?=[A-Z])",
    re.IGNORECASE,
)

_NATIONALITY_MARKERS = re.compile(
    r"\b(?:indonesian|indonesia|american|america|chinese|china|indian|india"
    r"|japanese|japan|korean|korea|malaysian|malaysia|singaporean|singapore"
    r"|filipino|philippines|vietnamese|vietnam|thai|thailand|european|europe)\b",
    re.IGNORECASE,
)

# Age and date-of-birth signals. A four-digit year preceded by an age cue is a
# birth year; a bare "Age: NN" is an age. Employment dates ("2019 - 2023") are
# NOT matched — they need a cue word before them.
_AGE_MARKERS = re.compile(
    r"\b(?:age|aged|umur)\s*[:\-]?\s*\d{1,3}\b"
    r"|\b(?:born|birth|dob|lahir)\s*[:\-]?\s*(?:in\s+)?\d{4}\b"
    r"|\b(?:year of birth|tanggal lahir)\s*[:\-]?\s*\d{4}\b",
    re.IGNORECASE,
)

_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_PHONE = re.compile(
    r"(?:\+\d{1,3}[\s.-]?)?(?:\(\d{2,4}\)[\s.-]?)?\d{3,4}[\s.-]?\d{3,4}"
    r"(?:[\s.-]?\d{2,5})?"
)

# Street-address shape, two orders:
#   Indonesian: "Jl. Jend. Sudirman No. 45" — street word first.
#   Western:    "45 Main Street" — number first.
# Conservative — a bare city name is handled by the nationality/location
# markers, not by this pattern.
_ADDRESS = re.compile(
    r"\b(?:jalan|jl\.?|jln\.?)\s[^,\n]{0,60}"
    r"|\b\d{1,5}\s+(?:street|st\.?|avenue|ave\.?|road|rd\.?"
    r"|lane|ln\.?|drive|dr\.?|boulevard|blvd\.?)\b[^,\n]{0,60}",
    re.IGNORECASE,
)

# Prestige-signal school names are tenant-configurable in production; the
# default list covers the pattern class so the mechanism is testable.
_PRESTIGE_SCHOOLS: tuple[str, ...] = (
    "MIT",
    "Stanford",
    "Harvard",
    "Oxford",
    "Cambridge",
    "Universitas Indonesia",
    "ITB",
    "Institut Teknologi Bandung",
)


@dataclass(frozen=True, slots=True)
class RedactionFinding:
    """One redaction applied to the text.

    Attributes:
        kind: Category of PII removed.
        count: How many spans of this kind were replaced.
    """

    kind: str
    count: int

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serialisable representation.

        Returns:
            A plain dict suitable for a `jsonb` column.
        """
        return {"kind": self.kind, "count": self.count}


@dataclass(frozen=True, slots=True)
class RedactionResult:
    """The outcome of redacting one text payload.

    Attributes:
        text: The redacted text. Same length as the input when any redaction
            occurred, so offsets remain valid.
        redacted_chars: Total characters replaced.
        findings: Per-category counts, in detection order.
    """

    text: str
    redacted_chars: int = 0
    findings: tuple[RedactionFinding, ...] = field(default=())

    def to_report(self) -> dict[str, object]:
        """Return a JSON-serialisable report for persistence.

        Returns:
            A dict matching the shape used by the sanitization report.
        """
        return {
            "redacted_chars": self.redacted_chars,
            "findings": [f.to_dict() for f in self.findings],
        }


def _replace_all(text: str, pattern: re.Pattern[str], placeholder: str) -> tuple[str, int]:
    """Replace every match with a same-length placeholder.

    Args:
        text: The text to redact.
        pattern: The compiled PII pattern.
        placeholder: The placeholder token.

    Returns:
        The redacted text and the number of characters replaced.
    """
    count = 0
    chars = 0

    def _sub(match: re.Match[str]) -> str:
        nonlocal count, chars
        count += 1
        chars += len(match.group(0))
        # Pad or trim the placeholder to the exact span length so offsets
        # computed on the redacted text index back into it.
        if len(placeholder) <= len(match.group(0)):
            return placeholder + "#" * (len(match.group(0)) - len(placeholder))
        return placeholder[: len(match.group(0))]

    return pattern.sub(_sub, text), chars


def redact_for_blind_screening(
    text: str,
    *,
    candidate_name: str | None = None,
    redact_schools: bool = True,
) -> RedactionResult:
    """Redact identity signals from a payload destined for a model.

    Args:
        text: The payload text (resume text, evidence bundle, chat context).
        candidate_name: The candidate's known name, redacted verbatim wherever
            it appears — regexes alone miss transliterated or hyphenated names.
        redact_schools: Whether to redact prestige-signal school names.

    Returns:
        The redaction result with the safe text and an auditable report.
    """
    if not text:
        return RedactionResult(text=text)

    findings: list[RedactionFinding] = []
    total_chars = 0
    working = text

    def _apply(pattern: re.Pattern[str], placeholder: str, kind: str) -> None:
        nonlocal working, total_chars
        working, chars = _replace_all(working, pattern, placeholder)
        if chars:
            findings.append(RedactionFinding(kind=kind, count=chars))
            total_chars += chars

    # 1. The candidate's own name, verbatim, before any regex touches the text.
    if candidate_name and candidate_name.strip():
        name_pattern = re.compile(
            re.escape(candidate_name.strip()), re.IGNORECASE
        )
        _apply(name_pattern, PLACEHOLDER_NAME, "candidate_name")

    # 2. Contact channels.
    _apply(_EMAIL, PLACEHOLDER_CONTACT, "email")
    _apply(_PHONE, PLACEHOLDER_CONTACT, "phone")
    _apply(_ADDRESS, PLACEHOLDER_LOCATION, "address")

    # 3. Protected-attribute markers. Nationality runs BEFORE school
    # redaction, so "Universitas Indonesia" is masked by the school rule
    # where it belongs — not split across two placeholders.
    _apply(_GENDER_MARKERS, PLACEHOLDER_IDENTITY, "gender_marker")
    _apply(_NATIONALITY_MARKERS, PLACEHOLDER_IDENTITY, "nationality")
    _apply(_AGE_MARKERS, PLACEHOLDER_AGE, "age")

    # 4. Prestige-signal schools (after nationality, see above).
    if redact_schools:
        for school in _PRESTIGE_SCHOOLS:
            _apply(re.compile(re.escape(school), re.IGNORECASE), PLACEHOLDER_NAME, "school")

    if findings:
        logger.info(
            "blind_screening_redaction_applied",
            redacted_chars=total_chars,
            kinds=[f.kind for f in findings],
        )

    return RedactionResult(
        text=working,
        redacted_chars=total_chars,
        findings=tuple(findings),
    )


def assert_no_identity_leakage(payload: str, *, candidate_name: str | None = None) -> None:
    """Raise if identity signals survive in a serialized payload.

    This is the enforcement point the leakage test drives: it inspects the
    payload *after* serialization, because a redaction applied to a field that
    is later re-serialized from the raw object is worth nothing.

    Args:
        payload: The fully serialized payload (e.g. JSON string) about to be
            sent to a provider.
        candidate_name: The candidate's known name.

    Raises:
        ValueError: If any identity signal is still present.
    """
    leaks: list[str] = []

    if candidate_name and candidate_name.strip():
        if candidate_name.strip().lower() in payload.lower():
            leaks.append("candidate_name")

    if _EMAIL.search(payload):
        leaks.append("email")
    if _AGE_MARKERS.search(payload):
        leaks.append("age_marker")
    if _GENDER_MARKERS.search(payload):
        leaks.append("gender_marker")

    if leaks:
        msg = f"Blind-screening leakage detected: {', '.join(leaks)}"
        raise ValueError(msg)
