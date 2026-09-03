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
from app.logging import get_logger
from app.utils.parsing import sanitize_filename

logger = get_logger(__name__)


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


class SupabaseObjectStore:
    """Durable object store backed by Supabase Storage.

    The revised stack (ARCHITECTURE-AGENTS.md §1.1) names Supabase Storage as
    the object store: one vendor account covers DB, Auth, and Storage. This
    adapter talks to the Storage REST API directly over HTTP — no vendor SDK —
    so the dependency surface stays small and the failure modes stay
    classifiable through the same error hierarchy as every other adapter.

    The service key is read from configuration and never logged, never returned
    in any response, and never sent anywhere except the Supabase endpoint.
    """

    def __init__(self, *, base_url: str, service_key: str, bucket: str) -> None:
        """Initialize the adapter.

        Args:
            base_url: Supabase project URL, e.g. ``https://xyz.supabase.co``.
            service_key: Service-role key. Server-side only.
            bucket: Target storage bucket. Must already exist.
        """
        self._base_url = base_url.rstrip("/")
        self._service_key = service_key
        self._bucket = bucket

    def _object_url(self, key: str) -> str:
        """Compose the REST object URL for a storage key.

        Args:
            key: The storage key.

        Returns:
            The absolute object endpoint URL.
        """
        return f"{self._base_url}/storage/v1/object/{self._bucket}/{key}"

    async def put(self, key: str, content: bytes, content_type: str) -> None:
        """Store `content` under `key`, creating the bucket if needed.

        Args:
            key: Storage key. Assumed tenant-prefixed (see `build_storage_key`).
            content: Raw bytes.
            content_type: Media type sent as the object's Content-Type.

        Raises:
            StorageError: If the upload fails after bucket auto-creation.
        """
        import httpx

        headers = {
            "Authorization": f"Bearer {self._service_key}",
            "apikey": self._service_key,
            "Content-Type": content_type,
            "x-upsert": "true",
        }
        url = self._object_url(key)
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(url, content=content, headers=headers)
                if response.status_code == 404 and "Bucket not found" in response.text:
                    # First write into a fresh project: create the bucket, then
                    # retry once. Bucket creation is idempotent-enough for this
                    # path because a concurrent creator yields a 400 we absorb.
                    await self._ensure_bucket(client)
                    response = await client.post(url, content=content, headers=headers)
                if response.status_code not in (200, 201):
                    logger.warning(
                        "supabase_storage_put_failed",
                        status=response.status_code,
                        key_prefix=key.split("/")[0],
                    )
                    raise StorageError(
                        f"Supabase storage upload failed (HTTP {response.status_code})."
                    )
        except httpx.HTTPError as err:
            logger.warning("supabase_storage_unreachable", reason=type(err).__name__)
            raise StorageError("Supabase storage is unreachable.") from err

    async def get(self, key: str) -> bytes:
        """Retrieve the bytes stored under `key`.

        Args:
            key: Storage key.

        Returns:
            The stored bytes.

        Raises:
            StorageError: If the object is missing or the backend is unreachable.
        """
        import httpx

        headers = {
            "Authorization": f"Bearer {self._service_key}",
            "apikey": self._service_key,
        }
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(self._object_url(key), headers=headers)
            if response.status_code == 404:
                raise StorageError("Object not found in storage.")
            if response.status_code != 200:
                logger.warning(
                    "supabase_storage_get_failed",
                    status=response.status_code,
                    key_prefix=key.split("/")[0],
                )
                raise StorageError(
                    f"Supabase storage download failed (HTTP {response.status_code})."
                )
            return response.content
        except httpx.HTTPError as err:
            logger.warning("supabase_storage_unreachable", reason=type(err).__name__)
            raise StorageError("Supabase storage is unreachable.") from err

    async def _ensure_bucket(self, client: "httpx.AsyncClient") -> None:
        """Create the configured bucket if it does not exist.

        Args:
            client: An open HTTP client to reuse.

        Raises:
            StorageError: If bucket creation fails for a reason other than
                the bucket already existing.
        """
        url = f"{self._base_url}/storage/v1/bucket"
        headers = {
            "Authorization": f"Bearer {self._service_key}",
            "apikey": self._service_key,
            "Content-Type": "application/json",
        }
        payload = {"id": self._bucket, "name": self._bucket, "public": False}
        response = await client.post(url, json=payload, headers=headers)
        # 200/201 = created; 400 "already exists" = a concurrent creator won.
        if response.status_code not in (200, 201) and "already" not in response.text.lower():
            raise StorageError(
                f"Supabase bucket creation failed (HTTP {response.status_code})."
            )


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
        StorageError: If the Supabase backend is selected but not configured,
            or if the memory backend is used in production.
    """
    global _STORE  # noqa: PLW0603
    cfg = settings or get_settings()
    if cfg.storage_backend == "supabase":
        if not (cfg.supabase_url and cfg.supabase_service_key):
            raise StorageError("Supabase storage selected but not configured.")
        return SupabaseObjectStore(
            base_url=cfg.supabase_url,
            service_key=cfg.supabase_service_key,
            bucket=cfg.storage_bucket,
        )
    if cfg.environment == "production":
        raise StorageError(
            "InMemoryObjectStore cannot be used in production. "
            "Set STORAGE_BACKEND to a durable adapter (e.g. 'supabase')."
        )
    if _STORE is None:
        _STORE = InMemoryObjectStore()
        logger.warning(
            "storage_backend_memory",
            msg="Using in-memory object store — data is NOT durable.",
            environment=cfg.environment,
        )
    return _STORE
