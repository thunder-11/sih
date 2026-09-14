"""Versioned, explainable deterministic findings for Phase 6.

This module contains no learned logic.  Every state is derived from immutable
normalized transfers and directory facts available to the selected run.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select, delete
from sqlalchemy.orm import Session

from app.persistence.models import (
    AddressRecord, AnalysisRun, Asset, NormalizedTransaction, ProtocolContract,
    RiskResult, RuleFinding,
)
from app.persistence.models import ComplaintRecord, ComplaintWallet


POLICY_VERSION = "prd-six-factor-v1"
WEIGHTS = {
    "mixer_interaction": 30,
    "bridge_or_swap": 20,
    "high_velocity_60m": 15,
    "peeling_chain": 15,
    "new_wallet_7d": 10,
    "linked_complaints": 10,
}


def risk_tier(score: int) -> str:
    if score >= 85:
        return "critical"
    if score >= 60:
        return "high"
    if score >= 30:
        return "medium"
    return "low"


def _evidence(run: AnalysisRun, db: Session):
    addresses = {row.id: row for row in db.execute(select(AddressRecord)).scalars()}
    assets = {row.id: row for row in db.execute(select(Asset)).scalars()}
    rows = list(db.execute(select(NormalizedTransaction).where(
        NormalizedTransaction.event_time <= run.event_cutoff,
        NormalizedTransaction.available_time <= run.cutoff_available_time,
        NormalizedTransaction.status.in_(["confirmed", "finalized"]),
    ).order_by(NormalizedTransaction.event_time, NormalizedTransaction.id)).scalars())
    reachable, frontier, seen = [], set(run.root_address_ids), set(run.root_address_ids)
    for _ in range(min(6, max(1, int(run.parameters.get("max_hops", 4))))):
        level = [tx for tx in rows if tx.from_address_id in frontier]
        if not level:
            break
        reachable.extend(level)
        frontier = {tx.to_address_id for tx in level if tx.to_address_id not in seen}
        seen.update(frontier)
    return reachable, addresses, assets


def evaluate(run: AnalysisRun, db: Session) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    txs, addresses, assets = _evidence(run, db)
    protocols = {(row.chain.upper(), row.contract_address.lower()): row for row in db.execute(
        select(ProtocolContract).where(
            ProtocolContract.valid_from <= run.cutoff_available_time,
            (ProtocolContract.valid_to.is_(None) | (ProtocolContract.valid_to > run.cutoff_available_time)),
        )
    ).scalars()}
    by_sender: dict[str, list[NormalizedTransaction]] = defaultdict(list)
    by_receiver: dict[str, list[NormalizedTransaction]] = defaultdict(list)
    for tx in txs:
        by_sender[tx.from_address_id].append(tx)
        by_receiver[tx.to_address_id].append(tx)

    evidence_ids = [tx.id for tx in txs]
    findings: list[dict[str, Any]] = []

    def add(rule_id: str, state: str, contribution: int = 0, **measured):
        findings.append({"rule_id": rule_id, "assessment_state": state, "contribution": contribution,
                         "measured_values": measured, "evidence_snapshot_ids": evidence_ids})

    protocol_hits: dict[str, list[dict[str, str]]] = defaultdict(list)
    for tx in txs:
        target = addresses.get(tx.to_address_id)
        if not target:
            continue
        protocol = protocols.get((tx.chain.upper(), target.canonical_address.lower()))
        if protocol:
            protocol_hits[protocol.protocol_type.lower()].append({"transfer_id": tx.id, "protocol": protocol.protocol_name})
    mixers = protocol_hits.get("mixer", [])
    bridges = protocol_hits.get("bridge", []) + protocol_hits.get("swap", []) + protocol_hits.get("dex", [])
    add("mixer_interaction", "triggered" if mixers else "not_triggered", WEIGHTS["mixer_interaction"] if mixers else 0,
        matches=mixers, boundary="unresolved_exit")
    add("bridge_or_swap", "triggered" if bridges else "not_triggered", WEIGHTS["bridge_or_swap"] if bridges else 0,
        matches=bridges, continuity="requires_verified_cross_chain_link")

    velocity_windows = []
    rapid_windows = []
    for sender, outgoing in by_sender.items():
        outgoing.sort(key=lambda item: item.event_time)
        for index, first in enumerate(outgoing):
            in_60 = [item for item in outgoing[index:] if item.event_time - first.event_time <= timedelta(minutes=60)]
            in_30 = [item for item in in_60 if item.event_time - first.event_time <= timedelta(minutes=30)]
            if len(in_30) >= 3:
                rapid_windows.append({"address_id": sender, "transfer_ids": [item.id for item in in_30], "count": len(in_30)})
            if len(in_60) >= 3:
                velocity_windows.append({"address_id": sender, "transfer_ids": [item.id for item in in_60], "count": len(in_60)})
                break
    add("high_velocity_60m", "triggered" if velocity_windows else "not_triggered",
        WEIGHTS["high_velocity_60m"] if velocity_windows else 0, windows=velocity_windows)
    add("rapid_dispersal_30m", "triggered" if rapid_windows else "not_triggered", windows=rapid_windows)

    peel_steps = []
    for address_id, incoming in by_receiver.items():
        incoming_by_asset = defaultdict(lambda: Decimal("0"))
        for tx in incoming:
            incoming_by_asset[tx.asset_id] += tx.amount
        for tx in by_sender.get(address_id, []):
            denominator = incoming_by_asset.get(tx.asset_id, Decimal("0"))
            if denominator > 0:
                ratio = tx.amount / denominator
                if ratio >= Decimal("0.80"):
                    peel_steps.append({"address_id": address_id, "transfer_id": tx.id, "retained_fraction": str(1 - ratio)})
    peeling = len(peel_steps) >= 2
    add("peeling_chain", "triggered" if peeling else "not_triggered", WEIGHTS["peeling_chain"] if peeling else 0,
        steps=peel_steps, minimum_repeated_steps=2)

    if txs:
        earliest = min(tx.event_time for tx in txs)
        age = run.event_cutoff - earliest
        new_wallet = age <= timedelta(days=7)
        add("new_wallet_7d", "triggered" if new_wallet else "not_triggered", WEIGHTS["new_wallet_7d"] if new_wallet else 0,
            first_evidenced_activity=earliest.isoformat(), age_seconds=max(0, int(age.total_seconds())),
            limitation="first evidenced activity is not guaranteed to be first on-chain activity")
    else:
        add("new_wallet_7d", "unknown", first_evidenced_activity=None, limitation="no eligible transfer evidence")

    complaint_ids = set(db.execute(select(ComplaintWallet.complaint_id).where(
        ComplaintWallet.address_id.in_(run.root_address_ids)
    )).scalars())
    victim_ids = set(db.execute(select(ComplaintRecord.victim_id).where(
        ComplaintRecord.id.in_(complaint_ids), ComplaintRecord.victim_id.is_not(None)
    )).scalars()) if complaint_ids else set()
    linked_count = max(0, len(complaint_ids) - 1)
    linked = linked_count >= 2 and len(victim_ids) >= 3
    add("linked_complaints", "triggered" if linked else "not_triggered", WEIGHTS["linked_complaints"] if linked else 0,
        distinct_complaint_count=len(complaint_ids), distinct_victim_count=len(victim_ids), distinct_other_complaints=linked_count)

    fan_out = [{"address_id": key, "count": len(value)} for key, value in by_sender.items() if len(value) >= 3]
    fan_in = [{"address_id": key, "count": len(value)} for key, value in by_receiver.items() if len(value) >= 3]
    add("fan_out", "triggered" if fan_out else "not_triggered", addresses=fan_out)
    add("fan_in_consolidation", "triggered" if fan_in else "not_triggered", addresses=fan_in)
    add("path_depth", "triggered" if len(txs) >= 4 else "not_triggered", observed_transfer_count=len(txs), threshold=4)

    assessed = [item for item in findings if item["rule_id"] in WEIGHTS and item["assessment_state"] != "unknown"]
    base_score = sum(item["contribution"] for item in assessed)

    # Elliptic++ ML Model inference
    from services.risk_scoring import predict_ml_wallet_risk
    ml_eval = None
    ml_score = 0
    if run.root_address_ids:
        root_rec = db.get(AddressRecord, run.root_address_ids[0])
        if root_rec:
            ml_eval = predict_ml_wallet_risk(root_rec.canonical_address, root_rec.chain, db)
            if ml_eval and ml_eval.get("status") == "inferred":
                ml_score = ml_eval.get("ml_risk_score", 0)
                add("ml_elliptic_plus_prediction", "triggered", ml_score,
                    ml_probability=ml_eval.get("ml_probability"),
                    raw_probability=ml_eval.get("raw_probability"),
                    model_version=ml_eval.get("model_version"),
                    features_analyzed=ml_eval.get("features_analyzed"))

    score = min(100, max(base_score, ml_score, 20 if (base_score > 0 or ml_eval) else 0))
    result = {"risk_kind": "composite_ml_and_rules", "score": score, "tier": risk_tier(score),
              "policy_version": POLICY_VERSION, "assessment_state": "assessed" if (assessed or ml_eval) else "unknown",
              "findings": findings, "ml_prediction": ml_eval,
              "limitations": ["Rule and ML output is decision support, not a criminality determination."]}
    return findings, result


def persist_evaluation(run: AnalysisRun, db: Session) -> RiskResult:
    existing = db.execute(select(RiskResult).where(
        RiskResult.run_id == run.id, RiskResult.rule_version == POLICY_VERSION
    ).order_by(RiskResult.revision.desc())).scalars().first()
    if existing:
        return existing
    findings, result = evaluate(run, db)
    db.execute(delete(RuleFinding).where(RuleFinding.run_id == run.id, RuleFinding.policy_version == POLICY_VERSION))
    for finding in findings:
        db.add(RuleFinding(run_id=run.id, rule_id=finding["rule_id"], policy_version=POLICY_VERSION,
                           temporal_partition="run_snapshot", measured_values=finding["measured_values"],
                           contribution=finding["contribution"], assessment_state=finding["assessment_state"],
                           evidence_snapshot_ids=finding["evidence_snapshot_ids"]))
    revision = (db.execute(select(func.coalesce(func.max(RiskResult.revision), 0)).where(RiskResult.case_id == run.case_id)).scalar_one() + 1)
    record = RiskResult(case_id=run.case_id, run_id=run.id, revision=revision, score=result["score"], tier=result["tier"],
                        rule_version=POLICY_VERSION, signals=result["findings"],
                        evidence_snapshot_ids=sorted({item for finding in findings for item in finding["evidence_snapshot_ids"]}))
    db.add(record)
    db.flush()
    return record
