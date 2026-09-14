from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.cache.keys import graph_cache_key
from app.persistence.models import AddressRecord, AnalysisRun, Asset, NormalizedTransaction, ProviderObservation, ReportEvent
from app.services.temporal_graph import GraphRequest, graph_payload, materialize_trace_graph
from database import Base
from models import Case


@pytest.fixture
def graph_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _case_with_evidence(session, hops=5):
    t0 = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
    case = Case(external_complaint_id="phase5", reported_loss_amount=Decimal("1"), fraud_typology="test", agency_id="agency")
    session.add(case); session.flush()
    report = ReportEvent(case_id=case.id, revision=1, report_timestamp=t0, reported_timezone="Z", original_timestamp=t0.isoformat(),
                         timestamp_precision="second", verification_state="verified", source_system="test", channel="test", payload_digest="a" * 64)
    session.add(report); session.flush(); case.primary_report_event_id = report.id
    addresses = [AddressRecord(chain="ETH", canonical_address=f"0x{i:040x}", display_address=f"0x{i:040x}") for i in range(hops + 1)]
    asset = Asset(chain="ETH", symbol="ETH", contract_address=None, decimals=18, asset_type="native")
    observation = ProviderObservation(provider="test", chain="ETH", request_fingerprint="b" * 64, available_time=t0 + timedelta(days=1),
                                      coverage_state="complete", parser_version="test", response_digest="c" * 64)
    session.add_all(addresses + [asset, observation]); session.flush()
    run = AnalysisRun(case_id=case.id, run_type="trace", revision=1, state="complete", report_event_id=report.id,
                      root_address_ids=[addresses[0].id], event_cutoff=t0 + timedelta(days=1), cutoff_available_time=t0 + timedelta(days=1),
                      parameters={"max_hops": min(hops, 6)}, stage="complete", checkpoint={}, coverage={"state": "complete"})
    session.add(run); session.flush()
    offsets = [-1, 0] + list(range(1, hops - 1))
    for index, offset in enumerate(offsets):
        session.add(NormalizedTransaction(chain="ETH", tx_hash=f"hash-{index}", transfer_index="0", from_address_id=addresses[index].id,
                                          to_address_id=addresses[index + 1].id, asset_id=asset.id, amount=Decimal("1.000001"), raw_amount="1000001",
                                          event_time=t0 + timedelta(seconds=offset), available_time=t0 + timedelta(days=1),
                                          provider_observation_id=observation.id, finality_state="final", status="confirmed"))
    session.commit()
    return case, run, report


def test_post_report_boundary_context_and_six_hops(graph_db):
    case, run, report = _case_with_evidence(graph_db, hops=6)
    exclusive = graph_payload(case, GraphRequest(trace_id=run.id, temporal_view="post_report", include_context=True), graph_db)
    inclusive = graph_payload(case, GraphRequest(trace_id=run.id, temporal_view="post_report", boundary="inclusive"), graph_db)
    assert exclusive["summary"]["selected_transfer_count"] == 4
    assert exclusive["summary"]["context_transfer_count"] == 2
    assert exclusive["summary"]["boundary_transfer_count"] == 1
    assert inclusive["summary"]["selected_transfer_count"] == 5
    assert all(edge["hop"] <= 6 for edge in exclusive["edges"])
    assert exclusive["summary"]["selected_amount"] == "4.000004"


def test_snapshot_and_cache_scope_are_immutable_and_revision_bound(graph_db):
    case, run, report = _case_with_evidence(graph_db)
    snapshot = materialize_trace_graph(graph_db, run_id=run.id)
    graph_db.commit()
    assert snapshot.node_count == 6
    assert snapshot.edge_count == 5
    first = graph_cache_key(case_id=case.id, trace_id=run.id, report_event_id=report.id, filters={"temporal_view": "post_report"})
    second = graph_cache_key(case_id=case.id, trace_id=run.id, report_event_id="another", filters={"temporal_view": "post_report"})
    assert first != second
    with pytest.raises(Exception) as mismatch:
        graph_payload(case, GraphRequest(trace_id=run.id, report_event_id=report.id, report_revision=2), graph_db)
    assert getattr(mismatch.value, "code", None) == "SNAPSHOT_CUTOFF_MISMATCH"
