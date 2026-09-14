from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.jobs.contracts import JobState
from app.persistence.models import AnalysisRun, BackgroundJob
from app.services.operations import append_run_progress, cancel_job, create_alert, retry_job
from database import Base
from models import Case, User


@pytest.fixture
def operations_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _context(session):
    user = User(id="phase10-user", email="phase10@example.test", full_name="Phase 10", password_hash="unused", role="analyst", status="active")
    case = Case(external_complaint_id="phase10-case", reported_loss_amount=Decimal("1"), fraud_typology="test", agency_id="agency")
    session.add_all([user, case]); session.flush()
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    run = AnalysisRun(case_id=case.id, run_type="initial", revision=1, state="running", requested_by=user.id,
        report_event_id="report", root_address_ids=[], event_cutoff=now, cutoff_available_time=now, parameters={}, coverage={})
    job = BackgroundJob(operation="trace", idempotency_key="phase10-job", case_id=case.id, state="failed", payload={}, max_attempts=3)
    session.add_all([run, job]); session.flush()
    return case, user, run, job


def test_progress_replay_rows_and_cancel_retry_states_are_durable(operations_db):
    _, _, run, job = _context(operations_db)
    first = append_run_progress(operations_db, run=run, state="running", progress_percent=25, message="Fetching")
    second = append_run_progress(operations_db, run=run, state="partial", progress_percent=50, message="Provider delayed")
    assert (first.sequence, second.sequence) == (1, 2)
    retry_job(operations_db, job)
    assert job.state == JobState.QUEUED.value
    cancel_job(operations_db, job)
    assert job.state == JobState.CANCELLED.value


def test_alert_trigger_is_deduplicated_and_recipient_state_is_separate(operations_db):
    case, user, _, _ = _context(operations_db)
    kwargs = dict(case_id=case.id, user_id=user.id, alert_type="provider_failure", severity="high", title="Provider delayed",
        message="Partial evidence is available", evidence_ids=["evidence-1"], fingerprint_material={"provider": "test", "error": "timeout"})
    first, created = create_alert(operations_db, **kwargs)
    second, replay = create_alert(operations_db, **kwargs)
    assert created is True and replay is False and first.id == second.id
