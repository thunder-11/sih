"""Phase 9 new-model inference, explanation, review, and lifecycle APIs."""

from sqlalchemy import func, select
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.errors import ApplicationError
from app.new_ml.serving import TRANSITIONS, _serving_spec, create_prediction, lifecycle_state, model_status, prediction_payload
from app.persistence.models import AnalystReview, MLPrediction, ModelLifecycleEvent, ModelPackage
from app.repositories.phase3 import WorkflowRepository
from app.schemas.phase9 import LifecycleTransition, PredictionCreate, ReviewCreate
from app.security.authorization import get_accessible_case
from auth.utils import get_current_user, require_role
from database import get_db
from models import User


router = APIRouter(prefix="/api/v1/ml", tags=["Fresh ML Inference and Review"])


@router.get("/models/status")
def get_model_status(db: Session = Depends(get_db), user: User = Depends(require_role("analyst", "admin"))):
    return model_status(db)


@router.post("/cases/{case_id}/predictions", status_code=status.HTTP_201_CREATED)
def predict(case_id: str, payload: PredictionCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    get_accessible_case(db, user, case_id, write=True)
    prediction = create_prediction(db, case_id=case_id, run_id=payload.analysis_run_id,
                                   feature_snapshot_id=payload.feature_snapshot_id, purpose=payload.purpose)
    WorkflowRepository(db).audit(actor_id=user.id, case_id=case_id, action="ml.prediction.created",
        resource_type="ml_prediction", resource_id=prediction.id, details={"model_version": prediction.model_version,
        "feature_snapshot_id": prediction.feature_snapshot_id, "decision": prediction.decision})
    db.commit()
    return prediction_payload(db, prediction)


@router.get("/cases/{case_id}/predictions/{prediction_id}")
def get_prediction(case_id: str, prediction_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    get_accessible_case(db, user, case_id)
    prediction = db.get(MLPrediction, prediction_id)
    if prediction is None or prediction.case_id != case_id:
        raise ApplicationError(code="PREDICTION_NOT_FOUND", message="Prediction not found", status_code=404)
    return prediction_payload(db, prediction)


@router.get("/cases/{case_id}/predictions/{prediction_id}/explanation")
def explanation(case_id: str, prediction_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return get_prediction(case_id, prediction_id, db, user)


@router.post("/cases/{case_id}/predictions/{prediction_id}/reviews", status_code=status.HTTP_201_CREATED)
def review_prediction(case_id: str, prediction_id: str, payload: ReviewCreate, db: Session = Depends(get_db),
                      user: User = Depends(require_role("investigator", "analyst", "admin"))):
    get_accessible_case(db, user, case_id, write=True)
    prediction = db.get(MLPrediction, prediction_id)
    if prediction is None or prediction.case_id != case_id:
        raise ApplicationError(code="PREDICTION_NOT_FOUND", message="Prediction not found", status_code=404)
    revision = db.execute(select(func.coalesce(func.max(AnalystReview.revision), 0)).where(AnalystReview.case_id == case_id)).scalar_one() + 1
    reason = payload.reason
    if payload.operational_priority:
        reason = f"{reason}\nOperational priority: {payload.operational_priority}. Evidence: {', '.join(payload.evidence_snapshot_ids) or 'none supplied'}"
    item = AnalystReview(case_id=case_id, prediction_id=prediction.id, revision=revision, reviewer_id=user.id,
                         disposition=payload.disposition, reason=reason, review_expires_at=payload.expires_at)
    db.add(item); db.flush()
    WorkflowRepository(db).audit(actor_id=user.id, case_id=case_id, action="ml.prediction.reviewed",
        resource_type="analyst_review", resource_id=item.id, details={"prediction_id": prediction.id,
        "disposition": item.disposition, "original_probability_preserved": True})
    db.commit()
    return {"id": item.id, "prediction_id": prediction.id, "revision": item.revision, "disposition": item.disposition,
            "reviewed_at": item.reviewed_at.isoformat(), "expires_at": item.review_expires_at.isoformat() if item.review_expires_at else None,
            "original_probability_preserved": True, "feedback_is_not_automatic_training_label": True}


@router.post("/models/{package_id}/lifecycle", status_code=status.HTTP_201_CREATED)
def transition_model(package_id: str, payload: LifecycleTransition, db: Session = Depends(get_db),
                     user: User = Depends(require_role("admin"))):
    package = db.get(ModelPackage, package_id)
    if package is None:
        raise ApplicationError(code="MODEL_PACKAGE_NOT_FOUND", message="Model package not found", status_code=404)
    current = lifecycle_state(db, package)
    if payload.transition not in TRANSITIONS:
        raise ApplicationError(code="INVALID_MODEL_TRANSITION", message="Unsupported model transition", status_code=422)
    if payload.transition == "production":
        if package.approved_at is None or package.approved_by is None:
            raise ApplicationError(code="MODEL_APPROVAL_REQUIRED", message="Production transition requires a separately approved package", status_code=409)
        if package.approved_by == user.id:
            raise ApplicationError(code="MODEL_SEPARATION_OF_DUTIES_REQUIRED", message="A different administrator must deploy an approved package", status_code=403)
        if current not in {"shadow", "canary", "validated"}:
            raise ApplicationError(code="INVALID_MODEL_TRANSITION", message="Production transition requires shadow, canary, or validated state", status_code=409)
        _serving_spec(package)
    if payload.transition == "canary" and current not in {"shadow", "validated"}:
        raise ApplicationError(code="INVALID_MODEL_TRANSITION", message="Canary transition requires shadow or validated state", status_code=409)
    if payload.transition == "rollback":
        prior = db.get(ModelPackage, payload.prior_package_id) if payload.prior_package_id else None
        if prior is None:
            raise ApplicationError(code="ROLLBACK_TARGET_REQUIRED", message="Rollback requires an existing compatible prior package", status_code=422)
        if prior.approved_at is None or prior.approved_by is None or prior.feature_schema_version != package.feature_schema_version:
            raise ApplicationError(code="ROLLBACK_TARGET_INCOMPATIBLE", message="Rollback target must be an approved compatible new package", status_code=409)
        _serving_spec(prior)
    event = ModelLifecycleEvent(package_id=package.id, prior_package_id=payload.prior_package_id, transition=payload.transition,
                                traffic_percent=payload.traffic_percent, reason=payload.reason, actor_id=user.id, scope=package.scope)
    db.add(event); db.flush()
    if payload.transition == "production":
        for active in db.execute(select(ModelPackage)).scalars():
            if active.id != package.id and lifecycle_state(db, active) == "production":
                db.add(ModelLifecycleEvent(package_id=active.id, prior_package_id=package.id, transition="retired", traffic_percent=0,
                    reason=f"Superseded by approved package {package.version}", actor_id=user.id, scope=active.scope))
    elif payload.transition == "rollback":
        db.add(ModelLifecycleEvent(package_id=prior.id, prior_package_id=package.id, transition="production", traffic_percent=100,
            reason=f"Atomic rollback from package {package.version}: {payload.reason}", actor_id=user.id, scope=prior.scope))
    WorkflowRepository(db).audit(actor_id=user.id, case_id=None, action="ml.model.lifecycle_transition",
        resource_type="ml_model_package", resource_id=package.id, details={"from": current, "to": payload.transition,
        "prior_package_id": payload.prior_package_id, "traffic_percent": payload.traffic_percent})
    db.commit()
    return {"id": event.id, "package_id": package.id, "from_state": current, "state": event.transition,
            "traffic_percent": event.traffic_percent, "occurred_at": event.occurred_at.isoformat(),
            "prior_predictions_preserved": True, "cache_invalidation_scope": "model/calibrator/schema version"}
