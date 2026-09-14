"""Point-in-time feature registry and wallet feature materialization."""

from __future__ import annotations

import math
from collections import defaultdict, deque
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ApplicationError
from app.new_ml.contracts import TEMPORAL_MODES
from app.new_ml.dataset import digest
from app.persistence.models import (
    AddressRecord, Asset, ComplaintRecord, ComplaintWallet, Entity,
    EntityAddressAssertion, FeatureDefinition, FeatureSnapshot,
    NormalizedTransaction, ProtocolContract, ProviderObservation,
)


FEATURE_SCHEMA_VERSION = "fresh-wallet-features-v1"
FEATURE_DEFINITIONS = (
    ("transfer_count", "velocity", "count", "eligible incoming and outgoing transfers"),
    ("outgoing_count_1m", "velocity", "count", "outgoing count in trailing 1 minute"),
    ("outgoing_count_5m", "velocity", "count", "outgoing count in trailing 5 minutes"),
    ("outgoing_count_30m", "velocity", "count", "outgoing count in trailing 30 minutes"),
    ("outgoing_count_60m", "velocity", "count", "outgoing count in trailing 60 minutes"),
    ("outgoing_count_24h", "velocity", "count", "outgoing count in trailing 24 hours"),
    ("outgoing_count_7d", "velocity", "count", "outgoing count in trailing 7 days"),
    ("outgoing_count_30d", "velocity", "count", "outgoing count in trailing 30 days"),
    ("unique_counterparties", "structure", "count", "network-qualified counterparties"),
    ("fan_in", "structure", "count", "distinct incoming counterparties"),
    ("fan_out", "structure", "count", "distinct outgoing counterparties"),
    ("asset_diversity", "amount_asset", "count", "distinct network-qualified assets"),
    ("splitting_entropy", "structure", "nats", "entropy of observed outgoing amounts"),
    ("peeling_depth", "path", "hops", "bounded conservation-aware forward chain"),
    ("vasp_proximity_hops", "vasp", "hops", "nearest reviewed VASP in eligible graph"),
    ("mixer_interaction_count", "protocol", "count", "reviewed mixer destinations"),
    ("bridge_interaction_count", "protocol", "count", "reviewed bridge destinations"),
    ("prior_complaint_count", "correlation", "count", "independent complaints known before cutoff"),
    ("provider_coverage_fraction", "data_quality", "ratio", "complete provider observations over referenced observations"),
    ("missing_price_fraction", "data_quality", "ratio", "eligible transfers without sourced fiat value"),
)


def register_definitions(session: Session) -> list[FeatureDefinition]:
    result = []
    for name, family, units, aggregation in FEATURE_DEFINITIONS:
        material = {"name": name, "version": FEATURE_SCHEMA_VERSION, "family": family, "units": units,
                    "source": "normalized_non_ml_evidence", "aggregation": aggregation,
                    "window_definition": {"mode": "point_in_time", "partitions": sorted(TEMPORAL_MODES)},
                    "cutoff_policy": {"event_time": "lte_event_cutoff", "available_time": "lte_knowledge_cutoff",
                                      "learned_transforms": "training_fold_only"},
                    "missing_behavior": "explicit_null_and_missing_indicator", "owner": "fresh_new_ml"}
        definition_hash = digest(material)
        existing = session.execute(select(FeatureDefinition).where(
            FeatureDefinition.name == name, FeatureDefinition.version == FEATURE_SCHEMA_VERSION
        )).scalar_one_or_none()
        if existing:
            if existing.definition_hash != definition_hash:
                raise ApplicationError(code="FEATURE_DEFINITION_CONFLICT", message="Feature definition version changed", status_code=409,
                                       details={"feature": name})
            result.append(existing)
            continue
        record = FeatureDefinition(name=name, version=FEATURE_SCHEMA_VERSION, family=family, value_type="decimal",
                                   units=units, source="normalized_non_ml_evidence", aggregation=aggregation,
                                   missing_behavior="explicit_null_and_missing_indicator", owner="fresh_new_ml",
                                   window_definition=material["window_definition"], cutoff_policy=material["cutoff_policy"],
                                   definition_hash=definition_hash)
        session.add(record); session.flush(); result.append(record)
    return result


def _eligible(session: Session, *, event_cutoff, knowledge_cutoff) -> list[NormalizedTransaction]:
    return list(session.execute(select(NormalizedTransaction).where(
        NormalizedTransaction.event_time <= event_cutoff,
        NormalizedTransaction.available_time <= knowledge_cutoff,
        NormalizedTransaction.status.in_(["confirmed", "finalized"]),
    ).order_by(NormalizedTransaction.event_time, NormalizedTransaction.id)).scalars())


