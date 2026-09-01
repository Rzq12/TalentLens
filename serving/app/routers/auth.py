"""Identity endpoints."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt
from fastapi import APIRouter, HTTPException, status

from app.config import get_settings
from app.schemas.auth import PrincipalResponse
from app.security import CurrentPrincipal

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/dev-token", include_in_schema=False)
async def issue_dev_token() -> dict[str, str]:
    """Issue a local-only token for the development Compose environment."""
    settings = get_settings()
    if not settings.dev_auth_enabled or settings.environment != "development":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    now = datetime.now(UTC)
    return {
        "access_token": jwt.encode(
            {
                "sub": "00000000-0000-0000-0000-000000000001",
                "tenant_id": "00000000-0000-0000-0000-000000000010",
                "roles": ["owner", "admin", "recruiter"],
                "iss": settings.jwt_issuer,
                "aud": settings.jwt_audience,
                "iat": now,
                "exp": now + timedelta(hours=8),
            },
            settings.jwt_secret,
            algorithm=settings.jwt_algorithms[0],
        ),
        "token_type": "bearer",
    }


@router.get(
    "/me",
    response_model=PrincipalResponse,
    summary="Describe the authenticated caller",
    description=(
        "Returns the identity derived from the bearer token. Identity is never "
        "read from query parameters or the request body."
    ),
)
async def read_me(principal: CurrentPrincipal) -> PrincipalResponse:
    """Return the verified caller's identity.

    Args:
        principal: Injected, token-derived identity.

    Returns:
        The caller's user id, tenant id, and roles.
    """
    return PrincipalResponse(
        user_id=principal.user_id,
        tenant_id=principal.tenant_id,
        roles=list(principal.roles),
    )
