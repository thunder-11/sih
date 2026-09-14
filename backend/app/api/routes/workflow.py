"""Phase 3 wallet validation, report correction, and case workflow APIs."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, Query, Request, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.providers.registry import provider_capabilities
from app.core.errors import ApplicationError
from app.persistence.models import AnalysisRun, BackgroundJob, CaseAccessGrant, CaseAttachment, CaseEvent, CaseNote, ReportEvent
from app.repositories.phase2 import DurableJobRepository
from app.repositories.phase3 import WorkflowRepository, canonical_digest
from app.schemas.phase3 import AttachmentMetadataCreate, CaseAccessGrantCreate, CaseNoteCreate, CaseUpdate, IngestionRequest, ReportEventCorrection, WalletValidationRequest
from app.security.authorization import active_agency_id, get_accessible_case
from app.security.data_protection import protect
from app.utils.addresses import validate_wallet
from app.utils.pagination import PageWindow, page_payload
from app.utils.timestamps import parse_report_timestamp
from auth.utils import get_current_user, require_role
from database import get_db
from models import Case, CaseWallet, User


router = APIRouter(prefix="/api/v1", tags=["Identity and Case Workflow"])

TRANSITIONS = {
    "new": {"investigating", "closed"},
    "investigating": {"escalated_to_vasp", "frozen", "closed"},
    "escalated_to_vasp": {"frozen", "closed", "investigating"},
    "frozen": {"closed", "investigating"},
    "closed": {"investigating"},
}
LEGACY_TO_CANONICAL = {"NEW": "new", "UNDER_INVESTIGATION": "investigating", "ATTRIBUTED": "investigating"}
CANONICAL_TO_LEGACY = {"new": "NEW", "investigating": "UNDER_INVESTIGATION", "escalated_to_vasp": "ATTRIBUTED",
                       "frozen": "FROZEN", "closed": "CLOSED"}


@router.get("/chains")
def chains(request: Request, user: User = Depends(get_current_user)):
    settings = request.app.state.settings
    return {"items": [{**item, "address_validation": "local", "retrieval": "provider_adapter"}
                      for item in provider_capabilities(settings)]}


@router.post("/cases/{case_id}/ingestions", status_code=status.HTTP_202_ACCEPTED)
def queue_case_ingestion(case_id: str, payload: IngestionRequest, request: Request,
                         idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
                         db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Queue a real-provider refresh; no HTTP request fabricates transaction data."""
    case = get_accessible_case(db, user, case_id, write=True)
    chain = payload.chain.upper()
    if chain not in request.app.state.settings.enabled_chains:
        raise ApplicationError(code="UNSUPPORTED_CHAIN", message="Chain is not enabled", status_code=422,
                               field_errors={"chain": "unsupported or disabled chain"})
    case_wallet = db.query(CaseWallet).filter(CaseWallet.case_id == case.id, CaseWallet.wallet_chain == chain,
                                              CaseWallet.wallet_address == payload.address).first()
    if case_wallet is None:
        raise ApplicationError(code="WALLET_NOT_IN_CASE", message="Wallet must be a validated case wallet", status_code=422)
    key = idempotency_key or f"ingest:{case.id}:{chain}:{payload.address}:{payload.cursor or 'first'}"
    job, created = DurableJobRepository(db).enqueue_once(
        operation="blockchain.ingest", idempotency_key=key, case_id=case.id,
        payload={"case_id": case.id, "chain": chain, "address": payload.address,
                 "cursor": payload.cursor, "page_size": payload.page_size},
    )
    job.actor_id = user.id
    WorkflowRepository(db).audit(actor_id=user.id, case_id=case.id, action="blockchain.ingest.queue",
                                 resource_type="background_job", resource_id=job.id,
                                 details={"chain": chain, "address": payload.address, "cursor": payload.cursor})
    db.commit()
    return {"job_id": job.id, "case_id": case.id, "status": job.state,
            "status_url": f"/api/v1/cases/{case.id}/status", "idempotent_replay": not created,
            "provider_state": request.app.state.settings.provider_status().get(chain)}


@router.post("/wallets/validate")
def validate_wallet_route(req: WalletValidationRequest, request: Request, user: User = Depends(get_current_user)):
    result = validate_wallet(req.address, req.chain, fixture_mode=request.app.state.settings.fixture_data_enabled)
    return {"valid": result.valid, "canonical_address": result.canonical_address,
            "network": req.chain if req.chain and result.valid else (result.candidates[0] if len(result.candidates) == 1 else None),
            "candidates": list(result.candidates), "ambiguous": result.valid and len(result.candidates) > 1 and req.chain is None,
            "checksum_state": result.checksum_state, "reason": result.reason,
            "data_mode": "fixture" if result.synthetic_fixture else "live_compatible"}


