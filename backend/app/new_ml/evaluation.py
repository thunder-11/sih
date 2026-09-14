"""Leakage-aware binary evaluation and preregistered Phase 8 gates."""

from __future__ import annotations

from typing import Iterable

import numpy as np
from sklearn.metrics import (
    average_precision_score, brier_score_loss, log_loss, precision_score,
    precision_recall_curve, recall_score,
)


def equal_frequency_ece(y_true, probabilities, bins: int = 10) -> tuple[float, list[dict]]:
    y = np.asarray(y_true, dtype=int)
    p = np.clip(np.asarray(probabilities, dtype=float), 1e-9, 1 - 1e-9)
    bucket_rows, weighted_error = [], 0.0
    for indices in np.array_split(np.argsort(p), bins):
        if not len(indices):
            continue
        confidence, frequency = float(p[indices].mean()), float(y[indices].mean())
        error = abs(confidence - frequency)
        weighted_error += error * len(indices) / len(y)
        bucket_rows.append({"count": int(len(indices)), "mean_probability": confidence,
                            "positive_rate": frequency, "absolute_error": error})
    return float(weighted_error), bucket_rows


def choose_review_threshold(y_true, probabilities, minimum_recall: float = 0.60) -> dict:
    y = np.asarray(y_true, dtype=int)
    p = np.asarray(probabilities, dtype=float)
    precision, recall, thresholds = precision_recall_curve(y, p)
    # The final curve point has no threshold, so align only the threshold rows.
    eligible = np.flatnonzero(recall[:-1] >= minimum_recall)
    if not len(eligible):
        return {"threshold": 1.0, "precision": 0.0, "recall": 0.0, "alerts": 0}
    best_index = max(eligible, key=lambda index: (precision[index], thresholds[index]))
    threshold = float(thresholds[best_index])
    alerts = int((p >= threshold).sum())
    return {"threshold": threshold, "precision": float(precision[best_index]),
            "recall": float(recall[best_index]), "alerts": alerts}


def _point_metrics(y, p, threshold: float, top_k: int) -> dict:
    predicted = p >= threshold
    true_negative = int(((y == 0) & ~predicted).sum())
    false_positive = int(((y == 0) & predicted).sum())
    prevalence = float(y.mean())
    top = np.argsort(p)[::-1][:min(top_k, len(y))]
    return {
        "samples": int(len(y)), "positives": int(y.sum()), "negatives": int((y == 0).sum()),
        "prevalence": prevalence,
        "precision": float(precision_score(y, predicted, zero_division=0)),
        "recall": float(recall_score(y, predicted, zero_division=0)),
        "false_positive_rate": false_positive / max(false_positive + true_negative, 1),
        "average_precision": float(average_precision_score(y, p)),
        "brier": float(brier_score_loss(y, p)),
        "log_loss": float(log_loss(y, np.column_stack((1 - p, p)), labels=[0, 1])),
        "precision_at_k": float(y[top].mean()) if len(top) else 0.0,
        "recall_at_k": float(y[top].sum() / max(y.sum(), 1)),
        "alerts_per_1000": float(predicted.mean() * 1000),
        "threshold": float(threshold),
    }


def grouped_precision_interval(y_true, probabilities, threshold: float, groups: Iterable,
                               seed: int, iterations: int = 100) -> dict:
    y, p, g = np.asarray(y_true, dtype=int), np.asarray(probabilities), np.asarray(list(groups))
    unique = np.unique(g)
    if len(unique) < 2:
        return {"lower_95": None, "upper_95": None, "groups": int(len(unique))}
    # A bounded group sample is sufficient for the prototype's shadow gate and
    # prevents a large public research dataset from turning evaluation into a
    # long-running bootstrap job.
    rng, scores = np.random.default_rng(seed), []
    if len(unique) > 2_000:
        unique = rng.choice(unique, size=2_000, replace=False)
    for _ in range(iterations):
        selected = rng.choice(unique, size=len(unique), replace=True)
        indices = np.concatenate([np.flatnonzero(g == item) for item in selected])
        score = precision_score(y[indices], p[indices] >= threshold, zero_division=0)
        scores.append(float(score))
    return {"lower_95": float(np.quantile(scores, 0.025)),
            "upper_95": float(np.quantile(scores, 0.975)), "groups": int(len(unique))}


def binary_metrics(y_true, probabilities, threshold: float, groups: Iterable, seed: int,
                   top_k: int = 100) -> dict:
    y = np.asarray(y_true, dtype=int)
    p = np.clip(np.asarray(probabilities, dtype=float), 1e-9, 1 - 1e-9)
    metrics = _point_metrics(y, p, threshold, top_k)
    metrics["calibration_ece"], metrics["calibration_bins"] = equal_frequency_ece(y, p)
    metrics["precision_group_bootstrap_95"] = grouped_precision_interval(y, p, threshold, groups, seed)
    baseline = np.full(len(y), y.mean(), dtype=float)
    metrics["prevalence_baseline"] = {
        "average_precision": float(y.mean()), "brier": float(brier_score_loss(y, baseline)),
        "log_loss": float(log_loss(y, np.column_stack((1 - baseline, baseline)), labels=[0, 1])),
    }
    return metrics


def phase8_quality_gates(metrics: dict, logistic_average_precision: float,
                         *, license_verified: bool, labels_dual_reviewed: bool) -> dict:
    interval = metrics["precision_group_bootstrap_95"]
    checks = {
        "minimum_gold_test_samples": metrics["positives"] >= 200 and metrics["negatives"] >= 200,
        "precision_point": metrics["precision"] >= 0.80,
        "precision_lower_95": interval["lower_95"] is not None and interval["lower_95"] >= 0.70,
        "recall_point": metrics["recall"] >= 0.60,
        "average_precision_above_prevalence": metrics["average_precision"] > metrics["prevalence"],
        "average_precision_above_logistic": metrics["average_precision"] > logistic_average_precision,
        "calibration_ece": metrics["calibration_ece"] <= 0.05,
        "brier_not_degraded": metrics["brier"] <= metrics["prevalence_baseline"]["brier"],
        "log_loss_not_degraded": metrics["log_loss"] <= metrics["prevalence_baseline"]["log_loss"],
        "license_verified": license_verified,
        "labels_dual_reviewed": labels_dual_reviewed,
    }
    return {"checks": checks, "passed": all(checks.values()),
            "state": "candidate" if all(checks.values()) else "shadow",
            "failed": [name for name, passed in checks.items() if not passed]}
