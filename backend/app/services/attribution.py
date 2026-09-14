"""Point-in-time entity attribution with conservative privacy boundaries."""

from __future__ import annotations

from collections import defaultdict, deque
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.persistence.models import (
    AddressRecord, AnalysisRun, Cluster, ClusterMembership, Entity,
    EntityAddressAssertion, NormalizedTransaction, ProtocolContract,
)


VASP_TYPES = {"vasp", "exchange"}
PUBLIC_SERVICE_TYPES = {"vasp", "exchange", "mixer", "bridge", "swap", "dex", "protocol", "issuer", "foundation", "treasury"}


def _active_labels(run: AnalysisRun, db: Session):
    entities = {row.id: row for row in db.execute(select(Entity)).scalars()}
    labels = defaultdict(list)
    for assertion in db.execute(select(EntityAddressAssertion).where(
        EntityAddressAssertion.review_status == "reviewed",
        EntityAddressAssertion.recorded_at <= run.cutoff_available_time,
        EntityAddressAssertion.valid_from <= run.cutoff_available_time,
        (EntityAddressAssertion.valid_to.is_(None) | (EntityAddressAssertion.valid_to > run.cutoff_available_time)),
    )).scalars():
        entity = entities.get(assertion.entity_id)
        if entity and entity.status == "active":
            labels[assertion.address_id].append((entity, assertion))
    return labels


def attribute_run(run: AnalysisRun, db: Session) -> dict:
    addresses = {row.id: row for row in db.execute(select(AddressRecord)).scalars()}
    labels = _active_labels(run, db)
    protocols = {(row.chain.upper(), row.contract_address.lower()): row for row in db.execute(select(ProtocolContract).where(
        ProtocolContract.valid_from <= run.cutoff_available_time,
        (ProtocolContract.valid_to.is_(None) | (ProtocolContract.valid_to > run.cutoff_available_time)),
    )).scalars()}
    txs = list(db.execute(select(NormalizedTransaction).where(
        NormalizedTransaction.event_time <= run.event_cutoff,
        NormalizedTransaction.available_time <= run.cutoff_available_time,
        NormalizedTransaction.status.in_(["confirmed", "finalized"]),
    ).order_by(NormalizedTransaction.event_time, NormalizedTransaction.id)).scalars())
    outgoing = defaultdict(list)
    for tx in txs:
        outgoing[tx.from_address_id].append(tx)

    max_hops = min(6, max(1, int(run.parameters.get("max_hops", 4))))
    queue = deque((root, []) for root in run.root_address_ids)
    visited = set(run.root_address_ids)
    reachable_transfer_ids = set()
    attributions, boundaries = [], []
    while queue:
        current, path = queue.popleft()
        if len(path) >= max_hops:
            continue
        for tx in outgoing.get(current, []):
            reachable_transfer_ids.add(tx.id)
            step = {"transfer_id": tx.id, "tx_hash": tx.tx_hash, "chain": tx.chain,
                    "from_address_id": tx.from_address_id, "to_address_id": tx.to_address_id,
                    "amount": str(tx.amount), "asset_id": tx.asset_id, "event_time": tx.event_time.isoformat()}
            candidate_path = path + [step]
            exact = [(entity, assertion) for entity, assertion in labels.get(tx.to_address_id, []) if entity.entity_type.lower() in VASP_TYPES]
            if exact:
                for entity, assertion in exact:
                    target = addresses[tx.to_address_id]
                    attributions.append({"entity_id": entity.id, "vasp_name": entity.canonical_name,
                                         "deposit_address": target.canonical_address, "chain": target.chain,
                                         "tier": "exact", "confidence_kind": "heuristic", "score": 95,
                                         "hop_count": len(candidate_path), "path": candidate_path,
                                         "label_sources": [{"assertion_id": assertion.id, "source": assertion.source,
                                                            "evidence_uri": assertion.evidence_uri,
                                                            "recorded_at": assertion.recorded_at.isoformat()}],
                                         "limitations": ["Directory attribution identifies a service destination, not its customer."]})
                continue
            target = addresses.get(tx.to_address_id)
            protocol = protocols.get((tx.chain.upper(), target.canonical_address.lower())) if target else None
            if protocol and protocol.protocol_type.lower() in {"mixer", "bridge", "swap"}:
                boundaries.append({"type": protocol.protocol_type.lower(), "protocol": protocol.protocol_name,
                                   "address": target.canonical_address, "chain": target.chain,
                                   "transfer_id": tx.id, "status": "unresolved",
                                   "limitation": "No exit or destination is inferred without a verified protocol link."})
                continue
            if tx.to_address_id not in visited:
                visited.add(tx.to_address_id)
                queue.append((tx.to_address_id, candidate_path))

    # Corroborating sweep: an unlabeled receiver forwards >=85% of the same asset
    # within six hours to an exact VASP address.
    for first in (item for item in txs if item.id in reachable_transfer_ids):
        if labels.get(first.to_address_id):
            continue
        for second in (item for item in outgoing.get(first.to_address_id, []) if item.id in reachable_transfer_ids):
            exact = [(e, a) for e, a in labels.get(second.to_address_id, []) if e.entity_type.lower() in VASP_TYPES]
            if not exact or second.asset_id != first.asset_id or second.event_time < first.event_time:
                continue
            elapsed = second.event_time - first.event_time
            ratio = second.amount / first.amount if first.amount else Decimal("0")
            if elapsed <= timedelta(hours=6) and ratio >= Decimal("0.85"):
                entity, assertion = exact[0]
                candidate = addresses[first.to_address_id]
                attributions.append({"entity_id": entity.id, "vasp_name": entity.canonical_name,
                                     "deposit_address": candidate.canonical_address, "chain": candidate.chain,
                                     "tier": "sweep", "confidence_kind": "heuristic", "score": 85,
                                     "hop_count": 2, "path": [{"transfer_id": first.id}, {"transfer_id": second.id}],
                                     "label_sources": [{"assertion_id": assertion.id, "source": assertion.source}],
                                     "measured": {"same_asset_fraction": str(ratio), "elapsed_seconds": int(elapsed.total_seconds()),
                                                  "observed_residual": str(first.amount - second.amount)},
                                     "limitations": ["Sweep behavior is corroboration, not proof that the candidate is a customer deposit address."]})

    attributions.sort(key=lambda item: (item["hop_count"], -item["score"], item["entity_id"]))
    return {"run_id": run.id, "attributions": attributions, "nearest": attributions[0] if attributions else None,
            "boundaries": boundaries, "coverage": run.coverage,
            "limitations": ["Attribution confidence is a versioned heuristic and is not ML probability."]}


