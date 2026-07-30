"""Application configuration.

Every runtime value the application needs is declared here and sourced from the
environment. No module outside this one may read `os.environ` directly, and no
default is provided for a secret — a missing secret must fail fast at startup
rather than silently fall back to something insecure.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


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

    storage_backend: Literal["memory", "supabase"] = "memory"
    supabase_url: str = ""
    supabase_service_key: str = ""
    storage_bucket: str = "resumes"

    max_upload_bytes: int = 10 * 1024 * 1024
    allowed_upload_mime_types: tuple[str, ...] = ("application/pdf", DOCX_MIME)

    cors_allow_origins: tuple[str, ...] = ("http://localhost:5173",)

    log_level: str = "INFO"


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
