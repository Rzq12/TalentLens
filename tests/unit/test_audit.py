from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from app.models import AuditEvent
from app.services.audit import _event_hash, verify_audit_chain


def _audit_metadata() -> dict[str, object]:
    return {
        "ip_address": "203.0.113.10",
        "request_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "occurred_at": datetime(2026, 8, 28, 12, 0, tzinfo=UTC),
    }


def test_verify_audit_chain_accepts_intact_events() -> None:
    tenant_id = uuid.uuid4()
    resource_id = str(uuid.uuid4())
    details = {"decision": "advance"}
    metadata = _audit_metadata()
    first_hash = _event_hash(
        previous_hash=None,
        tenant_id=tenant_id,
        user_id=None,
        action="screening.decision_recorded",
        resource_type="candidate_score",
        resource_id=resource_id,
        details=details,
        **metadata,
    )
    first = AuditEvent(
        id=1,
        tenant_id=tenant_id,
        action="screening.decision_recorded",
        resource_type="candidate_score",
        resource_id=resource_id,
        details=details,
        prev_hash=None,
        chain_hash=first_hash,
        **metadata,
    )
    second_resource_id = str(uuid.uuid4())
    second_metadata = {
        **_audit_metadata(),
        "request_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
    }
    second_hash = _event_hash(
        previous_hash=first_hash,
        tenant_id=tenant_id,
        user_id=None,
        action="screening.verdict_overridden",
        resource_type="requirement_verdict",
        resource_id=second_resource_id,
        details={"verdict": "met"},
        **second_metadata,
    )
    second = AuditEvent(
        id=2,
        tenant_id=tenant_id,
        action="screening.verdict_overridden",
        resource_type="requirement_verdict",
        resource_id=second_resource_id,
        details={"verdict": "met"},
        prev_hash=first_hash,
        chain_hash=second_hash,
        **second_metadata,
    )

    assert verify_audit_chain([first, second]) is None


def test_verify_audit_chain_reports_tampered_event() -> None:
    tenant_id = uuid.uuid4()
    event = AuditEvent(
        id=7,
        tenant_id=tenant_id,
        action="screening.decision_recorded",
        resource_type="candidate_score",
        resource_id=str(uuid.uuid4()),
        details={"decision": "advance"},
        prev_hash=None,
        chain_hash="tampered",
        **_audit_metadata(),
    )

    assert verify_audit_chain([event]) == 7


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("ip_address", "203.0.113.99"),
        ("request_id", "cccccccc-cccc-cccc-cccc-cccccccccccc"),
        ("occurred_at", datetime(2026, 8, 28, 13, 0, tzinfo=UTC)),
    ],
)
def test_verify_audit_chain_reports_tampered_metadata(field: str, value: object) -> None:
    tenant_id = uuid.uuid4()
    resource_id = str(uuid.uuid4())
    metadata = _audit_metadata()
    event = AuditEvent(
        id=7,
        tenant_id=tenant_id,
        action="screening.decision_recorded",
        resource_type="candidate_score",
        resource_id=resource_id,
        details={"decision": "advance"},
        prev_hash=None,
        chain_hash=_event_hash(
            previous_hash=None,
            tenant_id=tenant_id,
            user_id=None,
            action="screening.decision_recorded",
            resource_type="candidate_score",
            resource_id=resource_id,
            details={"decision": "advance"},
            **metadata,
        ),
        **metadata,
    )
    setattr(event, field, value)

    assert verify_audit_chain([event]) == 7