def _summary(session: Session, subject: AddressRecord, txs: list[NormalizedTransaction], *, event_cutoff, knowledge_cutoff,
             exclude_complaint_id: str | None) -> tuple[dict, list[str]]:
    incoming = [tx for tx in txs if tx.to_address_id == subject.id]
    outgoing = [tx for tx in txs if tx.from_address_id == subject.id]
    relevant = incoming + outgoing
    assets = {row.id: row for row in session.execute(select(Asset)).scalars()}
    counterparties = {tx.from_address_id for tx in incoming} | {tx.to_address_id for tx in outgoing}
    values = {
        "transfer_count": len(relevant),
        "incoming_count": len(incoming),
        "outgoing_count": len(outgoing),
        "unique_counterparties": len(counterparties),
        "fan_in": len({tx.from_address_id for tx in incoming}),
        "fan_out": len({tx.to_address_id for tx in outgoing}),
        "asset_diversity": len({(assets[tx.asset_id].chain, assets[tx.asset_id].contract_address or assets[tx.asset_id].symbol)
                                for tx in relevant if tx.asset_id in assets}),
    }
    for suffix, window in (("1m", timedelta(minutes=1)), ("5m", timedelta(minutes=5)),
                           ("30m", timedelta(minutes=30)), ("60m", timedelta(minutes=60)),
                           ("24h", timedelta(hours=24)), ("7d", timedelta(days=7)), ("30d", timedelta(days=30))):
        values[f"outgoing_count_{suffix}"] = sum(tx.event_time > event_cutoff - window for tx in outgoing)
    amounts = [float(tx.amount) for tx in outgoing if tx.amount > 0]
    total = sum(amounts)
    values["splitting_entropy"] = None if not amounts else -sum((amount / total) * math.log(amount / total) for amount in amounts)
    values["splitting_entropy_missing"] = not amounts

    outgoing_by_address = defaultdict(list)
    for tx in txs:
        outgoing_by_address[tx.from_address_id].append(tx)
    peel_depth, current, seen = 0, subject.id, {subject.id}
    while peel_depth < 6:
        candidates = outgoing_by_address.get(current, [])
        if len(candidates) != 1:
            break
        next_tx = candidates[0]
        inbound_value = sum((tx.amount for tx in txs if tx.to_address_id == current and tx.asset_id == next_tx.asset_id), Decimal("0"))
        if inbound_value <= 0 or next_tx.amount / inbound_value < Decimal("0.80") or next_tx.to_address_id in seen:
            break
        peel_depth += 1; current = next_tx.to_address_id; seen.add(current)
    values["peeling_depth"] = peel_depth

    protocols = {(row.chain.upper(), row.contract_address.lower()): row for row in session.execute(select(ProtocolContract).where(
        ProtocolContract.valid_from <= knowledge_cutoff,
        (ProtocolContract.valid_to.is_(None) | (ProtocolContract.valid_to > knowledge_cutoff)),
        ProtocolContract.reviewed_at.is_not(None), ProtocolContract.reviewed_at <= knowledge_cutoff,
    )).scalars()}
    addresses = {row.id: row for row in session.execute(select(AddressRecord)).scalars()}
    types = []
    for tx in relevant:
        target = addresses.get(tx.to_address_id)
        protocol = protocols.get((tx.chain.upper(), target.canonical_address.lower())) if target else None
        if protocol: types.append(protocol.protocol_type.lower())
    values["mixer_interaction_count"] = types.count("mixer")
    values["bridge_interaction_count"] = types.count("bridge")

    vasp_ids = set(session.execute(select(EntityAddressAssertion.address_id).join(
        Entity, Entity.id == EntityAddressAssertion.entity_id
    ).where(Entity.entity_type.in_(["vasp", "exchange"]), EntityAddressAssertion.review_status == "reviewed",
            EntityAddressAssertion.recorded_at <= knowledge_cutoff, EntityAddressAssertion.valid_from <= knowledge_cutoff,
            (EntityAddressAssertion.valid_to.is_(None) | (EntityAddressAssertion.valid_to > knowledge_cutoff)))).scalars())
    queue, visited, proximity = deque([(subject.id, 0)]), {subject.id}, None
    contributing_ids = {tx.id for tx in relevant}
    while queue:
        address_id, depth = queue.popleft()
        if address_id in vasp_ids:
            proximity = depth; break
        if depth >= 6: continue
        for tx in outgoing_by_address.get(address_id, []):
            contributing_ids.add(tx.id)
            if tx.to_address_id not in visited:
                visited.add(tx.to_address_id); queue.append((tx.to_address_id, depth + 1))
    values["vasp_proximity_hops"] = proximity
    values["vasp_proximity_missing"] = proximity is None

    complaint_query = select(ComplaintWallet.complaint_id).join(
        ComplaintRecord, ComplaintRecord.id == ComplaintWallet.complaint_id
    ).where(ComplaintWallet.address_id == subject.id, ComplaintRecord.received_time < event_cutoff,
            ComplaintRecord.created_at <= knowledge_cutoff)
    if exclude_complaint_id:
        complaint_query = complaint_query.where(ComplaintWallet.complaint_id != exclude_complaint_id)
    values["prior_complaint_count"] = len(set(session.execute(complaint_query).scalars()))

    observation_ids = {tx.provider_observation_id for tx in relevant}
    observations = list(session.execute(select(ProviderObservation).where(ProviderObservation.id.in_(observation_ids))).scalars()) if observation_ids else []
    values["provider_coverage_fraction"] = None if not observations else sum(row.coverage_state == "complete" for row in observations) / len(observations)
    values["provider_coverage_missing"] = not observations
    values["missing_price_fraction"] = None if not relevant else sum(tx.fiat_value is None for tx in relevant) / len(relevant)
    values["missing_price_fraction_missing"] = not relevant
    return values, sorted(contributing_ids)


