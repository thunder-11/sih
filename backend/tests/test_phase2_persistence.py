from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from database import Base
from models import Case, User
from app.persistence.models import (
    AddressRecord,
    AnalysisRun,
    Asset,
    ImmutableRecordError,
    NormalizedTransaction,
    OutboxEvent,
    ProviderObservation,
    ReportEvent,
)
from app.repositories.phase2 import DurableJobRepository, RevisionRepository
from app.jobs.dispatcher import dispatch_outbox_batch


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        user = User(
            id="user-1",
            email="phase2@example.test",
            full_name="Phase Two",
            password_hash="not-used",
            role="analyst",
        )
        case = Case(
            id="case-1",
            external_complaint_id="NCRP-PHASE2-1",
            reported_loss_amount=Decimal("100.0000"),
            fraud_typology="investment_scam",
            assigned_officer_id=user.id,
        )
        session.add_all([user, case])
        session.commit()
        yield session


def utc(hour: int) -> datetime:
    return datetime(2026, 9, 12, hour, 30, 0, 123456, tzinfo=timezone.utc)


def test_revision_append_is_monotonic_and_immutable(db_session):
    repository = RevisionRepository(db_session)
    first = repository.append(
        ReportEvent,
        "case_id",
        "case-1",
        report_timestamp=utc(5),
        reported_timezone="Asia/Calcutta",
        source_system="NCRP",
        external_event_id="event-1",
        payload_digest="a" * 64,
        created_by="user-1",
    )
    second = repository.append(
        ReportEvent,
        "case_id",
        "case-1",
        report_timestamp=utc(6),
        reported_timezone="Asia/Calcutta",
        source_system="NCRP",
        external_event_id="event-2",
        payload_digest="b" * 64,
        created_by="user-1",
    )
    db_session.commit()

    assert (first.revision, second.revision) == (1, 2)
    second.reported_timezone = "UTC"
    with pytest.raises(ImmutableRecordError):
        db_session.commit()
    db_session.rollback()


def test_normalized_transaction_preserves_exact_amounts_and_times(db_session):
    source = AddressRecord(chain="ETH", canonical_address="0xsource", display_address="0xSource")
    destination = AddressRecord(chain="ETH", canonical_address="0xdest", display_address="0xDest")
    asset = Asset(chain="ETH", symbol="USDT", contract_address="0xtoken", decimals=6, asset_type="token")
    observation = ProviderObservation(
        provider="etherscan",
        chain="ETH",
        request_fingerprint="f" * 64,
        event_time=utc(5),
        available_time=utc(6),
        ingested_at=utc(7),
        coverage_state="complete",
        response_digest="e" * 64,
        parser_version="etherscan-v1",
        finality_state="finalized",
        confirmations=64,
        provenance={"endpoint": "account/txlist"},
    )
    db_session.add_all([source, destination, asset, observation])
    db_session.flush()
    transaction = NormalizedTransaction(
        chain="ETH",
        tx_hash="0xabc",
        transfer_index="log:4",
        from_address_id=source.id,
        to_address_id=destination.id,
        asset_id=asset.id,
        amount=Decimal("9007199254740993.123456"),
        raw_amount="9007199254740993123456",
        fiat_value=Decimal("9007199254740993.123456789"),
        fiat_currency="USD",
        valuation_source="price-snapshot-v1",
        valuation_time=utc(6),
        event_time=utc(5),
        available_time=utc(6),
        ingested_at=utc(7),
        provider_observation_id=observation.id,
        finality_state="finalized",
    )
    db_session.add(transaction)
    db_session.commit()
    db_session.expire_all()

    stored = db_session.execute(select(NormalizedTransaction)).scalar_one()
    assert stored.amount == Decimal("9007199254740993.123456")
    assert stored.fiat_value == Decimal("9007199254740993.123456789")
    assert stored.raw_amount == "9007199254740993123456"
    assert stored.event_time == utc(5)
    assert stored.available_time == utc(6)
    assert stored.ingested_at == utc(7)


