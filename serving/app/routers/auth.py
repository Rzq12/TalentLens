"""Identity endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from app.schemas.auth import PrincipalResponse
from app.security import CurrentPrincipal

router = APIRouter(prefix="/auth", tags=["auth"])


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
