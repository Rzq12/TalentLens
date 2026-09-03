"""Supabase Auth (JWKS) token verification tests.

The revised stack (ARCHITECTURE-AGENTS.md §1.3) replaces the shared-secret JWT
with Supabase Auth: RS256-signed tokens verified against a public JWKS
endpoint, with tenancy carried in custom claims. These tests pin that path
against a locally generated RSA keypair and a JWKS stub — no network, no
Supabase project required.
"""

from __future__ import annotations

import base64
import json
import threading
import uuid
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.config import Settings
from app.exceptions import AuthenticationError
from app.security import decode_access_token

TENANT_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
USER_ID = uuid.UUID("33333333-3333-3333-3333-333333333333")


def _b64url_uint(value: int) -> str:
    """Encode an integer as base64url without padding (JWK form)."""
    raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _generate_keypair() -> tuple[Any, dict[str, str]]:
    """Generate an RSA keypair and its JWK representation."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pub = key.public_key().public_numbers()
    jwk = {
        "kty": "RSA",
        "use": "sig",
        "alg": "RS256",
        "kid": "test-key-1",
        "n": _b64url_uint(pub.n),
        "e": _b64url_uint(pub.e),
    }
    return key, jwk


class _JwksHandler(BaseHTTPRequestHandler):
    """Serves one static JWKS document."""

    jwks: dict[str, Any] = {}

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        """Silence request logging."""

    def do_GET(self) -> None:  # noqa: N802
        body = json.dumps(_JwksHandler.jwks).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture(scope="module")
def rsa_keypair() -> tuple[Any, dict[str, str]]:
    """One keypair for the whole module — key generation is slow."""
    return _generate_keypair()


@pytest.fixture()
def jwks_url(monkeypatch: pytest.MonkeyPatch, rsa_keypair: tuple[Any, dict[str, str]]) -> str:
    """Serve the JWKS stub and point the settings cache at it."""
    _, jwk = rsa_keypair
    _JwksHandler.jwks = {"keys": [jwk]}
    server = HTTPServer(("127.0.0.1", 0), _JwksHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}/auth/v1/.well-known/jwks.json"

    settings = Settings(
        database_url="postgresql+asyncpg://u:p@localhost/db",
        jwt_secret="x" * 40,
        environment="test",
        supabase_auth_jwks_url=url,
        jwt_audience="authenticated",
    )
    monkeypatch.setattr("app.security.get_settings", lambda: settings)
    yield url
    server.shutdown()
    server.server_close()


def _supabase_token(
    key: Any,
    *,
    tenant: uuid.UUID = TENANT_ID,
    roles: list[str] | None = None,
    expires_in: timedelta = timedelta(minutes=15),
    kid: str = "test-key-1",
    audience: str = "authenticated",
    drop_tenant: bool = False,
) -> str:
    """Mint an RS256 token shaped like a Supabase access token."""
    now = datetime.now(UTC)
    claims: dict[str, Any] = {
        "sub": str(USER_ID),
        "aud": audience,
        "iat": int(now.timestamp()),
        "exp": int((now + expires_in).timestamp()),
        "app_metadata": {},
    }
    if not drop_tenant:
        claims["app_metadata"]["tenant_id"] = str(tenant)
    if roles is not None:
        claims["roles"] = roles
    headers = {"kid": kid} if kid else {}
    return jwt.encode(claims, key, algorithm="RS256", headers=headers)


def test_supabase_token_yields_a_principal(jwks_url: str, rsa_keypair: tuple[Any, dict[str, str]]):
    """A valid RS256 token with tenant custom claims authenticates."""
    key, _ = rsa_keypair
    principal = decode_access_token(_supabase_token(key, roles=["recruiter"]))

    assert principal.user_id == USER_ID
    assert principal.tenant_id == TENANT_ID
    assert "recruiter" in principal.roles


def test_supabase_token_signed_by_wrong_key_is_rejected(
    jwks_url: str, rsa_keypair: tuple[Any, dict[str, str]]
):
    """A token signed by a key absent from the JWKS cannot authenticate."""
    attacker_key, _ = _generate_keypair()
    with pytest.raises(AuthenticationError):
        decode_access_token(_supabase_token(attacker_key))


def test_supabase_token_expired_is_rejected(
    jwks_url: str, rsa_keypair: tuple[Any, dict[str, str]]
):
    key, _ = rsa_keypair
    expired = _supabase_token(key, expires_in=timedelta(minutes=-5))
    with pytest.raises(AuthenticationError):
        decode_access_token(expired)


def test_supabase_token_missing_tenant_claim_is_rejected(
    jwks_url: str, rsa_keypair: tuple[Any, dict[str, str]]
):
    """Tenancy is structural: no tenant claim, no principal."""
    key, _ = rsa_keypair
    with pytest.raises(AuthenticationError):
        decode_access_token(_supabase_token(key, drop_tenant=True))


def test_supabase_token_wrong_audience_is_rejected(
    jwks_url: str, rsa_keypair: tuple[Any, dict[str, str]]
):
    key, _ = rsa_keypair
    with pytest.raises(AuthenticationError):
        decode_access_token(_supabase_token(key, audience="other-service"))


def test_supabase_roles_default_to_empty_when_absent(
    jwks_url: str, rsa_keypair: tuple[Any, dict[str, str]]
):
    """A token without a roles claim authenticates but holds no roles."""
    key, _ = rsa_keypair
    principal = decode_access_token(_supabase_token(key, roles=None))
    assert principal.roles == ()
