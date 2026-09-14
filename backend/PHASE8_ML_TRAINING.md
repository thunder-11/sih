# Phase 8 Fresh ML Training and Evaluation

Phase 8 trains fresh research models without importing legacy ML code, artifacts,
preprocessing, scores, or thresholds. The current experiments use a fresh direct
acquisition of the publisher-linked Elliptic++ data and are forcibly restricted
to `shadow` state.

## Supported research scope

- Chain: BTC only.
- Tasks: `transfer_risk` and `wallet_risk`, evaluated independently.
- Temporal mode: `retrospective_context` only.
- Target: publisher-labelled illicit versus licit activity. Unknown labels are
  excluded rather than treated as negatives.
- Meaning: analyst decision support, never proof of criminality.

The publisher repository does not state an explicit dataset license, its labels
are not locally dual-reviewed, and its 49 time steps are ordinal snapshots rather
than exact event timestamps. These facts block production/canary promotion even
if numerical gates pass.

## Independent acquisition

Raw data belongs in `data/external/elliptic_plus_plus/`, which is git-ignored.
The tracked source IDs, byte sizes, SHA-256 digests, citation, and limitations are
in `data/manifests/elliptic_plus_phase8.json`. Raw data and trained artifacts must
not be committed or redistributed from this repository.

Install the isolated training dependencies with:

```powershell
python -m pip install -r requirements-ml.txt
```

Run the experiments from `backend/`:

```powershell
python scripts/train_phase8_elliptic_plus.py --task transfer_risk --output-dir artifacts/ml/phase8-elliptic-plus-transfer-v1
python scripts/train_phase8_elliptic_plus.py --task wallet_risk --output-dir artifacts/ml/phase8-elliptic-plus-wallet-v1
```

Each output contains a hash-verified `model.joblib`, complete `experiment.json`,
and `MODEL_CARD.md`. The CLI reloads the artifact and reproduces the final-test
prediction digest before returning success.

## Features and leakage controls

The transfer experiment uses only the 17 publisher-named transaction fields.
The anonymous `Local_feature_*` and `Aggregate_feature_*` columns are excluded.
The wallet experiment uses publisher-named historical wallet fields and retains
only each wallet's final observation. Public addresses are converted into
snapshot-scoped irreversible sample/group identifiers before evaluation output.

The split was frozen before metrics were observed:

- Train: steps 1–25.
- Purge: step 26.
- Tuning validation: steps 27–32.
- Purge: step 33.
- Calibration: steps 34–39.
- Purge/embargo: step 40.
- Final test: steps 41–49.

No graph edge crosses Elliptic time steps. Each transfer time-step component is
assigned wholly to one partition. Wallets use one final observation per address.
Training-only class weighting is allowed; validation, calibration, and final-test
prevalence is unchanged.

## Prototype evaluation protocol

To keep the SIH prototype fast and reproducible, each task uses one balanced
logistic-regression baseline with a deterministic stochastic optimizer.
Challenger experiments and rolling-origin reruns are deliberately deferred. A
review threshold is selected on validation for at least 0.60 recall. A sigmoid
calibrator is then fitted only on the later, disjoint calibration partition. The
untouched final test is evaluated once.

Reported measures include precision, recall, false-positive rate, average
precision, Brier score, log loss, ten-bin equal-frequency ECE, precision/recall
at K, alerts per 1,000, group-bootstrap precision intervals, and measured batch
prediction latency.

Production gates remain the preregistered PRD gates: at least 200 adjudicated
positives and 200 negatives, precision >=0.80 with 95% lower bound >=0.70,
recall >=0.60, average precision above prevalence and logistic baselines,
ECE <=0.05, and non-degraded Brier/log loss. Verified licensing and local dual
review are mandatory non-metric gates.
