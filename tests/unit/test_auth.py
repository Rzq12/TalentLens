"""Authentication: JWT verification, principal extraction, and route protection."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest

PROTECTED_ROUTE = "/api/v1/auth/me"


# --------------------------------------------------------------------------- #
# Token verification                                                           #
# --------------------------------------------------------------------------- #


def test_valid_token_yields_a_principal(make_token):
    from app.security import decode_access_token

    principal = decode_access_token(make_token())

    assert principal.user_id == uuid.UUID("33333333-3333-3333-3333-333333333333")
    assert principal.tenant_id == uuid.UUID("11111111-1111-1111-1111-111111111111")
    assert "recruiter" in principal.roles


def test_expired_token_is_rejected(make_token):
    from app.exceptions import AuthenticationError
    from app.security import decode_access_token

    expired = make_token(expires_in=timedelta(minutes=-5))

    with pytest.raises(AuthenticationError):
        decode_access_token(expired)


def test_token_signed_with_wrong_secret_is_rejected(make_token):
    from app.exceptions import AuthenticationError
    from app.security import decode_access_token

    forged = make_token(secret="attacker-key")

    with pytest.raises(AuthenticationError):
        decode_access_token(forged)


def test_token_with_wrong_issuer_is_rejected(make_token):
    from app.exceptions import AuthenticationError
    from app.security import decode_access_token

    with pytest.raises(AuthenticationError):
        decode_access_token(make_token(issuer="https://evil.example/auth"))


def test_token_with_wrong_audience_is_rejected(make_token):
    from app.exceptions import AuthenticationError
    from app.security import decode_access_token

    with pytest.raises(AuthenticationError):
        decode_access_token(make_token(audience="some-other-service"))


def test_token_missing_tenant_claim_is_rejected(make_token):
    """Tenancy is not optional — a token without `tenant_id` cannot be trusted."""
    from app.exceptions import AuthenticationError
    from app.security import decode_access_token

    with pytest.raises(AuthenticationError):
        decode_access_token(make_token(drop_claims=("tenant_id",)))


def test_malformed_token_is_rejected():
    from app.exceptions import AuthenticationError
    from app.security import decode_access_token

    with pytest.raises(AuthenticationError):
        decode_access_token("not-a-jwt")


def test_algorithm_confusion_none_is_rejected():
    """A token with alg=none must never authenticate."""
    import jwt

    from app.exceptions import AuthenticationError
    from app.security import decode_access_token

    unsigned = jwt.encode(
        {"sub": str(uuid.uuid4()), "tenant_id": str(uuid.uuid4())},
        key="",
        algorithm="none",
    )

    with pytest.raises(AuthenticationError):
        decode_access_token(unsigned)


# --------------------------------------------------------------------------- #
# Route protection                                                             #
# --------------------------------------------------------------------------- #


async def test_protected_route_requires_a_token(client):
    response = await client.get(PROTECTED_ROUTE)

    assert response.status_code == 401
    assert response.json()["error"] == "UNAUTHENTICATED"


async def test_protected_route_rejects_a_bad_scheme(client, make_token):
    response = await client.get(
        PROTECTED_ROUTE, headers={"Authorization": f"Basic {make_token()}"}
    )

    assert response.status_code == 401


async def test_protected_route_accepts_a_valid_token(client, auth_headers):
    response = await client.get(PROTECTED_ROUTE, headers=auth_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["user_id"] == "33333333-3333-3333-3333-333333333333"
    assert body["tenant_id"] == "11111111-1111-1111-1111-111111111111"


async def test_caller_cannot_override_tenant_via_query_param(client, make_token):
    """Identity comes from the token alone — never from caller-supplied input."""
    headers = {"Authorization": f"Bearer {make_token()}"}

    response = await client.get(
        PROTECTED_ROUTE,
        headers=headers,
        params={"tenant_id": "22222222-2222-2222-2222-222222222222"},
    )

    assert response.status_code == 200
    assert response.json()["tenant_id"] == "11111111-1111-1111-1111-111111111111"


async def test_health_is_not_protected(client):
    assert (await client.get("/health")).status_code == 200
