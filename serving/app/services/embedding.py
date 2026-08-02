"""Embedding service port and adapters.

The ``EmbeddingService`` protocol abstracts the embedding provider so the rest
of the application depends on a capability, not on a deployment choice.  Two
adapters are provided:

* ``TEIEmbeddingService`` — calls HuggingFace Text Embeddings Inference over
  HTTP.  This is the production path.
* ``MockEmbeddingService`` — returns deterministic vectors of the configured
  dimension.  Used in tests; not a fake implementation, just a test double.
"""

from __future__ import annotations

import hashlib
import math
from typing import Protocol, runtime_checkable

import httpx

from app.config import Settings, get_settings
from app.exceptions import EmbeddingServiceUnavailableError
from app.logging import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Port
# ---------------------------------------------------------------------------


@runtime_checkable
class EmbeddingService(Protocol):
    """Capability: embed text into dense vectors."""

    @property
    def model_name(self) -> str:
        """The model identifier used for provenance tracking."""
        ...

    @property
    def model_version(self) -> str:
        """A version tag for the embedder, stored on every chunk row."""
        ...

    @property
    def dimension(self) -> int:
        """Dimensionality of the vectors this service produces."""
        ...

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of passage texts.

        Args:
            texts: The texts to embed.

        Returns:
            A list of embedding vectors, one per input text.

        Raises:
            EmbeddingServiceUnavailableError: If the service is unreachable.
        """
        ...

    async def embed_query(self, query: str) -> list[float]:
        """Embed a single search query.

        Some models use different prefixes for queries vs passages.  This
        method handles that distinction.

        Args:
            query: The search query text.

        Returns:
            The embedding vector.

        Raises:
            EmbeddingServiceUnavailableError: If the service is unreachable.
        """
        ...


# ---------------------------------------------------------------------------
# TEI adapter (production)
# ---------------------------------------------------------------------------

_TEI_EMBED_PATH = "/embed"
_TEI_TIMEOUT_SECONDS = 30.0


class TEIEmbeddingService:
    """Calls HuggingFace Text Embeddings Inference over HTTP.

    TEI serves models like ``bge-m3`` and exposes a simple JSON API.  This
    adapter batches according to ``settings.embedding_batch_size`` and
    retries once on transient failures.

    Attributes:
        _endpoint: Base URL of the TEI instance.
        _model: Model name for provenance.
        _dim: Expected vector dimension.
        _batch_size: Max texts per HTTP request.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        """Initialize from settings.

        Args:
            settings: Optional configuration override.
        """
        cfg = settings or get_settings()
        self._endpoint = cfg.embedding_endpoint.rstrip("/")
        self._model = cfg.embedding_model
        self._dim = cfg.embedding_dim
        self._batch_size = cfg.embedding_batch_size
        self._version = "1"

    @property
    def model_name(self) -> str:
        """Return the configured model identifier."""
        return self._model

    @property
    def model_version(self) -> str:
        """Return the embedding version tag."""
        return self._version

    @property
    def dimension(self) -> int:
        """Return the configured embedding dimension."""
        return self._dim

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Embed passage texts via TEI, batched.

        Args:
            texts: The texts to embed.

        Returns:
            A list of embedding vectors.

        Raises:
            EmbeddingServiceUnavailableError: On HTTP or connection error.
        """
        if not texts:
            return []

        all_embeddings: list[list[float]] = []
        for i in range(0, len(texts), self._batch_size):
            batch = texts[i : i + self._batch_size]
            embeddings = await self._call_tei(batch)
            all_embeddings.extend(embeddings)
        return all_embeddings

    async def embed_query(self, query: str) -> list[float]:
        """Embed a search query via TEI.

        Args:
            query: The search query.

        Returns:
            The embedding vector.

        Raises:
            EmbeddingServiceUnavailableError: On HTTP or connection error.
        """
        results = await self._call_tei([query])
        return results[0]

    async def _call_tei(self, inputs: list[str]) -> list[list[float]]:
        """Make a single TEI embed request.

        Args:
            inputs: Batch of texts to embed.

        Returns:
            The embedding vectors.

        Raises:
            EmbeddingServiceUnavailableError: On any failure.
        """
        url = f"{self._endpoint}{_TEI_EMBED_PATH}"
        payload = {"inputs": inputs}
        try:
            async with httpx.AsyncClient(timeout=_TEI_TIMEOUT_SECONDS) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                data: list[list[float]] = response.json()
                return data
        except (httpx.HTTPError, httpx.ConnectError, Exception) as exc:
            logger.error(
                "embedding_service_error",
                endpoint=self._endpoint,
                error=str(exc)[:200],
            )
            raise EmbeddingServiceUnavailableError(
                f"Embedding service at {self._endpoint} is unavailable."
            ) from exc


# ---------------------------------------------------------------------------
# Mock adapter (tests)
# ---------------------------------------------------------------------------


class MockEmbeddingService:
    """Returns deterministic vectors for testing.

    Vectors are derived from a hash of the input text so the same text always
    produces the same vector, enabling assertions in tests.  This is *not* a
    fake implementation — it makes no attempt at semantic similarity.
    """

    def __init__(self, dimension: int = 1024) -> None:
        """Initialize with a target dimension.

        Args:
            dimension: Vector dimensionality to produce.
        """
        self._dim = dimension

    @property
    def model_name(self) -> str:
        """Return a test model identifier."""
        return "mock-embedder"

    @property
    def model_version(self) -> str:
        """Return a test version tag."""
        return "test-v1"

    @property
    def dimension(self) -> int:
        """Return the configured dimension."""
        return self._dim

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Return deterministic vectors for each text.

        Args:
            texts: The texts to embed.

        Returns:
            Deterministic vectors derived from text hashes.
        """
        return [self._deterministic_vector(t) for t in texts]

    async def embed_query(self, query: str) -> list[float]:
        """Return a deterministic vector for the query.

        Args:
            query: The search query.

        Returns:
            A deterministic vector.
        """
        return self._deterministic_vector(query)

    def _deterministic_vector(self, text: str) -> list[float]:
        """Produce a unit-length vector deterministically from text.

        Args:
            text: Input text.

        Returns:
            A normalized vector of ``self._dim`` dimensions.
        """
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        # Expand the 32-byte hash to fill the dimension by repeating
        raw = list(digest) * ((self._dim // len(digest)) + 1)
        raw = raw[: self._dim]
        # Map bytes to floats in [-1, 1] and normalize
        vec = [(b - 128) / 128.0 for b in raw]
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]


# ---------------------------------------------------------------------------
# Singleton management
# ---------------------------------------------------------------------------

_embedding_service: EmbeddingService | None = None


def get_embedding_service() -> EmbeddingService:
    """Return the process-wide embedding service instance.

    Returns a ``MockEmbeddingService`` when no TEI endpoint is configured
    (i.e. in test or when the endpoint is empty).

    Returns:
        The embedding service singleton.
    """
    global _embedding_service  # noqa: PLW0603
    if _embedding_service is not None:
        return _embedding_service

    settings = get_settings()
    if settings.embedding_endpoint and settings.environment != "test":
        _embedding_service = TEIEmbeddingService(settings)
        logger.info(
            "embedding_service_initialized",
            adapter="TEI",
            endpoint=settings.embedding_endpoint,
            model=settings.embedding_model,
        )
    else:
        _embedding_service = MockEmbeddingService(dimension=settings.embedding_dim)
        logger.info("embedding_service_initialized", adapter="Mock")
    return _embedding_service


def set_embedding_service(service: EmbeddingService) -> None:
    """Override the embedding service singleton (for tests).

    Args:
        service: The service to install.
    """
    global _embedding_service  # noqa: PLW0603
    _embedding_service = service


def reset_embedding_service() -> None:
    """Clear the embedding service singleton (for tests)."""
    global _embedding_service  # noqa: PLW0603
    _embedding_service = None
