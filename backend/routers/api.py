"""Cases, Alerts, VASP, Notices, Reports, and Dashboard routers."""
import base64
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func
from database import get_db
from models import (
    Case, CaseWallet, Alert, VaspDirectory, VaspAddress,
    LegalNotice, ForensicReport, User, Transaction, Wallet,
)
from auth.utils import get_current_user, require_role
from app.utils.pagination import PageWindow, page_payload
from app.security.authorization import accessible_case_query, get_accessible_case
from app.persistence.models import CaseComplaint, ComplaintRecord, EvidenceManifest, ReportEvent, ReportRevision, Victim
from app.repositories.phase3 import WorkflowRepository, canonical_digest
from app.security.data_protection import unprotect
from services.report_generator import generate_freeze_notice, generate_forensic_report
from services.correlation import find_linked_cases
from services.risk_scoring import compute_risk_score


# ═══════════════════════════════════════════════════════════
# CASES ROUTER
# ═══════════════════════════════════════════════════════════
cases_router = APIRouter(prefix="/api/v1/cases", tags=["Cases"])


def _protected_case_fields(db: Session, case: Case) -> tuple[str | None, str | None, str | None]:
    link = db.query(CaseComplaint).filter(CaseComplaint.case_id == case.id, CaseComplaint.role == "primary").first()
    complaint = db.query(ComplaintRecord).filter(ComplaintRecord.id == link.complaint_id).first() if link else None
    victim = db.query(Victim).filter(Victim.id == complaint.victim_id).first() if complaint and complaint.victim_id else None
    return (
        unprotect(victim.name_ciphertext) if victim else case.victim_name,
        unprotect(victim.phone_ciphertext) if victim else case.victim_phone,
        unprotect(complaint.narrative_ciphertext) if complaint else case.complaint_text,
    )


