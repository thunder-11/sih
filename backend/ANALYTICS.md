# Deterministic Analytics and Attribution

Phase 6 analytics operate only on normalized transfers and directory facts that
were available by an immutable trace run's knowledge cutoff. They never invoke
or emulate an ML model.

## Outputs

- `risk_kind=deterministic_composite` identifies the versioned six-factor PRD
  policy. Its 0–100 score is not a probability.
- Entity attribution is a separate heuristic confidence: exact reviewed label
  95 and qualifying same-asset sweep 85. It is not ML confidence or ownership
  proof.
- Correlation reports evidence counts and a qualified review finding. Three
  distinct complaints and victims are required; shared public services alone
  are excluded.
- Cluster membership is a versioned hypothesis. Public service labels are
  explicitly exposed as a false-positive control and never establish common
  ownership.

## Boundary policy

The traversal stops a branch at its first reviewed VASP label. Mixer, bridge and
swap contracts are unresolved boundaries unless a separately verified protocol
message links source and destination executions. Time or amount similarity does
not create a confirmed continuation, and no mixer exit is synthesized.

## Directory governance

Only admins may import labels. Each address is locally validated and stored with
source, evidence URI, effective dates, review state, reviewer and knowledge
timestamp. Unreviewed or expired assertions are retained but excluded from
attribution. FIU and contact metadata have their own source/as-of fields;
`unknown` is distinct from `not_registered`.

## API workflow

`POST /api/v1/cases/{case_id}/analytics` materializes append-only rule findings
and an idempotent risk result for a trace. The corresponding `GET` endpoints are
read-only and never trigger tracing, provider retrieval or hidden analytics.
