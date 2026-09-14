from datetime import datetime, timedelta, timezone

from app.core.metrics import operational_metrics
from app.persistence.models import ModelPackage
from database import SessionLocal


def _admin_headers(client):
    response = client.post("/api/v1/auth/login", json={"email": "admin@cfas.gov.in", "password": "cfas2026"})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_measured_readiness_status_and_admin_metrics(client, auth_headers):
    live = client.get("/health/live")
    ready = client.get("/health/ready")
    status = client.get("/api/v1/system/status", headers=auth_headers)
    metrics = client.get("/api/v1/system/metrics", headers=_admin_headers(client))

    assert live.status_code == ready.status_code == status.status_code == metrics.status_code == 200
    assert ready.json()["database"]["state"] == "ready"
    assert {"database", "queue", "graph_projection", "new_ml"} <= set(status.json()["components"])
    assert metrics.json()["measurement_scope"] == "current_process_since_start"
    assert metrics.json()["latency_ms"]["sample_size"] >= 1


def test_drift_recording_and_retraining_remain_review_gated(client):
    headers = _admin_headers(client)
    with SessionLocal() as session:
        package = ModelPackage(version="phase13-monitoring-v1", experiment_run_id="phase13-experiment",
            model_hash="a" * 64, preprocessing_version="phase13-preprocess", feature_schema_version="phase13-schema",
            calibrator_version="phase13-calibrator", calibrator_hash="b" * 64, target_definition={"task": "wallet_risk"},
            scope={}, state="shadow")
        session.add(package); session.commit(); package_id = package.id
    start = datetime.now(timezone.utc) - timedelta(days=1)
    response = client.post("/api/v1/admin/ml/drift-evaluations", headers=headers, json={
        "model_package_id": package_id, "cohort": {"chain": "BTC"}, "window_start": start.isoformat(),
        "window_end": datetime.now(timezone.utc).isoformat(), "metric_name": "psi", "metric_value": 0.21,
        "sample_size": 1000, "threshold": 0.20, "trigger_reason": "Two consecutive qualified windows require review.",
    })
    assert response.status_code == 201
    assert response.json()["triggered"] is True
    request = client.post("/api/v1/admin/ml/retraining-requests", headers=headers, json={
        "drift_evaluation_id": response.json()["id"], "reason": "Review qualified drift and fresh label maturity before a new training run.",
        "dataset_proposal": "approved fresh BTC wallet snapshot", "scope": {"chain": "BTC"},
    })
    assert request.status_code == 201
    assert request.json()["automatic_training"] is False
    assert client.get("/api/v1/admin/ml/monitoring", headers=headers).json()["total"] >= 1


def test_operational_metrics_are_bounded_and_observed_only():
    operational_metrics.record_request(200, 2.5)
    snapshot = operational_metrics.snapshot()
    assert snapshot["request_counts"]["total"] >= 1
    assert snapshot["latency_ms"]["p95"] is not None
