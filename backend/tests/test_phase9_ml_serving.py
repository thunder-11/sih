from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.errors import ApplicationError
from app.new_ml.dataset import digest
from app.new_ml.serving import create_prediction, lifecycle_state, model_status, prediction_payload
from app.persistence.models import AnalysisRun, FeatureSnapshot, ModelLifecycleEvent, ModelPackage, MLPrediction
from database import Base
from models import Case, User


@pytest.fixture
def serving_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _context(session, *, package=True):
    now = datetime(2026, 1, 2, tzinfo=timezone.utc)
    user = User(id="phase9-admin", email="phase9@example.test", full_name="Phase 9", password_hash="unused",
                role="admin", status="active")
    case = Case(external_complaint_id="phase9-case", reported_loss_amount=Decimal("1"), fraud_typology="test", agency_id="agency")
    session.add_all([user, case]); session.flush()
    run = AnalysisRun(case_id=case.id, run_type="initial", revision=1, state="complete", requested_by=user.id,
                      report_event_id="report-event", root_address_ids=[], event_cutoff=now, cutoff_available_time=now,
                      parameters={}, stage="complete", coverage={})
    snapshot = FeatureSnapshot(subject_type="wallet", subject_id="wallet-1", schema_version="fresh-wallet-features-v1",
        temporal_partition="report_baseline", event_cutoff=now, availability_cutoff=now,
        values={"transfer_count": 3, "fan_out": 2}, evidence_ids=["evidence-1"],
        quality={"state": "complete"}, snapshot_hash="a" * 64)
    session.add_all([run, snapshot]); session.flush()
    if package:
        model = {"model_type": "linear_logistic", "intercept": -1, "coefficients": {"transfer_count": 0.5, "fan_out": -0.2},
                 "feature_schema_version": snapshot.schema_version}
        calibrator = {"type": "identity"}
        session.add(ModelPackage(version="fresh-phase9-v1", experiment_run_id="fresh-experiment", model_hash=digest(model),
            preprocessing_version="fresh-preprocess-v1", feature_schema_version=snapshot.schema_version,
            calibrator_version="identity-v1", calibrator_hash=digest(calibrator), target_definition={"task": "wallet_risk"},
            scope={"serving": {**model, "calibrator": calibrator, "review_threshold": 0.5}}, state="production",
            approved_by=user.id, approved_at=now))
        session.flush()
    return case, user, run, snapshot


def test_hash_verified_new_package_persists_explainable_prediction(serving_db):
    case, _, run, snapshot = _context(serving_db)
    prediction = create_prediction(serving_db, case_id=case.id, run_id=run.id, feature_snapshot_id=snapshot.id,
                                   purpose="investigator_support")
    payload = prediction_payload(serving_db, prediction)
    assert prediction.model_version == "fresh-phase9-v1"
    assert payload["risk_score"] > 0
    assert payload["contributing_signals"][0]["contribution_space"] == "log_odds"
    assert payload["evidence_snapshot_ids"] == ["evidence-1"]
    assert "not definitive proof" in payload["meaning"]


def test_unavailable_and_schema_or_coverage_gates_abstain_without_legacy_fallback(serving_db):
    case, _, run, snapshot = _context(serving_db, package=False)
    with pytest.raises(ApplicationError) as unavailable:
        create_prediction(serving_db, case_id=case.id, run_id=run.id, feature_snapshot_id=snapshot.id,
                          purpose="investigator_support")
    assert unavailable.value.code == "ML_UNAVAILABLE"
    assert model_status(serving_db)["legacy_ml_dependency"] is False
    assert serving_db.query(MLPrediction).count() == 0


def test_lifecycle_is_append_only_and_preserves_prior_prediction(serving_db):
    case, user, run, snapshot = _context(serving_db)
    prediction = create_prediction(serving_db, case_id=case.id, run_id=run.id, feature_snapshot_id=snapshot.id,
                                   purpose="investigator_support")
    package = serving_db.query(ModelPackage).one()
    event = ModelLifecycleEvent(package_id=package.id, transition="retired", traffic_percent=0,
                                reason="approved rollback drill", actor_id=user.id, scope=package.scope)
    serving_db.add(event); serving_db.flush()
    assert lifecycle_state(serving_db, package) == "retired"
    assert serving_db.get(MLPrediction, prediction.id).positive_class_probability == prediction.positive_class_probability