def cluster_payload(run: AnalysisRun, db: Session) -> list[dict]:
    addresses = {row.id: row for row in db.execute(select(AddressRecord)).scalars()}
    labels = _active_labels(run, db)
    txs = list(db.execute(select(NormalizedTransaction).where(
        NormalizedTransaction.event_time <= run.event_cutoff,
        NormalizedTransaction.available_time <= run.cutoff_available_time,
        NormalizedTransaction.status.in_(["confirmed", "finalized"]),
    )).scalars())
    reachable = set(run.root_address_ids)
    frontier = set(run.root_address_ids)
    for _ in range(min(6, max(1, int(run.parameters.get("max_hops", 4))))):
        level = [tx for tx in txs if tx.from_address_id in frontier]
        frontier = {tx.to_address_id for tx in level} - reachable
        reachable.update(frontier)
    relevant_cluster_ids = set(db.execute(select(ClusterMembership.cluster_id).where(
        ClusterMembership.address_id.in_(reachable)
    )).scalars()) if reachable else set()
    clusters = list(db.execute(select(Cluster).where(
        Cluster.id.in_(relevant_cluster_ids), Cluster.available_time <= run.cutoff_available_time
    )).scalars()) if relevant_cluster_ids else []
    result = []
    for cluster in clusters:
        memberships = list(db.execute(select(ClusterMembership).where(ClusterMembership.cluster_id == cluster.id)).scalars())
        public = []
        members = []
        for membership in memberships:
            member_labels = labels.get(membership.address_id, [])
            public.extend(entity.canonical_name for entity, _ in member_labels if entity.entity_type.lower() in PUBLIC_SERVICE_TYPES)
            address = addresses.get(membership.address_id)
            if address:
                members.append({"address_id": address.id, "address": address.canonical_address, "chain": address.chain,
                                "confidence": str(membership.confidence), "evidence": membership.evidence})
        result.append({"id": cluster.id, "version": cluster.version, "source_method": cluster.source_method,
                       "confidence": str(cluster.confidence), "members": members,
                       "ownership_claim": False, "shared_public_service": bool(public),
                       "false_positive_controls": {"public_service_labels": sorted(set(public)),
                                                   "public_service_only_is_ownership_evidence": False}})
    return result
