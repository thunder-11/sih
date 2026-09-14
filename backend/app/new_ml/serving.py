"""Hash-verified, fresh-model-only inference and immutable review helpers."""

from __future__ import annotations

import math
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import ApplicationError
from app.new_ml.dataset import digest
from app.persistence.models import (
    AnalystReview, AnalysisRun, FeatureSnapshot, MLPrediction, ModelLifecycleEvent,
    ModelPackage, PredictionExplanation,
)


DEPLOYABLE_STATES = {"shadow", "canary", "production"}
TRANSITIONS = {"shadow", "canary", "production", "rollback", "retired", "blocked"}


def lifecycle_state(session: Session, package: ModelPackage) -> str:
    event = session.execute(select(ModelLifecycleEvent).where(ModelLifecycleEvent.package_id == package.id)
                            .order_by(ModelLifecycleEvent.occurred_at.desc(), ModelLifecycleEvent.id.desc()).limit(1)).scalar_one_or_none()
    return event.transition if event else package.state


def model_status(session: Session) -> dict:
    packages = list(session.execute(select(ModelPackage).order_by(ModelPackage.created_at.desc())).scalars())
    items = [{"id": package.id, "version": package.version, "state": lifecycle_state(session, package),
              "feature_schema_version": package.feature_schema_version, "calibrator_version": package.calibrator_version,
              "scope": package.scope, "approved_at": package.approved_at.isoformat() if package.approved_at else None}
             for package in packages]
    production = next((item for item in items if item["state"] == "production"), None)
    return {"state": "active" if production else "unavailable", "active_package": production,
            "packages": items, "legacy_ml_dependency": False,
            "meaning": "New ML decision support only; it is not proof of fraud or a directive to enforce an action."}


def _serving_spec(package: ModelPackage) -> dict:
    serving = package.scope.get("serving") if isinstance(package.scope, dict) else None
    if not isinstance(serving, dict) or serving.get("model_type") != "linear_logistic":
        raise ApplicationError(code="MODEL_PACKAGE_UNAVAILABLE", message="Model package has no supported verified serving specification", status_code=503)
    if serving.get("feature_schema_version") != package.feature_schema_version:
        raise ApplicationError(code="MODEL_SCHEMA_MISMATCH", message="Model package feature schema is incompatible", status_code=503)
    model_material = {"model_type": serving["model_type"], "intercept": serving.get("intercept", 0),
                      "coefficients": serving.get("coefficients", {}), "feature_schema_version": serving["feature_schema_version"]}
    calibrator = serving.get("calibrator", {"type": "identity"})
    if digest(model_material) != package.model_hash or digest(calibrator) != package.calibrator_hash:
        raise ApplicationError(code="MODEL_HASH_VERIFICATION_FAILED", message="Model package hash verification failed", status_code=503)
    return serving


def _flatten(values: dict) -> dict:
    if "baseline" in values and "post_report" in values:
        return {**{f"baseline.{k}": v for k, v in values["baseline"].items()},
                **{f"post_report.{k}": v for k, v in values["post_report"].items()}}
    return dict(values)


def _active_package(session: Session, snapshot: FeatureSnapshot) -> ModelPackage:
    candidates = [item for item in session.execute(select(ModelPackage)).scalars()
                  if lifecycle_state(session, item) == "production" and item.feature_schema_version == snapshot.schema_version]
    if not candidates:
        raise ApplicationError(code="ML_UNAVAILABLE", message="No approved compatible new model package is active", status_code=503,
                               details={"fallback": "deterministic findings and analyst review remain available", "legacy_ml_used": False})
    return sorted(candidates, key=lambda row: row.created_at, reverse=True)[0]


