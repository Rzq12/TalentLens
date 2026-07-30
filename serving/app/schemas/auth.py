"""Request and response schemas for identity endpoints."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field


class PrincipalResponse(BaseModel):
    """The authenticated caller, as returned by `GET /api/v1/auth/me`."""

    user_id: uuid.UUID = Field(description="Subject of the access token.")
    tenant_id: uuid.UUID = Field(description="Tenant that owns this user's data.")
    roles: list[str] = Field(default_factory=list, description="Roles held in the tenant.")
