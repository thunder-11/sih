"""Authorized complaint intake and retrieval routes."""

from fastapi import APIRouter, Depends, Header, Query, Request, status
from sqlalchemy.orm import Session

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.core.config import get_settings
from app.core.errors import ApplicationError
from app.persistence.models import AddressRecord, AnalysisRun, CaseComplaint, ComplaintRecord, ComplaintWallet, ReportEvent, Victim
from app.repositories.phase2 import DurableJobRepository
from app.repositories.phase3 import WorkflowRepository, canonical_digest
from app.schemas.phase3 import ComplaintIntake, ReportEventCreate, WalletAssociationRequest
from app.security.authorization import accessible_case_query, active_agency_id, get_accessible_case
from app.security.data_protection import unprotect
from app.services.intake import ingest_complaint
from app.utils.addresses import validate_wallet
from app.utils.timestamps import parse_report_timestamp
from app.utils.pagination import PageWindow, page_payload
from auth.utils import get_current_user
from database import get_db
from models import Case, CaseWallet, User, Wallet


router = APIRouter(prefix="/api/v1/complaints", tags=["Complaints"])


@router.post("", status_code=status.HTTP_201_CREATED)
def create_complaint(req: ComplaintIntake, request: Request, db: Session = Depends(get_db),
                     user: User = Depends(get_current_user),
                     idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    return ingest_complaint(db, intake=req, user=user, idempotency_key=idempotency_key)


@router.get("")
def list_complaints(source: str | None = None, page: int = Query(1, ge=1),
                    page_size: int = Query(25, ge=1, le=100), db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    case_ids = accessible_case_query(db, user).with_entities(Case.id).subquery()
    complaint_ids = db.query(CaseComplaint.complaint_id).filter(CaseComplaint.case_id.in_(db.query(case_ids.c.id)))
    query = db.query(ComplaintRecord).filter(ComplaintRecord.agency_id == active_agency_id(db, user),
                                             ComplaintRecord.id.in_(complaint_ids))
    if source:
        query = query.filter(ComplaintRecord.source == source)
    window = PageWindow(page, page_size)
    total = query.count()
    records = query.order_by(ComplaintRecord.created_at.desc()).offset(window.offset).limit(window.page_size).all()
    items = [{"id": item.id, "source": item.source, "external_reference": item.external_reference,
              "reported_loss_amount": str(item.reported_loss), "loss_currency": item.loss_currency,
              "received_at": item.received_time.isoformat()} for item in records]
    return page_payload(items, total, window, complaints=items)


@router.get("/{complaint_id}")
def get_complaint(complaint_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    complaint = db.query(ComplaintRecord).filter(ComplaintRecord.id == complaint_id,
                                                 ComplaintRecord.agency_id == active_agency_id(db, user)).first()
    if complaint is None:
        from app.core.errors import ApplicationError
        raise ApplicationError(code="COMPLAINT_NOT_FOUND", message="Complaint not found", status_code=404)
    case_link = db.query(CaseComplaint).filter(CaseComplaint.complaint_id == complaint.id).first()
    if case_link is None:
        raise ApplicationError(code="COMPLAINT_NOT_FOUND", message="Complaint not found", status_code=404)
    get_accessible_case(db, user, case_link.case_id)
    victim = db.query(Victim).filter(Victim.id == complaint.victim_id).first() if complaint.victim_id else None
    wallets = db.query(ComplaintWallet).filter(ComplaintWallet.complaint_id == complaint.id).all()
    reports = db.query(ReportEvent).filter(ReportEvent.complaint_id == complaint.id).order_by(ReportEvent.revision).all()
    return {"id": complaint.id, "case_id": case_link.case_id if case_link else None, "source": complaint.source,
            "external_reference": complaint.external_reference,
            "victim_name": unprotect(victim.name_ciphertext) if victim else None,
            "victim_phone": unprotect(victim.phone_ciphertext) if victim else None,
            "complaint_text": unprotect(complaint.narrative_ciphertext),
            "reported_loss_amount": str(complaint.reported_loss), "loss_currency": complaint.loss_currency,
            "wallet_address_ids": [wallet.address_id for wallet in wallets],
            "report_events": [{"id": event.id, "revision": event.revision,
                               "reported_at_utc": event.report_timestamp.isoformat()} for event in reports]}


@router.get("/{complaint_id}/report-events")
def list_report_events(complaint_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    complaint = db.query(ComplaintRecord).filter(ComplaintRecord.id == complaint_id,
                                                 ComplaintRecord.agency_id == active_agency_id(db, user)).first()
    if complaint is None:
        from app.core.errors import ApplicationError
        raise ApplicationError(code="COMPLAINT_NOT_FOUND", message="Complaint not found", status_code=404)
    link = db.query(CaseComplaint).filter(CaseComplaint.complaint_id == complaint.id).first()
    if link is None:
        raise ApplicationError(code="COMPLAINT_NOT_FOUND", message="Complaint not found", status_code=404)
    get_accessible_case(db, user, link.case_id)
    events = db.query(ReportEvent).filter(ReportEvent.complaint_id == complaint_id).order_by(ReportEvent.revision).all()
    return {"items": [{"id": event.id, "case_id": event.case_id, "revision": event.revision,
                       "reported_at_utc": event.report_timestamp.isoformat(),
                       "original_timestamp": event.original_timestamp, "timezone": event.reported_timezone,
                       "iana_timezone": event.iana_timezone, "source": event.source_system,
                       "channel": event.channel, "receipt_reference": event.receipt_reference,
                       "precision": event.timestamp_precision, "verification_status": event.verification_state,
                       "correction_reason": event.correction_reason,
                       "supersedes_id": event.supersedes_id} for event in events]}


def _complaint_case(db: Session, user: User, complaint_id: str):
    complaint = db.query(ComplaintRecord).filter(ComplaintRecord.id == complaint_id,
                                                 ComplaintRecord.agency_id == active_agency_id(db, user)).first()
    link = db.query(CaseComplaint).filter(CaseComplaint.complaint_id == complaint_id).first() if complaint else None
    if complaint is None or link is None:
        raise ApplicationError(code="COMPLAINT_NOT_FOUND", message="Complaint not found", status_code=404)
    return complaint, get_accessible_case(db, user, link.case_id, write=True)


@router.post("/{complaint_id}/report-events", status_code=201)
def add_report_event(complaint_id: str, req: ReportEventCreate, db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    complaint, case = _complaint_case(db, user, complaint_id)
    parsed = parse_report_timestamp(req.reported_at, iana_timezone=req.report_timezone,
                                    future_skew_seconds=get_settings().report_time_max_future_skew_seconds)
    revision = db.query(ReportEvent).filter(ReportEvent.case_id == case.id).count() + 1
    event = ReportEvent(case_id=case.id, complaint_id=complaint.id, revision=revision,
                        report_timestamp=parsed.utc, reported_timezone=parsed.offset,
                        original_timestamp=parsed.original, iana_timezone=parsed.iana_timezone,
                        timestamp_precision=parsed.precision, verification_state=req.verification_status,
                        source_system=req.source, channel=req.channel, receipt_reference=req.receipt_reference,
                        external_event_id=req.receipt_reference, received_at=datetime.now(timezone.utc),
                        created_by=user.id, payload_digest=canonical_digest(req.model_dump()))
    db.add(event)
    db.flush()
    if case.primary_report_event_id is None:
        case.primary_report_event_id = event.id
    WorkflowRepository(db).audit(actor_id=user.id, case_id=case.id, action="report_event.create",
                                 resource_type="report_event", resource_id=event.id)
    db.commit()
    return {"id": event.id, "case_id": case.id, "complaint_id": complaint.id, "revision": event.revision,
            "reported_at_utc": event.report_timestamp.isoformat(), "original_timestamp": event.original_timestamp}


@router.post("/{complaint_id}/wallets", status_code=201)
def add_complaint_wallets(complaint_id: str, req: WalletAssociationRequest, request: Request,
                          db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    complaint, case = _complaint_case(db, user, complaint_id)
    address_ids = []
    errors = []
    for index, wallet in enumerate(req.wallets):
        result = validate_wallet(wallet.address, wallet.chain, fixture_mode=request.app.state.settings.fixture_data_enabled)
        if not result.valid or (wallet.chain is None and len(result.candidates) != 1):
            errors.append({"field": f"wallets.{index}", "message": result.reason or "Network selection required", "type": "value_error"})
            continue
        chain = wallet.chain or result.candidates[0]
        address = db.query(AddressRecord).filter(AddressRecord.chain == chain,
                                                 AddressRecord.canonical_address == result.canonical_address).first()
        if address is None:
            address = AddressRecord(chain=chain, canonical_address=result.canonical_address,
                                    display_address=wallet.address, address_type="wallet")
            db.add(address)
            db.flush()
        address_ids.append(address.id)
        if db.query(ComplaintWallet).filter_by(complaint_id=complaint.id, address_id=address.id).first() is None:
            db.add(ComplaintWallet(complaint_id=complaint.id, address_id=address.id, role=wallet.wallet_role,
                                   source="confirmed", confidence=Decimal("1")))
        if db.query(Wallet).filter_by(address=result.canonical_address, chain=chain).first() is None:
            db.add(Wallet(address=result.canonical_address, chain=chain, node_type="ORIGIN_VICTIM",
                          first_seen=datetime.now(timezone.utc), risk_flags="[]"))
        if db.query(CaseWallet).filter_by(case_id=case.id, wallet_address=result.canonical_address,
                                          wallet_chain=chain).first() is None:
            db.add(CaseWallet(case_id=case.id, wallet_address=result.canonical_address, wallet_chain=chain,
                              hop_depth=0, is_origin_reported=True))
    if errors:
        raise ApplicationError(code="INVALID_WALLET", message="One or more wallets require correction",
                               status_code=422, field_errors=errors)
    run = db.query(AnalysisRun).filter(AnalysisRun.case_id == case.id, AnalysisRun.run_type == "trace").first()
    job = None
    if run is None and req.auto_start and address_ids:
        report = db.query(ReportEvent).filter(ReportEvent.id == case.primary_report_event_id).first()
        if report is None:
            report = db.query(ReportEvent).filter(ReportEvent.complaint_id == complaint.id).order_by(ReportEvent.revision.desc()).first()
        if report:
            now = datetime.now(timezone.utc)
            run = AnalysisRun(case_id=case.id, run_type="trace", revision=1, state="queued", requested_by=user.id,
                              report_event_id=report.id, root_address_ids=address_ids, event_cutoff=now,
                              # The worker ingests evidence asynchronously after this immutable row
                              # is created; its available_time is stamped at fetch time, always later
                              # than "now" — the cutoff must already cover that window or the trace's
                              # own fetched evidence would be excluded by its own cutoff.
                              cutoff_available_time=now + timedelta(hours=1),
                              parameters={"max_hops": get_settings().default_max_hops},
                              stage="queued", checkpoint={}, coverage={"state": "not_requested"})
            db.add(run)
            db.flush()
            job, _ = DurableJobRepository(db).enqueue_once(operation="trace.run", idempotency_key=f"initial:{case.id}",
                                                           case_id=case.id, payload={"run_id": run.id, "case_id": case.id})
            job.actor_id = user.id
            case.status = "investigating"
    workflow = WorkflowRepository(db)
    workflow.append_case_event(case_id=case.id, event_type="complaint_wallets_confirmed", actor_id=user.id,
                               payload={"address_ids": address_ids, "run_id": run.id if run else None})
    workflow.audit(actor_id=user.id, case_id=case.id, action="complaint.wallets.confirm",
                   resource_type="complaint", resource_id=complaint.id, details={"address_ids": address_ids})
    db.commit()
    return {"complaint_id": complaint.id, "case_id": case.id, "address_ids": address_ids,
            "trace_id": run.id if run else None, "job_id": job.id if job else None,
            "status": "queued" if run else "awaiting_input"}
