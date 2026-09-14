"""Phase 2 persistence models.

Legacy tables remain registered in ``models.py`` for API compatibility. These
tables add the point-in-time, provenance, immutable revision, and durable work
records required by the updated PRD. PostgreSQL is authoritative in deployed
environments; SQLite is supported only for local development and test fixtures.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    event,
)
from sqlalchemy.orm import Mapper

from database import Base
from app.persistence.types import ExactDecimal, UtcTimestamp


def new_id() -> str:
    return str(uuid.uuid4())


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ImmutableRecordError(RuntimeError):
    """Raised when append-only forensic data is changed or deleted."""


class ImmutableRecord:
    """Marker for rows that may only be appended."""


class ReportEvent(Base, ImmutableRecord):
    __tablename__ = "report_events"
    id = Column(String(36), primary_key=True, default=new_id)
    case_id = Column(String(36), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    complaint_id = Column(String(36), ForeignKey("complaint_records.id", ondelete="CASCADE"), index=True)
    revision = Column(Integer, nullable=False)
    report_timestamp = Column(UtcTimestamp(), nullable=False)
    reported_timezone = Column(String(64), nullable=False)
    original_timestamp = Column(String(80), nullable=False, default="legacy-unspecified")
    iana_timezone = Column(String(64))
    timestamp_precision = Column(String(24), nullable=False, default="microsecond")
    verification_state = Column(String(24), nullable=False, default="unverified")
    verified_at = Column(UtcTimestamp())
    verified_by = Column(String(36), ForeignKey("users.id"))
    correction_reason = Column(Text)
    supersedes_id = Column(String(36), ForeignKey("report_events.id"))
    source_system = Column(String(64), nullable=False)
    channel = Column(String(64), nullable=False, default="legacy-unspecified")
    receipt_reference = Column(String(180))
    external_event_id = Column(String(150))
    received_at = Column(UtcTimestamp(), nullable=False, default=utc_now)
    created_by = Column(String(36), ForeignKey("users.id"))
    payload_digest = Column(String(64), nullable=False)
    __table_args__ = (
        UniqueConstraint("case_id", "revision", name="uq_report_event_case_revision"),
        UniqueConstraint("source_system", "external_event_id", name="uq_report_event_source_external"),
    )


class AddressRecord(Base):
    __tablename__ = "address_records"
    id = Column(String(36), primary_key=True, default=new_id)
    chain = Column(String(20), nullable=False)
    canonical_address = Column(String(160), nullable=False)
    display_address = Column(String(160), nullable=False)
    address_type = Column(String(32), nullable=False, default="wallet")
    first_seen_at = Column(UtcTimestamp())
    last_seen_at = Column(UtcTimestamp())
    created_at = Column(UtcTimestamp(), nullable=False, default=utc_now)
    __table_args__ = (UniqueConstraint("chain", "canonical_address", name="uq_address_chain_canonical"),)


class Asset(Base):
    __tablename__ = "assets"
    id = Column(String(36), primary_key=True, default=new_id)
    chain = Column(String(20), nullable=False)
    symbol = Column(String(32), nullable=False)
    contract_address = Column(String(160))
    decimals = Column(Integer, nullable=False)
    asset_type = Column(String(32), nullable=False)
    __table_args__ = (
        UniqueConstraint("chain", "symbol", "contract_address", name="uq_asset_identity"),
        CheckConstraint("decimals >= 0 AND decimals <= 36", name="ck_asset_decimals"),
    )


class ProviderObservation(Base, ImmutableRecord):
    __tablename__ = "provider_observations"
    id = Column(String(36), primary_key=True, default=new_id)
    provider = Column(String(64), nullable=False)
    chain = Column(String(20), nullable=False)
    request_fingerprint = Column(String(64), nullable=False)
    event_time = Column(UtcTimestamp())
    published_time = Column(UtcTimestamp())
    available_time = Column(UtcTimestamp(), nullable=False)
    fetched_at = Column(UtcTimestamp(), nullable=False, default=utc_now)
    ingested_at = Column(UtcTimestamp(), nullable=False, default=utc_now)
    coverage_state = Column(String(24), nullable=False)
    source_uri = Column(Text)
    cursor = Column(String(300))
    parser_version = Column(String(80), nullable=False)
    response_digest = Column(String(64), nullable=False)
    block_height = Column(String(78))
    block_hash = Column(String(150))
    confirmations = Column(Integer)
    finality_state = Column(String(24), nullable=False, default="unknown")
    provenance = Column(JSON, nullable=False, default=dict)
    __table_args__ = (
        UniqueConstraint("provider", "chain", "request_fingerprint", "response_digest", name="uq_provider_observation"),
    )


class NormalizedTransaction(Base, ImmutableRecord):
    __tablename__ = "normalized_transactions"
    id = Column(String(36), primary_key=True, default=new_id)
    chain = Column(String(20), nullable=False)
    tx_hash = Column(String(180), nullable=False)
    transfer_index = Column(String(80), nullable=False, default="0")
    from_address_id = Column(String(36), ForeignKey("address_records.id"), nullable=False)
    to_address_id = Column(String(36), ForeignKey("address_records.id"), nullable=False)
    asset_id = Column(String(36), ForeignKey("assets.id"), nullable=False)
    amount = Column(ExactDecimal(), nullable=False)
    raw_amount = Column(String(100), nullable=False)
    fiat_value = Column(ExactDecimal())
    fiat_currency = Column(String(8))
    valuation_source = Column(String(64))
    valuation_time = Column(UtcTimestamp())
    event_time = Column(UtcTimestamp(), nullable=False)
    available_time = Column(UtcTimestamp(), nullable=False)
    ingested_at = Column(UtcTimestamp(), nullable=False, default=utc_now)
    provider_observation_id = Column(String(36), ForeignKey("provider_observations.id"), nullable=False)
    block_height = Column(String(78))
    block_hash = Column(String(180))
    confirmations = Column(Integer)
    finality_state = Column(String(24), nullable=False, default="unknown")
    status = Column(String(24), nullable=False, default="confirmed")
    __table_args__ = (
        UniqueConstraint("chain", "tx_hash", "transfer_index", name="uq_normalized_transfer"),
        Index("ix_normalized_tx_event_time", "chain", "event_time"),
        Index("ix_normalized_tx_addresses", "from_address_id", "to_address_id"),
    )


class Entity(Base):
    __tablename__ = "entities"
    id = Column(String(36), primary_key=True, default=new_id)
    entity_type = Column(String(32), nullable=False)
    canonical_name = Column(String(200), nullable=False)
    legal_name = Column(String(200))
    service_type = Column(String(60))
    jurisdiction = Column(String(100))
    fiu_status = Column(String(32), nullable=False, default="unknown")
    fiu_source = Column(Text)
    fiu_as_of = Column(UtcTimestamp())
    contact_email = Column(String(255))
    contact_source = Column(Text)
    contact_as_of = Column(UtcTimestamp())
    status = Column(String(24), nullable=False, default="active")
    created_at = Column(UtcTimestamp(), nullable=False, default=utc_now)


class EntityAddressAssertion(Base, ImmutableRecord):
    __tablename__ = "entity_address_assertions"
    id = Column(String(36), primary_key=True, default=new_id)
    entity_id = Column(String(36), ForeignKey("entities.id", ondelete="CASCADE"), nullable=False)
    address_id = Column(String(36), ForeignKey("address_records.id", ondelete="CASCADE"), nullable=False)
    label = Column(String(150), nullable=False)
    confidence = Column(ExactDecimal(), nullable=False)
    source = Column(String(150), nullable=False)
    evidence_uri = Column(Text)
    review_status = Column(String(24), nullable=False, default="unreviewed")
    reviewed_by = Column(String(36), ForeignKey("users.id"))
    reviewed_at = Column(UtcTimestamp())
    valid_from = Column(UtcTimestamp(), nullable=False)
    valid_to = Column(UtcTimestamp())
    recorded_at = Column(UtcTimestamp(), nullable=False, default=utc_now)
    assertion_digest = Column(String(64), nullable=False, unique=True)


class AnalysisRun(Base, ImmutableRecord):
    __tablename__ = "analysis_runs"
    id = Column(String(36), primary_key=True, default=new_id)
    case_id = Column(String(36), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    run_type = Column(String(40), nullable=False)
    revision = Column(Integer, nullable=False)
    state = Column(String(24), nullable=False, default="queued")
    requested_by = Column(String(36), ForeignKey("users.id"))
    report_event_id = Column(String(36), ForeignKey("report_events.id"), nullable=False)
    root_address_ids = Column(JSON, nullable=False)
    event_cutoff = Column(UtcTimestamp(), nullable=False)
    cutoff_available_time = Column(UtcTimestamp(), nullable=False)
    parameters = Column(JSON, nullable=False)
    stage = Column(String(40), nullable=False, default="queued")
    checkpoint = Column(JSON, nullable=False, default=dict)
    requested_at = Column(UtcTimestamp(), nullable=False, default=utc_now)
    started_at = Column(UtcTimestamp())
    completed_at = Column(UtcTimestamp())
    coverage = Column(JSON, nullable=False, default=dict)
    error_code = Column(String(80))
    __table_args__ = (UniqueConstraint("case_id", "run_type", "revision", name="uq_analysis_run_revision"),)


class AnalysisRunEvent(Base, ImmutableRecord):
    __tablename__ = "analysis_run_events"
    id = Column(String(36), primary_key=True, default=new_id)
    run_id = Column(String(36), ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    sequence = Column(Integer, nullable=False)
    state = Column(String(24), nullable=False)
    progress_percent = Column(Integer, nullable=False)
    message = Column(Text)
    occurred_at = Column(UtcTimestamp(), nullable=False, default=utc_now)
    metadata_json = Column("metadata", JSON, nullable=False, default=dict)
    __table_args__ = (
        UniqueConstraint("run_id", "sequence", name="uq_analysis_event_sequence"),
        CheckConstraint("progress_percent >= 0 AND progress_percent <= 100", name="ck_analysis_progress"),
    )


class TracePath(Base, ImmutableRecord):
    __tablename__ = "trace_paths"
    id = Column(String(36), primary_key=True, default=new_id)
    run_id = Column(String(36), ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    path_index = Column(Integer, nullable=False)
    hop_count = Column(Integer, nullable=False)
    terminal_entity_id = Column(String(36), ForeignKey("entities.id"))
    total_amount = Column(ExactDecimal())
    path_payload = Column(JSON, nullable=False)
    evidence_digest = Column(String(64), nullable=False)
    __table_args__ = (UniqueConstraint("run_id", "path_index", name="uq_trace_path_index"),)


class GraphSnapshot(Base, ImmutableRecord):
    __tablename__ = "graph_snapshots"
    id = Column(String(36), primary_key=True, default=new_id)
    case_id = Column(String(36), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    run_id = Column(String(36), ForeignKey("analysis_runs.id"), nullable=False)
    revision = Column(Integer, nullable=False)
    report_event_id = Column(String(36), ForeignKey("report_events.id"), nullable=False)
    generated_at = Column(UtcTimestamp(), nullable=False, default=utc_now)
    cutoff_available_time = Column(UtcTimestamp(), nullable=False)
    node_count = Column(Integer, nullable=False)
    edge_count = Column(Integer, nullable=False)
    content_digest = Column(String(64), nullable=False)
    storage_uri = Column(Text)
    selected_filters = Column(JSON, nullable=False)
    membership_digest = Column(String(64), nullable=False)
    projection_revision = Column(Integer, nullable=False)
    continuity_gaps = Column(JSON, nullable=False, default=list)
    summary = Column(JSON, nullable=False, default=dict)
    __table_args__ = (UniqueConstraint("case_id", "revision", name="uq_graph_snapshot_revision"),)


class EvidenceSnapshot(Base, ImmutableRecord):
    __tablename__ = "evidence_snapshots"
    id = Column(String(36), primary_key=True, default=new_id)
    case_id = Column(String(36), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    revision = Column(Integer, nullable=False)
    evidence_type = Column(String(40), nullable=False)
    event_time = Column(UtcTimestamp())
    available_time = Column(UtcTimestamp(), nullable=False)
    ingested_at = Column(UtcTimestamp(), nullable=False, default=utc_now)
    source = Column(String(150), nullable=False)
    source_uri = Column(Text)
    content_digest = Column(String(64), nullable=False)
    storage_uri = Column(Text, nullable=False)
    temporal_class = Column(String(24), nullable=False)
    __table_args__ = (
        UniqueConstraint("case_id", "revision", name="uq_evidence_snapshot_revision"),
        CheckConstraint("temporal_class IN ('pre_report','at_report','post_report')", name="ck_evidence_temporal_class"),
    )


class RiskResult(Base, ImmutableRecord):
    __tablename__ = "risk_results"
    id = Column(String(36), primary_key=True, default=new_id)
    case_id = Column(String(36), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    run_id = Column(String(36), ForeignKey("analysis_runs.id"), nullable=False)
    revision = Column(Integer, nullable=False)
    score = Column(Integer, nullable=False)
    tier = Column(String(20), nullable=False)
    rule_version = Column(String(64), nullable=False)
    signals = Column(JSON, nullable=False)
    evidence_snapshot_ids = Column(JSON, nullable=False)
    created_at = Column(UtcTimestamp(), nullable=False, default=utc_now)
    __table_args__ = (
        UniqueConstraint("case_id", "revision", name="uq_risk_result_revision"),
        CheckConstraint("score >= 0 AND score <= 100", name="ck_risk_score"),
    )


class MLPrediction(Base, ImmutableRecord):
    __tablename__ = "ml_predictions"
    id = Column(String(36), primary_key=True, default=new_id)
    case_id = Column(String(36), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    run_id = Column(String(36), ForeignKey("analysis_runs.id"), nullable=False)
    revision = Column(Integer, nullable=False)
    model_version = Column(String(100), nullable=False)
    calibrator_version = Column(String(100), nullable=False)
    feature_snapshot_id = Column(String(100), nullable=False)
    risk_score = Column(Integer, nullable=False)
    calibrated_confidence = Column(ExactDecimal(), nullable=False)
    positive_class_probability = Column(ExactDecimal(), nullable=False)
    decision = Column(String(24), nullable=False)
    abstention_reason = Column(String(100))
    purpose = Column(String(80), nullable=False)
    event_cutoff = Column(UtcTimestamp(), nullable=False)
    availability_cutoff = Column(UtcTimestamp(), nullable=False)
    status = Column(String(24), nullable=False)
    contributing_features = Column(JSON, nullable=False)
    evidence_snapshot_ids = Column(JSON, nullable=False)
    limitations = Column(JSON, nullable=False, default=list)
    predicted_at = Column(UtcTimestamp(), nullable=False, default=utc_now)
    __table_args__ = (
        UniqueConstraint("case_id", "revision", name="uq_ml_prediction_revision"),
        CheckConstraint("risk_score >= 0 AND risk_score <= 100", name="ck_ml_risk_score"),
    )


class AnalystReview(Base, ImmutableRecord):
    __tablename__ = "analyst_reviews"
    id = Column(String(36), primary_key=True, default=new_id)
    case_id = Column(String(36), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    prediction_id = Column(String(36), ForeignKey("ml_predictions.id"))
    revision = Column(Integer, nullable=False)
    reviewer_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    disposition = Column(String(32), nullable=False)
    override_score = Column(Integer)
    reason = Column(Text, nullable=False)
    reviewed_at = Column(UtcTimestamp(), nullable=False, default=utc_now)
    review_expires_at = Column(UtcTimestamp())
    adjudication_id = Column(String(36), ForeignKey("ml_label_adjudications.id"))
    __table_args__ = (UniqueConstraint("case_id", "revision", name="uq_analyst_review_revision"),)


class ReportRevision(Base, ImmutableRecord):
    __tablename__ = "report_revisions"
    id = Column(String(36), primary_key=True, default=new_id)
    report_id = Column(String(36), ForeignKey("forensic_reports.id", ondelete="CASCADE"), nullable=False, index=True)
    revision = Column(Integer, nullable=False)
    case_id = Column(String(36), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False)
    graph_snapshot_id = Column(String(36), ForeignKey("graph_snapshots.id"))
    risk_result_id = Column(String(36), ForeignKey("risk_results.id"))
    ml_prediction_id = Column(String(36), ForeignKey("ml_predictions.id"))
    evidence_manifest = Column(JSON, nullable=False)
    content_digest = Column(String(64), nullable=False)
    pdf_digest = Column(String(64), nullable=False)
    storage_uri = Column(Text, nullable=False)
    report_cutoff = Column(UtcTimestamp(), nullable=False)
    review_status = Column(String(24), nullable=False)
    dispatch_status = Column(String(24), nullable=False)
    supersedes_id = Column(String(36), ForeignKey("report_revisions.id"))
    created_by = Column(String(36), ForeignKey("users.id"))
    created_at = Column(UtcTimestamp(), nullable=False, default=utc_now)
    __table_args__ = (UniqueConstraint("report_id", "revision", name="uq_report_revision"),)


class AuditEvent(Base, ImmutableRecord):
    __tablename__ = "audit_events"
    id = Column(String(36), primary_key=True, default=new_id)
    sequence = Column(Integer, nullable=False, unique=True)
    actor_id = Column(String(36), ForeignKey("users.id"))
    case_id = Column(String(36), ForeignKey("cases.id"))
    action = Column(String(100), nullable=False)
    resource_type = Column(String(80), nullable=False)
    resource_id = Column(String(100))
    occurred_at = Column(UtcTimestamp(), nullable=False, default=utc_now)
    request_id = Column(String(100))
    correlation_id = Column(String(100))
    ip_address = Column(String(64))
    details = Column(JSON, nullable=False, default=dict)
    outcome = Column(String(24), nullable=False)
    previous_digest = Column(String(64))
    event_digest = Column(String(64), nullable=False, unique=True)


class BackgroundJob(Base):
    __tablename__ = "background_jobs"
    id = Column(String(36), primary_key=True, default=new_id)
    operation = Column(String(80), nullable=False)
    idempotency_key = Column(String(180), nullable=False)
    case_id = Column(String(36), ForeignKey("cases.id"), index=True)
    actor_id = Column(String(36), ForeignKey("users.id"))
    state = Column(String(24), nullable=False, default="queued")
    priority = Column(Integer, nullable=False, default=100)
    payload = Column(JSON, nullable=False)
    attempt = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False, default=5)
    next_attempt_at = Column(UtcTimestamp(), nullable=False, default=utc_now)
    locked_by = Column(String(100))
    lock_expires_at = Column(UtcTimestamp())
    last_error_code = Column(String(80))
    created_at = Column(UtcTimestamp(), nullable=False, default=utc_now)
    updated_at = Column(UtcTimestamp(), nullable=False, default=utc_now)
    __table_args__ = (
        UniqueConstraint("operation", "idempotency_key", name="uq_job_operation_idempotency"),
        CheckConstraint("attempt >= 0 AND max_attempts > 0", name="ck_job_attempts"),
        Index("ix_jobs_claim", "state", "next_attempt_at", "priority"),
    )


class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    id = Column(String(36), primary_key=True, default=new_id)
    topic = Column(String(100), nullable=False)
    aggregate_type = Column(String(80), nullable=False)
    aggregate_id = Column(String(100), nullable=False)
    deduplication_key = Column(String(180), nullable=False, unique=True)
    payload = Column(JSON, nullable=False)
    state = Column(String(24), nullable=False, default="pending")
    attempt = Column(Integer, nullable=False, default=0)
    next_attempt_at = Column(UtcTimestamp(), nullable=False, default=utc_now)
    occurred_at = Column(UtcTimestamp(), nullable=False, default=utc_now)
    published_at = Column(UtcTimestamp())
    last_error = Column(Text)
    __table_args__ = (Index("ix_outbox_dispatch", "state", "next_attempt_at", "occurred_at"),)


class GraphProjectionCheckpoint(Base):
    __tablename__ = "graph_projection_checkpoints"
    projection_name = Column(String(100), primary_key=True)
    source_revision = Column(Integer, nullable=False)
    source_digest = Column(String(64), nullable=False)
    projected_at = Column(UtcTimestamp(), nullable=False, default=utc_now)
    state = Column(String(24), nullable=False)
    details = Column(JSON, nullable=False, default=dict)


class Agency(Base):
    __tablename__ = "agencies"
    id = Column(String(36), primary_key=True, default=new_id)
    name = Column(String(200), nullable=False)
    jurisdiction = Column(String(100), nullable=False)
    scope = Column(JSON, nullable=False, default=dict)
    status = Column(String(24), nullable=False, default="active")
    created_at = Column(UtcTimestamp(), nullable=False, default=utc_now)


class UserSession(Base):
    __tablename__ = "user_sessions"
    id = Column(String(36), primary_key=True, default=new_id)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash = Column(String(128), nullable=False, unique=True)
    scope = Column(JSON, nullable=False, default=list)
    issued_at = Column(UtcTimestamp(), nullable=False, default=utc_now)
    expires_at = Column(UtcTimestamp(), nullable=False)
    revoked_at = Column(UtcTimestamp())
    last_seen_at = Column(UtcTimestamp())
    revoked_reason = Column(String(100))


class ApiClient(Base):
    __tablename__ = "api_clients"
    id = Column(String(36), primary_key=True, default=new_id)
    agency_id = Column(String(36), ForeignKey("agencies.id"), nullable=False, index=True)
    name = Column(String(150), nullable=False)
    credential_hash = Column(String(128), nullable=False)
    scopes = Column(JSON, nullable=False, default=list)
    status = Column(String(24), nullable=False, default="active")
    expires_at = Column(UtcTimestamp())
    revoked_at = Column(UtcTimestamp())
    created_at = Column(UtcTimestamp(), nullable=False, default=utc_now)


class UserAgencyScope(Base):
    __tablename__ = "user_agency_scopes"
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    agency_id = Column(String(36), ForeignKey("agencies.id", ondelete="CASCADE"), primary_key=True)
    role = Column(String(40), nullable=False)
    permissions = Column(JSON, nullable=False, default=list)
    status = Column(String(24), nullable=False, default="active")
    valid_from = Column(UtcTimestamp(), nullable=False, default=utc_now)
    valid_to = Column(UtcTimestamp())


class Victim(Base):
    __tablename__ = "victims"
    id = Column(String(36), primary_key=True, default=new_id)
    agency_id = Column(String(36), ForeignKey("agencies.id"), nullable=False, index=True)
    name_ciphertext = Column(Text)
    phone_ciphertext = Column(Text)
    email_ciphertext = Column(Text)
    pii_key_version = Column(String(40), nullable=False)
    created_at = Column(UtcTimestamp(), nullable=False, default=utc_now)


class ComplaintRecord(Base):
    __tablename__ = "complaint_records"
    id = Column(String(36), primary_key=True, default=new_id)
    agency_id = Column(String(36), ForeignKey("agencies.id"), nullable=False, index=True)
    victim_id = Column(String(36), ForeignKey("victims.id"))
    source = Column(String(64), nullable=False)
    external_reference = Column(String(150), nullable=False)
    narrative_ciphertext = Column(Text)
    reported_loss = Column(ExactDecimal(), nullable=False)
    loss_currency = Column(String(12), nullable=False)
    incident_time = Column(UtcTimestamp())
    filed_time = Column(UtcTimestamp())
    received_time = Column(UtcTimestamp(), nullable=False)
    created_at = Column(UtcTimestamp(), nullable=False, default=utc_now)
    __table_args__ = (UniqueConstraint("agency_id", "source", "external_reference", name="uq_complaint_external"),)


class CaseComplaint(Base):
    __tablename__ = "case_complaints"
    case_id = Column(String(36), ForeignKey("cases.id", ondelete="CASCADE"), primary_key=True)
    complaint_id = Column(String(36), ForeignKey("complaint_records.id", ondelete="CASCADE"), primary_key=True)
    role = Column(String(24), nullable=False, default="primary")
    linked_at = Column(UtcTimestamp(), nullable=False, default=utc_now)
    linked_by = Column(String(36), ForeignKey("users.id"))


class ComplaintWallet(Base):
    __tablename__ = "complaint_wallets"
    complaint_id = Column(String(36), ForeignKey("complaint_records.id", ondelete="CASCADE"), primary_key=True)
    address_id = Column(String(36), ForeignKey("address_records.id", ondelete="CASCADE"), primary_key=True)
    role = Column(String(24), nullable=False)
    source = Column(String(64), nullable=False)
    confidence = Column(ExactDecimal())
    recorded_at = Column(UtcTimestamp(), nullable=False, default=utc_now)


class CaseNote(Base, ImmutableRecord):
    __tablename__ = "case_notes"
    id = Column(String(36), primary_key=True, default=new_id)
    case_id = Column(String(36), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    revision = Column(Integer, nullable=False)
    author_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    body_ciphertext = Column(Text, nullable=False)
    created_at = Column(UtcTimestamp(), nullable=False, default=utc_now)
    supersedes_id = Column(String(36), ForeignKey("case_notes.id"))
    __table_args__ = (UniqueConstraint("case_id", "revision", name="uq_case_note_revision"),)


class CaseEvent(Base, ImmutableRecord):
    __tablename__ = "case_events"
    id = Column(String(36), primary_key=True, default=new_id)
    case_id = Column(String(36), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    sequence = Column(Integer, nullable=False)
    event_type = Column(String(64), nullable=False)
    actor_id = Column(String(36), ForeignKey("users.id"))
    occurred_at = Column(UtcTimestamp(), nullable=False, default=utc_now)
    payload = Column(JSON, nullable=False, default=dict)
    __table_args__ = (UniqueConstraint("case_id", "sequence", name="uq_case_event_sequence"),)


class CaseAccessGrant(Base):
    __tablename__ = "case_access_grants"
    case_id = Column(String(36), ForeignKey("cases.id", ondelete="CASCADE"), primary_key=True)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    permission = Column(String(24), nullable=False, default="read")
    granted_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    granted_at = Column(UtcTimestamp(), nullable=False, default=utc_now)
    revoked_at = Column(UtcTimestamp())


class CaseAttachment(Base, ImmutableRecord):
    __tablename__ = "case_attachments"
    id = Column(String(36), primary_key=True, default=new_id)
    case_id = Column(String(36), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    filename = Column(String(255), nullable=False)
    mime_type = Column(String(120), nullable=False)
    size_bytes = Column(Integer, nullable=False)
    sha256 = Column(String(64), nullable=False)
    storage_reference = Column(Text, nullable=False)
    uploaded_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    created_at = Column(UtcTimestamp(), nullable=False, default=utc_now)
    __table_args__ = (
        CheckConstraint("size_bytes >= 0", name="ck_case_attachment_size"),
        UniqueConstraint("case_id", "sha256", name="uq_case_attachment_digest"),
    )


class IdempotencyRecord(Base, ImmutableRecord):
    __tablename__ = "idempotency_records"
    id = Column(String(36), primary_key=True, default=new_id)
    actor_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    operation = Column(String(80), nullable=False)
    idempotency_key = Column(String(180), nullable=False)
    request_digest = Column(String(64), nullable=False)
    response_status = Column(Integer, nullable=False)
    response_payload = Column(JSON, nullable=False)
    created_at = Column(UtcTimestamp(), nullable=False, default=utc_now)
    __table_args__ = (UniqueConstraint("actor_id", "operation", "idempotency_key", name="uq_idempotency_actor_operation_key"),)


class Network(Base):
    __tablename__ = "networks"
    id = Column(String(36), primary_key=True, default=new_id)
    code = Column(String(20), nullable=False, unique=True)
    display_name = Column(String(80), nullable=False)
    capabilities = Column(JSON, nullable=False, default=dict)
    finality_policy = Column(JSON, nullable=False, default=dict)
    status = Column(String(24), nullable=False, default="active")


class BitcoinOutpoint(Base, ImmutableRecord):
    __tablename__ = "bitcoin_outpoints"
    id = Column(String(36), primary_key=True, default=new_id)
    transaction_id = Column(String(36), ForeignKey("normalized_transactions.id"), nullable=False, index=True)
    output_index = Column(Integer, nullable=False)
    address_id = Column(String(36), ForeignKey("address_records.id"))
    amount_satoshi = Column(String(100), nullable=False)
    spent_by_transaction_id = Column(String(36), ForeignKey("normalized_transactions.id"))
    evidence_snapshot_id = Column(String(36), ForeignKey("evidence_snapshots.id"), nullable=False)
    __table_args__ = (UniqueConstraint("transaction_id", "output_index", name="uq_bitcoin_outpoint"),)


class ProtocolContract(Base):
    __tablename__ = "protocol_contracts"
    id = Column(String(36), primary_key=True, default=new_id)
    protocol_name = Column(String(120), nullable=False)
    protocol_version = Column(String(60))
    protocol_type = Column(String(40), nullable=False)
    chain = Column(String(20), nullable=False)
    contract_address = Column(String(160), nullable=False)
    valid_from = Column(UtcTimestamp(), nullable=False)
    valid_to = Column(UtcTimestamp())
    provenance = Column(JSON, nullable=False)
    reviewed_at = Column(UtcTimestamp())
    __table_args__ = (UniqueConstraint("chain", "contract_address", "protocol_version", name="uq_protocol_contract"),)


class CrossChainLink(Base, ImmutableRecord):
    __tablename__ = "cross_chain_links"
    id = Column(String(36), primary_key=True, default=new_id)
    protocol_contract_id = Column(String(36), ForeignKey("protocol_contracts.id"), nullable=False)
    message_identity = Column(String(180), nullable=False)
    source_transaction_id = Column(String(36), ForeignKey("normalized_transactions.id"), nullable=False)
    destination_transaction_id = Column(String(36), ForeignKey("normalized_transactions.id"))
    status = Column(String(24), nullable=False)
    evidence_snapshot_ids = Column(JSON, nullable=False)
    observed_at = Column(UtcTimestamp(), nullable=False, default=utc_now)
    __table_args__ = (UniqueConstraint("protocol_contract_id", "message_identity", name="uq_cross_chain_message"),)


class Cluster(Base, ImmutableRecord):
    __tablename__ = "clusters"
    id = Column(String(36), primary_key=True, default=new_id)
    version = Column(Integer, nullable=False)
    evidence_snapshot_id = Column(String(36), ForeignKey("evidence_snapshots.id"), nullable=False)
    source_method = Column(String(100), nullable=False)
    confidence = Column(ExactDecimal(), nullable=False)
    available_time = Column(UtcTimestamp(), nullable=False)
    content_digest = Column(String(64), nullable=False, unique=True)


class ClusterMembership(Base, ImmutableRecord):
    __tablename__ = "cluster_memberships"
    cluster_id = Column(String(36), ForeignKey("clusters.id", ondelete="CASCADE"), primary_key=True)
    address_id = Column(String(36), ForeignKey("address_records.id", ondelete="CASCADE"), primary_key=True)
    evidence = Column(JSON, nullable=False)
    confidence = Column(ExactDecimal(), nullable=False)


class RuleFinding(Base, ImmutableRecord):
    __tablename__ = "rule_findings"
    id = Column(String(36), primary_key=True, default=new_id)
    run_id = Column(String(36), ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    rule_id = Column(String(100), nullable=False)
    policy_version = Column(String(80), nullable=False)
    temporal_partition = Column(String(24), nullable=False)
    measured_values = Column(JSON, nullable=False)
    contribution = Column(Integer, nullable=False)
    assessment_state = Column(String(24), nullable=False)
    evidence_snapshot_ids = Column(JSON, nullable=False)
    created_at = Column(UtcTimestamp(), nullable=False, default=utc_now)
    __table_args__ = (UniqueConstraint("run_id", "rule_id", "policy_version", "temporal_partition", name="uq_rule_finding"),)


class DatasetSnapshot(Base, ImmutableRecord):
    __tablename__ = "ml_dataset_snapshots"
    id = Column(String(36), primary_key=True, default=new_id)
    version = Column(String(80), nullable=False, unique=True)
    purpose = Column(String(80), nullable=False)
    data_mode = Column(String(24), nullable=False, default="research")
    task_types = Column(JSON, nullable=False, default=list)
    manifest = Column(JSON, nullable=False, default=dict)
    snapshot_hash = Column(String(64), nullable=False, unique=True)
    period_start = Column(UtcTimestamp(), nullable=False)
    period_end = Column(UtcTimestamp(), nullable=False)
    retention_policy = Column(String(80), nullable=False)
    access_scope = Column(JSON, nullable=False)
    created_at = Column(UtcTimestamp(), nullable=False, default=utc_now)


class DatasetSource(Base, ImmutableRecord):
    __tablename__ = "ml_dataset_sources"
    id = Column(String(36), primary_key=True, default=new_id)
    dataset_snapshot_id = Column(String(36), ForeignKey("ml_dataset_snapshots.id", ondelete="CASCADE"), nullable=False)
    source_name = Column(String(150), nullable=False)
    source_uri = Column(Text)
    source_kind = Column(String(32), nullable=False, default="authorized")
    owner = Column(String(150), nullable=False, default="unknown")
    license_name = Column(String(150), nullable=False)
    permitted_purpose = Column(String(200), nullable=False, default="research")
    chains = Column(JSON, nullable=False, default=list)
    coverage_start = Column(UtcTimestamp())
    coverage_end = Column(UtcTimestamp())
    collection_method = Column(String(120), nullable=False, default="registered_import")
    identity_keys = Column(JSON, nullable=False, default=list)
    label_meaning = Column(Text)
    availability_semantics = Column(Text, nullable=False, default="recorded_at")
    quality_limits = Column(JSON, nullable=False, default=list)
    deletion_constraints = Column(Text)
    acquired_at = Column(UtcTimestamp(), nullable=False)
    content_hash = Column(String(64), nullable=False)
    provenance = Column(JSON, nullable=False)


class LabelRevision(Base, ImmutableRecord):
    __tablename__ = "ml_label_revisions"
    id = Column(String(36), primary_key=True, default=new_id)
    subject_type = Column(String(40), nullable=False)
    subject_id = Column(String(100), nullable=False)
    task = Column(String(40), nullable=False, default="wallet_risk")
    target_class = Column(String(80), nullable=False, default="fraud_linked_activity")
    group_key = Column(String(120), nullable=False, default="ungrouped")
    observation_window_start = Column(UtcTimestamp(), nullable=False)
    observation_window_end = Column(UtcTimestamp(), nullable=False)
    label = Column(String(24), nullable=False)
    maturity = Column(String(24), nullable=False)
    matures_at = Column(UtcTimestamp())
    known_at = Column(UtcTimestamp(), nullable=False)
    source_name = Column(String(150), nullable=False, default="authorized_review")
    license_name = Column(String(150), nullable=False, default="restricted")
    source_confidence = Column(ExactDecimal(), nullable=False, default="1")
    rationale = Column(Text, nullable=False, default="reviewed evidence")
    created_by = Column(String(36), ForeignKey("users.id"))
    evidence_snapshot_ids = Column(JSON, nullable=False)
    revision = Column(Integer, nullable=False)
    created_at = Column(UtcTimestamp(), nullable=False, default=utc_now)
    __table_args__ = (UniqueConstraint("subject_type", "subject_id", "task", "target_class", "revision",
                                       name="uq_label_revision"),)


class LabelAdjudication(Base, ImmutableRecord):
    __tablename__ = "ml_label_adjudications"
    id = Column(String(36), primary_key=True, default=new_id)
    label_revision_id = Column(String(36), ForeignKey("ml_label_revisions.id"), nullable=False)
    reviewer_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    decision = Column(String(24), nullable=False)
    reason = Column(Text, nullable=False)
    adjudicated_at = Column(UtcTimestamp(), nullable=False, default=utc_now)
    __table_args__ = (UniqueConstraint("label_revision_id", "reviewer_id", name="uq_label_reviewer"),)


class FeatureDefinition(Base, ImmutableRecord):
    __tablename__ = "ml_feature_definitions"
    id = Column(String(36), primary_key=True, default=new_id)
    name = Column(String(120), nullable=False)
    version = Column(String(80), nullable=False)
    family = Column(String(60), nullable=False, default="data_quality")
    value_type = Column(String(32), nullable=False, default="decimal")
    units = Column(String(40))
    source = Column(String(150), nullable=False, default="normalized_evidence")
    aggregation = Column(String(100), nullable=False, default="defined")
    missing_behavior = Column(String(100), nullable=False, default="explicit_missing_indicator")
    owner = Column(String(100), nullable=False, default="new_ml")
    window_definition = Column(JSON, nullable=False)
    cutoff_policy = Column(JSON, nullable=False)
    definition_hash = Column(String(64), nullable=False, unique=True)
    __table_args__ = (UniqueConstraint("name", "version", name="uq_feature_definition"),)


class FeatureSnapshot(Base, ImmutableRecord):
    __tablename__ = "ml_feature_snapshots"
    id = Column(String(36), primary_key=True, default=new_id)
    subject_type = Column(String(40), nullable=False)
    subject_id = Column(String(100), nullable=False)
    schema_version = Column(String(80), nullable=False)
    temporal_partition = Column(String(24), nullable=False)
    event_cutoff = Column(UtcTimestamp(), nullable=False)
    availability_cutoff = Column(UtcTimestamp(), nullable=False)
    max_event_time = Column(UtcTimestamp())
    max_available_time = Column(UtcTimestamp())
    values = Column(JSON, nullable=False)
    evidence_ids = Column(JSON, nullable=False, default=list)
    quality = Column(JSON, nullable=False, default=dict)
    snapshot_hash = Column(String(64), nullable=False, unique=True)
    created_at = Column(UtcTimestamp(), nullable=False, default=utc_now)


class SplitManifest(Base, ImmutableRecord):
    __tablename__ = "ml_split_manifests"
    id = Column(String(36), primary_key=True, default=new_id)
    dataset_snapshot_id = Column(String(36), ForeignKey("ml_dataset_snapshots.id"), nullable=False)
    version = Column(String(80), nullable=False, unique=True)
    temporal_rules = Column(JSON, nullable=False)
    group_rules = Column(JSON, nullable=False)
    purge_duration = Column(String(40), nullable=False)
    embargo_duration = Column(String(40), nullable=False)
    membership_uri = Column(Text, nullable=False)
    membership = Column(JSON, nullable=False, default=dict)
    class_counts = Column(JSON, nullable=False, default=dict)
    manifest_hash = Column(String(64), nullable=False, unique=True)


class ExperimentRun(Base, ImmutableRecord):
    __tablename__ = "ml_experiment_runs"
    id = Column(String(36), primary_key=True, default=new_id)
    external_run_id = Column(String(150), nullable=False, unique=True)
    dataset_snapshot_id = Column(String(36), ForeignKey("ml_dataset_snapshots.id"), nullable=False)
    split_manifest_id = Column(String(36), ForeignKey("ml_split_manifests.id"), nullable=False)
    feature_schema_version = Column(String(80), nullable=False)
    seeds = Column(JSON, nullable=False)
    parameters = Column(JSON, nullable=False)
    environment = Column(JSON, nullable=False)
    metrics = Column(JSON, nullable=False)
    artifact_manifest = Column(JSON, nullable=False)
    started_at = Column(UtcTimestamp(), nullable=False)
    completed_at = Column(UtcTimestamp())


class ModelPackage(Base, ImmutableRecord):
    __tablename__ = "ml_model_packages"
    id = Column(String(36), primary_key=True, default=new_id)
    version = Column(String(100), nullable=False, unique=True)
    experiment_run_id = Column(String(36), ForeignKey("ml_experiment_runs.id"), nullable=False)
    model_hash = Column(String(64), nullable=False)
    preprocessing_version = Column(String(80), nullable=False)
    feature_schema_version = Column(String(80), nullable=False)
    calibrator_version = Column(String(80), nullable=False)
    calibrator_hash = Column(String(64), nullable=False)
    target_definition = Column(JSON, nullable=False)
    scope = Column(JSON, nullable=False)
    state = Column(String(24), nullable=False)
    approved_by = Column(String(36), ForeignKey("users.id"))
    approved_at = Column(UtcTimestamp())
    created_at = Column(UtcTimestamp(), nullable=False, default=utc_now)


class ModelLifecycleEvent(Base, ImmutableRecord):
    """Append-only registry transition; package bytes and prior predictions never change."""
    __tablename__ = "ml_model_lifecycle_events"
    id = Column(String(36), primary_key=True, default=new_id)
    package_id = Column(String(36), ForeignKey("ml_model_packages.id", ondelete="CASCADE"), nullable=False, index=True)
    prior_package_id = Column(String(36), ForeignKey("ml_model_packages.id"))
    transition = Column(String(24), nullable=False)
    traffic_percent = Column(Integer, nullable=False, default=0)
    reason = Column(Text, nullable=False)
    actor_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    scope = Column(JSON, nullable=False, default=dict)
    occurred_at = Column(UtcTimestamp(), nullable=False, default=utc_now)
    __table_args__ = (CheckConstraint("traffic_percent >= 0 AND traffic_percent <= 100", name="ck_ml_lifecycle_traffic"),)


class PredictionExplanation(Base, ImmutableRecord):
    __tablename__ = "ml_prediction_explanations"
    id = Column(String(36), primary_key=True, default=new_id)
    prediction_id = Column(String(36), ForeignKey("ml_predictions.id", ondelete="CASCADE"), nullable=False, index=True)
    feature_name = Column(String(120), nullable=False)
    measured_value = Column(JSON, nullable=False)
    contribution = Column(ExactDecimal(), nullable=False)
    contribution_space = Column(String(40), nullable=False)
    direction = Column(String(16), nullable=False)
    temporal_partition = Column(String(24), nullable=False)
    evidence_snapshot_ids = Column(JSON, nullable=False)
    rank = Column(Integer, nullable=False)
    __table_args__ = (UniqueConstraint("prediction_id", "rank", name="uq_prediction_explanation_rank"),)


class DriftEvaluation(Base, ImmutableRecord):
    __tablename__ = "ml_drift_evaluations"
    id = Column(String(36), primary_key=True, default=new_id)
    model_package_id = Column(String(36), ForeignKey("ml_model_packages.id"), nullable=False)
    cohort = Column(JSON, nullable=False)
    window_start = Column(UtcTimestamp(), nullable=False)
    window_end = Column(UtcTimestamp(), nullable=False)
    metric_name = Column(String(80), nullable=False)
    metric_value = Column(ExactDecimal(), nullable=False)
    sample_size = Column(Integer, nullable=False)
    threshold = Column(ExactDecimal(), nullable=False)
    triggered = Column(Boolean, nullable=False)
    evaluated_at = Column(UtcTimestamp(), nullable=False, default=utc_now)


class RetrainingRequest(Base):
    __tablename__ = "ml_retraining_requests"
    id = Column(String(36), primary_key=True, default=new_id)
    drift_evaluation_id = Column(String(36), ForeignKey("ml_drift_evaluations.id"))
    requested_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    reason = Column(Text, nullable=False)
    state = Column(String(24), nullable=False, default="requested")
    approved_by = Column(String(36), ForeignKey("users.id"))
    outcome = Column(JSON)
    created_at = Column(UtcTimestamp(), nullable=False, default=utc_now)
    updated_at = Column(UtcTimestamp(), nullable=False, default=utc_now)


class AlertRecipient(Base):
    __tablename__ = "alert_recipients"
    alert_id = Column(String(36), ForeignKey("alerts.id", ondelete="CASCADE"), primary_key=True)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    read_at = Column(UtcTimestamp())
    acknowledged_at = Column(UtcTimestamp())


class AlertDelivery(Base):
    __tablename__ = "alert_deliveries"
    id = Column(String(36), primary_key=True, default=new_id)
    alert_id = Column(String(36), ForeignKey("alerts.id", ondelete="CASCADE"), nullable=False, index=True)
    channel = Column(String(32), nullable=False)
    recipient = Column(String(200), nullable=False)
    state = Column(String(24), nullable=False)
    attempt = Column(Integer, nullable=False, default=0)
    delivered_at = Column(UtcTimestamp())
    last_error = Column(Text)


class AlertTrigger(Base, ImmutableRecord):
    __tablename__ = "alert_triggers"
    id = Column(String(36), primary_key=True, default=new_id)
    alert_id = Column(String(36), ForeignKey("alerts.id", ondelete="CASCADE"), nullable=False, unique=True)
    fingerprint = Column(String(128), nullable=False, unique=True)
    run_id = Column(String(36), ForeignKey("analysis_runs.id"))
    prediction_id = Column(String(36), ForeignKey("ml_predictions.id"))
    evidence_snapshot_ids = Column(JSON, nullable=False)
    triggered_at = Column(UtcTimestamp(), nullable=False, default=utc_now)


class DepositDecision(Base, ImmutableRecord):
    __tablename__ = "deposit_decisions"
    id = Column(String(36), primary_key=True, default=new_id)
    partner_id = Column(String(100), nullable=False)
    idempotency_reference = Column(String(180), nullable=False)
    address_id = Column(String(36), ForeignKey("address_records.id"), nullable=False)
    asset_id = Column(String(36), ForeignKey("assets.id"), nullable=False)
    prediction_id = Column(String(36), ForeignKey("ml_predictions.id"))
    recommendation = Column(String(24), nullable=False)
    alert_id = Column(String(36), ForeignKey("alerts.id"))
    assessed_at = Column(UtcTimestamp(), nullable=False)
    expires_at = Column(UtcTimestamp(), nullable=False)
    latency_ms = Column(Integer, nullable=False)
    evidence_summary = Column(JSON, nullable=False)
    __table_args__ = (UniqueConstraint("partner_id", "idempotency_reference", name="uq_deposit_decision"),)


class MonitoringSubscription(Base):
    __tablename__ = "monitoring_subscriptions"
    id = Column(String(36), primary_key=True, default=new_id)
    case_id = Column(String(36), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    address_id = Column(String(36), ForeignKey("address_records.id"), nullable=False)
    interval_seconds = Column(Integer, nullable=False)
    expires_at = Column(UtcTimestamp(), nullable=False)
    policy_version = Column(String(80), nullable=False)
    checkpoint = Column(JSON, nullable=False, default=dict)
    state = Column(String(24), nullable=False)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    created_at = Column(UtcTimestamp(), nullable=False, default=utc_now)


class EvidenceObject(Base, ImmutableRecord):
    __tablename__ = "evidence_objects"
    id = Column(String(36), primary_key=True, default=new_id)
    source = Column(String(150), nullable=False)
    media_type = Column(String(120), nullable=False)
    byte_length = Column(String(40), nullable=False)
    sha256 = Column(String(64), nullable=False, unique=True)
    storage_uri = Column(Text, nullable=False)
    retention_until = Column(UtcTimestamp())
    legal_hold = Column(Boolean, nullable=False, default=False)
    created_at = Column(UtcTimestamp(), nullable=False, default=utc_now)


class EvidenceManifest(Base, ImmutableRecord):
    __tablename__ = "evidence_manifests"
    id = Column(String(36), primary_key=True, default=new_id)
    case_id = Column(String(36), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    revision = Column(Integer, nullable=False)
    object_ids = Column(JSON, nullable=False)
    manifest_hash = Column(String(64), nullable=False, unique=True)
    created_at = Column(UtcTimestamp(), nullable=False, default=utc_now)
    __table_args__ = (UniqueConstraint("case_id", "revision", name="uq_evidence_manifest_revision"),)


class PolicySetting(Base, ImmutableRecord):
    __tablename__ = "policy_settings"
    id = Column(String(36), primary_key=True, default=new_id)
    policy_name = Column(String(120), nullable=False)
    version = Column(String(80), nullable=False)
    effective_at = Column(UtcTimestamp(), nullable=False)
    thresholds = Column(JSON, nullable=False)
    preferences = Column(JSON, nullable=False, default=dict)
    approved_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    change_reason = Column(Text, nullable=False)
    content_hash = Column(String(64), nullable=False, unique=True)
    __table_args__ = (UniqueConstraint("policy_name", "version", name="uq_policy_version"),)


PHASE2_TABLE_NAMES = (
    "report_events", "address_records", "assets", "provider_observations",
    "normalized_transactions", "entities", "entity_address_assertions",
    "analysis_runs", "analysis_run_events", "trace_paths", "graph_snapshots",
    "evidence_snapshots", "risk_results", "ml_predictions", "analyst_reviews",
    "report_revisions", "audit_events", "background_jobs", "outbox_events",
    "graph_projection_checkpoints",
    "agencies", "user_sessions", "api_clients", "user_agency_scopes", "victims", "complaint_records",
    "case_complaints", "complaint_wallets", "case_notes", "case_events", "case_access_grants",
    "case_attachments", "idempotency_records", "networks",
    "bitcoin_outpoints", "protocol_contracts", "cross_chain_links", "clusters",
    "cluster_memberships", "rule_findings", "ml_dataset_snapshots", "ml_dataset_sources",
    "ml_label_revisions", "ml_label_adjudications", "ml_feature_definitions",
    "ml_feature_snapshots", "ml_split_manifests", "ml_experiment_runs", "ml_model_packages", "ml_model_lifecycle_events",
    "ml_prediction_explanations", "ml_drift_evaluations", "ml_retraining_requests",
    "alert_recipients", "alert_deliveries", "alert_triggers", "deposit_decisions", "monitoring_subscriptions",
    "evidence_objects", "evidence_manifests", "policy_settings",
)


def _prevent_change(mapper: Mapper, connection, target: ImmutableRecord) -> None:
    raise ImmutableRecordError(f"{type(target).__name__} records are append-only")


for _immutable_model in (
    ReportEvent, ProviderObservation, NormalizedTransaction, EntityAddressAssertion,
    AnalysisRun, AnalysisRunEvent, TracePath, GraphSnapshot, EvidenceSnapshot, RiskResult,
    MLPrediction, AnalystReview, ReportRevision, AuditEvent, CaseNote, CaseEvent,
    CaseAttachment, IdempotencyRecord,
    BitcoinOutpoint, CrossChainLink, Cluster, ClusterMembership, RuleFinding,
    DatasetSnapshot, DatasetSource, LabelRevision, LabelAdjudication, FeatureDefinition,
    FeatureSnapshot, SplitManifest, ExperimentRun, ModelPackage, ModelLifecycleEvent, PredictionExplanation,
    DriftEvaluation, AlertTrigger, DepositDecision, EvidenceObject, EvidenceManifest, PolicySetting,
):
    event.listen(_immutable_model, "before_update", _prevent_change)
    event.listen(_immutable_model, "before_delete", _prevent_change)
