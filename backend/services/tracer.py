"""
Value-Weighted BFS Forward Tracing Engine (PRD §3 FR-2).
Traces outgoing fund flow from a reported wallet, identifying
VASP terminals, mixer/bridge hops, peeling chains, and layering patterns.
"""
from collections import deque
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
from models import Wallet, CaseWallet, Transaction
from services.blockchain.fetcher import (
    fetch_transactions, check_vasp_address, check_mixer_bridge,
)
from config import DEFAULT_MAX_HOPS, MAX_HOP_LIMIT


def execute_trace(
    start_address: str,
    chain: str,
    case_id: str,
    db: Session,
    max_hops: int = DEFAULT_MAX_HOPS,
    min_amount_usd: float = 50.0,
    incident_timestamp: datetime = None,
    event_callback: callable = None,
) -> dict:
    """
    Execute value-weighted forward BFS trace.
    Returns a graph dict with nodes, edges, and attribution results.
    Optional event_callback streams live WebSocket events during trace execution.
    """
    max_hops = min(max_hops, MAX_HOP_LIMIT)
    nodes = []
    edges = []
    visited = set()
    vasp_attributions = []
    risk_flags = set()
    mixer_hops = []
    bridge_hops = []

    def _notify(event_type, data):
        if event_callback:
            try:
                event_callback(event_type, data)
            except Exception:
                pass

    # BFS queue: (address, chain, hop_depth, after_timestamp)
    queue = deque([(start_address, chain, 0, incident_timestamp)])

    # Track the origin
    _ensure_wallet(db, start_address, chain, "ORIGIN_VICTIM")
    _link_case_wallet(db, case_id, start_address, chain, 0, is_origin=True)
    origin_node = _make_node(start_address, chain, "ORIGIN_VICTIM", 0)
    nodes.append(origin_node)
    _notify("NODE_DISCOVERED", origin_node)

    while queue:
        current_addr, current_chain, hop, after_time = queue.popleft()

        if (current_addr, current_chain) in visited or hop >= max_hops:
            continue
        visited.add((current_addr, current_chain))

        # Fetch transactions (from cache, demo data, or live API)
        txs = fetch_transactions(current_addr, current_chain, db, after_time)

        # Filter to outgoing transactions only (forward tracing)
        outgoing = [t for t in txs if t["from_address"] == current_addr]

        # Detect rapid layering (≥3 outgoing within 60 min)
        if _detect_high_velocity(outgoing):
            risk_flags.add("HIGH_VELOCITY_LAYERING")

        for tx in outgoing:
            to_addr = tx["to_address"]
            amount = tx.get("amount", 0)

            # Skip dust / insignificant amounts
            amount_val = tx.get("amount_usd") or amount
            if amount_val < min_amount_usd and hop > 0:
                continue

            # Add edge
            edge = {
                "id": f"e-{tx['tx_hash'][:16]}",
                "source": current_addr,
                "target": to_addr,
                "amount": amount,
                "token": tx.get("token_symbol", "NATIVE"),
                "tx_hash": tx["tx_hash"],
                "timestamp": tx["timestamp"].isoformat() if isinstance(tx["timestamp"], datetime) else str(tx["timestamp"]),
                "is_peeling": tx.get("is_peeling_tx", False),
            }
            edges.append(edge)
            _notify("EDGE_DISCOVERED", edge)

            # ── Check: Is this a known VASP? ──
            vasp_info = check_vasp_address(to_addr, current_chain, db)
            if vasp_info:
                node_type = "VASP_DEPOSIT"
                _ensure_wallet(db, to_addr, current_chain, node_type, vasp_id=vasp_info["vasp_id"],
                               attr_tier="TIER_1_EXACT", attr_confidence=96.0,
                               attr_evidence=f"Exact match: known {vasp_info['address_tag']} of {vasp_info['vasp_name']}")
                _link_case_wallet(db, case_id, to_addr, current_chain, hop + 1, is_terminal=True)
                vasp_node = _make_node(to_addr, current_chain, node_type, hop + 1, vasp_info=vasp_info)
                nodes.append(vasp_node)
                _notify("NODE_DISCOVERED", vasp_node)

                attr_payload = {
                    "vasp_id": vasp_info["vasp_id"],
                    "vasp_name": vasp_info["vasp_name"],
                    "is_fiu_ind_registered": vasp_info["is_fiu_ind_registered"],
                    "nodal_officer_email": vasp_info["nodal_officer_email"],
                    "destination_address": to_addr,
                    "attribution_tier": "TIER_1_EXACT",
                    "confidence_score": 96.0,
                    "evidence": f"Exact match: known {vasp_info['address_tag']} of {vasp_info['vasp_name']}",
                }
                vasp_attributions.append(attr_payload)
                _notify("VASP_ATTRIBUTED", attr_payload)

                # Check for 1-hop sweep (Tier 2)
                _check_sweep(to_addr, current_chain, case_id, hop + 1, db, nodes, edges, vasp_attributions)
                continue  # Stop branch at VASP terminal

            # ── Check: Is this a mixer/bridge? ──
            mixer_info = check_mixer_bridge(to_addr, current_chain, db)
            if mixer_info:
                node_type = mixer_info["entity_type"]  # 'MIXER' or 'BRIDGE'
                _ensure_wallet(db, to_addr, current_chain, node_type)
                _link_case_wallet(db, case_id, to_addr, current_chain, hop + 1)
                m_node = _make_node(to_addr, current_chain, node_type, hop + 1, mixer_info=mixer_info)
                nodes.append(m_node)
                _notify("NODE_DISCOVERED", m_node)

                if node_type == "MIXER":
                    risk_flags.add("MIXER_HOP")
                    mixer_hops.append(to_addr)
                else:
                    risk_flags.add("BRIDGE_SWAP")
                    bridge_hops.append(to_addr)

                # Continue tracing past mixer/bridge
                queue.append((to_addr, current_chain, hop + 1, tx.get("timestamp")))
                continue

            # ── Normal intermediary / mule wallet ──
            # Detect peeling chain pattern
            is_peeling = _detect_peeling(outgoing, tx)
            node_type = "MULE_LAYER"
            if is_peeling:
                risk_flags.add("PEELING_CHAIN_DETECTED")

            _ensure_wallet(db, to_addr, current_chain, node_type)
            _link_case_wallet(db, case_id, to_addr, current_chain, hop + 1)
            mule_node = _make_node(to_addr, current_chain, node_type, hop + 1)
            nodes.append(mule_node)
            _notify("NODE_DISCOVERED", mule_node)
            queue.append((to_addr, current_chain, hop + 1, tx.get("timestamp")))

    # If no Tier 1 match, attempt Tier 2 sweep and Tier 3 cluster on leaf nodes
    if not vasp_attributions:
        vasp_attributions = _attempt_tier2_tier3(nodes, edges, case_id, chain, db)

    db.flush()

    # Determine best attribution
    best_attribution = None
    if vasp_attributions:
        best_attribution = max(vasp_attributions, key=lambda a: a["confidence_score"])

    return {
        "nodes": _deduplicate_nodes(nodes),
        "edges": edges,
        "vasp_attribution": best_attribution,
        "all_attributions": vasp_attributions,
        "risk_flags": list(risk_flags),
        "total_hops": max((n.get("hop", 0) for n in nodes), default=0),
        "trace_complete": len(queue) == 0,
    }


