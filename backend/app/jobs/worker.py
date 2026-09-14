"""In-process durable job worker.

Polls the database-backed queue (``DurableJobRepository``) and executes
handlers by ``operation``. Runs as a background thread started from the
FastAPI lifespan so a single ``uvicorn main:app`` is sufficient — no separate
worker process is required for local/dev/demo operation.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid

from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.providers.contracts import ProviderError
from app.repositories.phase2 import DurableJobRepository
from app.services.ingestion import process_ingestion_job
from app.services.trace_execution import process_trace_job

logger = logging.getLogger("sih26183.jobs.worker")

HANDLERS = {
    "trace.run": process_trace_job,
    "blockchain.ingest": process_ingestion_job,
}


def _claim_job(session: Session, worker_id: str):
    """Reclaim expired leases and claim the next job. Caller owns the session."""
    DurableJobRepository(session).reclaim_expired()
    session.commit()
    job = DurableJobRepository(session).claim_next(worker_id=worker_id, lease_seconds=120)
    session.commit()
    return job


def _run_handler(session: Session, settings: Settings, job) -> None:
    """Execute the claimed job's handler and commit its terminal state."""
    handler = HANDLERS.get(job.operation)
    try:
        if handler is None:
            DurableJobRepository(session).fail(job, error_code="UNKNOWN_OPERATION", retryable=False)
        else:
            handler(session, settings=settings, job=job)
        session.commit()
    except ProviderError:
        # Handlers call DurableJobRepository.fail(job, ...) before raising a
        # ProviderError, so the session already holds the correct terminal
        # state for this job — commit it rather than discarding that work.
        session.commit()
        logger.warning("job worker: provider error for operation=%s job_id=%s", job.operation, job.id)
    except Exception:
        session.rollback()
        logger.exception("job worker: handler failed for operation=%s job_id=%s", job.operation, job.id)
        DurableJobRepository(session).fail(job, error_code="WORKER_EXCEPTION", retryable=True)
        session.commit()


def run_worker_tick(session_factory: sessionmaker, settings: Settings, *, worker_id: str) -> bool:
    """Claim and execute at most one job. Returns True if a job was processed.

    Every code path below closes its session exactly once via ``with`` — a
    session left open on the (very common) "no job available" branch would
    leak a pooled connection every idle tick and eventually starve the API.
    """
    with session_factory() as session:
        try:
            job = _claim_job(session, worker_id)
        except Exception:
            session.rollback()
            logger.exception("job worker: claim phase failed")
            return False
        if job is None:
            return False
        _run_handler(session, settings, job)
    return True


def run_worker_loop(session_factory: sessionmaker, settings: Settings, stop_event: threading.Event,
                     *, poll_interval_seconds: float = 2.0) -> None:
    worker_id = f"inprocess-{uuid.uuid4().hex[:12]}"
    logger.info("job worker started: worker_id=%s", worker_id)
    while not stop_event.is_set():
        try:
            processed = run_worker_tick(session_factory, settings, worker_id=worker_id)
        except Exception:
            logger.exception("job worker: unexpected tick failure")
            processed = False
        if not processed:
            stop_event.wait(poll_interval_seconds)
    logger.info("job worker stopped: worker_id=%s", worker_id)


def start_worker_thread(session_factory: sessionmaker, settings: Settings) -> tuple[threading.Thread, threading.Event]:
    stop_event = threading.Event()
    thread = threading.Thread(
        target=run_worker_loop, args=(session_factory, settings, stop_event),
        name="sih26183-job-worker", daemon=True,
    )
    thread.start()
    return thread, stop_event
