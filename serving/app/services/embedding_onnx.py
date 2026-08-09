"""In-process ONNX embedding service — e5-small, CPU, no GPU.

Replaces TEI (GPU) endpoint requirement. Uses optimum.onnxruntime
for efficient CPU inference. Two model flavors:
- ``intfloat/multilingual-e5-small`` — 384-dim, multilingual (ID+EN)
- Falls back to mock when ONNX model unavailable (dev/test).

ARCHITECTURE-AGENTS.md §1.1 choice: CPU-viable small model behind
``EmbeddingProvider`` port. Quality measured via recall@K, not assumed.
"""

from __future__ import annotations

import math
from typing import ClassVar

from app.config import Settings, get_settings
from app.exceptions import EmbeddingServiceUnavailableError
from app.logging import get_logger

logger = get_logger(__name__)

_ONNX_MODEL_ID = "intfloat/multilingual-e5-small"
_ONNX_DIM = 384
_ONNX_VERSION = "onnx-e5-small-v1"

# query: prefix for asymmetric search (passage vs query)
_QUERY_PREFIX = "query: "
_PASSAGE_PREFIX = "passage: "


class OnnxEmbeddingService:
    """Embed texts using e5-small via ONNX Runtime, in-process, CPU.

    Loads on first use. Falls back gracefully when the model file
    is not available (e.g. in CI without network).
    """

    model_name: ClassVar[str] = _ONNX_MODEL_ID
    model_version: ClassVar[str] = _ONNX_VERSION
    dimension: ClassVar[int] = _ONNX_DIM

    def __init__(self, settings: Settings | None = None) -> None:
        self._model = None
        self._tokenizer = None
        self._loaded = False
        self._load_error: str | None = None

    async def _ensure_loaded(self) -> bool:
        if self._loaded:
            return self._model is not None
        self._loaded = True
        try:
            from optimum.onnxruntime import ORTModelForFeatureExtraction
            from transformers import AutoTokenizer

            self._tokenizer = AutoTokenizer.from_pretrained(_ONNX_MODEL_ID)
            self._model = ORTModelForFeatureExtraction.from_pretrained(
                _ONNX_MODEL_ID, export=False, provider="CPUExecutionProvider"
            )
            logger.info("onnx_embedding_loaded", model=_ONNX_MODEL_ID, dim=_ONNX_DIM)
            return True
        except Exception as exc:
            self._load_error = str(exc)[:200]
            logger.warning(
                "onnx_embedding_load_failed",
                model=_ONNX_MODEL_ID,
                error=self._load_error,
            )
            return False

    def _mean_pool(self, hidden_states, attention_mask):
        """Average pooling over token dimension."""
        import numpy as np

        mask = np.expand_dims(attention_mask, axis=-1)
        masked = hidden_states * mask
        summed = masked.sum(axis=1)
        counts = mask.sum(axis=1).clip(min=1e-9)
        return summed / counts

    def _normalize(self, vec):
        norm = math.sqrt(sum(v * v for v in vec))
        return [v / norm for v in vec] if norm > 0 else vec

    async def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if not await self._ensure_loaded():
            raise EmbeddingServiceUnavailableError(
                f"ONNX embedding model unavailable: {self._load_error or 'unknown'}"
            )
        import numpy as np

        inputs = self._tokenizer(
            texts,
            padding=True,
            truncation=True,
            max_length=512,
            return_tensors="np",
        )
        outputs = self._model(**inputs)
        embeddings = self._mean_pool(
            outputs.last_hidden_state, inputs["attention_mask"]
        )
        return [self._normalize(vec.tolist()) for vec in embeddings]

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Embed passage texts with 'passage: ' prefix."""
        prefixed = [f"{_PASSAGE_PREFIX}{t}" for t in texts]
        return await self._embed_batch(prefixed)

    async def embed_query(self, query: str) -> list[float]:
        """Embed a search query with 'query: ' prefix."""
        results = await self._embed_batch([f"{_QUERY_PREFIX}{query}"])
        return results[0]


def get_embedding_service() -> "OnnxEmbeddingService":
    """Return the process-wide ONNX embedding singleton."""
    return OnnxEmbeddingService()
