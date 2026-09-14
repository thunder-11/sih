"""Durable status, SSE replay, alert, and job-control contracts."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ApplicationError
from app.persistence.models import AnalysisRun, AnalysisRunEvent, BackgroundJob
from app.repositories.phase3 import WorkflowRepository
from app.security.authorization import get_accessible_case
from app.services.operations import cancel_job, job_payload, retry_job
from auth.utils import get_current_user
from database import SessionLocal, get_db
from models import User

router = APIRouter(prefix="/api/v1", tags=["Real-Time Status and Alerts"])


def _run_for_case(db: Session, case_id: str, run_id: str) -> AnalysisRun:
    run = db.get(AnalysisRun, run_id)
    if run is None or run.case_id != case_id:
        raise ApplicationError(code="ANALYSIS_RUN_NOT_FOUND", message="Analysis run not found", status_code=404)
    return run


@router.post("/cases/{case_id}/jobs/{job_id}/cancel")
def cancel(case_id: str, job_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    get_accessible_case(db, user, case_id, write=True)
    job = db.get(BackgroundJob, job_id)
    if job is None or job.case_id != case_id:
        raise ApplicationError(code="JOB_NOT_FOUND", message="Job not found", status_code=404)
    cancel_job(db, job); WorkflowRepository(db).audit(actor_id=user.id, case_id=case_id, action="job.cancelled", resource_type="background_job", resource_id=job.id)
    db.commit(); return job_payload(job)


@router.post("/cases/{case_id}/jobs/{job_id}/retry", status_code=status.HTTP_202_ACCEPTED)
def retry(case_id: str, job_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    get_accessible_case(db, user, case_id, write=True)
    job = db.get(BackgroundJob, job_id)
    if job is None or job.case_id != case_id:
        raise ApplicationError(code="JOB_NOT_FOUND", message="Job not found", status_code=404)
    retry_job(db, job); WorkflowRepository(db).audit(actor_id=user.id, case_id=case_id, action="job.retried", resource_type="background_job", resource_id=job.id)
    db.commit(); return job_payload(job)


@router.get("/cases/{case_id}/events")
async def events(case_id: str, last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
                 heartbeat_seconds: int = Query(15, ge=5, le=30), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    get_accessible_case(db, user, case_id)
    try: cursor = int(last_event_id or 0)
    except ValueError as exc: raise ApplicationError(code="INVALID_EVENT_CURSOR", message="Last-Event-ID must be a sequence number", status_code=400) from exc
    run_ids = [row.id for row in db.execute(select(AnalysisRun).where(AnalysisRun.case_id == case_id)).scalars()]
    async def stream():
        nonlocal cursor
        while True:
            with SessionLocal() as session:
                rows = list(session.execute(select(AnalysisRunEvent).where(AnalysisRunEvent.run_id.in_(run_ids), AnalysisRunEvent.sequence > cursor)
                    .order_by(AnalysisRunEvent.sequence)).scalars()) if run_ids else []
                for item in rows:
                    cursor = max(cursor, item.sequence)
                    body = {"event_id": item.id, "sequence": item.sequence, "type": "analysis.progress", "case_id": case_id,
                            "timestamp": item.occurred_at.isoformat(), "payload": {"state": item.state, "progress_percent": item.progress_percent,
                            "message": item.message, "metadata": item.metadata_json}}
                    yield f"id: {item.sequence}\nevent: analysis.progress\ndata: {json.dumps(body, default=str)}\n\n"
            yield f": heartbeat {datetime.now(timezone.utc).isoformat()}\n\n"
            await asyncio.sleep(heartbeat_seconds)
    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
