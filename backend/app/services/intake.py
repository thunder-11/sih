"""Atomic complaint intake and exactly-once initial analysis initiation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import ApplicationError
from app.jobs.contracts import JobState
from app.persistence.models import (
    AddressRecord, AnalysisRun, CaseComplaint, CaseEvent, ComplaintRecord, ComplaintWallet,
    ReportEvent, Victim,
)
from app.repositories.phase2 import DurableJobRepository
from app.repositories.phase3 import WorkflowRepository, canonical_digest
from app.schemas.phase3 import ComplaintIntake
from app.security.authorization import active_agency_id, get_accessible_case
from app.security.data_protection import protect
from app.utils.addresses import validate_wallet
from app.utils.timestamps import parse_report_timestamp
from models import Case, CaseWallet, User, Wallet


def _parse_optional_time(value: str | None, field: str) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ApplicationError(code="INVALID_TIMESTAMP", message=f"Invalid {field}", status_code=422,
                               field_errors=[{"field": field, "message": "Invalid ISO-8601 timestamp", "type": "value_error"}]) from exc
    if parsed.tzinfo is None:
        raise ApplicationError(code="INVALID_TIMESTAMP", message=f"{field} requires an offset", status_code=422)
    return parsed.astimezone(timezone.utc)


def _report_payload(event: ReportEvent) -> dict:
    return {"id": event.id, "revision": event.revision, "reported_at_utc": event.report_timestamp.isoformat(),
            "original_timestamp": event.original_timestamp, "timezone": event.reported_timezone,
            "iana_timezone": event.iana_timezone, "source": event.source_system, "channel": event.channel,
            "verification_status": event.verification_state}


def ingest_complaint(session: Session, *, intake: ComplaintIntake, user: User, idempotency_key: str | None) -> dict:
    settings = get_settings()
    if intake.data_mode and intake.data_mode != settings.data_mode:
        raise ApplicationError(code="DATA_MODE_MISMATCH", message="Requested data mode is unavailable", status_code=422)
    agency_id = active_agency_id(session, user)
    request_data = intake.model_dump(mode="json")
    request_digest = canonical_digest(request_data)
    natural_key = f"{agency_id}:{intake.complaint_source}:{intake.external_complaint_id}"
    key = idempotency_key or natural_key
    workflow = WorkflowRepository(session)
    replay = workflow.idempotency_replay(actor_id=user.id, operation="complaint.create", key=key,
                                         request_digest=request_digest)
    if replay is not None:
        replay["idempotent_replay"] = True
        return replay

    validated: list[tuple[object, object]] = []
    field_errors: list[dict] = []
    for index, wallet in enumerate(intake.suspect_wallets):
        result = validate_wallet(wallet.address, wallet.chain, fixture_mode=settings.fixture_data_enabled)
        if not result.valid:
            field_errors.append({"field": f"suspect_wallets.{index}.address", "message": result.reason or "Invalid wallet", "type": "value_error"})
        elif wallet.chain is None and len(result.candidates) != 1:
            field_errors.append({"field": f"suspect_wallets.{index}.chain", "message": f"Select one network from {list(result.candidates)}", "type": "ambiguous_network"})
        else:
            validated.append((wallet, result))
    if field_errors:
        raise ApplicationError(code="INVALID_WALLET", message="One or more wallets require correction", status_code=422,
                               field_errors=field_errors)

    now = datetime.now(timezone.utc)
    report_value = intake.victim_reported_at or now.isoformat().replace("+00:00", "Z")
    report = parse_report_timestamp(report_value, iana_timezone=intake.report_timezone,
                                    future_skew_seconds=settings.report_time_max_future_skew_seconds, now=now)
    incident_time = _parse_optional_time(intake.incident_timestamp, "incident_timestamp")
    filed_time = _parse_optional_time(intake.filed_at, "filed_at")

    existing = session.execute(select(ComplaintRecord).where(
        ComplaintRecord.agency_id == agency_id, ComplaintRecord.source == intake.complaint_source,
        ComplaintRecord.external_reference == intake.external_complaint_id,
    )).scalar_one_or_none()
    if existing is not None:
        raise ApplicationError(code="DUPLICATE_COMPLAINT", message="Complaint reference already exists with different input", status_code=409)

    victim = None
    if intake.victim_name or intake.victim_phone or intake.victim_details:
        victim = Victim(agency_id=agency_id, name_ciphertext=protect(intake.victim_name),
                        phone_ciphertext=protect(intake.victim_phone),
                        email_ciphertext=protect(str(intake.victim_details.get("email"))) if intake.victim_details.get("email") else None,
                        pii_key_version="phase3-v1")
        session.add(victim)
        session.flush()
    complaint = ComplaintRecord(agency_id=agency_id, victim_id=victim.id if victim else None,
                                source=intake.complaint_source, external_reference=intake.external_complaint_id,
                                narrative_ciphertext=protect(intake.complaint_text), reported_loss=Decimal(intake.reported_loss_amount),
                                loss_currency=intake.loss_currency.upper(), incident_time=incident_time,
                                filed_time=filed_time, received_time=report.utc)
    session.add(complaint)
    session.flush()

    if intake.existing_case_id:
        case = get_accessible_case(session, user, intake.existing_case_id, write=True)
    else:
        case = Case(complaint_source=intake.complaint_source, external_complaint_id=intake.external_complaint_id,
                    victim_name=None, victim_phone=None,
                    reported_loss_amount=intake.reported_loss_amount, loss_currency=intake.loss_currency.upper(),
                    incident_timestamp=incident_time, complaint_text=None,
                    fraud_typology=intake.fraud_typology or "UNKNOWN", status="new", assigned_officer_id=user.id,
                    agency_id=agency_id, revision=1, created_by=user.id)
        session.add(case)
        session.flush()
    has_primary = session.query(CaseComplaint).filter(CaseComplaint.case_id == case.id,
                                                      CaseComplaint.role == "primary").first() is not None
    session.add(CaseComplaint(case_id=case.id, complaint_id=complaint.id,
                              role="secondary" if has_primary else "primary", linked_by=user.id))

    report_revision = session.execute(select(func.coalesce(func.max(ReportEvent.revision), 0)).where(
        ReportEvent.case_id == case.id)).scalar_one() + 1
    report_event = ReportEvent(case_id=case.id, complaint_id=complaint.id, revision=report_revision,
                               report_timestamp=report.utc, reported_timezone=report.offset,
                               original_timestamp=report.original, iana_timezone=report.iana_timezone,
                               timestamp_precision=report.precision, verification_state=intake.report_verification_status,
                               source_system=intake.report_timestamp_source, channel=intake.complaint_source,
                               receipt_reference=intake.receipt_reference, external_event_id=intake.receipt_reference,
                               received_at=now, created_by=user.id, payload_digest=canonical_digest({
                                   "complaint_id": complaint.id, "reported_at": report.original,
                                   "source": intake.report_timestamp_source, "receipt": intake.receipt_reference,
                               }))
    session.add(report_event)
    session.flush()
    if case.primary_report_event_id is None:
        case.primary_report_event_id = report_event.id

    address_ids: list[str] = []
    for wallet_input, result in validated:
        chain = wallet_input.chain or result.candidates[0]
        address = session.execute(select(AddressRecord).where(
            AddressRecord.chain == chain, AddressRecord.canonical_address == result.canonical_address,
        )).scalar_one_or_none()
        if address is None:
            address = AddressRecord(chain=chain, canonical_address=result.canonical_address,
                                    display_address=wallet_input.address, address_type="wallet")
            session.add(address)
            session.flush()
        address_ids.append(address.id)
        session.add(ComplaintWallet(complaint_id=complaint.id, address_id=address.id, role=wallet_input.wallet_role,
                                    source="reported", confidence=Decimal("1")))
        legacy_wallet = session.query(Wallet).filter_by(address=result.canonical_address, chain=chain).first()
        if legacy_wallet is None:
            session.add(Wallet(address=result.canonical_address, chain=chain, node_type="ORIGIN_VICTIM",
                               first_seen=now, risk_flags="[]"))
        session.add(CaseWallet(case_id=case.id, wallet_address=result.canonical_address, wallet_chain=chain,
                               hop_depth=0, is_origin_reported=True))

    run = None
    job = None
    if validated and intake.auto_start:
        run_revision = session.execute(select(func.coalesce(func.max(AnalysisRun.revision), 0)).where(
            AnalysisRun.case_id == case.id, AnalysisRun.run_type == "trace")).scalar_one() + 1
        run = AnalysisRun(case_id=case.id, run_type="trace", revision=run_revision, state="queued", requested_by=user.id,
                          report_event_id=report_event.id, root_address_ids=address_ids, event_cutoff=now,
                          # The worker ingests evidence asynchronously after this immutable row is
                          # created; its available_time is stamped at fetch time, always later than
                          # "now" — the cutoff must already cover that window or the trace's own
                          # fetched evidence would be excluded by its own cutoff.
                          cutoff_available_time=now + timedelta(hours=1),
                          parameters={"max_hops": settings.default_max_hops},
                          stage="queued", checkpoint={}, coverage={"state": "not_requested"})
        session.add(run)
        session.flush()
        job, _ = DurableJobRepository(session).enqueue_once(operation="trace.run", idempotency_key=f"intake:{complaint.id}",
                                                               case_id=case.id, payload={"run_id": run.id, "case_id": case.id,
                                                                                         "root_address_ids": address_ids})
        job.actor_id = user.id
        case.status = "investigating"
    initiation_status = JobState.QUEUED.value if job else "awaiting_input"
    workflow.append_case_event(case_id=case.id, event_type="complaint_ingested", actor_id=user.id,
                               payload={"complaint_id": complaint.id, "report_event_id": report_event.id,
                                        "run_id": run.id if run else None, "status": initiation_status})
    workflow.audit(actor_id=user.id, case_id=case.id, action="complaint.create", resource_type="complaint",
                   resource_id=complaint.id, details={"source": complaint.source, "run_id": run.id if run else None})
    response = {"success": True, "complaint_id": complaint.id, "case_id": case.id,
                "external_complaint_id": intake.external_complaint_id, "report_event": _report_payload(report_event),
                "wallets": [{"address": result.canonical_address,
                             "network": wallet.chain or result.candidates[0],
                             "checksum_state": result.checksum_state,
                             "data_mode": "fixture" if result.synthetic_fixture else "live_compatible"}
                            for wallet, result in validated],
                "report_event_id": report_event.id, "trace_id": run.id if run else None,
                "job_id": job.id if job else None, "status": initiation_status,
                "status_url": f"/api/v1/traces/{run.id}" if run else None,
                "trace_ready": bool(run), "data_mode": settings.data_mode, "idempotent_replay": False,
                "message": "Complaint registered and analysis queued" if run else "Complaint registered; validated wallet input is required"}
    workflow.remember(actor_id=user.id, operation="complaint.create", key=key, request_digest=request_digest,
                      response=response)
    session.commit()
    return response
