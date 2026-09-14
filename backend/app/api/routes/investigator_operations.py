"""Phase 11 immutable report evidence, search, and audit read operations."""

from hashlib import sha256
import json
from datetime import datetime, timezone

from pathlib import Path

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import FileResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.errors import ApplicationError
from app.persistence.models import AuditEvent, EvidenceManifest, GraphSnapshot, MLPrediction, PolicySetting, ReportRevision, RiskResult
from app.repositories.phase3 import WorkflowRepository
from app.schemas.phase11 import NoticeDispatch, NoticeReview, PolicyCreate, ReportRevisionCreate
from app.security.authorization import accessible_case_query, get_accessible_case
from app.utils.pagination import PageWindow, page_payload
from auth.utils import get_current_user, require_role
from database import get_db
from models import Case, CaseWallet, ForensicReport, LegalNotice, Transaction, User

router = APIRouter(prefix="/api/v1", tags=["Reports, Evidence, and Operations"])


def _digest(value: dict) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


@router.post("/cases/{case_id}/reports/{report_id}/revisions", status_code=status.HTTP_201_CREATED)
def create_revision(case_id: str, report_id: str, payload: ReportRevisionCreate,
                    db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    case = get_accessible_case(db, user, case_id, write=True)
    report = db.get(ForensicReport, report_id)
    if report is None or report.case_id != case.id:
        raise ApplicationError(code="REPORT_NOT_FOUND", message="Report not found", status_code=404)
    graph_snapshot_id, risk_result_id, prediction_id = payload.graph_snapshot_id, payload.risk_result_id, payload.prediction_id
    graph = db.get(GraphSnapshot, graph_snapshot_id) if graph_snapshot_id else None
    risk, prediction = (db.get(RiskResult, risk_result_id) if risk_result_id else None), (db.get(MLPrediction, prediction_id) if prediction_id else None)
    if graph and graph.case_id != case.id or risk and risk.case_id != case.id or prediction and prediction.case_id != case.id:
        raise ApplicationError(code="REPORT_EVIDENCE_SCOPE_MISMATCH", message="Selected report evidence is outside this case", status_code=409)
    revision = db.execute(select(func.coalesce(func.max(ReportRevision.revision), 0)).where(ReportRevision.report_id == report.id)).scalar_one() + 1
    manifest = {"case_id": case.id, "report_id": report.id, "report_sha256": report.sha256_content_hash,
        "graph_snapshot_id": graph_snapshot_id, "risk_result_id": risk_result_id, "prediction_id": prediction_id,
        "temporal_separation": "pre-report context and post-report activity are separately scoped evidence"}
    evidence_revision = db.execute(select(func.coalesce(func.max(EvidenceManifest.revision), 0)).where(EvidenceManifest.case_id == case.id)).scalar_one() + 1
    evidence = EvidenceManifest(case_id=case.id, revision=evidence_revision, object_ids=[], manifest_hash=_digest(manifest))
    db.add(evidence); db.flush()
    item = ReportRevision(report_id=report.id, revision=revision, case_id=case.id, graph_snapshot_id=graph_snapshot_id,
        risk_result_id=risk_result_id, ml_prediction_id=prediction_id, evidence_manifest={**manifest, "manifest_id": evidence.id},
        content_digest=report.sha256_content_hash, pdf_digest=report.sha256_content_hash, storage_uri=report.pdf_storage_path,
        report_cutoff=graph.generated_at if graph else report.generated_at, review_status="draft", dispatch_status="not_dispatched", created_by=user.id)
    db.add(item); db.flush()
    WorkflowRepository(db).audit(actor_id=user.id, case_id=case.id, action="report.revision.create", resource_type="report_revision",
                                 resource_id=item.id, details={"revision": revision, "manifest_hash": evidence.manifest_hash})
    db.commit()
    return {"id": item.id, "revision": item.revision, "manifest_hash": evidence.manifest_hash, "pdf_sha256": item.pdf_digest,
            "review_status": item.review_status, "legal_certification": "not automatic; human review/signature required"}


@router.get("/reports")
def reports(page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    query = accessible_case_query(db, user).join(ForensicReport, ForensicReport.case_id == Case.id)
    window, total = PageWindow(page, page_size), query.count()
    rows = query.with_entities(ForensicReport).order_by(ForensicReport.generated_at.desc()).offset(window.offset).limit(window.page_size).all()
    items = [{"id": row.id, "case_id": row.case_id, "reference": row.report_reference_number, "sha256": row.sha256_content_hash,
              "generated_at": row.generated_at.isoformat() if row.generated_at else None} for row in rows]
    return page_payload(items, total, window, reports=items)


@router.get("/reports/{report_id}/manifest")
def manifest(report_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    report = db.get(ForensicReport, report_id)
    if report is None: raise ApplicationError(code="REPORT_NOT_FOUND", message="Report not found", status_code=404)
    get_accessible_case(db, user, report.case_id)
    item = db.execute(select(ReportRevision).where(ReportRevision.report_id == report.id).order_by(ReportRevision.revision.desc())).scalar_one_or_none()
    if item is None: raise ApplicationError(code="REPORT_REVISION_NOT_FOUND", message="Immutable report revision not found", status_code=404)
    return {"report_id": report.id, "revision": item.revision, "manifest": item.evidence_manifest, "content_digest": item.content_digest, "pdf_digest": item.pdf_digest}


@router.get("/reports/{report_id}/download")
def download_report(report_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    report = db.get(ForensicReport, report_id)
    if report is None: raise ApplicationError(code="REPORT_NOT_FOUND", message="Report not found", status_code=404)
    get_accessible_case(db, user, report.case_id)
    path = Path(report.pdf_storage_path).resolve()
    if not path.is_file(): raise ApplicationError(code="REPORT_FILE_UNAVAILABLE", message="Report file is unavailable", status_code=503)
    actual = sha256(path.read_bytes()).hexdigest()
    if actual != report.sha256_content_hash:
        raise ApplicationError(code="REPORT_INTEGRITY_FAILED", message="Stored report digest does not match", status_code=409)
    return FileResponse(path, media_type="application/pdf", filename=path.name)


@router.post("/reports/{report_id}/verify")
def verify_report(report_id: str, digest: str | None = None, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    report = db.get(ForensicReport, report_id)
    if report is None: raise ApplicationError(code="REPORT_NOT_FOUND", message="Report not found", status_code=404)
    get_accessible_case(db, user, report.case_id)
    path = Path(report.pdf_storage_path).resolve()
    actual = sha256(path.read_bytes()).hexdigest() if path.is_file() else None
    return {"report_id": report.id, "stored_digest": report.sha256_content_hash, "actual_digest": actual,
            "verified": actual is not None and actual == report.sha256_content_hash and (digest is None or digest == actual)}


@router.get("/search")
def search(q: str = Query(min_length=2, max_length=120), page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100),
           db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    query = accessible_case_query(db, user).filter(or_(Case.external_complaint_id.ilike(f"%{q}%"), Case.fraud_typology.ilike(f"%{q}%"),
        Case.id.in_(db.query(CaseWallet.case_id).filter(CaseWallet.wallet_address.ilike(f"%{q}%"))),
        Case.id.in_(db.query(CaseWallet.case_id).join(Transaction, Transaction.from_address == CaseWallet.wallet_address).filter(Transaction.tx_hash.ilike(f"%{q}%")))))
    window, total = PageWindow(page, page_size), query.count()
    rows = query.order_by(Case.created_at.desc()).offset(window.offset).limit(window.page_size).all()
    return page_payload([{"type": "case", "id": row.id, "reference": row.external_complaint_id, "status": row.status} for row in rows], total, window)


@router.get("/audit-logs")
def audit_logs(case_id: str | None = None, action: str | None = None, page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100),
               db: Session = Depends(get_db), user: User = Depends(require_role("admin"))):
    query = db.query(AuditEvent)
    if case_id: get_accessible_case(db, user, case_id); query = query.filter(AuditEvent.case_id == case_id)
    if action: query = query.filter(AuditEvent.action == action)
    window, total = PageWindow(page, page_size), query.count()
    rows = query.order_by(AuditEvent.sequence.desc()).offset(window.offset).limit(window.page_size).all()
    return page_payload([{"id": row.id, "sequence": row.sequence, "actor_id": row.actor_id, "case_id": row.case_id, "action": row.action,
        "resource_type": row.resource_type, "occurred_at": row.occurred_at.isoformat(), "outcome": row.outcome} for row in rows], total, window)


@router.get("/notices/{notice_id}")
def get_notice(notice_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    notice = db.get(LegalNotice, notice_id)
    if notice is None: raise ApplicationError(code="NOTICE_NOT_FOUND", message="Notice not found", status_code=404)
    get_accessible_case(db, user, notice.case_id)
    return {"id": notice.id, "case_id": notice.case_id, "reference": notice.reference_number, "status": notice.status,
            "recipient": notice.dispatched_to_email, "dispatched_at": notice.dispatched_at.isoformat() if notice.dispatched_at else None,
            "legal_effect": "draft only until independently authorized and actually delivered"}


@router.patch("/notices/{notice_id}")
def review_notice(notice_id: str, payload: NoticeReview, db: Session = Depends(get_db), user: User = Depends(require_role("analyst", "admin"))):
    notice = db.get(LegalNotice, notice_id)
    if notice is None: raise ApplicationError(code="NOTICE_NOT_FOUND", message="Notice not found", status_code=404)
    get_accessible_case(db, user, notice.case_id, write=True)
    notice.status = payload.status.upper()
    WorkflowRepository(db).audit(actor_id=user.id, case_id=notice.case_id, action="notice.review", resource_type="legal_notice",
                                 resource_id=notice.id, details={"status": payload.status, "reason": payload.reason})
    db.commit(); return get_notice(notice_id, db, user)


@router.post("/notices/{notice_id}/dispatch")
def dispatch_notice(notice_id: str, payload: NoticeDispatch, request: Request, db: Session = Depends(get_db), user: User = Depends(require_role("admin"))):
    notice = db.get(LegalNotice, notice_id)
    if notice is None: raise ApplicationError(code="NOTICE_NOT_FOUND", message="Notice not found", status_code=404)
    get_accessible_case(db, user, notice.case_id, write=True)
    if notice.status != "READY_FOR_DISPATCH": raise ApplicationError(code="NOTICE_REVIEW_REQUIRED", message="Notice must be reviewed before dispatch", status_code=409)
    if not payload.simulate or not request.app.state.settings.fixture_data_enabled:
        raise ApplicationError(code="NOTICE_DISPATCH_UNAVAILABLE", message="No authorized real dispatch integration is configured", status_code=503)
    notice.status, notice.dispatched_at = "DISPATCH_SIMULATED", datetime.now(timezone.utc)
    WorkflowRepository(db).audit(actor_id=user.id, case_id=notice.case_id, action="notice.dispatch.simulated", resource_type="legal_notice",
                                 resource_id=notice.id, details={"reason": payload.reason, "simulated": True})
    db.commit(); return {"id": notice.id, "status": notice.status, "simulated": True, "funds_frozen": False}


@router.get("/admin/settings")
def admin_settings(request: Request, db: Session = Depends(get_db), user: User = Depends(require_role("admin"))):
    rows = db.query(PolicySetting).order_by(PolicySetting.effective_at.desc()).all()
    return {"providers": request.app.state.settings.provider_status(), "secrets_exposed": False,
            "policies": [{"id": row.id, "name": row.policy_name, "version": row.version, "effective_at": row.effective_at.isoformat(),
                          "thresholds": row.thresholds, "preferences": row.preferences} for row in rows]}


@router.post("/admin/settings", status_code=status.HTTP_201_CREATED)
def create_policy(payload: PolicyCreate, db: Session = Depends(get_db), user: User = Depends(require_role("admin"))):
    material = payload.model_dump(mode="json")
    item = PolicySetting(**payload.model_dump(), approved_by=user.id, content_hash=_digest(material))
    db.add(item); db.flush()
    WorkflowRepository(db).audit(actor_id=user.id, case_id=None, action="policy.create", resource_type="policy_setting",
                                 resource_id=item.id, details={"name": item.policy_name, "version": item.version})
    db.commit(); return {"id": item.id, "name": item.policy_name, "version": item.version, "content_hash": item.content_hash}
