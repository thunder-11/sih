"""Phase 7 fresh-ML data, label, feature, and split governance APIs."""

from collections import defaultdict
from datetime import datetime

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ApplicationError
from app.new_ml.contracts import task_contracts
from app.new_ml.dataset import create_dataset, digest
from app.new_ml.features import FEATURE_SCHEMA_VERSION, materialize_wallet_features, register_definitions
from app.new_ml.labels import add_review, append_label, eligibility
from app.new_ml.splitter import SplitSample, grouped_chronological_split
from app.persistence.models import DatasetSnapshot, DatasetSource, FeatureDefinition, LabelRevision, SplitManifest
from app.schemas.phase7 import DatasetCreate, FeatureMaterializeRequest, LabelCreate, LabelReviewCreate, SplitCreate
from app.utils.pagination import PageWindow, page_payload
from auth.utils import get_current_user, require_role
from database import get_db
from models import User


router = APIRouter(prefix="/api/v1/ml-data", tags=["Fresh ML Data and Features"])


@router.get("/contracts")
def contracts(user: User = Depends(get_current_user)):
    return {**task_contracts(), "feature_schema_version": FEATURE_SCHEMA_VERSION,
            "legacy_ml_dependency": False, "production_model_available": False}


@router.post("/datasets", status_code=status.HTTP_201_CREATED)
def create_dataset_route(payload: DatasetCreate, db: Session = Depends(get_db),
                         user: User = Depends(require_role("admin"))):
    snapshot = create_dataset(db, version=payload.version, purpose=payload.purpose, data_mode=payload.data_mode,
                              task_types=payload.task_types, period_start=payload.period_start, period_end=payload.period_end,
                              retention_policy=payload.retention_policy, access_scope=payload.access_scope,
                              manifest=payload.manifest, sources=[item.model_dump() for item in payload.sources])
    db.commit()
    return {"id": snapshot.id, "version": snapshot.version, "snapshot_hash": snapshot.snapshot_hash,
            "data_mode": snapshot.data_mode, "task_types": snapshot.task_types,
            "synthetic_excluded_from_quality_claims": snapshot.data_mode == "synthetic"}


@router.get("/datasets")
def list_datasets(page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100),
                  db: Session = Depends(get_db), user: User = Depends(require_role("analyst", "admin"))):
    query = db.query(DatasetSnapshot)
    window, total = PageWindow(page, page_size), query.count()
    rows = query.order_by(DatasetSnapshot.created_at.desc()).offset(window.offset).limit(window.page_size).all()
    items = [{"id": row.id, "version": row.version, "purpose": row.purpose, "data_mode": row.data_mode,
              "task_types": row.task_types, "snapshot_hash": row.snapshot_hash,
              "period_start": row.period_start.isoformat(), "period_end": row.period_end.isoformat(),
              "source_count": db.query(DatasetSource).filter(DatasetSource.dataset_snapshot_id == row.id).count()}
             for row in rows]
    return page_payload(items, total, window, datasets=items)


@router.post("/labels", status_code=status.HTTP_201_CREATED)
def create_label(payload: LabelCreate, db: Session = Depends(get_db),
                 user: User = Depends(require_role("analyst", "admin"))):
    label = append_label(db, subject_type=payload.subject_type, subject_id=payload.subject_id, task=payload.task,
                         target_class=payload.target_class, group_key=payload.group_key,
                         window_start=payload.observation_window_start, window_end=payload.observation_window_end,
                         label=payload.label, maturity=payload.maturity, known_at=payload.known_at,
                         evidence_snapshot_ids=payload.evidence_snapshot_ids, source_name=payload.source_name,
                         license_name=payload.license_name, source_confidence=payload.source_confidence,
                         rationale=payload.rationale, created_by=user.id, maturation_days=payload.maturation_days)
    db.commit()
    return {"id": label.id, "revision": label.revision, "label": label.label, "maturity": label.maturity,
            "matures_at": label.matures_at.isoformat() if label.matures_at else None, "training_eligible": False,
            "reason": "independent dual review and label cutoff are required"}


@router.post("/labels/{label_id}/reviews", status_code=status.HTTP_201_CREATED)
def review_label(label_id: str, payload: LabelReviewCreate, db: Session = Depends(get_db),
                 user: User = Depends(require_role("analyst", "admin"))):
    label = db.get(LabelRevision, label_id)
    if label is None:
        raise ApplicationError(code="LABEL_NOT_FOUND", message="Label revision not found", status_code=404)
    review = add_review(db, label_revision=label, reviewer_id=user.id, decision=payload.decision, reason=payload.reason)
    db.commit()
    return {"id": review.id, "label_revision_id": label.id, "reviewer_id": user.id,
            "decision": review.decision, "adjudicated_at": review.adjudicated_at.isoformat()}


@router.get("/labels/{label_id}/eligibility")
def label_eligibility(label_id: str, label_cutoff: datetime, db: Session = Depends(get_db),
                      user: User = Depends(require_role("analyst", "admin"))):
    label = db.get(LabelRevision, label_id)
    if label is None:
        raise ApplicationError(code="LABEL_NOT_FOUND", message="Label revision not found", status_code=404)
    return {"label_revision_id": label.id, **eligibility(db, label, label_cutoff=label_cutoff)}


