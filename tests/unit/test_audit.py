from __future__ import annotations

import uuid

from app.models import AuditEvent
from app.services.audit import _event_hash, verify_audit_chain


def test_verify_audit_chain_accepts_intact_events() -> None:
    tenant_id = uuid.uuid4()
    resource_id = str(uuid.uuid4())
    details = {"decision": "advance"}
    first_hash = _event_hash(
        previous_hash=None,
        tenant_id=tenant_id,
        user_id=None,
        action="screening.decision_recorded",
        resource_type="candidate_score",
        resource_id=resource_id,
        details=details,
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
    )
    second_resource_id = str(uuid.uuid4())
    second_hash = _event_hash(
        previous_hash=first_hash,
        tenant_id=tenant_id,
        user_id=None,
        action="screening.verdict_overridden",
        resource_type="requirement_verdict",
        resource_id=second_resource_id,
        details={"verdict": "met"},
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
    )

    assert verify_audit_chain([event]) == 7