def _report_dict(event: ReportEvent) -> dict:
    return {"id": event.id, "complaint_id": event.complaint_id, "case_id": event.case_id,
            "revision": event.revision, "reported_at_utc": event.report_timestamp.isoformat(),
            "original_timestamp": event.original_timestamp, "timezone": event.reported_timezone,
            "iana_timezone": event.iana_timezone, "source": event.source_system, "channel": event.channel,
            "receipt_reference": event.receipt_reference, "precision": event.timestamp_precision,
            "verification_status": event.verification_state, "correction_reason": event.correction_reason,
            "supersedes_id": event.supersedes_id}


@router.post("/report-events/{event_id}/revisions", status_code=status.HTTP_201_CREATED)
def correct_report_event(event_id: str, req: ReportEventCorrection, db: Session = Depends(get_db),
                         user: User = Depends(get_current_user)):
    prior = db.query(ReportEvent).filter(ReportEvent.id == event_id).first()
    if prior is None:
        raise ApplicationError(code="REPORT_EVENT_NOT_FOUND", message="Report event not found", status_code=404)
    case = get_accessible_case(db, user, prior.case_id, write=True)
    successor = db.query(ReportEvent).filter(ReportEvent.supersedes_id == prior.id).first()
    if prior.revision != req.expected_revision or successor is not None:
        raise ApplicationError(code="REVISION_CONFLICT", message="Report event revision changed", status_code=409,
                               details={"current_revision": successor.revision if successor else prior.revision})
    next_revision = db.query(func.coalesce(func.max(ReportEvent.revision), 0)).filter(
        ReportEvent.case_id == case.id).scalar() + 1
    parsed = parse_report_timestamp(req.reported_at, iana_timezone=req.report_timezone,
                                    future_skew_seconds=get_settings().report_time_max_future_skew_seconds)
    corrected = ReportEvent(case_id=case.id, complaint_id=prior.complaint_id, revision=next_revision,
                            report_timestamp=parsed.utc, reported_timezone=parsed.offset,
                            original_timestamp=parsed.original, iana_timezone=parsed.iana_timezone,
                            timestamp_precision=parsed.precision, verification_state=req.verification_status,
                            correction_reason=req.reason, supersedes_id=prior.id, source_system=req.source,
                            channel=req.channel, receipt_reference=req.receipt_reference, received_at=datetime.now(timezone.utc),
                            created_by=user.id, payload_digest=canonical_digest(req.model_dump()))
    db.add(corrected)
    db.flush()
    if case.primary_report_event_id == prior.id:
        case.primary_report_event_id = corrected.id
    case.revision += 1
    workflow = WorkflowRepository(db)
    workflow.append_case_event(case_id=case.id, event_type="report_timestamp_corrected", actor_id=user.id,
                               payload={"prior_id": prior.id, "new_id": corrected.id, "reason": req.reason})
    workflow.audit(actor_id=user.id, case_id=case.id, action="report_event.correct", resource_type="report_event",
                   resource_id=corrected.id, details={"supersedes": prior.id, "reason": req.reason})
    db.commit()
    return _report_dict(corrected)


