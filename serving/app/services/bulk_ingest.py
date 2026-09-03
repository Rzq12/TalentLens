"""Bulk ZIP ingestion with archive-hardening.

A ZIP is hostile input wearing a friendly extension. The classic attacks:

* **Zip bomb (ratio)** — a 10 MB archive that decompresses to 10 GB. Defeated
  by tracking *uncompressed* size as entries are read and aborting the moment
  the cumulative total crosses the budget.
* **Zip bomb (count)** — 100k tiny entries to exhaust entry-count limits and
  slow validation. Defeated by an entry cap enforced before reading any entry.
* **Path traversal** — `../../etc/passwd` style names. Defeated by never
  trusting archive paths: the candidate-facing filename is the entry's basename
  only, re-sanitized through the same path as single uploads.
* **Nested archives** — `bomb.zip` inside `outer.zip`. Not expanded; entries
  that fail media validation are reported, not recursed into.

Defense order matters: count → total compressed size → per-entry budget while
reading. Every defense reads sizes from the ZIP central directory *before*
decompression, so an attacker cannot make us allocate first and discover too
late.
"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass, field
from io import BytesIO

from app.exceptions import (
    EmptyDocumentError,
    PayloadTooLargeError,
    UnsupportedMediaTypeError,
    ValidationFailedError,
)
from app.logging import get_logger

logger = get_logger(__name__)

# Archive-level defaults. Tunable via keyword so tests and tenants can tighten
# them; the values are deliberately small enough that a hostile archive fails
# fast while a realistic batch (hundreds of resumes) sails through.
DEFAULT_MAX_ENTRIES = 200
DEFAULT_MAX_UNCOMPRESSED_BYTES = 2 * 1024 * 1024 * 1024  # 2 GiB across all entries
DEFAULT_MAX_TOTAL_COMPRESSED_BYTES = 200 * 1024 * 1024  # 200 MiB archive size
# Compression ratio per entry beyond which we stop trusting the archive — a
# legitimate resume compresses poorly; anything near 1000:1 is a bomb signal.
DEFAULT_MAX_RATIO = 1000.0


@dataclass(frozen=True, slots=True)
class ZipEntry:
    """One candidate archive member accepted for ingestion.

    Attributes:
        filename: The entry's basename, safe for reuse as an upload filename.
        content: The decompressed bytes (validated as PDF/DOCX later).
    """

    filename: str
    content: bytes


@dataclass(frozen=True, slots=True)
class ZipExtractionResult:
    """The outcome of opening and extracting an archive.

    Attributes:
        entries: Accepted members with their bytes.
        rejected: Filenames rejected with the reason (unsupported media, oversize
            entry, parse-invalid bytes) — reported to the caller, never silently
            dropped.
        total_uncompressed_bytes: Sum of accepted + rejected member sizes, i.e.
            everything the archive actually contained.
    """

    entries: tuple[ZipEntry, ...] = ()
    rejected: tuple[tuple[str, str], ...] = ()
    total_uncompressed_bytes: int = 0


def _sanitize_entry_name(raw_name: str) -> str:
    """Reduce an archive path to a safe basename.

    Args:
        raw_name: The entry's full path inside the archive.

    Returns:
        The last path component, stripped of directories. Returns "" for
        directory entries.
    """
    name = raw_name.replace("\\", "/")
    if name.endswith("/"):
        return ""
    return name.rsplit("/", 1)[-1]


def extract_resumes_from_zip(
    data: bytes,
    *,
    max_entries: int = DEFAULT_MAX_ENTRIES,
    max_uncompressed_bytes: int = DEFAULT_MAX_UNCOMPRESSED_BYTES,
    max_total_compressed_bytes: int = DEFAULT_MAX_TOTAL_COMPRESSED_BYTES,
    max_ratio: float = DEFAULT_MAX_RATIO,
    validate_entry: "callable[[bytes], str] | None" = None,
) -> ZipExtractionResult:
    """Safely extract resume documents from an uploaded ZIP archive.

    Every defense reads metadata before decompressing anything. The function
    never recurses into nested archives and never trusts archive paths.

    Args:
        data: The raw ZIP bytes.
        max_entries: Maximum number of file entries permitted.
        max_uncompressed_bytes: Cumulative decompressed-size budget.
        max_total_compressed_bytes: Maximum archive (compressed) size.
        max_ratio: Maximum per-entry compression ratio before rejection.
        validate_entry: Optional validator returning the detected media type
            for a member's bytes; members failing it are rejected, not parsed.
            Defaults to size-only checks when omitted.

    Returns:
        The extraction result with accepted entries and per-file rejections.

    Raises:
        EmptyDocumentError: If the archive is empty.
        PayloadTooLargeError: If the archive or its decompressed bulk exceeds
            the configured ceilings.
        ValidationFailedError: If the bytes are not a valid ZIP or violate the
            entry-count cap.
    """
    if not data:
        raise EmptyDocumentError()
    if len(data) > max_total_compressed_bytes:
        raise PayloadTooLargeError()

    try:
        archive = zipfile.ZipFile(BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ValidationFailedError(
            message="Uploaded file is not a valid ZIP archive."
        ) from exc

    infolist = archive.infolist()
    file_entries = [info for info in infolist if not info.is_dir()]

    if len(file_entries) > max_entries:
        raise ValidationFailedError(
            message=(
                f"Archive contains {len(file_entries)} files; "
                f"the limit is {max_entries}."
            )
        )

    # Central-directory pass: sum declared sizes and check ratios BEFORE any
    # decompression. A hostile archive is rejected on metadata alone.
    declared_total = sum(info.file_size for info in file_entries)
    if declared_total > max_uncompressed_bytes:
        raise PayloadTooLargeError()
    for info in file_entries:
        if info.compress_size > 0 and info.file_size / info.compress_size > max_ratio:
            raise PayloadTooLargeError(
                message=(
                    f"Archive member '{info.filename}' has a suspicious "
                    f"compression ratio ({info.file_size / info.compress_size:.0f}:1)."
                )
            )

    accepted: list[ZipEntry] = []
    rejected: list[tuple[str, str]] = []
    consumed = 0

    with archive:
        for info in file_entries:
            safe_name = _sanitize_entry_name(info.filename)
            if not safe_name:
                continue

            # Trust the central directory but verify while reading: decompress
            # incrementally and abort the instant the budget is crossed. This
            # closes the gap where declared metadata lies.
            with archive.open(info) as member:
                chunks: list[bytes] = []
                size = 0
                while True:
                    chunk = member.read(64 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if consumed + size > max_uncompressed_bytes:
                        logger.warning(
                            "zip_bomb_budget_exceeded",
                            entry=safe_name,
                            consumed=consumed + size,
                        )
                        raise PayloadTooLargeError(
                            message=(
                                "Archive decompressed size exceeds the "
                                f"{max_uncompressed_bytes} byte budget."
                            )
                        )
                    chunks.append(chunk)

            content = b"".join(chunks)
            consumed += size

            if validate_entry is not None:
                try:
                    validate_entry(content)
                except Exception as exc:  # noqa: BLE001 — report, don't abort the batch
                    rejected.append((safe_name, str(exc)))
                    continue

            accepted.append(ZipEntry(filename=safe_name, content=content))

    return ZipExtractionResult(
        entries=tuple(accepted),
        rejected=tuple(rejected),
        total_uncompressed_bytes=consumed,
    )
