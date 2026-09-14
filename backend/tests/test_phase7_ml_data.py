import ast
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.errors import ApplicationError
from app.new_ml.dataset import create_dataset
from app.new_ml.audit import audit
from app.new_ml.features import FEATURE_DEFINITIONS, materialize_wallet_features, register_definitions
from app.new_ml.labels import add_review, append_label, eligibility
from app.new_ml.splitter import SplitSample, grouped_chronological_split
from app.persistence.models import (
    AddressRecord, Asset, EvidenceSnapshot, LabelRevision, NormalizedTransaction,
    ProviderObservation,
)
from database import Base
from models import Case, User


@pytest.fixture
def ml_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _source(**overrides):
    source = {"source_name": "Independent reviewed source", "source_uri": "https://data.example/release",
              "source_kind": "public_research", "owner": "Original Publisher", "license_name": "Research Terms v1",
              "permitted_purpose": "non-production research evaluation", "chains": ["BTC"],
              "coverage_start": datetime(2025, 1, 1, tzinfo=timezone.utc),
              "coverage_end": datetime(2025, 12, 31, tzinfo=timezone.utc),
              "collection_method": "fresh acquisition from original publisher", "identity_keys": ["tx_hash", "event_index"],
              "label_meaning": "publisher-reviewed illicit activity class", "availability_semantics": "publisher release date",
              "quality_limits": ["BTC only", "research use"], "deletion_constraints": "remove when terms expire",
              "acquired_at": datetime(2026, 1, 1, tzinfo=timezone.utc), "content_hash": "a" * 64,
              "provenance": {"release": "v1", "independently_acquired": True}}
    source.update(overrides)
    return source


def test_dataset_manifest_is_reproducible_private_and_partitioned(ml_db):
    kwargs = {"version": "research-btc-v1", "purpose": "wallet_risk_research", "data_mode": "research",
              "task_types": ["wallet_risk"], "period_start": datetime(2025, 1, 1, tzinfo=timezone.utc),
              "period_end": datetime(2026, 1, 1, tzinfo=timezone.utc), "retention_policy": "terms-v1",
              "access_scope": ["ml_researchers"], "manifest": {"raw_records_unchanged": True}, "sources": [_source()]}
    first = create_dataset(ml_db, **kwargs)
    second = create_dataset(ml_db, **kwargs)
    assert first.id == second.id
    assert first.manifest["synthetic_excluded_from_quality_claims"] is False
    with pytest.raises(ApplicationError) as privacy:
        create_dataset(ml_db, **{**kwargs, "version": "bad-pii-v1", "manifest": {"victim_phone": "secret"}})
    assert privacy.value.code == "ML_DATA_PRIVACY_VIOLATION"
    with pytest.raises(ApplicationError) as isolation:
        create_dataset(ml_db, **{**kwargs, "version": "mixed-v1", "sources": [_source(source_kind="synthetic")]})
    assert isolation.value.code == "SYNTHETIC_DATA_ISOLATION_REQUIRED"
    with pytest.raises(ApplicationError) as conflict:
        create_dataset(ml_db, **{**kwargs, "version": "poisoned-v1",
            "sources": [_source(), _source(source_name="Conflicting attribution", license_name="Other terms")]})
    assert conflict.value.code == "ML_SOURCE_CONFLICT"