def create_prediction(session: Session, *, case_id: str, run_id: str, feature_snapshot_id: str, purpose: str) -> MLPrediction:
    run = session.get(AnalysisRun, run_id)
    if run is None or run.case_id != case_id:
        raise ApplicationError(code="ANALYSIS_RUN_NOT_FOUND", message="Analysis run is not available for this case", status_code=404)
    snapshot = session.get(FeatureSnapshot, feature_snapshot_id)
    if snapshot is None:
        raise ApplicationError(code="FEATURES_PENDING", message="Eligible materialized features are required before inference", status_code=202)
    if snapshot.quality.get("state") != "complete":
        raise ApplicationError(code="ML_ABSTAINED", message="Feature coverage is insufficient for a scored prediction", status_code=422,
                               details={"abstention_reason": "insufficient_feature_coverage"})
    if snapshot.event_cutoff > run.event_cutoff or snapshot.availability_cutoff > run.cutoff_available_time:
        raise ApplicationError(code="SNAPSHOT_CUTOFF_MISMATCH", message="Feature snapshot exceeds the investigation run cutoff", status_code=409)
    package = _active_package(session, snapshot)
    spec, values = _serving_spec(package), _flatten(snapshot.values)
    coefficients = spec.get("coefficients", {})
    missing = [name for name in coefficients if name not in values or values[name] is None]
    if missing:
        raise ApplicationError(code="ML_ABSTAINED", message="Required model features are unavailable", status_code=422,
                               details={"abstention_reason": "required_feature_missing", "features": missing})
    try:
        terms = [(name, float(values[name]), float(weight)) for name, weight in coefficients.items()]
    except (TypeError, ValueError) as exc:
        raise ApplicationError(code="ML_ABSTAINED", message="Feature values are outside the model input contract", status_code=422,
                               details={"abstention_reason": "out_of_distribution_input"}) from exc
    if any(not math.isfinite(value) or abs(value) > 1e12 for _, value, _ in terms):
        raise ApplicationError(code="ML_ABSTAINED", message="Feature values are outside the supported distribution", status_code=422,
                               details={"abstention_reason": "out_of_distribution_input"})
    logit = float(spec.get("intercept", 0)) + sum(value * weight for _, value, weight in terms)
    probability = 1 / (1 + math.exp(-max(-60, min(60, logit))))
    calibrator = spec.get("calibrator", {"type": "identity"})
    if calibrator.get("type") == "platt":
        probability = 1 / (1 + math.exp(-max(-60, min(60, float(calibrator["a"]) * logit + float(calibrator["b"])))))
    elif calibrator.get("type") != "identity":
        raise ApplicationError(code="MODEL_CALIBRATOR_UNAVAILABLE", message="Unsupported calibrated probability contract", status_code=503)
    ranked = sorted(((name, value * weight, value) for name, value, weight in terms), key=lambda item: abs(item[1]), reverse=True)
    revision = session.execute(select(func.coalesce(func.max(MLPrediction.revision), 0)).where(MLPrediction.case_id == case_id)).scalar_one() + 1
    decision = "review" if probability >= float(spec.get("review_threshold", 0.5)) else "monitor"
    prediction = MLPrediction(case_id=case_id, run_id=run.id, revision=revision, model_version=package.version,
        calibrator_version=package.calibrator_version, feature_snapshot_id=snapshot.id, risk_score=round(probability * 100),
        calibrated_confidence=Decimal(str(probability)), positive_class_probability=Decimal(str(probability)), decision=decision,
        purpose=purpose, event_cutoff=snapshot.event_cutoff, availability_cutoff=snapshot.availability_cutoff,
        status="shadow" if lifecycle_state(session, package) != "production" else "advisory",
        contributing_features=[name for name, _, _ in ranked[:10]], evidence_snapshot_ids=snapshot.evidence_ids,
        limitations=["Decision support only; not proof of fraud.", "Operational action requires authorized human review.",
                     "Prediction is pinned to the recorded package, feature snapshot, and cutoffs."])
    session.add(prediction); session.flush()
    for rank, (name, contribution, value) in enumerate(ranked[:10], start=1):
        session.add(PredictionExplanation(prediction_id=prediction.id, feature_name=name, measured_value={"value": value},
            contribution=Decimal(str(contribution)), contribution_space="log_odds", direction="increases_risk" if contribution >= 0 else "reduces_risk",
            temporal_partition=snapshot.temporal_partition, evidence_snapshot_ids=snapshot.evidence_ids, rank=rank))
    session.flush()
    return prediction


def prediction_payload(session: Session, prediction: MLPrediction) -> dict:
    explanations = list(session.execute(select(PredictionExplanation).where(PredictionExplanation.prediction_id == prediction.id)
                                        .order_by(PredictionExplanation.rank)).scalars())
    review = session.execute(select(AnalystReview).where(AnalystReview.prediction_id == prediction.id)
                            .order_by(AnalystReview.reviewed_at.desc()).limit(1)).scalar_one_or_none()
    return {"id": prediction.id, "case_id": prediction.case_id, "risk_score": prediction.risk_score,
            "calibrated_confidence": str(prediction.calibrated_confidence), "positive_class_probability": str(prediction.positive_class_probability),
            "decision": prediction.decision, "status": prediction.status, "abstention_reason": prediction.abstention_reason,
            "model_version": prediction.model_version, "calibrator_version": prediction.calibrator_version,
            "feature_snapshot_id": prediction.feature_snapshot_id, "event_cutoff": prediction.event_cutoff.isoformat(),
            "availability_cutoff": prediction.availability_cutoff.isoformat(), "evidence_snapshot_ids": prediction.evidence_snapshot_ids,
            "limitations": prediction.limitations, "contributing_signals": [{"feature_name": item.feature_name, "measured_value": item.measured_value,
                "contribution": str(item.contribution), "contribution_space": item.contribution_space, "direction": item.direction,
                "temporal_partition": item.temporal_partition, "evidence_snapshot_ids": item.evidence_snapshot_ids, "rank": item.rank} for item in explanations],
            "review_state": None if review is None else {"disposition": review.disposition, "reviewed_at": review.reviewed_at.isoformat(),
                "expires_at": review.review_expires_at.isoformat() if review.review_expires_at else None},
            "meaning": "New ML decision support only; it is not definitive proof of fraud."}
