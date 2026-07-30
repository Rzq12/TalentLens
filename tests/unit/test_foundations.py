"""Phase 0 foundations: settings, app factory, health, error envelope, request id."""

from __future__ import annotations

import uuid

import pytest

_DOCX_MIMES = ("application/vnd.openxmlformats-officedocument.wordprocessingml.document",)


# --------------------------------------------------------------------------- #
# Settings                                                                     #
# --------------------------------------------------------------------------- #


def test_settings_loads_required_values_from_environment():
    from app.config import get_settings

    settings = get_settings()

    assert settings.database_url.startswith("postgresql+asyncpg://")
    assert settings.jwt_secret
    assert settings.environment == "test"


def test_settings_applies_documented_defaults():
    from app.config import get_settings

    settings = get_settings()

    assert settings.api_v1_prefix == "/api/v1"
    assert settings.max_upload_bytes == 10 * 1024 * 1024
    assert settings.allowed_upload_mime_types == ("application/pdf", *_DOCX_MIMES)


def test_settings_missing_required_field_fails_fast(monkeypatch):
    """Fail fast: a missing DATABASE_URL must raise, not silently default."""
    from pydantic import ValidationError

    from app.config import Settings

    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_get_settings_is_cached():
    from app.config import get_settings

    assert get_settings() is get_settings()


# --------------------------------------------------------------------------- #
# App factory and health                                                       #
# --------------------------------------------------------------------------- #


async def test_health_returns_200_without_authentication(client):
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_health_response_includes_version(client):
    response = await client.get("/health")

    assert "version" in response.json()


async def test_openapi_schema_is_generated(client):
    response = await client.get("/openapi.json")

    assert response.status_code == 200
    assert response.json()["info"]["title"]


# --------------------------------------------------------------------------- #
# Request id + error envelope                                                  #
# --------------------------------------------------------------------------- #


async def test_every_response_carries_a_request_id_header(client):
    response = await client.get("/health")

    request_id = response.headers.get("x-request-id")
    assert request_id is not None
    uuid.UUID(request_id)


async def test_supplied_request_id_is_echoed_back(client):
    supplied = str(uuid.uuid4())

    response = await client.get("/health", headers={"X-Request-ID": supplied})

    assert response.headers["x-request-id"] == supplied


async def test_unknown_route_returns_the_standard_error_envelope(client):
    response = await client.get("/api/v1/does-not-exist")

    assert response.status_code == 404
    body = response.json()
    assert set(body) >= {"request_id", "error", "message", "status_code"}
    assert body["status_code"] == 404
    uuid.UUID(body["request_id"])


def test_exception_hierarchy_exposes_stable_error_codes():
    from app import exceptions as exc

    expected = {
        exc.DocumentParseError: ("DOCUMENT_PARSE_FAILED", 422),
        exc.UnsupportedMediaTypeError: ("UNSUPPORTED_MEDIA_TYPE", 422),
        exc.PayloadTooLargeError: ("PAYLOAD_TOO_LARGE", 413),
        exc.AuthenticationError: ("UNAUTHENTICATED", 401),
        exc.AuthorizationError: ("FORBIDDEN", 403),
        exc.ResourceNotFoundError: ("NOT_FOUND", 404),
    }
    for klass, (code, status) in expected.items():
        assert issubclass(klass, exc.TalentLensError)
        assert klass.error_code == code
        assert klass.status_code == status
