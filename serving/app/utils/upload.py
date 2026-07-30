"""Bounded file-upload reader.

Reads an ``UploadFile`` in chunks and raises early if the content exceeds the
configured ceiling. This prevents an attacker from forcing the server to buffer
an arbitrarily large payload into memory before validation rejects it.
"""

from __future__ import annotations

from fastapi import UploadFile

from app.config import Settings, get_settings
from app.exceptions import EmptyDocumentError, PayloadTooLargeError

CHUNK_SIZE = 64 * 1024  # 64 KiB per read


async def read_upload_bounded(
    file: UploadFile,
    settings: Settings | None = None,
) -> bytes:
    """Read an upload file with an enforced size ceiling.

    The file is consumed in chunks. As soon as the cumulative size exceeds
    ``settings.max_upload_bytes`` the read is aborted and
    :class:`PayloadTooLargeError` is raised — the remaining bytes are never
    buffered.

    Args:
        file: The FastAPI upload file to read.
        settings: Optional configuration override.

    Returns:
        The complete file content as bytes.

    Raises:
        EmptyDocumentError: If the file contains zero bytes.
        PayloadTooLargeError: If the file exceeds the configured size ceiling.
    """
    cfg = settings or get_settings()
    max_bytes = cfg.max_upload_bytes
    chunks: list[bytes] = []
    total = 0

    while True:
        chunk = await file.read(CHUNK_SIZE)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise PayloadTooLargeError()
        chunks.append(chunk)

    if total == 0:
        raise EmptyDocumentError()

    return b"".join(chunks)
