"""Controller functions for measured, configuration-safe service health."""

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.metrics import operational_metrics
from app.new_ml.serving import model_status
from app.persistence.models import BackgroundJob, GraphProjectionCheckpoint


def liveness_payload(settings: Settings) -> dict:
    return {"status": "ok", "service": "sih26183-backend", "version": settings.app_version}


def readiness_payload(settings: Settings, db: Session | None = None) -> dict:
    providers = settings.provider_status()
    unavailable = [chain for chain, state in providers.items() if state != "configured"]
    database = {"state": "not_checked"}
    if db is not None:
        try:
            db.execute(text("SELECT 1"))
            database = {"state": "ready"}
        except Exception:
            database = {"state": "unavailable"}
    return {
        "status": "ready" if database["state"] == "ready" and (settings.fixture_data_enabled or not unavailable) else "degraded",
        "data_mode": settings.data_mode,
        "providers": providers,
        "database": database,
        "warnings": [f"Missing provider configuration: {', '.join(unavailable)}"] if unavailable else [],
    }


def system_status_payload(settings: Settings, db: Session) -> dict:
    readiness = readiness_payload(settings, db)
    queue_states = {state: count for state, count in db.execute(
        select(BackgroundJob.state, func.count()).group_by(BackgroundJob.state)
    )}
    checkpoint_states = {state: count for state, count in db.execute(
        select(GraphProjectionCheckpoint.state, func.count()).group_by(GraphProjectionCheckpoint.state)
    )}
    return {
        "status": readiness["status"],
        "measured_at": "request_time",
        "data_mode": settings.data_mode,
        "components": {
            "database": readiness["database"],
            "providers": {"state": "degraded" if readiness["warnings"] else "ready", "chains": readiness["providers"]},
            "queue": {"state": "ready" if not queue_states.get("failed") else "degraded", "jobs_by_state": queue_states},
            "graph_projection": {"state": "ready" if not checkpoint_states.get("failed") else "degraded", "checkpoints_by_state": checkpoint_states},
            "new_ml": model_status(db),
        },
        "warnings": readiness["warnings"],
        "limitations": ["Metrics are process-local measurements, not a distributed monitoring guarantee."],
    }


def metrics_payload() -> dict:
    return operational_metrics.snapshot()
