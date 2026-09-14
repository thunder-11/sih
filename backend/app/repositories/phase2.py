"""Repositories for append-only revisions and durable work records."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, TypeVar

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.jobs.contracts import JobState
from app.persistence.models import (
    AnalysisRunEvent,
    BackgroundJob,
    GraphSnapshot,
    OutboxEvent,
    ReportEvent,
    ReportRevision,
)


RevisionModel = TypeVar("RevisionModel", ReportEvent, GraphSnapshot, ReportRevision)
ACTIVE_JOB_STATES = {JobState.QUEUED.value, JobState.RETRYING.value, JobState.RUNNING.value}


class RevisionRepository:
    """Append revisions while holding the parent row on PostgreSQL."""

    def __init__(self, session: Session):
        self.session = session

    def append(self, model: type[RevisionModel], scope_field: str, scope_id: str, **values: Any) -> RevisionModel:
        scope_column = getattr(model, scope_field)
        # PostgreSQL serializes concurrent appenders on existing revision rows.
        latest = self.session.execute(
            select(model).where(scope_column == scope_id).order_by(model.revision.desc()).limit(1).with_for_update()
        ).scalar_one_or_none()
        revision = 1 if latest is None else latest.revision + 1
        record = model(**{scope_field: scope_id, "revision": revision, **values})
        self.session.add(record)
        self.session.flush()
        return record


class DurableJobRepository:
    """Database-backed queue with idempotent enqueue and lease-based claims."""

    def __init__(self, session: Session):
        self.session = session

    def enqueue_once(
        self,
        *,
        operation: str,
        idempotency_key: str,
        payload: dict[str, Any],
        case_id: str | None = None,
        max_attempts: int = 5,
        priority: int = 100,
        topic: str = "jobs.requested",
        now: datetime | None = None,
    ) -> tuple[BackgroundJob, bool]:
        now = now or datetime.now(timezone.utc)
        existing = self.session.execute(
            select(BackgroundJob).where(
                BackgroundJob.operation == operation,
                BackgroundJob.idempotency_key == idempotency_key,
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing, False

        job = BackgroundJob(
            operation=operation,
            idempotency_key=idempotency_key,
            case_id=case_id,
            state=JobState.QUEUED.value,
            payload=payload,
            max_attempts=max_attempts,
            priority=priority,
            next_attempt_at=now,
            created_at=now,
            updated_at=now,
        )
        try:
            with self.session.begin_nested():
                self.session.add(job)
                self.session.flush()
        except IntegrityError:
            # A concurrent requester won. Recover the canonical job.
            canonical = self.session.execute(
                select(BackgroundJob).where(
                    BackgroundJob.operation == operation,
                    BackgroundJob.idempotency_key == idempotency_key,
                )
            ).scalar_one()
            return canonical, False

        self.session.add(OutboxEvent(
            topic=topic,
            aggregate_type="background_job",
            aggregate_id=job.id,
            deduplication_key=f"job:{job.id}:requested",
            payload={"job_id": job.id, "operation": operation},
            next_attempt_at=now,
            occurred_at=now,
        ))
        self.session.flush()
        return job, True

    def reclaim_expired(self, *, now: datetime | None = None) -> int:
        """Return jobs abandoned by a dead worker to the retry queue."""
        now = now or datetime.now(timezone.utc)
        expired = list(self.session.execute(
            select(BackgroundJob).where(
                BackgroundJob.state == JobState.RUNNING.value,
                BackgroundJob.lock_expires_at.is_not(None),
                BackgroundJob.lock_expires_at <= now,
            ).with_for_update(skip_locked=True)
        ).scalars())
        for job in expired:
            job.state = JobState.RETRYING.value if job.attempt < job.max_attempts else JobState.FAILED.value
            job.next_attempt_at = now
            job.last_error_code = "WORKER_LEASE_EXPIRED"
            job.locked_by = None
            job.lock_expires_at = None
            job.updated_at = now
        self.session.flush()
        return len(expired)

    def claim_next(self, *, worker_id: str, lease_seconds: int = 60, now: datetime | None = None) -> BackgroundJob | None:
        now = now or datetime.now(timezone.utc)
        job = self.session.execute(
            select(BackgroundJob)
            .where(
                BackgroundJob.state.in_([JobState.QUEUED.value, JobState.RETRYING.value]),
                BackgroundJob.next_attempt_at <= now,
            )
            .order_by(BackgroundJob.priority.asc(), BackgroundJob.created_at.asc())
            .limit(1)
            .with_for_update(skip_locked=True)
        ).scalar_one_or_none()
        if job is None:
            return None
        job.state = JobState.RUNNING.value
        job.attempt += 1
        job.locked_by = worker_id
        job.lock_expires_at = now + timedelta(seconds=lease_seconds)
        job.updated_at = now
        self.session.flush()
        return job

    def complete(self, job: BackgroundJob, *, now: datetime | None = None) -> None:
        now = now or datetime.now(timezone.utc)
        job.state = JobState.COMPLETE.value
        job.locked_by = None
        job.lock_expires_at = None
        job.updated_at = now
        self.session.add(OutboxEvent(
            topic="jobs.completed",
            aggregate_type="background_job",
            aggregate_id=job.id,
            deduplication_key=f"job:{job.id}:completed",
            payload={"job_id": job.id, "operation": job.operation},
            next_attempt_at=now,
            occurred_at=now,
        ))

    def fail(
        self,
        job: BackgroundJob,
        *,
        error_code: str,
        retryable: bool,
        retry_delay_seconds: int = 30,
        now: datetime | None = None,
    ) -> None:
        now = now or datetime.now(timezone.utc)
        can_retry = retryable and job.attempt < job.max_attempts
        job.state = JobState.RETRYING.value if can_retry else JobState.FAILED.value
        job.next_attempt_at = now + timedelta(seconds=retry_delay_seconds) if can_retry else now
        job.last_error_code = error_code
        job.locked_by = None
        job.lock_expires_at = None
        job.updated_at = now


class OutboxRepository:
    """Leases outbox records for at-least-once delivery."""

    def __init__(self, session: Session):
        self.session = session

    def pending(self, *, limit: int = 100, now: datetime | None = None) -> list[OutboxEvent]:
        now = now or datetime.now(timezone.utc)
        return list(self.session.execute(
            select(OutboxEvent)
            .where(OutboxEvent.state.in_(["pending", "retrying"]), OutboxEvent.next_attempt_at <= now)
            .order_by(OutboxEvent.occurred_at.asc())
            .limit(limit)
            .with_for_update(skip_locked=True)
        ).scalars())

    def mark_published(self, event: OutboxEvent, *, now: datetime | None = None) -> None:
        event.state = "published"
        event.published_at = now or datetime.now(timezone.utc)
        event.last_error = None

    def mark_failed(self, event: OutboxEvent, error: str, *, now: datetime | None = None) -> None:
        now = now or datetime.now(timezone.utc)
        event.state = "retrying"
        event.attempt += 1
        event.last_error = error[:2000]
        event.next_attempt_at = now + timedelta(seconds=min(3600, 2 ** min(event.attempt, 10)))


class ProgressEventRepository:
    def __init__(self, session: Session):
        self.session = session

    def append(self, *, run_id: str, state: str, progress_percent: int, message: str | None = None,
               metadata: dict[str, Any] | None = None) -> AnalysisRunEvent:
        next_sequence = (self.session.execute(
            select(func.coalesce(func.max(AnalysisRunEvent.sequence), 0)).where(AnalysisRunEvent.run_id == run_id)
        ).scalar_one() + 1)
        event = AnalysisRunEvent(
            run_id=run_id,
            sequence=next_sequence,
            state=state,
            progress_percent=progress_percent,
            message=message,
            metadata_json=metadata or {},
        )
        self.session.add(event)
        self.session.flush()
        return event
