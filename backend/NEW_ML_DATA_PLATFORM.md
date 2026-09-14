# Fresh ML Data and Feature Platform

Phase 7 is an independently implemented data boundary under `app/new_ml`. It
uses normalized non-ML blockchain evidence and reviewed directory facts. It does
not import the compatibility tracer, legacy deterministic score, NLP code,
prepared features, models, predictions, explainers, or artifacts.

## Task and label contracts

The platform registers four separate tasks: wallet snapshot risk, transfer risk,
pattern multilabel classification, and locally processed complaint typology.
Their outputs describe reviewed evidence for observed activity; they are not a
criminality determination or forecast.

Labels are append-only revisions with states `positive`, `negative`, `unknown`,
`disputed`, and `censored`. Positive, negative, and disputed states require
evidence references. A label becomes training-eligible only when it is mature,
known by the training label cutoff, has two independent confirming reviewers,
and has no rejecting review. Model scores, alerts, and operational overrides are
prohibited label sources.

## Dataset governance

Every immutable dataset snapshot hashes its version, task scope, period, access
policy, manifest, and ordered source manifests. A source records its owner,
license, permitted purpose, chains, coverage, acquisition method, identity keys,
label meaning, availability semantics, limitations, deletion constraints,
acquisition time, content SHA-256, and provenance.

Manifest payloads reject PII/secret-shaped fields. Reused content hashes with
conflicting provenance are quarantined as conflicts. Public research data must
attest independent acquisition and reviewed license terms. Synthetic sources
are isolated in synthetic datasets and are excluded from quality or calibration
claims. Live datasets accept only authorized or provider-observation sources.

## Point-in-time features

The initial `fresh-wallet-features-v1` registry defines temporal velocity,
counterparty, fan-in/fan-out, asset-diversity, splitting entropy, peeling depth,
reviewed protocol exposure, VASP proximity, prior independent complaint, and
provider-quality features. Each definition includes source, units, aggregation,
missing-value behavior, owner, window, and cutoff policy.

- `report_baseline`: event time and availability must both be at or before T0.
- `post_report`: freezes the genuine baseline namespace and separately computes
  events in T0 < event time <= T1 using knowledge available by K1.
- `retrospective_context`: permits later-known evidence through its declared
  knowledge cutoff and cannot be represented as as-known-at-report.

Feature snapshots store hashes, exact cutoffs, maximum contributing event and
availability times, evidence IDs, explicit missingness, and coverage state.
They contain no wallet strings, case IDs, victim/officer identities, verdicts,
or learned transforms. Scaling, imputation, encoding, and feature selection are
reserved for training folds in Phase 8.

## Split protocol

Split manifests use chronological group ordering and keep every campaign or
related-wallet group in exactly one of train, tuning validation, calibration,
or final test. Labels unavailable at the declared cutoff are excluded. Purge and
embargo durations, membership, class counts, exclusions, and hashes are frozen
in the manifest. Phase 8 will use these manifests for training and rolling-origin
validation without changing final-test membership.

## Current data status

No production-quality dataset or performance claim is created by this phase.
Tests use isolated synthetic fixtures solely to prove cutoffs, privacy controls,
review governance, reproducibility, and split behavior. Real promotion remains
blocked until appropriately licensed, reviewed, representative data is supplied.