@cases_router.get("")
def list_cases(
    status: str = None,
    fraud_type: str = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = accessible_case_query(db, user)
    if status:
        aliases = {
            "NEW": ["NEW", "new"],
            "UNDER_INVESTIGATION": ["UNDER_INVESTIGATION", "investigating"],
            "ATTRIBUTED": ["ATTRIBUTED", "escalated_to_vasp"],
            "FROZEN": ["FROZEN", "frozen"],
            "CLOSED": ["CLOSED", "closed"],
        }
        query = query.filter(Case.status.in_(aliases.get(status, [status])))
    if fraud_type:
        query = query.filter(Case.fraud_typology == fraud_type)

    window = PageWindow(page=page, page_size=page_size)
    total = query.count()
    cases = query.order_by(Case.created_at.desc()).offset(window.offset).limit(window.page_size).all()
    items = [
            {
                "id": c.id,
                "external_complaint_id": c.external_complaint_id,
                "complaint_source": c.complaint_source,
                "victim_name": _protected_case_fields(db, c)[0],
                "fraud_typology": c.fraud_typology,
                "reported_loss_amount": float(c.reported_loss_amount),
                "loss_currency": c.loss_currency,
                "status": c.status,
                "compatibility_status": {"new": "NEW", "investigating": "UNDER_INVESTIGATION",
                                         "escalated_to_vasp": "ATTRIBUTED", "frozen": "FROZEN",
                                         "closed": "CLOSED"}.get(c.status, c.status),
                "revision": c.revision,
                "risk_score": c.risk_score,
                "risk_tier": c.risk_tier,
                "possible_syndicate": c.possible_syndicate,
                "created_at": c.created_at.isoformat() if c.created_at else None,
            }
            for c in cases
        ]
    return page_payload(items, total, window, cases=items)


@cases_router.get("/{case_id}")
def get_case(case_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    case = get_accessible_case(db, user, case_id)
    victim_name, victim_phone, complaint_text = _protected_case_fields(db, case)

    # Get wallets
    wallets = db.query(CaseWallet).filter_by(case_id=case_id).order_by(CaseWallet.hop_depth).all()

    return {
        "id": case.id,
        "external_complaint_id": case.external_complaint_id,
        "complaint_source": case.complaint_source,
        "victim_name": victim_name,
        "victim_phone": victim_phone,
        "fraud_typology": case.fraud_typology,
        "reported_loss_amount": float(case.reported_loss_amount),
        "loss_currency": case.loss_currency,
        "incident_timestamp": case.incident_timestamp.isoformat() if case.incident_timestamp else None,
        "complaint_text": complaint_text,
        "status": case.status,
        "compatibility_status": {"new": "NEW", "investigating": "UNDER_INVESTIGATION",
                                 "escalated_to_vasp": "ATTRIBUTED", "frozen": "FROZEN",
                                 "closed": "CLOSED"}.get(case.status, case.status),
        "revision": case.revision,
        "primary_report_event_id": case.primary_report_event_id,
        "risk_score": case.risk_score,
        "risk_tier": case.risk_tier,
        "possible_syndicate": case.possible_syndicate,
        "created_at": case.created_at.isoformat() if case.created_at else None,
        "wallets": [
            {
                "address": w.wallet_address,
                "chain": w.wallet_chain,
                "hop_depth": w.hop_depth,
                "is_origin": w.is_origin_reported,
                "is_terminal": w.is_terminal_destination,
            }
            for w in wallets
        ],
    }


# ═══════════════════════════════════════════════════════════
# ALERTS ROUTER
# ═══════════════════════════════════════════════════════════
alerts_router = APIRouter(prefix="/api/v1/alerts", tags=["Alerts"])


@alerts_router.get("")
def list_alerts(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = db.query(Alert).filter_by(user_id=user.id)
    window = PageWindow(page=page, page_size=page_size)
    total = query.count()
    alerts = query.order_by(Alert.created_at.desc()).offset(window.offset).limit(window.page_size).all()
    unread = query.filter_by(is_read=False).count()
    items = [
            {
                "id": a.id,
                "case_id": a.case_id,
                "alert_type": a.alert_type,
                "severity": a.severity,
                "title": a.title,
                "message": a.message,
                "is_read": a.is_read,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in alerts
        ]
    return page_payload(items, total, window, alerts=items, unread_count=unread)


@alerts_router.put("/{alert_id}/read")
def mark_alert_read(alert_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    alert = db.query(Alert).filter_by(id=alert_id, user_id=user.id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    alert.is_read = True
    db.commit()
    return {"success": True}


# ═══════════════════════════════════════════════════════════
# VASP DIRECTORY ROUTER
# ═══════════════════════════════════════════════════════════
vasp_router = APIRouter(prefix="/api/v1/vasp", tags=["VASP Directory"])


@vasp_router.get("/directory")
def list_vasp_directory(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = db.query(VaspDirectory)
    window = PageWindow(page=page, page_size=page_size)
    total = query.count()
    vasps = query.order_by(VaspDirectory.vasp_name).offset(window.offset).limit(window.page_size).all()
    items = [
            {
                "id": v.id,
                "vasp_name": v.vasp_name,
                "legal_entity_name": v.legal_entity_name,
                "is_fiu_ind_registered": v.is_fiu_ind_registered,
                "nodal_officer_email": v.nodal_officer_email,
                "jurisdiction": v.jurisdiction,
                "sla_freeze_hours": v.sla_freeze_hours,
                "address_count": db.query(VaspAddress).filter_by(vasp_id=v.id).count(),
            }
            for v in vasps
        ]
    return page_payload(items, total, window, vasps=items)


@vasp_router.get("/addresses")
def list_vasp_addresses(
    vasp_id: str = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = db.query(VaspAddress)
    if vasp_id:
        query = query.filter_by(vasp_id=vasp_id)
    window = PageWindow(page=page, page_size=page_size)
    total = query.count()
    addrs = query.offset(window.offset).limit(window.page_size).all()
    items = [
            {
                "address": a.address,
                "chain": a.chain,
                "vasp_id": a.vasp_id,
                "vasp_name": a.vasp.vasp_name if a.vasp else "N/A",
                "address_tag": a.address_tag,
                "is_verified": a.is_verified,
            }
            for a in addrs
        ]
    return page_payload(items, total, window, addresses=items)


class VaspAddressCreate(BaseModel):
    address: str
    chain: str
    vasp_id: str
    address_tag: str


@vasp_router.post("/addresses")
def add_vasp_address(req: VaspAddressCreate, db: Session = Depends(get_db), user: User = Depends(require_role("admin", "analyst"))):
    existing = db.query(VaspAddress).filter_by(address=req.address, chain=req.chain).first()
    if existing:
        raise HTTPException(status_code=409, detail="Address already exists in VASP directory")
    addr = VaspAddress(address=req.address, chain=req.chain, vasp_id=req.vasp_id, address_tag=req.address_tag)
    db.add(addr)
    db.commit()
    return {"success": True, "message": "VASP address added"}


@vasp_router.delete("/addresses/{address}/{chain}")
def delete_vasp_address(address: str, chain: str, db: Session = Depends(get_db), user: User = Depends(require_role("admin"))):
    addr = db.query(VaspAddress).filter_by(address=address, chain=chain).first()
    if not addr:
        raise HTTPException(status_code=404, detail="Address not found")
    db.delete(addr)
    db.commit()
    return {"success": True}


# ═══════════════════════════════════════════════════════════
# NOTICES ROUTER (Sec 94 BNSS Freeze)
# ═══════════════════════════════════════════════════════════
notices_router = APIRouter(prefix="/api/v1/cases", tags=["Legal Notices"])


class FreezeNoticeRequest(BaseModel):
    vasp_id: str
    police_station: str = "Cyber Crime Police Station"
    officer_name: str = "Investigating Officer"
    fir_cr_number: str = ""
    designation: str = "Inspector"


@notices_router.post("/{case_id}/generate-freeze-notice")
def gen_freeze_notice(case_id: str, req: FreezeNoticeRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    case = get_accessible_case(db, user, case_id, write=True)

    vasp = db.query(VaspDirectory).filter_by(id=req.vasp_id).first()
    if not vasp:
        raise HTTPException(status_code=404, detail="VASP not found")

    # Get trace data for the notice
    terminal = db.query(CaseWallet).filter_by(case_id=case_id, is_terminal_destination=True).first()
    origin = db.query(CaseWallet).filter_by(case_id=case_id, is_origin_reported=True).first()

    # Find the last transaction to the terminal wallet
    last_tx = None
    if terminal:
        last_tx = db.query(Transaction).filter_by(to_address=terminal.wallet_address).first()

    case_data = {
        "external_complaint_id": case.external_complaint_id,
        "reported_loss_amount": float(case.reported_loss_amount),
        "loss_currency": case.loss_currency,
        "reported_wallet": origin.wallet_address if origin else "N/A",
    }

    vasp_data = {
        "vasp_name": vasp.vasp_name,
        "legal_entity_name": vasp.legal_entity_name or vasp.vasp_name,
        "nodal_officer_email": vasp.nodal_officer_email,
    }

    trace_data = {
        "destination_address": terminal.wallet_address if terminal else "N/A",
        "tx_hash": last_tx.tx_hash if last_tx else "N/A",
        "amount": float(last_tx.amount) if last_tx else 0,
        "chain": terminal.wallet_chain if terminal else "N/A",
        "timestamp": last_tx.timestamp.isoformat() if last_tx and last_tx.timestamp else "N/A",
        "confidence": None,
    }

    officer_info = {
        "officer_name": req.officer_name,
        "police_station": req.police_station,
        "designation": req.designation,
        "fir_number": req.fir_cr_number,
        "station_code": "HQ",
    }

    result = generate_freeze_notice(case_data, vasp_data, trace_data, officer_info)

    # Store notice record
    existing_notice = db.query(LegalNotice).filter_by(reference_number=result["reference_number"]).first()
    if existing_notice:
        db.delete(existing_notice)
        db.flush()

    notice = LegalNotice(
        case_id=case_id,
        vasp_id=req.vasp_id,
        reference_number=result["reference_number"],
        target_wallet=terminal.wallet_address if terminal else "N/A",
        target_tx_hash=last_tx.tx_hash if last_tx else None,
        amount_to_freeze=float(case.reported_loss_amount),
        currency=case.loss_currency,
        status="GENERATED",
        pdf_storage_path=result["pdf_path"],
        dispatched_to_email=vasp.nodal_officer_email,
        generated_by=user.id,
    )
    db.add(notice)
    db.commit()

    # Return PDF as base64
    pdf_b64 = base64.b64encode(result["pdf_bytes"]).decode()

    return {
        "notice_id": notice.id,
        "reference_number": result["reference_number"],
        "statutory_section": "Section 94 BNSS, 2023 (formerly Sec 91 CrPC)",
        "recipient": {
            "vasp_name": vasp.vasp_name,
            "nodal_email": vasp.nodal_officer_email,
        },
        "content_hash": result["content_hash"],
        "pdf_base64": pdf_b64,
        "pdf_filename": result["pdf_filename"],
    }


# ═══════════════════════════════════════════════════════════
# REPORTS ROUTER (Sec 63 BSA Forensic)
# ═══════════════════════════════════════════════════════════
reports_router = APIRouter(prefix="/api/v1/cases", tags=["Forensic Reports"])


@reports_router.post("/{case_id}/generate-court-report")
def gen_court_report(case_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    case = get_accessible_case(db, user, case_id)

    # Build trace result from stored data
    case_wallets = db.query(CaseWallet).filter_by(case_id=case_id).all()
    wallet_addrs = {cw.wallet_address for cw in case_wallets}
    txs = db.query(Transaction).filter(
        Transaction.from_address.in_(wallet_addrs),
        Transaction.to_address.in_(wallet_addrs),
    ).all()

    edges = [
        {
            "source": tx.from_address,
            "target": tx.to_address,
            "amount": float(tx.amount),
            "token": tx.token_symbol,
            "tx_hash": tx.tx_hash,
            "timestamp": tx.timestamp.isoformat() if tx.timestamp else "",
            "is_peeling": tx.is_peeling_tx,
        }
        for tx in txs
    ]

    # Get VASP attribution
    terminal = db.query(CaseWallet).filter_by(case_id=case_id, is_terminal_destination=True).first()
    attribution = None
    if terminal:
        wallet = db.query(Wallet).filter_by(address=terminal.wallet_address, chain=terminal.wallet_chain).first()
        if wallet and wallet.vasp_id:
            vasp = db.query(VaspDirectory).filter_by(id=wallet.vasp_id).first()
            if vasp:
                attribution = {
                    "vasp_name": vasp.vasp_name,
                    "is_fiu_ind_registered": vasp.is_fiu_ind_registered,
                    "nodal_officer_email": vasp.nodal_officer_email,
                    "attribution_tier": wallet.attribution_tier,
                    "confidence_score": wallet.attribution_confidence,
                    "evidence": wallet.attribution_evidence,
                    "destination_address": terminal.wallet_address,
                }

    trace_result = {
        "vasp_attribution": attribution,
        "edges": edges,
        "risk_flags": [],
    }

    case_data = {
        "external_complaint_id": case.external_complaint_id,
        "complaint_source": case.complaint_source,
        "fraud_typology": case.fraud_typology,
        "reported_loss_amount": float(case.reported_loss_amount),
        "loss_currency": case.loss_currency,
        "victim_name": case.victim_name,
        "incident_timestamp": case.incident_timestamp.isoformat() if case.incident_timestamp else "N/A",
    }

    risk_data = {
        "composite_risk_score": case.risk_score,
        "risk_tier": case.risk_tier,
        "contributing_factors": [],
    }

    correlation = find_linked_cases(case_id, db)

    result = generate_forensic_report(case_data, trace_result, risk_data, correlation)

    # Store report record
    existing_rep = db.query(ForensicReport).filter_by(report_reference_number=result["report_reference"]).first()
    if existing_rep:
        db.delete(existing_rep)
        db.flush()

    report = ForensicReport(
        case_id=case_id,
        report_reference_number=result["report_reference"],
        sha256_content_hash=result["sha256_pdf_hash"],
        generated_by=user.id,
        pdf_storage_path=result["pdf_path"],
        is_court_certified=False,
    )
    db.add(report)
    db.flush()
    report_event = db.query(ReportEvent).filter(ReportEvent.id == case.primary_report_event_id).first()
    cutoff = report_event.report_timestamp if report_event else datetime.now(timezone.utc)
    manifest = {
        "case_id": case.id, "report_id": report.id, "report_event_id": report_event.id if report_event else None,
        "content_digest": result["sha256_content_hash"], "pdf_digest": result["sha256_pdf_hash"],
        "report_event_revision": report_event.revision if report_event else None,
        "report_cutoff": cutoff.isoformat(), "pre_report_context": "retained_separately",
        "post_report_activity": "strictly_after_selected_report_cutoff", "transaction_count": len(edges),
        "source_references": sorted({tx.tx_hash for tx in txs}), "graph_snapshot_id": None,
        "risk_result_id": None, "ml_prediction_id": None,
        "limitations": ["Legacy-compatible immediate generation", "Human review and signature required"],
    }
    evidence_revision = (db.query(func.coalesce(func.max(EvidenceManifest.revision), 0))
                         .filter(EvidenceManifest.case_id == case.id).scalar() + 1)
    evidence_manifest = EvidenceManifest(case_id=case.id, revision=evidence_revision, object_ids=[],
                                         manifest_hash=canonical_digest(manifest))
    db.add(evidence_manifest); db.flush()
    revision = ReportRevision(report_id=report.id, revision=1, case_id=case.id, evidence_manifest={**manifest, "manifest_id": evidence_manifest.id},
        content_digest=result["sha256_content_hash"], pdf_digest=result["sha256_pdf_hash"], storage_uri=result["pdf_path"],
        report_cutoff=cutoff, review_status="draft", dispatch_status="not_dispatched", created_by=user.id)
    db.add(revision)
    db.flush()
    WorkflowRepository(db).audit(actor_id=user.id, case_id=case.id, action="report.generate", resource_type="report_revision",
                                 resource_id=revision.id, details={"manifest_hash": evidence_manifest.manifest_hash})
    db.commit()

    pdf_b64 = base64.b64encode(result["pdf_bytes"]).decode()

    return {
        "report_id": report.id,
        "report_reference": result["report_reference"],
        "sha256_hash": result["sha256_pdf_hash"],
        "legal_admissibility": "Draft evidence report; human completion, review, and signature are required",
        "is_court_certified": False,
        "manifest_hash": evidence_manifest.manifest_hash,
        "pdf_base64": pdf_b64,
        "pdf_filename": result["pdf_filename"],
    }


# ═══════════════════════════════════════════════════════════
# DASHBOARD ROUTER
# ═══════════════════════════════════════════════════════════
dashboard_router = APIRouter(prefix="/api/v1/dashboard", tags=["Dashboard"])


@dashboard_router.get("/stats")
def get_dashboard_stats(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    scoped = accessible_case_query(db, user)
    scoped_ids = scoped.with_entities(Case.id).subquery()
    total_cases = scoped.count()
    total_wallets = db.query(CaseWallet).filter(CaseWallet.case_id.in_(db.query(scoped_ids.c.id))).count()
    total_attributed = scoped.filter(Case.status.in_(["ATTRIBUTED", "escalated_to_vasp"])).count()
    total_syndicate = scoped.filter(Case.possible_syndicate == True).count()

    # Cases by fraud type
    fraud_type_counts = scoped.with_entities(Case.fraud_typology, func.count(Case.id)).group_by(Case.fraud_typology).all()

    # Cases by status
    status_counts = scoped.with_entities(Case.status, func.count(Case.id)).group_by(Case.status).all()

    # Cases by risk tier
    risk_counts = scoped.with_entities(Case.risk_tier, func.count(Case.id)).group_by(Case.risk_tier).all()

    # Total loss tracked
    total_loss = scoped.with_entities(func.sum(Case.reported_loss_amount)).scalar() or 0

    return {
        "total_cases": total_cases,
        "total_wallets_traced": total_wallets,
        "total_attributed": total_attributed,
        "total_syndicate_flags": total_syndicate,
        "total_loss_tracked": float(total_loss),
        "cases_by_fraud_type": {ft: count for ft, count in fraud_type_counts},
        "cases_by_status": {s: count for s, count in status_counts},
        "cases_by_risk_tier": {r: count for r, count in risk_counts},
    }
