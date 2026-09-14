"""Fresh Phase 8 model training; imports no legacy ML implementation."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import platform
from pathlib import Path
import time

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import SGDClassifier

from app.new_ml.elliptic_plus import (
    FEATURE_SCHEMA_VERSION, SPLIT_STEPS, TRANSACTION_FEATURES, WALLET_FEATURES,
    WALLET_FEATURE_SCHEMA_VERSION, load_transaction_dataset, load_wallet_dataset,
)
from app.new_ml.evaluation import binary_metrics, choose_review_threshold, phase8_quality_gates


EXPERIMENT_VERSION = "phase8-elliptic-plus-transfer-v1"
SEED = 26183


@dataclass(frozen=True)
class SigmoidCalibrator:
    slope: float
    intercept: float
    version: str = "platt-sigmoid-v1"

    def predict(self, probabilities) -> np.ndarray:
        p = np.clip(np.asarray(probabilities, dtype=float), 1e-8, 1 - 1e-8)
        logits = np.log(p / (1 - p))
        return 1 / (1 + np.exp(-(self.slope * logits + self.intercept)))


def _fit_calibrator(y_true, probabilities, seed: int) -> SigmoidCalibrator:
    p = np.clip(np.asarray(probabilities, dtype=float), 1e-8, 1 - 1e-8)
    logits = np.log(p / (1 - p)).reshape(-1, 1)
    model = LogisticRegression(random_state=seed, max_iter=300).fit(logits, y_true)
    return SigmoidCalibrator(slope=float(model.coef_[0, 0]), intercept=float(model.intercept_[0]))


def _candidate_models(seed: int) -> dict[str, Pipeline]:
    """Return the one intentionally lightweight Phase 8 prototype baseline."""
    return {
        "logistic_regression": Pipeline([
            ("imputer", SimpleImputer(strategy="median", add_indicator=True)),
            ("scale", StandardScaler()),
            ("classifier", SGDClassifier(
                loss="log_loss", class_weight="balanced", alpha=0.0001,
                max_iter=100, tol=1e-3, average=True, random_state=seed,
            )),
        ]),
    }


def _partition(frame: pd.DataFrame, split: str, feature_names):
    subset = frame.loc[frame["split"] == split]
    return (subset.loc[:, feature_names], subset["target"].to_numpy(),
            subset["group_key"].to_numpy(), subset["time_step"].to_numpy())


def _latency(model, calibrator: SigmoidCalibrator, features: pd.DataFrame) -> dict:
    sample = features.iloc[:min(1000, len(features))]
    measurements = []
    for _ in range(20):
        started = time.perf_counter()
        calibrator.predict(model.predict_proba(sample)[:, 1])
        measurements.append((time.perf_counter() - started) * 1000 / max(len(sample), 1))
    return {"batch_size": int(len(sample)), "runs": len(measurements),
            "median_ms_per_sample": float(np.median(measurements)),
            "p95_ms_per_sample": float(np.quantile(measurements, 0.95))}


def _canonical_bytes(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def _prediction_digest(probabilities) -> str:
    # Parallel tree reductions may differ below machine-stable byte identity.
    # Eight decimals is stricter than the PRD same-runtime tolerance of 1e-6.
    stable = np.round(np.asarray(probabilities, dtype="<f8"), decimals=8)
    return hashlib.sha256(stable.tobytes()).hexdigest()


def _write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def run_elliptic_plus_experiment(data_dir: Path, output_dir: Path, seed: int = SEED,
                                 task: str = "transfer_risk") -> dict:
    if task == "transfer_risk":
        dataset, feature_names = load_transaction_dataset(data_dir), TRANSACTION_FEATURES
        feature_schema_version, experiment_version = FEATURE_SCHEMA_VERSION, EXPERIMENT_VERSION
        target_definition = "publisher-labelled illicit transaction versus licit transaction"
    elif task == "wallet_risk":
        dataset, feature_names = load_wallet_dataset(data_dir), WALLET_FEATURES
        feature_schema_version = WALLET_FEATURE_SCHEMA_VERSION
        experiment_version = "phase8-elliptic-plus-wallet-v1"
        target_definition = "publisher-labelled illicit wallet versus licit wallet"
    else:
        raise ValueError("Elliptic++ Phase 8 supports transfer_risk or wallet_risk")
    frame = dataset.frame
    x_train, y_train, _, _ = _partition(frame, "train", feature_names)
    x_validation, y_validation, _, _ = _partition(frame, "validation", feature_names)
    x_calibration, y_calibration, _, _ = _partition(frame, "calibration", feature_names)
    x_test, y_test, test_groups, test_steps = _partition(frame, "test", feature_names)
    for name, target in (("train", y_train), ("validation", y_validation),
                         ("calibration", y_calibration), ("test", y_test)):
        if len(target) == 0 or len(np.unique(target)) != 2:
            raise ValueError(f"Frozen {name} split does not contain both classes")

    candidates, fitted, validation_scores = _candidate_models(seed), {}, {}
    for name, model in candidates.items():
        fitted[name] = model.fit(x_train, y_train)
        probabilities = fitted[name].predict_proba(x_validation)[:, 1]
        validation_scores[name] = float(average_precision_score(y_validation, probabilities))
    baseline_name = "logistic_regression"
    selected_name = baseline_name
    selected = fitted[selected_name]

    validation_raw = selected.predict_proba(x_validation)[:, 1]
    raw_threshold = choose_review_threshold(y_validation, validation_raw)
    calibration_raw = selected.predict_proba(x_calibration)[:, 1]
    calibrator = _fit_calibrator(y_calibration, calibration_raw, seed)
    calibrated_threshold = float(calibrator.predict([raw_threshold["threshold"]])[0])
    test_probabilities = calibrator.predict(selected.predict_proba(x_test)[:, 1])
    selected_metrics = binary_metrics(y_test, test_probabilities, calibrated_threshold,
                                      test_groups, seed=seed)

    baseline = fitted[baseline_name]
    baseline_calibrator = _fit_calibrator(y_calibration, baseline.predict_proba(x_calibration)[:, 1], seed)
    baseline_validation_threshold = choose_review_threshold(y_validation, baseline.predict_proba(x_validation)[:, 1])
    baseline_threshold = float(baseline_calibrator.predict([baseline_validation_threshold["threshold"]])[0])
    baseline_metrics = binary_metrics(y_test, baseline_calibrator.predict(baseline.predict_proba(x_test)[:, 1]),
                                      baseline_threshold, test_groups, seed=seed)
    gates = phase8_quality_gates(selected_metrics, baseline_metrics["average_precision"],
                                 license_verified=False, labels_dual_reviewed=False)

    output_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = output_dir / "model.joblib"
    joblib.dump({"model": selected, "calibrator": calibrator,
                 "feature_names": list(feature_names)}, artifact_path, compress=3)
    artifact_hash = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
    prediction_digest = _prediction_digest(test_probabilities)
    completed = datetime.now(timezone.utc).isoformat()
    manifest = {
        "experiment_version": experiment_version,
        "completed_at": completed,
        "task": task,
        "target": target_definition,
        "temporal_mode": "retrospective_context",
        "chain": "BTC",
        "state": gates["state"],
        "promotion_prohibited": True,
        "promotion_reasons": gates["failed"],
        "dataset_snapshot_hash": dataset.snapshot_hash,
        "dataset_file_hashes": dataset.file_hashes,
        "dataset_audit": dataset.audit,
        "feature_schema_version": feature_schema_version,
        "feature_names": list(feature_names),
        "split_protocol": {"steps": {key: list(value) for key, value in SPLIT_STEPS.items()},
                           "frozen_before_evaluation": True},
        "seed": seed,
        "candidate_validation_average_precision": validation_scores,
        "candidate_parameters": {
            name: {
                "imputer": "median_with_missing_indicators",
                "standard_scaler": name == "logistic_regression",
                "classifier": model.named_steps["classifier"].get_params(),
            }
            for name, model in candidates.items()
        },
        "selection_rule": "Phase 8 prototype uses the fixed logistic-regression baseline only",
        "selected_model": selected_name,
        "threshold_selection": {"partition": "validation", "minimum_recall": 0.60,
                                "raw": raw_threshold, "calibrated_threshold": calibrated_threshold},
        "calibration": {"partition": "calibration", **asdict(calibrator)},
        "metrics": {"selected_final_test": selected_metrics, "logistic_final_test": baseline_metrics},
        "quality_gates": gates,
        "rolling_origin": {"status": "deferred_for_lightweight_prototype"},
        "latency": _latency(selected, calibrator, x_test),
        "environment": {"python": platform.python_version(), "platform": platform.platform(),
                        "numpy": np.__version__, "pandas": pd.__version__, "scikit_learn": sklearn.__version__,
                        "joblib": joblib.__version__},
        "artifact": {"path": artifact_path.name, "sha256": artifact_hash,
                     "test_prediction_sha256": prediction_digest,
                     "prediction_digest_decimals": 8,
                     "required_same_runtime_tolerance": 1e-6},
    }
    manifest["manifest_sha256"] = hashlib.sha256(_canonical_bytes(manifest)).hexdigest()
    _write_json(output_dir / "experiment.json", manifest)
    model_card = (
        f"# Phase 8 Elliptic++ {task.replace('_', '-')} research model\n\n"
        f"State: **{gates['state']}** (production promotion prohibited)\n\n"
        f"Selected model: `{selected_name}`\n\n"
        f"Dataset snapshot: `{dataset.snapshot_hash}`\n\n"
        f"Scope: BTC {task.replace('_', ' ')} retrospective research only. It is decision support, not proof of crime.\n\n"
        "The publisher repository does not state a dataset license, labels are not locally dual-reviewed, "
        "time steps are ordinal rather than exact event timestamps, and only the 17 named transaction fields "
        "are used. Unknown labels are excluded. These limitations force shadow status regardless of metrics.\n"
    )
    (output_dir / "MODEL_CARD.md").write_text(model_card, encoding="utf-8")
    return manifest


def verify_artifact(output_dir: Path, expected_manifest: dict, data_dir: Path) -> dict:
    artifact_path = output_dir / expected_manifest["artifact"]["path"]
    actual_hash = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
    if expected_manifest["task"] == "wallet_risk":
        source, feature_names = load_wallet_dataset(data_dir), WALLET_FEATURES
    else:
        source, feature_names = load_transaction_dataset(data_dir), TRANSACTION_FEATURES
    x_test, _, _, _ = _partition(source.frame, "test", feature_names)
    package = joblib.load(artifact_path)
    probabilities = package["calibrator"].predict(package["model"].predict_proba(x_test)[:, 1])
    prediction_hash = _prediction_digest(probabilities)
    return {"artifact_hash_matches": actual_hash == expected_manifest["artifact"]["sha256"],
            "prediction_hash_matches": prediction_hash == expected_manifest["artifact"]["test_prediction_sha256"],
            "dataset_hash_matches": source.snapshot_hash == expected_manifest["dataset_snapshot_hash"],
            "passed": actual_hash == expected_manifest["artifact"]["sha256"]
                      and prediction_hash == expected_manifest["artifact"]["test_prediction_sha256"]
                      and source.snapshot_hash == expected_manifest["dataset_snapshot_hash"]}
