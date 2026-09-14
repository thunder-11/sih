from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.analytics.deterministic import POLICY_VERSION, evaluate, persist_evaluation
from app.persistence.models import (
    AddressRecord, AnalysisRun, Asset, Entity, EntityAddressAssertion,
    NormalizedTransaction, ProtocolContract, ProviderObservation, ReportEvent,
)
from app.services.attribution import attribute_run
from database import Base
from models import Case


@pytest.fixture
def analytics_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _evidence(session):
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    case = Case(external_complaint_id="phase6", reported_loss_amount=Decimal("10"), fraud_typology="test", agency_id="agency")
    session.add(case); session.flush()
    report = ReportEvent(case_id=case.id, revision=1, report_timestamp=t0, reported_timezone="Z",
                         original_timestamp=t0.isoformat(), timestamp_precision="second", verification_state="verified",
                         source_system="test", channel="test", payload_digest="a" * 64)
    addresses = [AddressRecord(chain="ETH", canonical_address=f"0x{i:040x}", display_address=f"0x{i:040x}") for i in range(6)]
    asset = Asset(chain="ETH", symbol="ETH", decimals=18, asset_type="native")
    observation = ProviderObservation(provider="test", chain="ETH", request_fingerprint="b" * 64,
                                      available_time=t0 + timedelta(days=1), coverage_state="complete",
                                      parser_version="test", response_digest="c" * 64)
    session.add_all([report, *addresses, asset, observation]); session.flush()
    case.primary_report_event_id = report.id
    run = AnalysisRun(case_id=case.id, run_type="trace", revision=1, state="complete", report_event_id=report.id,
                      root_address_ids=[addresses[0].id], event_cutoff=t0 + timedelta(hours=2),
                      cutoff_available_time=t0 + timedelta(days=1), parameters={"max_hops": 4},
                      stage="complete", checkpoint={}, coverage={"state": "complete"})
    session.add(run); session.flush()
    return t0, case, run, addresses, asset, observation


def _tx(session, observation, asset, source, target, number, moment, amount="1"):
    row = NormalizedTransaction(chain="ETH", tx_hash=f"tx-{number}", transfer_index="0",
                                from_address_id=source.id, to_address_id=target.id, asset_id=asset.id,
                                amount=Decimal(amount), raw_amount=amount, event_time=moment,
                                available_time=observation.available_time, provider_observation_id=observation.id,
                                finality_state="final", status="confirmed")
    session.add(row); session.flush()
    return row


def test_nearest_exact_vasp_and_mixer_boundary_do_not_invent_exit(analytics_db):
    t0, case, run, addresses, asset, observation = _evidence(analytics_db)
    direct = _tx(analytics_db, observation, asset, addresses[0], addresses[1], 1, t0 + timedelta(minutes=1))
    _tx(analytics_db, observation, asset, addresses[0], addresses[2], 2, t0 + timedelta(minutes=2))
    _tx(analytics_db, observation, asset, addresses[2], addresses[3], 3, t0 + timedelta(minutes=3))
    entity = Entity(entity_type="vasp", canonical_name="Evidence Exchange", jurisdiction="India")
    analytics_db.add(entity); analytics_db.flush()
    analytics_db.add(EntityAddressAssertion(entity_id=entity.id, address_id=addresses[1].id, label="deposit",
                                             confidence=Decimal("1"), source="reviewed-registry",
                                             evidence_uri="https://registry.example/item", valid_from=t0 - timedelta(days=1),
                                             review_status="reviewed", recorded_at=t0, assertion_digest="d" * 64))
    analytics_db.add(ProtocolContract(protocol_name="Privacy Pool", protocol_type="mixer", chain="ETH",
                                      contract_address=addresses[2].canonical_address,
                                      valid_from=t0 - timedelta(days=1), provenance={"source": "reviewed"}))
    analytics_db.flush()
    result = attribute_run(run, analytics_db)
    assert result["nearest"]["score"] == 95
    assert result["nearest"]["path"][0]["transfer_id"] == direct.id
    assert result["boundaries"][0]["type"] == "mixer"
    assert all(item["deposit_address"] != addresses[3].canonical_address for item in result["attributions"])


