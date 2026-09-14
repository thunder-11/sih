"""Phase 6 entity attribution, clustering, correlation and rule APIs."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.analytics.deterministic import POLICY_VERSION, persist_evaluation
from app.core.errors import ApplicationError
from app.persistence.models import (
    AddressRecord, AnalysisRun, Entity, EntityAddressAssertion, RiskResult, RuleFinding,
)
from app.schemas.phase6 import AnalyticsRequest, DirectoryImportRequest
from app.security.authorization import get_accessible_case
from app.services.attribution import attribute_run, cluster_payload
from app.services.correlation import related_cases
from app.utils.pagination import PageWindow, page_payload
from app.utils.addresses import validate_wallet
from auth.utils import get_current_user, require_role
from database import get_db
from models import User


router = APIRouter(prefix="/api/v1", tags=["Attribution and Deterministic Analytics"])


def _get_run_or_none(case_id: str, trace_id: str | None, db: Session) -> AnalysisRun | None:
    if trace_id:
        run = db.get(AnalysisRun, trace_id)
        if run is None or run.case_id != case_id or run.run_type != "trace":
            raise ApplicationError(code="TRACE_NOT_FOUND", message="Trace run not found for case", status_code=404)
        return run
    return db.execute(select(AnalysisRun).where(
        AnalysisRun.case_id == case_id, AnalysisRun.run_type == "trace"
    ).order_by(AnalysisRun.revision.desc()).limit(1)).scalar_one_or_none()


def _run(case_id: str, trace_id: str | None, db: Session) -> AnalysisRun:
    run = _get_run_or_none(case_id, trace_id, db)
    if run is None:
        raise ApplicationError(code="TRACE_REQUIRED", message="A completed evidence trace is required", status_code=422)
    return run


@router.post("/cases/{case_id}/analytics", status_code=status.HTTP_201_CREATED)
def analyze_case(case_id: str, payload: AnalyticsRequest, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    case = get_accessible_case(db, user, case_id, write=True)
    run = _run(case.id, payload.trace_id, db)
    existing = db.execute(select(RiskResult).where(
        RiskResult.run_id == run.id, RiskResult.rule_version == POLICY_VERSION
    )).scalar_one_or_none()
    result = existing or persist_evaluation(run, db)
    from models import Case
    case_obj = db.get(Case, case.id)
    if case_obj and result:
        case_obj.risk_score = result.score
        case_obj.risk_tier = (result.tier or "MEDIUM").upper()
        db.add(case_obj)
    db.commit()
    return {"id": result.id, "case_id": case.id, "trace_id": run.id, "risk_kind": "deterministic_composite",
            "score": result.score, "tier": result.tier, "policy_version": result.rule_version,
            "signals": result.signals, "ml_prediction": None, "idempotent_replay": existing is not None,
            "limitations": ["Deterministic rules are decision support and are separate from ML predictions."]}


@router.get("/cases/{case_id}/risk")
def case_risk(case_id: str, trace_id: str | None = None, db: Session = Depends(get_db),
              user: User = Depends(get_current_user)):
    case = get_accessible_case(db, user, case_id)
    run = _get_run_or_none(case.id, trace_id, db)
    if run is None:
        return {"case_id": case.id, "trace_id": None, "risk_kind": "deterministic_composite",
                "assessment_state": "not_assessed", "score": None, "tier": "unknown",
                "policy_version": POLICY_VERSION, "findings": [], "ml_predictions": []}
    result = db.execute(select(RiskResult).where(
        RiskResult.run_id == run.id, RiskResult.rule_version == POLICY_VERSION
    )).scalar_one_or_none()
    if result is None:
        try:
            result = persist_evaluation(run, db)
            from models import Case
            case_obj = db.get(Case, case.id)
            if case_obj and result:
                case_obj.risk_score = result.score
                case_obj.risk_tier = (result.tier or "MEDIUM").upper()
                db.add(case_obj)
            db.commit()
        except Exception:
            db.rollback()
            result = None
    if result is None:
        return {"case_id": case.id, "trace_id": run.id, "risk_kind": "deterministic_composite",
                "assessment_state": "not_assessed", "score": None, "tier": "unknown",
                "policy_version": POLICY_VERSION, "findings": [], "ml_predictions": []}
    findings = list(db.execute(select(RuleFinding).where(
        RuleFinding.run_id == run.id, RuleFinding.policy_version == POLICY_VERSION
    ).order_by(RuleFinding.rule_id)).scalars())
    return {"case_id": case.id, "trace_id": run.id, "risk_kind": "deterministic_composite",
            "assessment_state": "assessed", "score": result.score, "tier": result.tier,
            "policy_version": result.rule_version,
            "findings": [{"rule_id": item.rule_id, "assessment_state": item.assessment_state,
                          "contribution": item.contribution, "measured_values": item.measured_values,
                          "evidence_ids": item.evidence_snapshot_ids} for item in findings],
            "ml_predictions": [], "limitations": ["This score is not an ML probability."]}



@router.get("/cases/{case_id}/attributions")
def case_attributions(case_id: str, trace_id: str | None = None, db: Session = Depends(get_db),
                      user: User = Depends(get_current_user)):
    case = get_accessible_case(db, user, case_id)
    run = _get_run_or_none(case.id, trace_id, db)
    if run is None:
        return {"case_id": case.id, "run_id": None, "attributions": [], "nearest": None,
                "boundaries": [], "coverage": {"state": "not_started"},
                "limitations": ["Attribution confidence is a versioned heuristic and is not ML probability."]}
    return {"case_id": case.id, **attribute_run(run, db)}


@router.get("/cases/{case_id}/clusters")
def case_clusters(case_id: str, trace_id: str | None = None, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    case = get_accessible_case(db, user, case_id)
    run = _get_run_or_none(case.id, trace_id, db)
    if run is None:
        return {"case_id": case.id, "trace_id": None, "items": [], "total": 0, "page": 1, "page_size": 0}
    items = cluster_payload(run, db)
    return {"case_id": case.id, "trace_id": run.id, "items": items, "total": len(items), "page": 1, "page_size": len(items)}


@router.get("/cases/{case_id}/related")
def related(case_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return related_cases(get_accessible_case(db, user, case_id), db)


@router.get("/entities")
def entities(entity_type: str | None = None, page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100),
             db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    query = db.query(Entity)
    if entity_type:
        query = query.filter(func.lower(Entity.entity_type) == entity_type.lower())
    window, total = PageWindow(page, page_size), query.count()
    rows = query.order_by(Entity.canonical_name).offset(PageWindow(page, page_size).offset).limit(page_size).all()
    items = [{"id": row.id, "canonical_name": row.canonical_name, "entity_type": row.entity_type,
              "legal_name": row.legal_name, "service_type": row.service_type,
              "jurisdiction": row.jurisdiction, "status": row.status, "fiu_status": row.fiu_status,
              "fiu_source": row.fiu_source, "fiu_as_of": row.fiu_as_of.isoformat() if row.fiu_as_of else None,
              "contact_email": row.contact_email, "contact_source": row.contact_source,
              "contact_as_of": row.contact_as_of.isoformat() if row.contact_as_of else None,
              "address_count": db.query(EntityAddressAssertion).filter(EntityAddressAssertion.entity_id == row.id,
                                                                        EntityAddressAssertion.valid_to.is_(None)).count()}
             for row in rows]
    return page_payload(items, total, window, entities=items)


@router.get("/entities/{entity_id}")
def entity_detail(entity_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    entity = db.get(Entity, entity_id)
    if entity is None:
        raise ApplicationError(code="ENTITY_NOT_FOUND", message="Entity not found", status_code=404)
    assertions = list(db.execute(select(EntityAddressAssertion, AddressRecord).join(
        AddressRecord, AddressRecord.id == EntityAddressAssertion.address_id
    ).where(EntityAddressAssertion.entity_id == entity.id).order_by(EntityAddressAssertion.recorded_at.desc())).all())
    return {"id": entity.id, "canonical_name": entity.canonical_name, "legal_name": entity.legal_name,
            "entity_type": entity.entity_type, "service_type": entity.service_type,
            "jurisdiction": entity.jurisdiction, "status": entity.status, "fiu_status": entity.fiu_status,
            "fiu_source": entity.fiu_source, "fiu_as_of": entity.fiu_as_of.isoformat() if entity.fiu_as_of else None,
            "contact_email": entity.contact_email, "contact_source": entity.contact_source,
            "contact_as_of": entity.contact_as_of.isoformat() if entity.contact_as_of else None,
            "labels": [{"id": assertion.id, "address": address.canonical_address, "chain": address.chain,
                        "label": assertion.label, "confidence": str(assertion.confidence), "source": assertion.source,
                        "evidence_uri": assertion.evidence_uri, "review_status": assertion.review_status,
                        "reviewed_by": assertion.reviewed_by,
                        "reviewed_at": assertion.reviewed_at.isoformat() if assertion.reviewed_at else None,
                        "valid_from": assertion.valid_from.isoformat(),
                        "valid_to": assertion.valid_to.isoformat() if assertion.valid_to else None,
                        "recorded_at": assertion.recorded_at.isoformat()} for assertion, address in assertions]}


@router.post("/directory/imports", status_code=status.HTTP_201_CREATED)
def import_directory(payload: DirectoryImportRequest, request: Request, db: Session = Depends(get_db),
                     user: User = Depends(require_role("admin"))):
    now = datetime.now(timezone.utc)
    imported_entities = imported_labels = 0
    for item in payload.entities:
        entity = db.execute(select(Entity).where(
            func.lower(Entity.canonical_name) == item.canonical_name.lower(), Entity.entity_type == item.entity_type
        )).scalar_one_or_none()
        if entity is None:
            entity = Entity(canonical_name=item.canonical_name, legal_name=item.legal_name,
                            entity_type=item.entity_type, service_type=item.entity_type,
                            jurisdiction=item.jurisdiction, fiu_status=item.fiu_status,
                            fiu_source=item.fiu_source, fiu_as_of=item.fiu_as_of,
                            contact_email=item.contact_email, contact_source=item.contact_source,
                            contact_as_of=item.contact_as_of, status="active")
            db.add(entity); db.flush(); imported_entities += 1
        for label in item.labels:
            chain = label.chain.upper()
            validation = validate_wallet(label.address, chain, fixture_mode=request.app.state.settings.fixture_data_enabled)
            if not validation.valid or validation.canonical_address is None:
                raise ApplicationError(code="INVALID_DIRECTORY_ADDRESS", message="Directory label address is invalid",
                                       status_code=422, details={"chain": chain, "address": label.address,
                                                                "reason": validation.reason})
            canonical = validation.canonical_address
            address = db.execute(select(AddressRecord).where(
                AddressRecord.chain == chain, AddressRecord.canonical_address == canonical
            )).scalar_one_or_none()
            if address is None:
                address = AddressRecord(chain=chain, canonical_address=canonical, display_address=label.address)
                db.add(address); db.flush()
            material = {"entity_id": entity.id, "address_id": address.id, "label": label.label,
                        "confidence": str(label.confidence), "source": label.source,
                        "source_name": payload.source_name, "evidence_uri": label.evidence_uri or payload.source_uri,
                        "valid_from": label.valid_from.isoformat(), "valid_to": label.valid_to.isoformat() if label.valid_to else None}
            digest = hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()
            if db.execute(select(EntityAddressAssertion).where(EntityAddressAssertion.assertion_digest == digest)).scalar_one_or_none():
                continue
            db.add(EntityAddressAssertion(entity_id=entity.id, address_id=address.id, label=label.label,
                                           confidence=label.confidence, source=label.source,
                                           evidence_uri=label.evidence_uri or payload.source_uri,
                                           review_status="reviewed" if payload.reviewed else "unreviewed",
                                           reviewed_by=user.id if payload.reviewed else None,
                                           reviewed_at=now if payload.reviewed else None,
                                           valid_from=label.valid_from, valid_to=label.valid_to,
                                           recorded_at=now, assertion_digest=digest))
            imported_labels += 1
    db.commit()
    import_id = hashlib.sha256(json.dumps(payload.model_dump(mode="json"), sort_keys=True).encode()).hexdigest()
    return {"id": import_id, "status": "completed", "source_name": payload.source_name,
            "review_status": "reviewed" if payload.reviewed else "unreviewed",
            "imported_entities": imported_entities, "imported_labels": imported_labels, "errors": []}
