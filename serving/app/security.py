"""Caller identity.

This module is the single source of caller identity. No router may accept a
caller-supplied user or tenant id: `current_principal` is the only way to learn
who is making a request, and it reads that exclusively from a verified token.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Annotated, Any, Final

import jwt
from fastapi import Depends, Request

from app.config import Settings, get_settings
from app.exceptions import AuthenticationError, AuthorizationError
from app.logging import get_logger

logger = get_logger(__name__)

BEARER_PREFIX = "bearer"


@dataclass(frozen=True, slots=True)
class Principal:
    """The verified identity behind a request.

    Attributes:
        user_id: Subject of the access token.
        tenant_id: Owning tenant. Every tenant-scoped query filters on this.
        roles: Roles granted to this user within the tenant.
    """

    user_id: uuid.UUID
    tenant_id: uuid.UUID
    roles: tuple[str, ...] = field(default=())

    def require_role(self, *allowed: str) -> None:
        """Assert that this principal holds at least one of `allowed`.

        Args:
            *allowed: Role names, any one of which satisfies the check.

        Raises:
            AuthorizationError: If the principal holds none of them.
        """
        if not set(allowed) & set(self.roles):
            raise AuthorizationError()


def decode_access_token(token: str, settings: Settings | None = None) -> Principal:
    """Verify a JWT and project it into a `Principal`.

    Signature, expiry, issuer, and audience are all verified. The accepted
    algorithm list comes from configuration and never includes "none", so an
    unsigned token cannot authenticate.

    Args:
        token: The raw JWT, without the "Bearer " prefix.
        settings: Optional override; defaults to the process settings.

    Returns:
        The verified principal.

    Raises:
        AuthenticationError: If the token is malformed, expired, signed with an
            unexpected key or algorithm, issued by an unexpected issuer, or is
            missing a claim required to establish tenancy.
    """
    cfg = settings or get_settings()
    try:
        claims: dict[str, Any] = jwt.decode(
            token,
            cfg.jwt_secret,
            algorithms=list(cfg.jwt_algorithms),
            issuer=cfg.jwt_issuer,
            audience=cfg.jwt_audience,
            options={"require": ["exp", "sub"]},
        )
    except jwt.PyJWTError as err:
        logger.warning("auth_token_rejected", reason=type(err).__name__)
        raise AuthenticationError() from err

    try:
        user_id = uuid.UUID(str(claims["sub"]))
        tenant_id = uuid.UUID(str(claims["tenant_id"]))
    except (KeyError, ValueError) as err:
        logger.warning("auth_claims_invalid", reason=str(err))
        raise AuthenticationError() from err

    raw_roles = claims.get("roles") or ()
    roles = tuple(str(r) for r in raw_roles) if isinstance(raw_roles, list | tuple) else ()
    return Principal(user_id=user_id, tenant_id=tenant_id, roles=roles)


def _extract_bearer_token(request: Request) -> str:
    """Pull the bearer token out of the Authorization header.

    Args:
        request: The incoming request.

    Returns:
        The raw token.

    Raises:
        AuthenticationError: If the header is absent or not a Bearer credential.
    """
    header = request.headers.get("Authorization")
    if not header:
        raise AuthenticationError()
    scheme, _, token = header.partition(" ")
    if scheme.lower() != BEARER_PREFIX or not token.strip():
        # Truncate: the scheme is attacker-controlled and unbounded, and an
        # unbounded value written to logs is a flooding and injection vector.
        logger.warning("auth_bad_scheme", scheme=scheme[:32])
        raise AuthenticationError()
    return token.strip()


async def current_principal(request: Request) -> Principal:
    """FastAPI dependency yielding the verified caller.

    Args:
        request: The incoming request.

    Returns:
        The verified principal.

    Raises:
        AuthenticationError: If no valid credential is present.
    """
    return decode_access_token(_extract_bearer_token(request))


CurrentPrincipal = Annotated[Principal, Depends(current_principal)]

# Roles permitted to ingest documents and manage job descriptions. Read-only
# roles (`viewer`, `auditor`) are deliberately excluded from write paths.
WRITE_ROLES: Final = ("owner", "admin", "recruiter")
READ_ROLES: Final = ("owner", "admin", "recruiter", "hiring_manager", "auditor", "viewer")


def require_roles(*allowed: str) -> Callable[[Principal], Awaitable[Principal]]:
    """Build a dependency that admits only principals holding one of `allowed`.

    Authentication alone is not authorization. Without this, any validly signed
    token — regardless of the roles it carries — reaches every endpoint, and
    the `roles` claim is decorative.

    Args:
        *allowed: Role names, any one of which grants access.

    Returns:
        A FastAPI dependency yielding the principal when permitted.
    """

    async def _guard(principal: CurrentPrincipal) -> Principal:
        """Admit the caller only if they hold a permitted role.

        Args:
            principal: The verified caller.

        Returns:
            The same principal, unchanged.

        Raises:
            AuthorizationError: If the caller holds none of the allowed roles.
        """
        if not set(allowed) & set(principal.roles):
            logger.warning(
                "authorization_denied",
                user_id=str(principal.user_id),
                tenant_id=str(principal.tenant_id),
                required=list(allowed),
            )
            raise AuthorizationError()
        return principal

    return _guard


WritePrincipal = Annotated[Principal, Depends(require_roles(*WRITE_ROLES))]
ReadPrincipal = Annotated[Principal, Depends(require_roles(*READ_ROLES))]