@router.get("/features/definitions")
def feature_definitions(db: Session = Depends(get_db), user: User = Depends(require_role("analyst", "admin"))):
    rows = list(db.execute(select(FeatureDefinition).where(
        FeatureDefinition.version == FEATURE_SCHEMA_VERSION
    ).order_by(FeatureDefinition.name)).scalars())
    return {"schema_version": FEATURE_SCHEMA_VERSION, "items": [_definition(item) for item in rows]}


@router.post("/features/definitions/register", status_code=status.HTTP_201_CREATED)
def register_feature_definitions(db: Session = Depends(get_db), user: User = Depends(require_role("admin"))):
    rows = register_definitions(db); db.commit()
    return {"schema_version": FEATURE_SCHEMA_VERSION, "items": [_definition(item) for item in rows]}


def _definition(row: FeatureDefinition) -> dict:
    return {"id": row.id, "name": row.name, "family": row.family, "units": row.units,
            "source": row.source, "aggregation": row.aggregation, "missing_behavior": row.missing_behavior,
            "cutoff_policy": row.cutoff_policy, "definition_hash": row.definition_hash}


@router.post("/features/materialize", status_code=status.HTTP_201_CREATED)
def materialize_features(payload: FeatureMaterializeRequest, db: Session = Depends(get_db),
                         user: User = Depends(require_role("analyst", "admin"))):
    snapshot = materialize_wallet_features(db, subject_address_id=payload.subject_address_id,
        mode=payload.temporal_mode, report_time=payload.report_time, event_cutoff=payload.event_cutoff,
        knowledge_cutoff=payload.knowledge_cutoff, exclude_complaint_id=payload.exclude_complaint_id)
    db.commit()
    return {"id": snapshot.id, "subject_type": snapshot.subject_type, "subject_id": snapshot.subject_id,
            "schema_version": snapshot.schema_version, "temporal_mode": snapshot.temporal_partition,
            "event_cutoff": snapshot.event_cutoff.isoformat(), "knowledge_cutoff": snapshot.availability_cutoff.isoformat(),
            "max_feature_event_time": snapshot.max_event_time.isoformat() if snapshot.max_event_time else None,
            "max_feature_available_at": snapshot.max_available_time.isoformat() if snapshot.max_available_time else None,
            "values": snapshot.values, "evidence_ids": snapshot.evidence_ids, "quality": snapshot.quality,
            "snapshot_hash": snapshot.snapshot_hash}


@router.post("/splits", status_code=status.HTTP_201_CREATED)
def create_split(payload: SplitCreate, db: Session = Depends(get_db), user: User = Depends(require_role("admin"))):
    dataset = db.get(DatasetSnapshot, payload.dataset_snapshot_id)
    if dataset is None:
        raise ApplicationError(code="DATASET_NOT_FOUND", message="Dataset snapshot not found", status_code=404)
    if db.execute(select(SplitManifest).where(SplitManifest.version == payload.version)).scalar_one_or_none():
        raise ApplicationError(code="SPLIT_VERSION_CONFLICT", message="Split version already exists", status_code=409)
    revisions = list(db.execute(select(LabelRevision).where(LabelRevision.known_at <= payload.label_cutoff)
                                .order_by(LabelRevision.subject_type, LabelRevision.subject_id, LabelRevision.revision.desc())).scalars())
    latest = {}
    for row in revisions:
        latest.setdefault((row.subject_type, row.subject_id, row.task, row.target_class), row)
    samples, ineligible = [], []
    for row in latest.values():
        state = eligibility(db, row, label_cutoff=payload.label_cutoff)
        if state["eligible"]:
            samples.append(SplitSample(sample_id=row.id, observed_at=row.observation_window_end,
                                       label_known_at=row.known_at, group_key=row.group_key, label=row.label))
        else:
            ineligible.append({"id": row.id, "reasons": state["reasons"]})
    audit = grouped_chronological_split(samples, label_cutoff=payload.label_cutoff,
                                        purge_days=payload.purge_days, embargo_days=payload.embargo_days)
    manifest_hash = digest({"dataset_snapshot_id": dataset.id, "version": payload.version,
                            "rules": audit["rules"], "membership": audit["membership"],
                            "class_counts": audit["class_counts"]})
    manifest = SplitManifest(dataset_snapshot_id=dataset.id, version=payload.version,
                             temporal_rules={**audit["rules"], "label_maturity_days": 90},
                             group_rules={"group_key": "campaign_or_related_wallet", "strict_group_holdout": True,
                                          "ineligible_labels": ineligible},
                             purge_duration=f"P{payload.purge_days}D", embargo_duration=f"P{payload.embargo_days}D",
                             membership_uri=f"db://ml_split_manifests/{payload.version}/membership",
                             membership=audit["membership"], class_counts=audit["class_counts"],
                             manifest_hash=manifest_hash)
    db.add(manifest); db.commit()
    return {"id": manifest.id, "version": manifest.version, "manifest_hash": manifest.manifest_hash,
            "class_counts": manifest.class_counts, "membership_count": len(manifest.membership),
            "excluded": audit["excluded"] + ineligible}
