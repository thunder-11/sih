"""Durable Phase 10 run progress and alert operations."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ApplicationError
from app.jobs.contracts import JobState
from app.persistence.models import AlertRecipient, AlertTrigger, AnalysisRun, BackgroundJob
from app.repositories.phase2 import DurableJobRepository, ProgressEventRepository
from app.repositories.phase3 import canonical_digest
from models import Alert


def job_payload(job: BackgroundJob) -> dict:
    return {"id": job.id, "operation": job.operation, "case_id": job.case_id, "state": job.state,
            "attempt": job.attempt, "max_attempts": job.max_attempts, "last_error_code": job.last_error_code,
            "next_attempt_at": job.next_attempt_at.isoformat(), "updated_at": job.updated_at.isoformat()}


def append_run_progress(session: Session, *, run: AnalysisRun, state: str, progress_percent: int,
                        message: str | None = None, metadata: dict | None = None):
    if state not in {item.value for item in JobState}:
        raise ApplicationError(code="INVALID_RUN_STATE", message="Unsupported analysis state", status_code=422)
    return ProgressEventRepository(session).append(run_id=run.id, state=state, progress_percent=progress_percent,
                                                   message=message, metadata=metadata)


def cancel_job(session: Session, job: BackgroundJob) -> None:
    if job.state in {JobState.COMPLETE.value, JobState.CANCELLED.value}:
        raise ApplicationError(code="JOB_NOT_CANCELLABLE", message="Completed or cancelled jobs cannot be cancelled", status_code=409)
    job.state, job.locked_by, job.lock_expires_at = JobState.CANCELLED.value, None, None
    job.updated_at = datetime.now(timezone.utc)


def retry_job(session: Session, job: BackgroundJob) -> None:
    if job.state not in {JobState.FAILED.value, JobState.CANCELLED.value, JobState.UNAVAILABLE.value, JobState.PARTIAL.value}:
        raise ApplicationError(code="JOB_NOT_RETRYABLE", message="Job is not in a retryable terminal state", status_code=409)
    job.state, job.last_error_code, job.locked_by, job.lock_expires_at = JobState.QUEUED.value, None, None, None
    job.next_attempt_at = job.updated_at = datetime.now(timezone.utc)


def create_alert(session: Session, *, case_id: str, user_id: str, alert_type: str, severity: str, title: str,
                 message: str, evidence_ids: list[str], fingerprint_material: dict, run_id: str | None = None,
                 prediction_id: str | None = None) -> tuple[Alert, bool]:
    fingerprint = canonical_digest({"case_id": case_id, "alert_type": alert_type, **fingerprint_material})
    existing_trigger = session.execute(select(AlertTrigger).where(AlertTrigger.fingerprint == fingerprint)).scalar_one_or_none()
    if existing_trigger:
        return session.get(Alert, existing_trigger.alert_id), False
    alert = Alert(case_id=case_id, user_id=user_id, alert_type=alert_type, severity=severity, title=title, message=message)
    session.add(alert); session.flush()
    session.add(AlertTrigger(alert_id=alert.id, fingerprint=fingerprint, run_id=run_id, prediction_id=prediction_id,
                             evidence_snapshot_ids=evidence_ids))
    session.add(AlertRecipient(alert_id=alert.id, user_id=user_id))
    session.flush()
    return alert, True
