from pathlib import Path

import numpy as np
import pandas as pd

from app.new_ml.elliptic_plus import (
    PURGED_STEPS, SPLIT_STEPS, TRANSACTION_FEATURES, WALLET_FEATURES,
    load_transaction_dataset, load_wallet_dataset,
)
from app.new_ml.evaluation import binary_metrics, choose_review_threshold, equal_frequency_ece
from app.new_ml.training import run_elliptic_plus_experiment, verify_artifact


def _research_fixture(root: Path, rows_per_step: int = 8) -> Path:
    root.mkdir()
    feature_rows, class_rows, wallet_rows = [], [], []
    tx_id = 1
    for step in range(1, 50):
        for member in range(rows_per_step):
            target = 1 if member in {0, 1} else 0
            row = {"txId": tx_id, "Time step": step}
            for index, feature in enumerate(TRANSACTION_FEATURES):
                row[feature] = float(target * (index + 1) + step / 100 + member / 1000)
            feature_rows.append(row)
            class_rows.append({"txId": tx_id, "class": 1 if target else 2})
            wallet = {"address": f"wallet-{tx_id}", "Time step": step,
                      "class": 1 if target else 2}
            wallet.update({name: float(target * (index + 1) + step / 100)
                           for index, name in enumerate(WALLET_FEATURES)})
            wallet_rows.append(wallet)
            tx_id += 1
    class_rows.append({"txId": tx_id, "class": 3})
    unknown = {"txId": tx_id, "Time step": 1}
    unknown.update({name: 0.0 for name in TRANSACTION_FEATURES})
    feature_rows.append(unknown)
    pd.DataFrame(feature_rows).to_csv(root / "txs_features.csv", index=False)
    pd.DataFrame(class_rows).to_csv(root / "txs_classes.csv", index=False)
    pd.DataFrame({"txId1": [1], "txId2": [2]}).to_csv(root / "txs_edgelist.csv", index=False)
    pd.DataFrame(wallet_rows).to_csv(root / "wallets_features_classes_combined.csv", index=False)
    return root


def test_elliptic_plus_adapter_freezes_temporal_component_splits(tmp_path):
    dataset = load_transaction_dataset(_research_fixture(tmp_path / "data"))
    assert dataset.audit["unknown_labels_excluded"] == 1
    assert set(dataset.frame["time_step"]).isdisjoint(PURGED_STEPS)
    for split, steps in SPLIT_STEPS.items():
        assert set(dataset.frame.loc[dataset.frame["split"] == split, "time_step"]).issubset(steps)
    assert dataset.frame.groupby("group_key")["split"].nunique().max() == 1
    assert not any(name.startswith(("Local_feature", "Aggregate_feature"))
                   for name in dataset.audit["feature_columns"])
    wallets = load_wallet_dataset(tmp_path / "data")
    assert wallets.audit["conflicting_wallet_labels_excluded"] == 0
    assert wallets.frame["sample_id"].str.len().eq(64).all()


def test_calibration_metrics_and_thresholds_are_explicit():
    y = np.array([0, 0, 0, 1, 1, 1])
    probabilities = np.array([0.01, 0.2, 0.3, 0.7, 0.8, 0.99])
    threshold = choose_review_threshold(y, probabilities, minimum_recall=0.60)
    assert threshold["recall"] >= 0.60
    ece, bins = equal_frequency_ece(y, probabilities, bins=3)
    assert 0 <= ece <= 1 and sum(row["count"] for row in bins) == len(y)
    metrics = binary_metrics(y, probabilities, threshold["threshold"], ["a", "a", "b", "b", "c", "c"], 7)
    assert metrics["average_precision"] > metrics["prevalence_baseline"]["average_precision"]
    assert "precision_group_bootstrap_95" in metrics


def test_full_training_is_reproducible_hash_verified_and_forced_shadow(tmp_path):
    data = _research_fixture(tmp_path / "data")
    first_dir, second_dir = tmp_path / "first", tmp_path / "second"
    first = run_elliptic_plus_experiment(data, first_dir, seed=123)
    second = run_elliptic_plus_experiment(data, second_dir, seed=123)
    assert first["artifact"]["test_prediction_sha256"] == second["artifact"]["test_prediction_sha256"]
    assert first["state"] == "shadow"
    assert {"license_verified", "labels_dual_reviewed"}.issubset(first["quality_gates"]["failed"])
    assert first["split_protocol"]["frozen_before_evaluation"] is True
    assert verify_artifact(first_dir, first, data)["passed"] is True
