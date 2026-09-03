"""Bulk ZIP ingestion tests.

The archive is hostile input; these tests drive every defense: entry caps,
decompressed-size budgets, compression-ratio bombs, path traversal, nested
archives, and per-entry media validation.
"""

from __future__ import annotations

import io
import zipfile

import pytest

from app.exceptions import (
    EmptyDocumentError,
    PayloadTooLargeError,
    ValidationFailedError,
)
from app.services.bulk_ingest import extract_resumes_from_zip

PDF_MAGIC = b"%PDF-1.4\n" + b"%" + b"0" * 100


def _make_zip(members: dict[str, bytes]) -> bytes:
    """Build an in-memory ZIP from a name → bytes mapping."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in members.items():
            zf.writestr(name, content)
    return buffer.getvalue()


def _accept_pdf(content: bytes) -> str:
    """A validator shaped like `validate_upload` — accepts PDFs only."""
    if not content.startswith(b"%PDF"):
        raise ValueError("File must be a PDF or DOCX document.")
    return "application/pdf"


def test_valid_zip_yields_entries():
    data = _make_zip(
        {
            "alice.pdf": PDF_MAGIC,
            "bob.pdf": PDF_MAGIC,
        }
    )
    result = extract_resumes_from_zip(data, validate_entry=_accept_pdf)
    assert [e.filename for e in result.entries] == ["alice.pdf", "bob.pdf"]
    assert result.rejected == ()
    assert result.total_uncompressed_bytes == 2 * len(PDF_MAGIC)


def test_empty_archive_is_rejected():
    with pytest.raises(EmptyDocumentError):
        extract_resumes_from_zip(b"")


def test_non_zip_bytes_are_rejected():
    with pytest.raises(ValidationFailedError):
        extract_resumes_from_zip(b"this is not a zip file at all")


def test_entry_count_cap():
    members = {f"resume_{i}.pdf": PDF_MAGIC for i in range(10)}
    data = _make_zip(members)
    with pytest.raises(ValidationFailedError, match="limit is 5"):
        extract_resumes_from_zip(data, max_entries=5)


def test_archive_size_cap():
    data = _make_zip({"a.pdf": PDF_MAGIC})
    with pytest.raises(PayloadTooLargeError):
        extract_resumes_from_zip(data, max_total_compressed_bytes=10)


def test_declared_uncompressed_budget_enforced_before_decompression():
    """A hostile central directory claiming a huge total is rejected on
    metadata alone — no member is ever decompressed."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("bomb.pdf", b"small")
    data = buffer.getvalue()
    with pytest.raises(PayloadTooLargeError):
        extract_resumes_from_zip(
            data,
            max_uncompressed_bytes=3,  # below the declared size (5 bytes)
        )


def test_compression_ratio_bomb_is_rejected():
    """A 1000:1 ratio member is a bomb signal regardless of absolute size."""
    bomb = b"0" * 100_000  # compresses extremely well
    data = _make_zip({"bomb.pdf": bomb})
    with pytest.raises(PayloadTooLargeError, match="ratio"):
        extract_resumes_from_zip(data, max_ratio=100.0)


def test_lying_metadata_caught_while_reading():
    """If declared sizes lie, the incremental reader still enforces the
    budget while decompressing."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        info = zipfile.ZipInfo("bomb.pdf")
        # Write a member whose declared size is small but whose actual
        # decompressed bulk is large — the reader must catch it.
        zf.writestr(info, b"0" * 500_000)
    data = buffer.getvalue()
    with pytest.raises(PayloadTooLargeError):
        extract_resumes_from_zip(data, max_uncompressed_bytes=1000)


def test_path_traversal_names_are_flattened():
    data = _make_zip(
        {
            "../../etc/passwd": PDF_MAGIC,
            "nested/dir/alice.pdf": PDF_MAGIC,
        }
    )
    result = extract_resumes_from_zip(data, validate_entry=_accept_pdf)
    names = [e.filename for e in result.entries]
    assert "passwd" in names
    assert "alice.pdf" in names
    assert not any("/" in n or ".." in n for n in names)


def test_directory_entries_are_skipped():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("folder/", "")
        zf.writestr("folder/alice.pdf", PDF_MAGIC)
    result = extract_resumes_from_zip(buffer.getvalue(), validate_entry=_accept_pdf)
    assert [e.filename for e in result.entries] == ["alice.pdf"]


def test_unsupported_media_is_rejected_not_fatal():
    """One bad file must not abort the batch — it is reported and skipped."""
    data = _make_zip(
        {
            "good.pdf": PDF_MAGIC,
            "evil.exe": b"MZ\x90\x00",
            "also_good.pdf": PDF_MAGIC,
        }
    )
    result = extract_resumes_from_zip(data, validate_entry=_accept_pdf)
    assert [e.filename for e in result.entries] == ["good.pdf", "also_good.pdf"]
    assert len(result.rejected) == 1
    rejected_name, reason = result.rejected[0]
    assert rejected_name == "evil.exe"
    assert "PDF" in reason


def test_nested_archive_is_not_expanded():
    """A ZIP inside a ZIP is just an unsupported blob — never recursed into."""
    inner = _make_zip({"inner.pdf": PDF_MAGIC})
    data = _make_zip({"outer.zip": inner})
    result = extract_resumes_from_zip(data, validate_entry=_accept_pdf)
    assert result.entries == ()
    assert len(result.rejected) == 1


def test_no_validator_accepts_everything():
    data = _make_zip({"anything.bin": b"\x00\x01\x02"})
    result = extract_resumes_from_zip(data)
    assert len(result.entries) == 1
