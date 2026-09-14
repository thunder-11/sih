"""
Composite Forensic Risk Scoring Engine (PRD §3 FR-4).
Combines Elliptic++ Machine Learning Classifier inference with topological heuristics.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
import numpy as np
import pandas as pd
from sqlalchemy.orm import Session
from sqlalchemy import select
from models import CaseWallet, Transaction
from app.persistence.models import AddressRecord, NormalizedTransaction
from config import (
    RISK_WEIGHT_MIXER, RISK_WEIGHT_BRIDGE, RISK_WEIGHT_HIGH_VELOCITY,
    RISK_WEIGHT_PEELING, RISK_WEIGHT_BURNER, RISK_WEIGHT_MULTI_COMPLAINT,
)

# Cache loaded ML model in memory
_ML_MODEL_CACHE = None


def get_ml_model():
    global _ML_MODEL_CACHE
    if _ML_MODEL_CACHE is not None:
        return _ML_MODEL_CACHE
    try:
        import joblib
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        model_path = os.path.join(base_dir, "artifacts", "ml", "phase8-elliptic-plus-wallet-v1", "model.joblib")
        if os.path.exists(model_path):
            pkg = joblib.load(model_path)
            _ML_MODEL_CACHE = {
                "model": pkg["model"],
                "calibrator": pkg["calibrator"],
                "feature_names": pkg["feature_names"],
                "version": "phase8-elliptic-plus-wallet-v1",
            }
            return _ML_MODEL_CACHE
    except Exception:
        pass
    return None


def predict_ml_wallet_risk(wallet_address: str, chain: str, db: Session) -> dict:
    """Run inference with the trained Elliptic++ ML pipeline on live wallet evidence."""
    ml_pkg = get_ml_model()
    if not ml_pkg:
        return {"ml_risk_score": 0, "ml_probability": 0.0, "status": "model_not_found"}

    try:
        addr = db.execute(select(AddressRecord).where(
            AddressRecord.canonical_address == wallet_address
        )).scalars().first()

        in_txs = []
        out_txs = []
        if addr:
            in_txs = db.execute(select(NormalizedTransaction).where(NormalizedTransaction.to_address_id == addr.id)).scalars().all()
            out_txs = db.execute(select(NormalizedTransaction).where(NormalizedTransaction.from_address_id == addr.id)).scalars().all()

        n_send = len(out_txs)
        n_recv = len(in_txs)
        tot = n_send + n_recv
        sent_amts = [float(t.amount) for t in out_txs] if out_txs else [0.0]
        recv_amts = [float(t.amount) for t in in_txs] if in_txs else [0.0]
        all_amts = sent_amts + recv_amts

        row = {f: 0.0 for f in ml_pkg["feature_names"]}
        row["num_txs_as_sender"] = float(n_send)
        row["num_txs_as receiver"] = float(n_recv)
        row["total_txs"] = float(tot)
        row["btc_sent_total"] = float(sum(sent_amts))
        row["btc_sent_min"] = float(min(sent_amts))
        row["btc_sent_max"] = float(max(sent_amts))
        row["btc_sent_mean"] = float(sum(sent_amts) / max(1, n_send))
        row["btc_received_total"] = float(sum(recv_amts))
        row["btc_received_min"] = float(min(recv_amts))
        row["btc_received_max"] = float(max(recv_amts))
        row["btc_received_mean"] = float(sum(recv_amts) / max(1, n_recv))
        row["btc_transacted_total"] = float(sum(all_amts))
        row["btc_transacted_min"] = float(min(all_amts))
        row["btc_transacted_max"] = float(max(all_amts))
        row["btc_transacted_mean"] = float(sum(all_amts) / max(1, tot))

        df = pd.DataFrame([row])
        raw_proba = float(ml_pkg["model"].predict_proba(df)[0, 1])
        calibrated_proba = float(ml_pkg["calibrator"].predict(np.array([raw_proba]))[0])

        ml_score = int(round(calibrated_proba * 100))
        return {
            "ml_risk_score": ml_score,
            "ml_probability": round(calibrated_proba, 4),
            "raw_probability": round(raw_proba, 4),
            "model_version": ml_pkg["version"],
            "features_analyzed": tot,
            "status": "inferred",
        }
    except Exception as exc:
        return {"ml_risk_score": 0, "ml_probability": 0.0, "status": f"error: {exc}"}


def compute_risk_score(
    case_id: str,
    risk_flags: list[str],
    wallet_address: str,
    chain: str,
    db: Session,
) -> dict:
    """
    Compute composite risk score combining ML model prediction and topological heuristics.
    Returns dict with score, tier, and contributing factors.
    """
    score = 0
    factors = []

    # 1. Elliptic++ ML Model Inference
    ml_res = predict_ml_wallet_risk(wallet_address, chain, db)
    ml_score = ml_res.get("ml_risk_score", 0)
    if ml_res.get("status") == "inferred":
        factors.append({
            "factor": "ML_ELLIPTIC_PLUS_CLASSIFICATION",
            "weight": ml_score,
            "description": f"Elliptic++ ML Model ({ml_res.get('model_version')}) computed fraud risk probability of {ml_res.get('ml_probability') * 100:.1f}% ({ml_res.get('features_analyzed')} on-chain features evaluated)",
            "ml_metadata": ml_res,
        })
        score = max(score, ml_score)

    # 2. Factor 1: Mixer interaction
    if "MIXER_HOP" in risk_flags:
        score += RISK_WEIGHT_MIXER
        factors.append({
            "factor": "MIXER_INTERACTION",
            "weight": RISK_WEIGHT_MIXER,
            "description": "Funds routed through privacy protocol / mixer",
        })

    # 3. Factor 2: Cross-chain bridge
    if "BRIDGE_SWAP" in risk_flags:
        score += RISK_WEIGHT_BRIDGE
        factors.append({
            "factor": "CROSS_CHAIN_BRIDGE",
            "weight": RISK_WEIGHT_BRIDGE,
            "description": "Funds moved across blockchain via bridge/swap protocol",
        })

    # 4. Factor 3: High velocity layering
    if "HIGH_VELOCITY_LAYERING" in risk_flags:
        score += RISK_WEIGHT_HIGH_VELOCITY
        factors.append({
            "factor": "HIGH_VELOCITY_LAYERING",
            "weight": RISK_WEIGHT_HIGH_VELOCITY,
            "description": "≥3 outgoing transfers within 60 minutes of deposit",
        })

    # 5. Factor 4: Peeling chain detected
    if "PEELING_CHAIN_DETECTED" in risk_flags:
        score += RISK_WEIGHT_PEELING
        factors.append({
            "factor": "PEELING_CHAIN",
            "weight": RISK_WEIGHT_PEELING,
            "description": "Repeated asymmetric value split (>80% / <20%) — classic mule commission pattern",
        })

    # 6. Factor 5: Burner / new wallet (age < 7 days)
    first_tx = db.query(Transaction).filter(
        (Transaction.from_address == wallet_address) | (Transaction.to_address == wallet_address),
        Transaction.chain == chain,
    ).order_by(Transaction.timestamp.asc()).first()

    if first_tx and first_tx.timestamp:
        wallet_age = (datetime.now(timezone.utc) - first_tx.timestamp).days
        if wallet_age < 7:
            score += RISK_WEIGHT_BURNER
            factors.append({
                "factor": "BURNER_WALLET",
                "weight": RISK_WEIGHT_BURNER,
                "description": f"Wallet age: {wallet_age} days (< 7 day threshold)",
            })

    # 7. Factor 6: Multi-complaint link
    linked_cases = db.query(CaseWallet).filter(
        CaseWallet.wallet_address == wallet_address,
        CaseWallet.case_id != case_id,
    ).count()
    if linked_cases >= 2:
        score += RISK_WEIGHT_MULTI_COMPLAINT
        factors.append({
            "factor": "MULTI_COMPLAINT_LINK",
            "weight": RISK_WEIGHT_MULTI_COMPLAINT,
            "description": f"Wallet appears in {linked_cases} other complaint cases",
        })

    # Cap at 100
    score = min(100, max(15, score if score > 0 else (ml_score or 20)))

    # Determine tier
    if score >= 66:
        tier = "CRITICAL"
    elif score >= 31:
        tier = "HIGH"
    elif score > 15:
        tier = "MEDIUM"
    else:
        tier = "LOW"

    return {
        "composite_risk_score": score,
        "risk_tier": tier,
        "ml_risk": ml_res,
        "contributing_factors": factors,
        "triggers": [f["factor"] for f in factors],
    }