def _feature_evidence(session):
    t0 = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
    addresses = [AddressRecord(chain="ETH", canonical_address=f"0x{i:040x}", display_address=f"0x{i:040x}") for i in range(4)]
    asset = Asset(chain="ETH", symbol="ETH", decimals=18, asset_type="native")
    observation = ProviderObservation(provider="fresh-test", chain="ETH", request_fingerprint="b" * 64,
        available_time=t0 - timedelta(minutes=1), coverage_state="complete", parser_version="fresh-v1", response_digest="c" * 64)
    late_observation = ProviderObservation(provider="fresh-test", chain="ETH", request_fingerprint="d" * 64,
        available_time=t0 + timedelta(hours=1), coverage_state="complete", parser_version="fresh-v1", response_digest="e" * 64)
    session.add_all([*addresses, asset, observation, late_observation]); session.flush()
    pre = NormalizedTransaction(chain="ETH", tx_hash="pre", transfer_index="0", from_address_id=addresses[0].id,
        to_address_id=addresses[1].id, asset_id=asset.id, amount=Decimal("1"), raw_amount="1",
        event_time=t0 - timedelta(minutes=2), available_time=t0 - timedelta(minutes=1),
        provider_observation_id=observation.id, status="confirmed", finality_state="final")
    late_pre = NormalizedTransaction(chain="ETH", tx_hash="late-pre", transfer_index="0", from_address_id=addresses[0].id,
        to_address_id=addresses[2].id, asset_id=asset.id, amount=Decimal("2"), raw_amount="2",
        event_time=t0 - timedelta(minutes=3), available_time=t0 + timedelta(hours=1),
        provider_observation_id=late_observation.id, status="confirmed", finality_state="final")
    session.add_all([pre, late_pre]); session.flush()
    return t0, addresses, asset, observation


def test_point_in_time_features_reject_future_and_late_knowledge(ml_db):
    t0, addresses, asset, observation = _feature_evidence(ml_db)
    baseline = materialize_wallet_features(ml_db, subject_address_id=addresses[0].id, mode="report_baseline",
        report_time=t0, event_cutoff=t0, knowledge_cutoff=t0)
    assert baseline.values["transfer_count"] == 1
    future = NormalizedTransaction(chain="ETH", tx_hash="future", transfer_index="0", from_address_id=addresses[0].id,
        to_address_id=addresses[3].id, asset_id=asset.id, amount=Decimal("3"), raw_amount="3",
        event_time=t0 + timedelta(minutes=1), available_time=t0 + timedelta(minutes=1),
        provider_observation_id=observation.id, status="confirmed", finality_state="final")
    ml_db.add(future); ml_db.flush()
    repeated = materialize_wallet_features(ml_db, subject_address_id=addresses[0].id, mode="report_baseline",
        report_time=t0, event_cutoff=t0, knowledge_cutoff=t0)
    assert repeated.id == baseline.id
    assert repeated.snapshot_hash == baseline.snapshot_hash
    retrospective = materialize_wallet_features(ml_db, subject_address_id=addresses[0].id, mode="retrospective_context",
        report_time=None, event_cutoff=t0 + timedelta(hours=2), knowledge_cutoff=t0 + timedelta(hours=2))
    assert retrospective.values["transfer_count"] == 3
    assert retrospective.max_event_time <= retrospective.event_cutoff
    assert retrospective.max_available_time <= retrospective.availability_cutoff


def test_post_report_features_keep_frozen_baseline_namespace(ml_db):
    t0, addresses, asset, observation = _feature_evidence(ml_db)
    post = NormalizedTransaction(chain="ETH", tx_hash="post", transfer_index="0", from_address_id=addresses[0].id,
        to_address_id=addresses[3].id, asset_id=asset.id, amount=Decimal("3"), raw_amount="3",
        event_time=t0 + timedelta(minutes=1), available_time=t0 + timedelta(minutes=1),
        provider_observation_id=observation.id, status="confirmed", finality_state="final")
    ml_db.add(post); ml_db.flush()
    snapshot = materialize_wallet_features(ml_db, subject_address_id=addresses[0].id, mode="post_report",
        report_time=t0, event_cutoff=t0 + timedelta(hours=2), knowledge_cutoff=t0 + timedelta(hours=2))
    assert snapshot.values["baseline"]["transfer_count"] == 1
    assert snapshot.values["post_report"]["transfer_count"] == 1
    assert snapshot.quality["future_evidence_excluded"] is True


def _label_context(session):
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    case = Case(external_complaint_id="label-case", reported_loss_amount=Decimal("1"), fraud_typology="test", agency_id="agency")
    address = AddressRecord(chain="BTC", canonical_address="bc1qphase7", display_address="bc1qphase7")
    users = [User(id=f"reviewer-{i}", email=f"r{i}@example.test", full_name=f"Reviewer {i}",
                  password_hash="unused", role="analyst", status="active") for i in range(3)]
    session.add_all([case, address, *users]); session.flush()
    evidence = EvidenceSnapshot(case_id=case.id, revision=1, evidence_type="review_packet", event_time=t0,
        available_time=t0 + timedelta(days=1), source="authorized_case_review", content_digest="f" * 64,
        storage_uri="evidence://phase7", temporal_class="pre_report")
    session.add(evidence); session.flush()
    return t0, address, users, evidence