def materialize_wallet_features(session: Session, *, subject_address_id: str, mode: str, report_time,
                                event_cutoff, knowledge_cutoff, exclude_complaint_id: str | None = None) -> FeatureSnapshot:
    if mode not in TEMPORAL_MODES:
        raise ApplicationError(code="INVALID_TEMPORAL_MODE", message="Unsupported feature temporal mode", status_code=422)
    subject = session.get(AddressRecord, subject_address_id)
    if subject is None:
        raise ApplicationError(code="FEATURE_SUBJECT_NOT_FOUND", message="Feature subject address not found", status_code=404)
    if knowledge_cutoff < event_cutoff:
        raise ApplicationError(code="INVALID_KNOWLEDGE_CUTOFF", message="Knowledge cutoff cannot precede event cutoff", status_code=422)
    if mode == "report_baseline" and (report_time is None or event_cutoff != report_time or knowledge_cutoff != report_time):
        raise ApplicationError(code="INVALID_BASELINE_CUTOFF", message="Baseline event and knowledge cutoffs must equal T0", status_code=422)
    if mode == "post_report" and (report_time is None or event_cutoff <= report_time):
        raise ApplicationError(code="INVALID_POST_REPORT_CUTOFF", message="Post-report cutoff must be later than T0", status_code=422)
    register_definitions(session)
    all_eligible = _eligible(session, event_cutoff=event_cutoff, knowledge_cutoff=knowledge_cutoff)
    if mode == "post_report":
        baseline_txs = [tx for tx in all_eligible if tx.event_time <= report_time and tx.available_time <= report_time]
        post_txs = [tx for tx in all_eligible if report_time < tx.event_time <= event_cutoff]
        baseline, baseline_ids = _summary(session, subject, baseline_txs, event_cutoff=report_time,
                                          knowledge_cutoff=report_time, exclude_complaint_id=exclude_complaint_id)
        post, post_ids = _summary(session, subject, post_txs, event_cutoff=event_cutoff,
                                  knowledge_cutoff=knowledge_cutoff, exclude_complaint_id=exclude_complaint_id)
        values, evidence_ids = {"baseline": baseline, "post_report": post}, sorted(set(baseline_ids + post_ids))
    else:
        values, evidence_ids = _summary(session, subject, all_eligible, event_cutoff=event_cutoff,
                                        knowledge_cutoff=knowledge_cutoff, exclude_complaint_id=exclude_complaint_id)
    contributing = [tx for tx in all_eligible if tx.id in evidence_ids]
    quality = {"state": "complete" if contributing else "insufficient_as_of_coverage",
               "mode": mode, "future_evidence_excluded": True, "target_complaint_excluded": bool(exclude_complaint_id),
               "pii_features_present": False, "learned_transforms_fitted": False}
    material = {"subject_type": "wallet", "subject_id": subject.id, "schema_version": FEATURE_SCHEMA_VERSION,
                "mode": mode, "report_time": report_time.isoformat() if report_time else None,
                "event_cutoff": event_cutoff.isoformat(), "availability_cutoff": knowledge_cutoff.isoformat(),
                "values": values, "evidence_ids": evidence_ids, "quality": quality}
    snapshot_hash = digest(material)
    existing = session.execute(select(FeatureSnapshot).where(FeatureSnapshot.snapshot_hash == snapshot_hash)).scalar_one_or_none()
    if existing: return existing
    record = FeatureSnapshot(subject_type="wallet", subject_id=subject.id, schema_version=FEATURE_SCHEMA_VERSION,
                             temporal_partition=mode, event_cutoff=event_cutoff, availability_cutoff=knowledge_cutoff,
                             max_event_time=max((tx.event_time for tx in contributing), default=None),
                             max_available_time=max((tx.available_time for tx in contributing), default=None),
                             values=values, evidence_ids=evidence_ids, quality=quality, snapshot_hash=snapshot_hash)
    session.add(record); session.flush(); return record