def test_transaction_deduplicates_by_chain_hash_and_transfer_index(db_session):
    source = AddressRecord(chain="TRON", canonical_address="tsource", display_address="TSource")
    destination = AddressRecord(chain="TRON", canonical_address="tdest", display_address="TDest")
    asset = Asset(chain="TRON", symbol="USDT", contract_address="ttoken", decimals=6, asset_type="token")
    observation = ProviderObservation(
        provider="trongrid", chain="TRON", request_fingerprint="1" * 64,
        available_time=utc(6), ingested_at=utc(7), coverage_state="complete",
        response_digest="2" * 64, finality_state="finalized",
        parser_version="trongrid-v1",
    )
    db_session.add_all([source, destination, asset, observation])
    db_session.flush()
    values = dict(
        chain="TRON", tx_hash="tx-1", transfer_index="0", from_address_id=source.id,
        to_address_id=destination.id, asset_id=asset.id, amount="1.000001", raw_amount="1000001",
        event_time=utc(5), available_time=utc(6), provider_observation_id=observation.id,
    )
    db_session.add(NormalizedTransaction(**values))
    db_session.commit()
    db_session.add(NormalizedTransaction(**values))
    with pytest.raises(Exception):
        db_session.commit()
    db_session.rollback()


def test_job_enqueue_retry_and_outbox_are_idempotent(db_session):
    repository = DurableJobRepository(db_session)
    first, created = repository.enqueue_once(
        operation="trace_case", idempotency_key="trace:case-1:r1", payload={"case_id": "case-1"},
        case_id="case-1", now=utc(8),
    )
    duplicate, duplicate_created = repository.enqueue_once(
        operation="trace_case", idempotency_key="trace:case-1:r1", payload={"ignored": True},
        case_id="case-1", now=utc(8),
    )
    db_session.commit()
    assert created is True
    assert duplicate_created is False
    assert duplicate.id == first.id

    claimed = repository.claim_next(worker_id="worker-1", now=utc(8))
    assert claimed.id == first.id
    assert claimed.state == "running"
    assert claimed.attempt == 1
    repository.fail(claimed, error_code="PROVIDER_RATE_LIMITED", retryable=True, now=utc(8))
    assert claimed.state == "retrying"
    assert claimed.next_attempt_at == utc(8) + timedelta(seconds=30)
    db_session.commit()

    reclaimed_candidate = repository.claim_next(worker_id="worker-dead", now=utc(9))
    assert reclaimed_candidate.id == first.id
    assert repository.reclaim_expired(now=utc(9) + timedelta(seconds=61)) == 1
    assert reclaimed_candidate.state == "retrying"


def test_outbox_dispatch_retries_then_publishes(db_session):
    repository = DurableJobRepository(db_session)
    repository.enqueue_once(
        operation="normalize_wallet", idempotency_key="normalize:case-1:eth", payload={"chain": "ETH"},
        case_id="case-1", now=utc(8),
    )
    db_session.commit()

    def unavailable(topic, envelope):
        raise ConnectionError("broker unavailable")

    published, failed = dispatch_outbox_batch(db_session, unavailable)
    assert (published, failed) == (0, 1)
    db_session.commit()

    delivered = []
    published, failed = dispatch_outbox_batch(
        db_session, lambda topic, envelope: delivered.append((topic, envelope)), limit=10
    )
    # Backoff keeps the event unavailable until its next attempt time.
    assert (published, failed) == (0, 0)
    event = db_session.execute(select(OutboxEvent)).scalar_one()
    event.next_attempt_at = utc(8)
    db_session.commit()
    published, failed = dispatch_outbox_batch(
        db_session, lambda topic, envelope: delivered.append((topic, envelope)), limit=10
    )
    assert (published, failed) == (1, 0)
    assert delivered[0][1]["deduplication_key"].startswith("job:")


def test_analysis_run_requires_point_in_time_cutoff(db_session):
    report = RevisionRepository(db_session).append(
        ReportEvent, "case_id", "case-1", report_timestamp=utc(5),
        reported_timezone="UTC", source_system="NCRP", external_event_id="event-cutoff",
        payload_digest="c" * 64,
    )
    db_session.flush()
    run = AnalysisRun(
        case_id="case-1", run_type="trace", revision=1, state="queued",
        report_event_id=report.id, root_address_ids=["address-1"], event_cutoff=utc(5),
        cutoff_available_time=utc(8), parameters={"max_hops": 4},
    )
    db_session.add(run)
    db_session.commit()
    assert run.cutoff_available_time.tzinfo == timezone.utc
    run.state = "running"
    with pytest.raises(ImmutableRecordError):
        db_session.commit()
    db_session.rollback()
