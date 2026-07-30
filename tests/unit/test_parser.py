"""Resume parser: text extraction, offset anchoring, and format detection.

The parser is deterministic — no LLM. These tests pin the exact behaviour the
evidence-citation layer depends on: byte-accurate offsets and honest failure.
"""

from __future__ import annotations

import pytest

# --------------------------------------------------------------------------- #
# Content-type sniffing (magic bytes, not the client's claim)                  #
# --------------------------------------------------------------------------- #


def test_pdf_is_detected_from_magic_bytes(minimal_pdf_bytes):
    from app.utils.parsing import detect_media_type

    assert detect_media_type(minimal_pdf_bytes) == "application/pdf"


def test_docx_is_detected_from_magic_bytes(minimal_docx_bytes):
    from app.config import DOCX_MIME
    from app.utils.parsing import detect_media_type

    assert detect_media_type(minimal_docx_bytes) == DOCX_MIME


def test_a_lying_extension_does_not_fool_detection():
    """A .pdf name over PNG bytes must be detected as PNG, not PDF."""
    from app.utils.parsing import detect_media_type

    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32

    assert detect_media_type(png) != "application/pdf"


def test_empty_bytes_have_no_media_type():
    from app.utils.parsing import detect_media_type

    assert detect_media_type(b"") is None


# --------------------------------------------------------------------------- #
# PDF extraction                                                               #
# --------------------------------------------------------------------------- #


def test_pdf_text_is_extracted(minimal_pdf_bytes):
    from app.services.parser import parse_document

    result = parse_document(minimal_pdf_bytes, "application/pdf")

    assert "Jane Doe" in result.text
    assert "Kubernetes" in result.text


def test_pdf_parse_reports_page_count(minimal_pdf_bytes):
    from app.services.parser import parse_document

    result = parse_document(minimal_pdf_bytes, "application/pdf")

    assert result.page_count == 1
    assert len(result.pages) == 1


def test_pdf_parse_records_parser_version(minimal_pdf_bytes):
    """Provenance: every parse is attributable to a parser version."""
    from app.services.parser import parse_document

    result = parse_document(minimal_pdf_bytes, "application/pdf")

    assert result.parser_version


def test_page_offsets_index_back_into_the_extracted_text(minimal_pdf_bytes):
    """The offsets are the evidence anchor — they must be exact, not approximate."""
    from app.services.parser import parse_document

    result = parse_document(minimal_pdf_bytes, "application/pdf")

    for page in result.pages:
        assert result.text[page.start_char : page.end_char] == page.text


def test_scanned_pdf_yields_no_text_and_flags_ocr(scanned_pdf_bytes):
    """A page with no text layer must set needs_ocr rather than silently return ''."""
    from app.services.parser import parse_document

    result = parse_document(scanned_pdf_bytes, "application/pdf")

    assert result.needs_ocr is True
    assert result.parse_status == "low_yield"


def test_text_bearing_pdf_does_not_request_ocr(minimal_pdf_bytes):
    from app.services.parser import parse_document

    result = parse_document(minimal_pdf_bytes, "application/pdf")

    assert result.needs_ocr is False
    assert result.parse_status == "ok"


def test_corrupt_pdf_raises_rather_than_returning_garbage(corrupt_pdf_bytes):
    """Never degrade to a guessed profile — a bad parse propagates across jobs."""
    from app.exceptions import DocumentParseError
    from app.services.parser import parse_document

    with pytest.raises(DocumentParseError):
        parse_document(corrupt_pdf_bytes, "application/pdf")


# --------------------------------------------------------------------------- #
# DOCX extraction                                                              #
# --------------------------------------------------------------------------- #


def test_docx_text_is_extracted(minimal_docx_bytes):
    from app.config import DOCX_MIME
    from app.services.parser import parse_document

    result = parse_document(minimal_docx_bytes, DOCX_MIME)

    assert "Jane Doe" in result.text
    assert "PostgreSQL" in result.text


def test_docx_offsets_index_back_into_the_extracted_text(minimal_docx_bytes):
    from app.config import DOCX_MIME
    from app.services.parser import parse_document

    result = parse_document(minimal_docx_bytes, DOCX_MIME)

    for page in result.pages:
        assert result.text[page.start_char : page.end_char] == page.text


def test_corrupt_docx_raises(corrupt_pdf_bytes):
    from app.config import DOCX_MIME
    from app.exceptions import DocumentParseError
    from app.services.parser import parse_document

    with pytest.raises(DocumentParseError):
        parse_document(corrupt_pdf_bytes, DOCX_MIME)


# --------------------------------------------------------------------------- #
# Guard rails                                                                  #
# --------------------------------------------------------------------------- #


def test_unsupported_media_type_is_rejected():
    from app.exceptions import UnsupportedMediaTypeError
    from app.services.parser import parse_document

    with pytest.raises(UnsupportedMediaTypeError):
        parse_document(b"\x89PNG\r\n\x1a\n", "image/png")


def test_empty_payload_is_rejected():
    from app.exceptions import EmptyDocumentError
    from app.services.parser import parse_document

    with pytest.raises(EmptyDocumentError):
        parse_document(b"", "application/pdf")


def test_content_hash_is_stable_and_content_addressed(minimal_pdf_bytes):
    """Dedupe key: identical bytes must hash identically, different bytes must not."""
    from app.utils.parsing import content_sha256

    assert content_sha256(minimal_pdf_bytes) == content_sha256(minimal_pdf_bytes)
    assert content_sha256(minimal_pdf_bytes) != content_sha256(minimal_pdf_bytes + b"x")
    assert len(content_sha256(minimal_pdf_bytes)) == 64


def test_filename_is_sanitized_against_traversal():
    from app.utils.parsing import sanitize_filename

    assert "/" not in sanitize_filename("../../etc/passwd")
    assert "\\" not in sanitize_filename(r"..\..\windows\system32\cmd.exe")
    assert sanitize_filename("resume final (1).pdf").endswith(".pdf")
    assert sanitize_filename("") == "unnamed"
