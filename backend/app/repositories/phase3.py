"""Repositories for scoped workflow history, audit, and idempotency."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.persistence.models import AuditEvent, CaseEvent, IdempotencyRecord


def canonical_digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


class WorkflowRepository:
    def __init__(self, session: Session):
        self.session = session

    def append_case_event(self, *, case_id: str, event_type: str, actor_id: str | None, payload: dict) -> CaseEvent:
        sequence = self.session.execute(
            select(func.coalesce(func.max(CaseEvent.sequence), 0)).where(CaseEvent.case_id == case_id)
        ).scalar_one() + 1
        event = CaseEvent(case_id=case_id, sequence=sequence, event_type=event_type, actor_id=actor_id, payload=payload)
        self.session.add(event)
        self.session.flush()
        return event

    def audit(self, *, actor_id: str | None, case_id: str | None, action: str, resource_type: str,
              resource_id: str | None, outcome: str = "success", details: dict | None = None,
              request_id: str | None = None, correlation_id: str | None = None,
              ip_address: str | None = None) -> AuditEvent:
        previous = self.session.execute(select(AuditEvent).order_by(AuditEvent.sequence.desc()).limit(1)).scalar_one_or_none()
        sequence = 1 if previous is None else previous.sequence + 1
        body = {"sequence": sequence, "actor_id": actor_id, "case_id": case_id, "action": action,
                "resource_type": resource_type, "resource_id": resource_id, "outcome": outcome,
                "details": details or {}, "previous_digest": previous.event_digest if previous else None}
        record = AuditEvent(sequence=sequence, actor_id=actor_id, case_id=case_id, action=action,
                            resource_type=resource_type, resource_id=resource_id, outcome=outcome,
                            details=details or {}, request_id=request_id, correlation_id=correlation_id,
                            ip_address=ip_address, previous_digest=body["previous_digest"], event_digest=canonical_digest(body))
        self.session.add(record)
        self.session.flush()
        return record

    def idempotency_replay(self, *, actor_id: str, operation: str, key: str, request_digest: str) -> dict | None:
        record = self.session.execute(select(IdempotencyRecord).where(
            IdempotencyRecord.actor_id == actor_id,
            IdempotencyRecord.operation == operation,
            IdempotencyRecord.idempotency_key == key,
        )).scalar_one_or_none()
        if record is None:
            return None
        if record.request_digest != request_digest:
            from app.core.errors import ApplicationError
            raise ApplicationError(code="IDEMPOTENCY_CONFLICT", message="Idempotency key was used with different input", status_code=409)
        return dict(record.response_payload)

    def remember(self, *, actor_id: str, operation: str, key: str, request_digest: str, response: dict,
                 status: int = 201) -> None:
        self.session.add(IdempotencyRecord(actor_id=actor_id, operation=operation, idempotency_key=key,
                                           request_digest=request_digest, response_status=status,
                                           response_payload=response))
        self.session.flush()