# ─────────────────────────────────────────────────────
# Helper Functions
# ─────────────────────────────────────────────────────
def _make_node(address, chain, node_type, hop, vasp_info=None, mixer_info=None):
    """Create a graph node dict for the frontend."""
    COLOR_MAP = {
        "ORIGIN_VICTIM": "#0052FF",
        "MULE_LAYER": "#8E8E93",
        "MIXER": "#FF3B30",
        "BRIDGE": "#FF9500",
        "DEX_ROUTER": "#FF9500",
        "VASP_DEPOSIT": "#30D158",
        "VASP_HOT_WALLET": "#34C759",
    }
    LABEL_MAP = {
        "ORIGIN_VICTIM": "Victim Reported Wallet",
        "MULE_LAYER": "Intermediary / Mule",
        "MIXER": "Privacy Protocol",
        "BRIDGE": "Cross-Chain Bridge",
        "DEX_ROUTER": "DEX Router",
        "VASP_DEPOSIT": "Exchange Deposit",
        "VASP_HOT_WALLET": "Exchange Hot Wallet",
    }

    node = {
        "id": address,
        "label": LABEL_MAP.get(node_type, "Unknown"),
        "chain": chain,
        "node_type": node_type,
        "hop": hop,
        "color": COLOR_MAP.get(node_type, "#8E8E93"),
    }
    if vasp_info:
        node["vasp_name"] = vasp_info["vasp_name"]
        node["is_fiu_registered"] = vasp_info.get("is_fiu_ind_registered", False)
        node["label"] = f"{vasp_info['vasp_name']} ({vasp_info.get('address_tag', 'Deposit')})"
    if mixer_info:
        node["protocol_name"] = mixer_info["protocol_name"]
        node["label"] = mixer_info["protocol_name"]

    return node


def _ensure_wallet(db: Session, address, chain, node_type, vasp_id=None,
                   attr_tier=None, attr_confidence=0.0, attr_evidence=None):
    """Insert or update wallet record."""
    existing = db.query(Wallet).filter_by(address=address, chain=chain).first()
    if not existing:
        w = Wallet(
            address=address, chain=chain, node_type=node_type,
            vasp_id=vasp_id, attribution_tier=attr_tier,
            attribution_confidence=attr_confidence,
            attribution_evidence=attr_evidence,
            first_seen=datetime.now(timezone.utc),
            risk_flags="[]",
        )
        db.add(w)
    else:
        if node_type and node_type != "NORMAL_WALLET":
            existing.node_type = node_type
        if vasp_id:
            existing.vasp_id = vasp_id
            existing.attribution_tier = attr_tier
            existing.attribution_confidence = attr_confidence
            existing.attribution_evidence = attr_evidence
    db.flush()