@router.patch("/cases/{case_id}")
def update_case(case_id: str, req: CaseUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    case = get_accessible_case(db, user, case_id, write=True)
    if case.revision != req.revision:
        raise ApplicationError(code="REVISION_CONFLICT", message="Case revision changed", status_code=409,
                               details={"current_revision": case.revision})
    changes = {}
    current = LEGACY_TO_CANONICAL.get(case.status, case.status)
    if req.status and req.status != current:
        if req.status not in TRANSITIONS.get(current, set()):
            raise ApplicationError(code="INVALID_CASE_TRANSITION", message=f"Cannot transition {current} to {req.status}", status_code=409)
        if req.status in {"escalated_to_vasp", "frozen"} and not req.external_action_reference:
            raise ApplicationError(code="EXTERNAL_ACTION_REQUIRED", message="External action reference is required", status_code=422)
        case.status = req.status
        changes["status"] = {"from": current, "to": req.status, "external_action_reference": req.external_action_reference}
    if req.assigned_officer_id and req.assigned_officer_id != case.assigned_officer_id:
        if user.role not in {"analyst", "admin"}:
            raise ApplicationError(code="FORBIDDEN", message="Assignment requires analyst or admin role", status_code=403)
        assignee = db.query(User).filter(User.id == req.assigned_officer_id,
                                        User.primary_agency_id == active_agency_id(db, user), User.status == "active").first()
        if assignee is None:
            raise ApplicationError(code="INVALID_ASSIGNEE", message="Assignee is outside the active agency", status_code=422)
        changes["assigned_officer_id"] = {"from": case.assigned_officer_id, "to": assignee.id}
        case.assigned_officer_id = assignee.id
    if not changes:
        raise ApplicationError(code="NO_CASE_CHANGES", message="No case changes were requested", status_code=422)
    case.revision += 1
    workflow = WorkflowRepository(db)
    workflow.append_case_event(case_id=case.id, event_type="case_updated", actor_id=user.id,
                               payload={"changes": changes, "reason": req.reason, "revision": case.revision})
    workflow.audit(actor_id=user.id, case_id=case.id, action="case.update", resource_type="case",
                   resource_id=case.id, details={"changes": changes, "reason": req.reason})
    db.commit()
    return {"id": case.id, "status": case.status, "compatibility_status": CANONICAL_TO_LEGACY.get(case.status, case.status),
            "assigned_officer_id": case.assigned_officer_id, "revision": case.revision}


@router.get("/cases/{case_id}/status")
def case_status(case_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    case = get_accessible_case(db, user, case_id)
    runs = db.query(AnalysisRun).filter(AnalysisRun.case_id == case.id).order_by(AnalysisRun.revision.desc()).all()
    report = db.query(ReportEvent).filter(ReportEvent.id == case.primary_report_event_id).first()
    jobs = db.query(BackgroundJob).filter(BackgroundJob.case_id == case.id).order_by(BackgroundJob.updated_at.desc()).all()
    return {"case_id": case.id, "case_lifecycle": LEGACY_TO_CANONICAL.get(case.status, case.status),
            "compatibility_status": CANONICAL_TO_LEGACY.get(case.status, case.status), "revision": case.revision,
            "selected_report_event": _report_dict(report) if report else None,
            "analysis_runs": [{"id": run.id, "state": run.state, "stage": run.stage,
                               "revision": run.revision, "coverage": run.coverage, "error_code": run.error_code} for run in runs],
            "jobs": [{"id": job.id, "operation": job.operation, "state": job.state, "attempt": job.attempt,
                      "max_attempts": job.max_attempts, "last_error_code": job.last_error_code,
                      "next_attempt_at": job.next_attempt_at.isoformat()} for job in jobs],
            "poll_after_seconds": 3, "event_stream": f"/api/v1/cases/{case.id}/events"}


@router.get("/traces/{trace_id}")
def trace_status(trace_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    run = db.query(AnalysisRun).filter(AnalysisRun.id == trace_id).first()
    if run is None:
        raise ApplicationError(code="TRACE_NOT_FOUND", message="Trace not found", status_code=404)
    get_accessible_case(db, user, run.case_id)
    job = db.query(BackgroundJob).filter(BackgroundJob.case_id == run.case_id,
                                         BackgroundJob.operation == "trace.run").order_by(BackgroundJob.created_at.desc()).first()
    return {"id": run.id, "case_id": run.case_id, "state": job.state if job else run.state,
            "stage": run.stage, "requested_at": run.requested_at.isoformat(),
            "job_id": job.id if job else None, "warnings": [],
            "error": job.last_error_code if job else run.error_code}


@router.get("/cases/{case_id}/history")
def case_history(case_id: str, page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100),
                 db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    case = get_accessible_case(db, user, case_id)
    query = db.query(CaseEvent).filter(CaseEvent.case_id == case.id)
    window = PageWindow(page, page_size)
    total = query.count()
    events = query.order_by(CaseEvent.sequence.desc()).offset(window.offset).limit(window.page_size).all()
    items = [{"id": event.id, "sequence": event.sequence, "type": event.event_type,
              "actor_id": event.actor_id, "occurred_at": event.occurred_at.isoformat(),
              "payload": event.payload} for event in events]
    return page_payload(items, total, window, history=items)


@router.get("/cases/{case_id}/notes")
def list_notes(case_id: str, page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100),
               db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    case = get_accessible_case(db, user, case_id)
    query = db.query(CaseNote).filter(CaseNote.case_id == case.id)
    window = PageWindow(page, page_size)
    total = query.count()
    notes = query.order_by(CaseNote.revision.desc()).offset(window.offset).limit(window.page_size).all()
    items = [{"id": note.id, "revision": note.revision, "author_id": note.author_id,
              "content": "[protected]", "created_at": note.created_at.isoformat()} for note in notes]
    return page_payload(items, total, window, notes=items)


@router.post("/cases/{case_id}/notes", status_code=201)
def add_note(case_id: str, req: CaseNoteCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    case = get_accessible_case(db, user, case_id, write=True)
    revision = db.query(func.coalesce(func.max(CaseNote.revision), 0)).filter(CaseNote.case_id == case.id).scalar() + 1
    note = CaseNote(case_id=case.id, revision=revision, author_id=user.id, body_ciphertext=protect(req.content))
    db.add(note)
    workflow = WorkflowRepository(db)
    workflow.append_case_event(case_id=case.id, event_type="note_added", actor_id=user.id,
                               payload={"note_id": note.id, "evidence_ids": req.evidence_ids})
    workflow.audit(actor_id=user.id, case_id=case.id, action="case.note.create", resource_type="case_note",
                   resource_id=note.id, details={"evidence_ids": req.evidence_ids})
    db.commit()
    return {"id": note.id, "case_id": case.id, "revision": note.revision, "created_at": note.created_at.isoformat()}


@router.post("/cases/{case_id}/attachments", status_code=201)
def add_attachment(case_id: str, req: AttachmentMetadataCreate, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    case = get_accessible_case(db, user, case_id, write=True)
    attachment = CaseAttachment(case_id=case.id, filename=req.filename, mime_type=req.mime_type,
                                size_bytes=req.size_bytes, sha256=req.sha256.lower(),
                                storage_reference=req.storage_reference, uploaded_by=user.id)
    db.add(attachment)
    workflow = WorkflowRepository(db)
    workflow.append_case_event(case_id=case.id, event_type="attachment_registered", actor_id=user.id,
                               payload={"attachment_id": attachment.id, "sha256": attachment.sha256})
    workflow.audit(actor_id=user.id, case_id=case.id, action="case.attachment.create", resource_type="case_attachment",
                   resource_id=attachment.id, details={"sha256": attachment.sha256})
    db.commit()
    return {"id": attachment.id, "case_id": case.id, "filename": attachment.filename,
            "sha256": attachment.sha256, "created_at": attachment.created_at.isoformat()}


@router.get("/cases/{case_id}/attachments")
def list_attachments(case_id: str, page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100),
                     db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    case = get_accessible_case(db, user, case_id)
    query = db.query(CaseAttachment).filter(CaseAttachment.case_id == case.id)
    window = PageWindow(page, page_size)
    total = query.count()
    records = query.order_by(CaseAttachment.created_at.desc()).offset(window.offset).limit(window.page_size).all()
    items = [{"id": item.id, "filename": item.filename, "mime_type": item.mime_type,
              "size_bytes": item.size_bytes, "sha256": item.sha256,
              "storage_reference": item.storage_reference, "uploaded_by": item.uploaded_by,
              "created_at": item.created_at.isoformat()} for item in records]
    return page_payload(items, total, window, attachments=items)


@router.post("/cases/{case_id}/access-grants", status_code=201)
def grant_case_access(case_id: str, req: CaseAccessGrantCreate, db: Session = Depends(get_db),
                      user: User = Depends(require_role("analyst", "admin"))):
    case = get_accessible_case(db, user, case_id, write=True)
    recipient = db.query(User).filter(User.id == req.user_id,
                                      User.primary_agency_id == active_agency_id(db, user),
                                      User.status == "active").first()
    if recipient is None:
        raise ApplicationError(code="INVALID_CASE_RECIPIENT", message="Recipient is outside the active agency", status_code=422)
    grant = db.query(CaseAccessGrant).filter_by(case_id=case.id, user_id=recipient.id).first()
    if grant is None:
        grant = CaseAccessGrant(case_id=case.id, user_id=recipient.id, permission=req.permission, granted_by=user.id)
        db.add(grant)
    else:
        grant.permission = req.permission
        grant.revoked_at = None
        grant.granted_by = user.id
        grant.granted_at = datetime.now(timezone.utc)
    workflow = WorkflowRepository(db)
    workflow.append_case_event(case_id=case.id, event_type="case_access_granted", actor_id=user.id,
                               payload={"user_id": recipient.id, "permission": req.permission})
    workflow.audit(actor_id=user.id, case_id=case.id, action="case.access.grant", resource_type="case",
                   resource_id=case.id, details={"user_id": recipient.id, "permission": req.permission})
    db.commit()
    return {"case_id": case.id, "user_id": recipient.id, "permission": grant.permission, "state": "active"}


@router.delete("/cases/{case_id}/access-grants/{recipient_id}", status_code=204)
def revoke_case_access(case_id: str, recipient_id: str, db: Session = Depends(get_db),
                       user: User = Depends(require_role("analyst", "admin"))):
    case = get_accessible_case(db, user, case_id, write=True)
    grant = db.query(CaseAccessGrant).filter_by(case_id=case.id, user_id=recipient_id).first()
    if grant is None or grant.revoked_at is not None:
        raise ApplicationError(code="CASE_GRANT_NOT_FOUND", message="Case access grant not found", status_code=404)
    grant.revoked_at = datetime.now(timezone.utc)
    workflow = WorkflowRepository(db)
    workflow.append_case_event(case_id=case.id, event_type="case_access_revoked", actor_id=user.id,
                               payload={"user_id": recipient_id})
    workflow.audit(actor_id=user.id, case_id=case.id, action="case.access.revoke", resource_type="case",
                   resource_id=case.id, details={"user_id": recipient_id})
    db.commit()
    from fastapi import Response
    return Response(status_code=204)
