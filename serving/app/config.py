"""Application configuration.

Every runtime value the application needs is declared here and sourced from the
environment. No module outside this one may read `os.environ` directly, and no
default is provided for a secret — a missing secret must fail fast at startup
rather than silently fall back to something insecure.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal, Self

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

MIN_JWT_SECRET_LENGTH = 32


class Settings(BaseSettings):
    """Runtime configuration, populated from the environment or a `.env` file.

    Attributes:
        database_url: Async SQLAlchemy DSN for PostgreSQL. Required.
        jwt_secret: Symmetric signing key used to verify access tokens. Required.
        jwt_issuer: Expected `iss` claim. Tokens from any other issuer are rejected.
        jwt_audience: Expected `aud` claim.
        jwt_algorithms: Accepted signing algorithms. Deliberately excludes "none".
        storage_backend: Which `ObjectStore` adapter to bind at startup.
        max_upload_bytes: Hard ceiling enforced before a document is read.
        allowed_upload_mime_types: MIME allowlist for resume/JD uploads.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    environment: Literal["development", "test", "production"] = "development"
    app_name: str = "TalentLens"
    version: str = "0.1.0"
    api_v1_prefix: str = "/api/v1"

    database_url: str
    db_pool_size: int = 10
    db_max_overflow: int = 20

    jwt_secret: str
    jwt_issuer: str = "https://localhost/auth/v1"
    jwt_audience: str = "authenticated"
    jwt_algorithms: tuple[str, ...] = ("HS256",)

    # Supabase Auth JWKS URL. When set, the app validates bearer tokens
    # against Supabase's public JWKS endpoint rather than a shared secret.
    # This is the revised-stack auth strategy (ARCHITECTURE-AGENTS.md §1.3).
    supabase_auth_jwks_url: str = ""

    storage_backend: Literal["memory", "supabase"] = "memory"
    supabase_url: str = ""
    supabase_service_key: str = ""
    storage_bucket: str = "resumes"

    max_upload_bytes: int = 10 * 1024 * 1024
    allowed_upload_mime_types: tuple[str, ...] = ("application/pdf", DOCX_MIME)

    # --- Embedding (Phase 2) -------------------------------------------------
    # In-process ONNX e5-small (revised stack, ARCHITECTURE-AGENTS.md §1.1).
    # Set EMBEDDING_BACKEND=tei to use external HuggingFace TEI endpoint instead.
    embedding_backend: Literal["onnx", "tei"] = "onnx"
    embedding_endpoint: str = "http://localhost:8080"
    embedding_model: str = "intfloat/multilingual-e5-small"
    embedding_dim: int = 384
    embedding_batch_size: int = 32

    # Ceiling on child chunks embedded per document. Embedding runs inline in the
    # upload request while a pooled connection is held, so an unbounded document
    # would occupy that connection for hundreds of sequential backend calls and
    # starve `db_pool_size`. At the default child size this covers a CV far longer
    # than any real one; excess children are dropped with a warning rather than
    # rejecting the upload outright.
    indexing_max_child_chunks: int = 600

    # --- Search (Phase 2) ----------------------------------------------------
    search_dense_weight: float = 0.6
    search_lexical_weight: float = 0.4
    search_top_k_recall: int = 20
    search_rerank_top_k: int = 10

    # --- Reranker (Phase 2, optional) ------------------------------------------
    # Set to "onnx" for in-process CPU reranker or "tei" for external endpoint.
    # "noop" passes through scores unchanged (safe default for dev/test).
    reranker_backend: Literal["noop", "onnx", "tei"] = "noop"
    reranker_endpoint: str = ""
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"

    # --- LLM providers (Phase 4) --------------------------------------------
    # Keys default to empty so a developer without provider credentials can
    # still boot the app and run the deterministic suite. A missing key is
    # discovered when a chain is assembled, not at import time.
    google_api_key: str = ""
    groq_api_key: str = ""

    # Model ids live here and nowhere else. Free-tier models are deprecated
    # without notice, so recovering from one must be a config change rather
    # than a code change.
    gemini_model: str = "gemini-3.5-flash"
    groq_model: str = "llama-3.3-70b-versatile"

    # Pinned at zero: a screening score must be reproducible, and sampling
    # would make the same candidate score differently on a re-run.
    llm_temperature: float = 0.0
    llm_timeout_seconds: float = 60.0
    llm_max_output_tokens: int = 2048

    cors_allow_origins: tuple[str, ...] = ("http://localhost:5173",)

    log_level: str = "INFO"

    @model_validator(mode="after")
    def _enforce_production_secrets(self) -> Self:
        """Reject weak JWT secrets in production.

        A short secret drastically reduces the key space an attacker must
        search. In production this is never acceptable; in development and test
        convenience outweighs the risk.

        Returns:
            The validated settings instance.

        Raises:
            ValueError: If the JWT secret is too short for production.
        """
        if self.environment == "production" and len(self.jwt_secret) < MIN_JWT_SECRET_LENGTH:
            msg = (
                f"JWT_SECRET must be at least {MIN_JWT_SECRET_LENGTH} characters "
                f"in production (got {len(self.jwt_secret)})."
            )
            raise ValueError(msg)
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings singleton.

    Cached so configuration is parsed once and every caller observes the same
    object. Tests that need a different configuration construct `Settings`
    directly rather than mutating this cache.

    Returns:
        The validated `Settings` instance.
    """
    return Settings()