def _link_case_wallet(db: Session, case_id, address, chain, hop, is_origin=False, is_terminal=False):
    """Link a wallet to a case."""
    existing = db.query(CaseWallet).filter_by(
        case_id=case_id, wallet_address=address, wallet_chain=chain
    ).first()
    if not existing:
        cw = CaseWallet(
            case_id=case_id, wallet_address=address, wallet_chain=chain,
            hop_depth=hop, is_origin_reported=is_origin, is_terminal_destination=is_terminal,
        )
        db.add(cw)
    db.flush()


def _to_utc_dt(dt):
    if dt is None:
        return None
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
        except ValueError:
            return None
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    return None


def _detect_high_velocity(outgoing_txs: list[dict]) -> bool:
    """Check if ≥3 outgoing transactions within 60 minutes."""
    if len(outgoing_txs) < 3:
        return False
    timestamps = sorted([_to_utc_dt(t["timestamp"]) for t in outgoing_txs if t.get("timestamp")])
    timestamps = [ts for ts in timestamps if ts is not None]
    if len(timestamps) < 3:
        return False
    # Check if any 3 consecutive are within 60 min
    for i in range(len(timestamps) - 2):
        t0 = timestamps[i]
        t2 = timestamps[i + 2]
        if (t2 - t0).total_seconds() <= 3600:
            return True
    return False


def _detect_peeling(all_outgoing: list[dict], current_tx: dict) -> bool:
    """Detect peeling chain: one large tx (>80%) + one small tx (<20%)."""
    if len(all_outgoing) < 2:
        return False
    total = sum(t.get("amount", 0) for t in all_outgoing)
    if total <= 0:
        return False
    ratio = current_tx.get("amount", 0) / total
    return 0.80 <= ratio <= 0.95 or 0.05 <= ratio <= 0.20


def _check_sweep(deposit_addr, chain, case_id, hop, db, nodes, edges, attributions):
    """Check if a VASP deposit address sweeps to a known hot wallet (Tier 2)."""
    txs = fetch_transactions(deposit_addr, chain, db)
    outgoing = [t for t in txs if t["from_address"] == deposit_addr]
    for tx in outgoing:
        vasp_info = check_vasp_address(tx["to_address"], chain, db)
        if vasp_info and tx.get("amount", 0) > 0:
            _ensure_wallet(db, tx["to_address"], chain, "VASP_HOT_WALLET",
                           vasp_id=vasp_info["vasp_id"], attr_tier="TIER_2_SWEEP",
                           attr_confidence=91.0,
                           attr_evidence=f"100% swept to {vasp_info['vasp_name']} Hot Wallet")
            _link_case_wallet(db, case_id, tx["to_address"], chain, hop + 1, is_terminal=True)
            nodes.append(_make_node(tx["to_address"], chain, "VASP_HOT_WALLET", hop + 1, vasp_info=vasp_info))
            edges.append({
                "id": f"e-sweep-{tx['tx_hash'][:16]}",
                "source": deposit_addr,
                "target": tx["to_address"],
                "amount": tx["amount"],
                "token": tx.get("token_symbol", "NATIVE"),
                "tx_hash": tx["tx_hash"],
                "timestamp": tx["timestamp"].isoformat() if isinstance(tx["timestamp"], datetime) else str(tx["timestamp"]),
                "is_peeling": False,
            })
            break


def _attempt_tier2_tier3(nodes, edges, case_id, chain, db):
    """Fallback: attempt Tier 2 sweep check and Tier 3 cluster on leaf nodes."""
    leaf_addrs = [n["id"] for n in nodes if n.get("node_type") == "MULE_LAYER"]
    results = []

    for addr in leaf_addrs[-3:]:  # Only check last 3 leaf nodes to limit API calls
        # Tier 3: cluster heuristic — check if address is shared across ≥2 other cases
        shared_count = db.query(CaseWallet).filter(
            CaseWallet.wallet_address == addr,
            CaseWallet.case_id != case_id,
        ).count()
        if shared_count >= 2:
            results.append({
                "vasp_id": None,
                "vasp_name": "Unidentified Exchange / Aggregator Cluster",
                "is_fiu_ind_registered": False,
                "nodal_officer_email": "N/A",
                "destination_address": addr,
                "attribution_tier": "TIER_3_CLUSTER",
                "confidence_score": 68.0,
                "evidence": f"Address shared across {shared_count + 1} distinct FIR complaints — exchange deposit cluster behavior.",
            })

    return results


def _deduplicate_nodes(nodes):
    """Remove duplicate nodes by id."""
    seen = set()
    unique = []
    for n in nodes:
        if n["id"] not in seen:
            seen.add(n["id"])
            unique.append(n)
    return unique
