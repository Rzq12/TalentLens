"""Pure helpers for document identification and naming.

No I/O, no side effects. Content type is decided by inspecting the bytes, never
by trusting a client-supplied filename or `Content-Type` header.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
import zipfile
from io import BytesIO

from app.config import DOCX_MIME

PDF_MAGIC = b"%PDF-"
ZIP_MAGIC = b"PK\x03\x04"
MAX_FILENAME_LENGTH = 120
_UNSAFE_FILENAME_CHARS = re.compile(r"[^A-Za-z0-9._ -]")
_REPEATED_DOTS = re.compile(r"\.{2,}")


def content_sha256(content: bytes) -> str:
    """Return the lowercase hex SHA-256 of `content`.

    Used as the content-addressed dedupe key: the same resume arriving through
    three channels must resolve to one stored document.

    Args:
        content: Raw file bytes.

    Returns:
        A 64-character hex digest.
    """
    return hashlib.sha256(content).hexdigest()


def _is_docx(content: bytes) -> bool:
    """Report whether a ZIP container is specifically a Word document.

    Args:
        content: Raw file bytes already known to start with the ZIP magic.

    Returns:
        True if the archive carries the WordprocessingML main document part.
    """
    try:
        with zipfile.ZipFile(BytesIO(content)) as archive:
            return "word/document.xml" in archive.namelist()
    except (zipfile.BadZipFile, OSError):
        return False


def detect_media_type(content: bytes) -> str | None:
    """Identify a document's real media type from its leading bytes.

    A filename extension is a claim, not evidence. DOCX is a ZIP container, so
    identifying it requires looking inside for the WordprocessingML part rather
    than stopping at the ZIP magic — otherwise any .zip would pass as a resume.

    Args:
        content: Raw file bytes.

    Returns:
        The detected media type, or None if the bytes match nothing supported.
    """
    if not content:
        return None
    if content.startswith(PDF_MAGIC):
        return "application/pdf"
    if content.startswith(ZIP_MAGIC) and _is_docx(content):
        return DOCX_MIME
    return None


def sanitize_filename(filename: str) -> str:
    """Reduce a client-supplied filename to something safe to store and log.

    Strips directory components (defeating traversal), normalizes Unicode to
    ASCII, removes characters outside a conservative allowlist, and truncates.

    Args:
        filename: The untrusted original name.

    Returns:
        A safe filename; "unnamed" when nothing usable survives.
    """
    tail = filename.replace("\\", "/").rsplit("/", maxsplit=1)[-1]
    normalized = unicodedata.normalize("NFKD", tail).encode("ascii", "ignore").decode()
    cleaned = _UNSAFE_FILENAME_CHARS.sub("_", normalized)
    cleaned = _REPEATED_DOTS.sub(".", cleaned).strip(". _")
    if not cleaned:
        return "unnamed"
    return cleaned[:MAX_FILENAME_LENGTH]
