"""Tamper-evident audit event writer and chain verifier."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditEvent


def _advisory_lock_key(tenant_id: uuid.UUID) -> int:
    """Return a process-stable signed 64-bit PostgreSQL advisory lock key."""
    value = int.from_bytes(tenant_id.bytes[:8], byteorder="big", signed=False)
    return value - (1 << 64) if value >= (1 << 63) else value


def _event_hash(
    *,
    previous_hash: str | None,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID | None,
    action: str,
    resource_type: str,
    resource_id: str,
    details: dict[str, object] | None,
    ip_address: str | None,
    request_id: str | None,
    occurred_at: datetime,
) -> str:
    payload = {
        "action": action,
        "details": details or {},
        "ip_address": ip_address or "",
        "occurred_at": occurred_at.isoformat(),
        "previous_hash": previous_hash or "",
        "request_id": request_id or "",
        "resource_id": resource_id,
        "resource_type": resource_type,
        "tenant_id": str(tenant_id),
        "user_id": str(user_id) if user_id else "",
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


async def record_audit_event(
    *,
    session: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID | None,
    action: str,
    resource_type: str,
    resource_id: str,
    details: dict[str, object] | None = None,
    ip_address: str | None = None,
    request_id: str | None = None,
) -> AuditEvent:
    """Append an audit event to a tenant-local hash chain."""
    if session.bind and session.bind.dialect.name == "postgresql":
        await session.execute(select(func.pg_advisory_xact_lock(_advisory_lock_key(tenant_id))))
    previous = await session.scalar(
        select(AuditEvent)
        .where(AuditEvent.tenant_id == tenant_id)
        .order_by(AuditEvent.id.desc())
        .limit(1)
    )
    previous_hash = previous.chain_hash if previous else None
    occurred_at = datetime.now(UTC)
    event = AuditEvent(
        tenant_id=tenant_id,
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        details=details,
        ip_address=ip_address,
        request_id=request_id,
        occurred_at=occurred_at,
        prev_hash=previous_hash,
        chain_hash=_event_hash(
            previous_hash=previous_hash,
            tenant_id=tenant_id,
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details,
            ip_address=ip_address,
            request_id=request_id,
            occurred_at=occurred_at,
        ),
    )
    session.add(event)
    await session.flush()
    return event


def verify_audit_chain(events: Sequence[AuditEvent]) -> int | None:
    """Return the first invalid event id, or ``None`` for a valid chain."""
    previous_hash: str | None = None
    for event in events:
        expected = _event_hash(
            previous_hash=previous_hash,
            tenant_id=event.tenant_id,
            user_id=event.user_id,
            action=event.action,
            resource_type=event.resource_type,
            resource_id=event.resource_id,
            details=event.details,
            ip_address=event.ip_address,
            request_id=event.request_id,
            occurred_at=event.occurred_at,
        )
        if event.prev_hash != previous_hash or event.chain_hash != expected:
            return event.id
        previous_hash = event.chain_hash
    return None