def test_labels_require_evidence_independent_dual_review_and_maturity(ml_db):
    t0, address, users, evidence = _label_context(ml_db)
    label = append_label(ml_db, subject_type="wallet", subject_id=address.id, task="wallet_risk",
        target_class="fraud_linked_activity", group_key="campaign-a", window_start=t0,
        window_end=t0 + timedelta(days=1), label="positive", maturity="mature",
        known_at=t0 + timedelta(days=2), evidence_snapshot_ids=[evidence.id], source_name="authorized_review",
        license_name="restricted", source_confidence=Decimal("0.9"), rationale="two-source case evidence",
        created_by=users[0].id, maturation_days=90)
    with pytest.raises(ApplicationError) as self_review:
        add_review(ml_db, label_revision=label, reviewer_id=users[0].id, decision="confirm", reason="self")
    assert self_review.value.code == "INDEPENDENT_REVIEW_REQUIRED"
    add_review(ml_db, label_revision=label, reviewer_id=users[1].id, decision="confirm", reason="evidence verified")
    assert eligibility(ml_db, label, label_cutoff=t0 + timedelta(days=300))["eligible"] is False
    add_review(ml_db, label_revision=label, reviewer_id=users[2].id, decision="confirm", reason="independent verification")
    assert eligibility(ml_db, label, label_cutoff=t0 + timedelta(days=300))["eligible"] is True
    unknown = append_label(ml_db, subject_type="wallet", subject_id=address.id, task="wallet_risk",
        target_class="other_target", group_key="campaign-a", window_start=t0, window_end=t0 + timedelta(days=1),
        label="unknown", maturity="censored", known_at=t0 + timedelta(days=2), evidence_snapshot_ids=[],
        source_name="authorized_review", license_name="restricted", source_confidence=Decimal("0.5"),
        rationale="insufficient evidence", created_by=users[0].id)
    assert "label_state_unknown" in eligibility(ml_db, unknown, label_cutoff=t0 + timedelta(days=200))["reasons"]


def test_grouped_chronological_split_has_no_group_or_label_cutoff_leakage():
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    samples = []
    for group_index in range(8):
        for member in range(2):
            samples.append(SplitSample(sample_id=f"s-{group_index}-{member}",
                observed_at=start + timedelta(days=group_index * 30 + member),
                label_known_at=start + timedelta(days=group_index * 30 + 10), group_key=f"g-{group_index}",
                label="positive" if group_index % 2 else "negative"))
    samples.append(SplitSample(sample_id="future-label", observed_at=start, label_known_at=start + timedelta(days=999),
                               group_key="future", label="positive"))
    audit = grouped_chronological_split(samples, label_cutoff=start + timedelta(days=500))
    assert "future-label" not in audit["membership"]
    for group_index in range(8):
        memberships = {audit["membership"][f"s-{group_index}-{member}"] for member in range(2)}
        assert len(memberships) == 1
    assert set(audit["class_counts"]) == {"train", "validation", "calibration", "test"}


def test_feature_registry_is_fresh_and_legacy_ml_imports_are_absent(ml_db):
    definitions = register_definitions(ml_db)
    assert len(definitions) == len(FEATURE_DEFINITIONS)
    assert all(item.owner == "fresh_new_ml" for item in definitions)
    root = Path(__file__).parents[1] / "app" / "new_ml"
    forbidden = ("services.risk_scoring", "services.tracer", "app.ml", "backend.ml")
    violations = []
    for path in root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import): names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom): names = [node.module or ""]
            violations.extend((path.name, name) for name in names if name.startswith(forbidden))
    assert violations == []
    repository_root = Path(__file__).parents[1]
    result = audit(repository_root / "app" / "new_ml", repository_root)
    assert result["passed"] is True
    assert result["legacy_model_artifacts"] == []
