"""Measured ML monitoring and review-gated retraining requests."""

from decimal import Decimal

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ApplicationError
from app.persistence.models import DriftEvaluation, ModelPackage, RetrainingRequest
from app.repositories.phase3 import WorkflowRepository
from app.schemas.phase13 import DriftEvaluationCreate, RetrainingRequestCreate
from auth.utils import require_role
from database import get_db
from models import User


router = APIRouter(prefix="/api/v1/admin/ml", tags=["Operational ML Monitoring"])


def _evaluation_payload(item: DriftEvaluation) -> dict:
    return {
        "id": item.id, "model_package_id": item.model_package_id, "cohort": item.cohort,
        "window_start": item.window_start.isoformat(), "window_end": item.window_end.isoformat(),
        "metric_name": item.metric_name, "metric_value": str(item.metric_value),
        "sample_size": item.sample_size, "threshold": str(item.threshold), "triggered": item.triggered,
        "evaluated_at": item.evaluated_at.isoformat(),
        "interpretation": "A drift signal requires investigation; it is not proof of degraded model performance.",
    }


@router.get("/monitoring")
def monitoring(db: Session = Depends(get_db), user: User = Depends(require_role("admin"))):
    items = list(db.execute(select(DriftEvaluation).order_by(DriftEvaluation.evaluated_at.desc())).scalars())
    return {"items": [_evaluation_payload(item) for item in items], "total": len(items),
            "requirements": {"psi": "Two consecutive windows with adequate sample size are required before escalation.",
                             "retraining": "No request automatically trains, promotes, or deploys a model."}}


@router.post("/drift-evaluations", status_code=status.HTTP_201_CREATED)
def record_drift(payload: DriftEvaluationCreate, db: Session = Depends(get_db), user: User = Depends(require_role("admin"))):
    package = db.get(ModelPackage, payload.model_package_id)
    if package is None:
        raise ApplicationError(code="MODEL_PACKAGE_NOT_FOUND", message="Model package not found", status_code=404)
    triggered = payload.sample_size >= 1_000 and payload.metric_value > payload.threshold
    item = DriftEvaluation(model_package_id=package.id, cohort=payload.cohort, window_start=payload.window_start,
                           window_end=payload.window_end, metric_name=payload.metric_name,
                           metric_value=Decimal(str(payload.metric_value)), sample_size=payload.sample_size,
                           threshold=Decimal(str(payload.threshold)), triggered=triggered)
    db.add(item); db.flush()
    WorkflowRepository(db).audit(actor_id=user.id, case_id=None, action="ml.drift.evaluated",
        resource_type="ml_drift_evaluation", resource_id=item.id,
        details={"model_package_id": package.id, "metric": payload.metric_name, "triggered": triggered,
                 "trigger_reason": payload.trigger_reason})
    db.commit()
    return _evaluation_payload(item)


@router.post("/retraining-requests", status_code=status.HTTP_201_CREATED)
def request_retraining(payload: RetrainingRequestCreate, db: Session = Depends(get_db), user: User = Depends(require_role("admin"))):
    evaluation = db.get(DriftEvaluation, payload.drift_evaluation_id) if payload.drift_evaluation_id else None
    if payload.drift_evaluation_id and evaluation is None:
        raise ApplicationError(code="DRIFT_EVALUATION_NOT_FOUND", message="Drift evaluation not found", status_code=404)
    item = RetrainingRequest(drift_evaluation_id=evaluation.id if evaluation else None, requested_by=user.id,
                             reason=payload.reason, state="requested",
                             outcome={"dataset_proposal": payload.dataset_proposal, "scope": payload.scope,
                                      "automatic_training": False, "automatic_promotion": False})
    db.add(item); db.flush()
    WorkflowRepository(db).audit(actor_id=user.id, case_id=None, action="ml.retraining.requested",
        resource_type="ml_retraining_request", resource_id=item.id,
        details={"drift_evaluation_id": item.drift_evaluation_id, "dataset_proposal": payload.dataset_proposal})
    db.commit()
    return {"id": item.id, "state": item.state, "created_at": item.created_at.isoformat(),
            "automatic_training": False, "automatic_promotion": False,
            "next_steps": ["freeze eligible data and labels", "run fresh chronological evaluation", "obtain independent approval"]}