def test_sweep_requires_same_asset_fraction_and_discloses_residual(analytics_db):
    t0, case, run, addresses, asset, observation = _evidence(analytics_db)
    first = _tx(analytics_db, observation, asset, addresses[0], addresses[1], 1, t0 + timedelta(minutes=1), "10")
    second = _tx(analytics_db, observation, asset, addresses[1], addresses[2], 2, t0 + timedelta(minutes=20), "9")
    entity = Entity(entity_type="exchange", canonical_name="Sweep Exchange")
    analytics_db.add(entity); analytics_db.flush()
    analytics_db.add(EntityAddressAssertion(entity_id=entity.id, address_id=addresses[2].id, label="hot wallet",
                                             confidence=Decimal("1"), source="analyst-reviewed",
                                             review_status="reviewed", valid_from=t0 - timedelta(days=1),
                                             recorded_at=t0, assertion_digest="e" * 64))
    analytics_db.flush()
    sweeps = [item for item in attribute_run(run, analytics_db)["attributions"] if item["tier"] == "sweep"]
    assert sweeps[0]["score"] == 85
    assert sweeps[0]["measured"] == {"same_asset_fraction": "0.9", "elapsed_seconds": 1140, "observed_residual": "1"}
    assert sweeps[0]["path"] == [{"transfer_id": first.id}, {"transfer_id": second.id}]


def test_deterministic_policy_is_versioned_explainable_and_idempotent(analytics_db):
    t0, case, run, addresses, asset, observation = _evidence(analytics_db)
    for index in range(3):
        _tx(analytics_db, observation, asset, addresses[0], addresses[index + 1], index,
            t0 + timedelta(minutes=index + 1))
    analytics_db.add(ProtocolContract(protocol_name="Reviewed Bridge", protocol_type="bridge", chain="ETH",
                                      contract_address=addresses[1].canonical_address,
                                      valid_from=t0 - timedelta(days=1), provenance={"source": "official"}))
    analytics_db.flush()
    findings, payload = evaluate(run, analytics_db)
    assert payload["policy_version"] == POLICY_VERSION
    assert payload["score"] == 45  # bridge 20 + velocity 15 + evidenced-new-wallet 10
    assert payload["tier"] == "medium"
    assert next(item for item in findings if item["rule_id"] == "rapid_dispersal_30m")["assessment_state"] == "triggered"
    first = persist_evaluation(run, analytics_db)
    analytics_db.flush()
    second = persist_evaluation(run, analytics_db)
    assert first.id == second.id


def test_directory_import_preserves_provenance_and_rejects_investigator(client, auth_headers):
    payload = {"source_name": "Reviewed Test Registry", "source_uri": "https://registry.example/v1", "reviewed": True,
               "entities": [{"canonical_name": "Phase Six Exchange", "entity_type": "vasp", "jurisdiction": "India",
                             "labels": [{"chain": "ETH", "address": "0x1111111111111111111111111111111111111111",
                                         "label": "hot wallet", "confidence": "0.99", "source": "registry release 1",
                                         "valid_from": "2026-01-01T00:00:00Z"}]}]}
    forbidden = client.post("/api/v1/directory/imports", json=payload, headers=auth_headers)
    assert forbidden.status_code == 403
    login = client.post("/api/v1/auth/login", json={"email": "admin@cfas.gov.in", "password": "cfas2026"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    imported = client.post("/api/v1/directory/imports", json=payload, headers=headers)
    assert imported.status_code == 201
    detail = client.get("/api/v1/entities", params={"entity_type": "vasp"}, headers=headers)
    item = next(row for row in detail.json()["items"] if row["canonical_name"] == "Phase Six Exchange")
    label = client.get(f"/api/v1/entities/{item['id']}", headers=headers).json()["labels"][0]
    assert label["source"] == "registry release 1"
    assert label["evidence_uri"] == "https://registry.example/v1"
