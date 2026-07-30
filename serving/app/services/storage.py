"""Object storage behind a narrow port.

The application depends on the `ObjectStore` protocol, never on Supabase or S3
directly, so swapping the backing store later is a new adapter plus a config
flip rather than a change to any caller.
"""

from __future__ import annotations

import uuid
from typing import Protocol

from app.config import Settings, get_settings
from app.exceptions import StorageError
from app.utils.parsing import sanitize_filename


class ObjectStore(Protocol):
    """Minimal storage contract required by ingestion."""

    async def put(self, key: str, content: bytes, content_type: str) -> None:
        """Store `content` under `key`."""
        ...

    async def get(self, key: str) -> bytes:
        """Retrieve the bytes stored under `key`."""
        ...


class InMemoryObjectStore:
    """Process-local store used by tests and local development.

    Deliberately not durable — it exists so the ingestion path can be exercised
    end to end without a network dependency.
    """

    def __init__(self) -> None:
        """Initialize an empty store."""
        self._objects: dict[str, bytes] = {}

    async def put(self, key: str, content: bytes, content_type: str) -> None:
        """Store `content` under `key`.

        Args:
            key: Storage key.
            content: Raw bytes.
            content_type: Media type, retained by real backends.
        """
        self._objects[key] = content

    async def get(self, key: str) -> bytes:
        """Retrieve the bytes stored under `key`.

        Args:
            key: Storage key.

        Returns:
            The stored bytes.

        Raises:
            StorageError: If nothing is stored under `key`.
        """
        try:
            return self._objects[key]
        except KeyError as err:
            raise StorageError("Object not found in storage.") from err


_STORE: InMemoryObjectStore | None = None


def build_storage_key(tenant_id: uuid.UUID, sha256: str, filename: str) -> str:
    """Compose a tenant-prefixed, content-addressed storage key.

    The tenant prefix keeps one tenant's objects enumerable without touching
    another's, and the hash makes the key stable for identical content.

    Args:
        tenant_id: Owning tenant.
        sha256: Content hash of the document.
        filename: Original filename; sanitized before use.

    Returns:
        A storage key of the form `tenants/<tenant>/resumes/<sha>/<name>`.
    """
    return f"tenants/{tenant_id}/resumes/{sha256}/{sanitize_filename(filename)}"


def get_object_store(settings: Settings | None = None) -> ObjectStore:
    """Return the configured object store adapter.

    Args:
        settings: Optional configuration override.

    Returns:
        The adapter selected by `Settings.storage_backend`.

    Raises:
        StorageError: If the Supabase backend is selected but not configured.
    """
    global _STORE
    cfg = settings or get_settings()
    if cfg.storage_backend == "supabase":
        if not (cfg.supabase_url and cfg.supabase_service_key):
            raise StorageError("Supabase storage selected but not configured.")
        raise StorageError("Supabase adapter is not implemented in Phase 1.")
    if _STORE is None:
        _STORE = InMemoryObjectStore()
    return _STORE
