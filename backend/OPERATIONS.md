# SIH26183 Operations and Release Runbook

## Deployment boundary

Production-like deployments use `APP_ENV=staging` or `production`,
`DATA_MODE=live`, `DEMO_ENABLED=false`, PostgreSQL, explicit CORS origins, and
environment-only credentials. The API refuses SQLite and fixture/demo data in
deployed modes. Configure provider credentials only for enabled chains; a
missing provider is reported as unavailable/degraded, never replaced by
fixture history.

`compose.yaml` supplies a local staging-shaped API, PostgreSQL, and Redis
topology. Before admitting API traffic, run `alembic upgrade head` as a
separate controlled release step. The database-backed job/outbox contracts are
durable; production deployments must operate their consumer/worker process
separately and monitor backlog, retrying, and failed job counts.

## Health and telemetry

- `GET /health/live` checks process liveness.
- `GET /health/ready` probes database readiness and reports only provider
  configuration state.
- Authenticated `GET /api/v1/system/status` reports measured database, queue,
  graph-checkpoint, provider, and new-ML status without credentials or PII.
- Admin-only `GET /api/v1/system/metrics` returns bounded request count and
  latency measurements for the current process. Export it to a durable metrics
  system before process replacement; it is not a distributed SLO claim.

Alert on sustained readiness degradation, failed/retrying queue backlog,
provider coverage loss, unusual request error rate/latency, graph projection
failure, and ML service unavailability. Keep latency, provider lag, and
external-provider time distinct from API work; do not present an unmeasured
deposit-check latency target as achieved.

## ML monitoring, fairness, and retraining

Admins can record measured drift windows at
`POST /api/v1/admin/ml/drift-evaluations`, inspect them at
`GET /api/v1/admin/ml/monitoring`, and create a review-gated retraining request
at `POST /api/v1/admin/ml/retraining-requests`. A request never trains,
promotes, or deploys a package automatically.

Investigate provider/feature quality and delayed labels before treating a drift
signal as model degradation. Evaluate eligible baseline/post-report modes and
permissible cohorts separately. Small cohorts are recorded as insufficient
evidence. Exclude protected identities from scoring and assess allowed chain,
asset, activity, complaint-source, coverage, and narrative-language cohorts
only through approved evaluation access.

Retraining requires frozen fresh data and adjudicated labels, chronological
group-safe splits, fresh initialization, recalibration, robustness/fairness
gates, shadow/canary evidence, and independent approval. Keep the previous
approved compatible NEW package for atomic rollback. Never use legacy ML,
unreviewed complaints, or analyst overrides as automatic training data.

## Backup, restore, and rollback

1. Back up PostgreSQL, including the Alembic revision, and content-addressed
   evidence objects independently. Record backup time, manifest hashes, and
   storage locations in the deployment change record.
2. Restore into an isolated target. Run `alembic upgrade head`, verify stored
   report/evidence digests, and confirm `/health/ready` before traffic cutover.
3. Rebuild Redis and graph projections from restored authoritative relational
   evidence; do not restore them as forensic source-of-truth.
4. Record the restore drill, checksum results, projection revision, operator,
   and any failed objects in the audit/change system.
5. For an ML rollback, use the controlled lifecycle endpoint with an approved,
   compatible NEW package. Prior predictions remain immutable. If no compatible
   package exists, return explicit ML unavailable/abstained status and retain
   deterministic findings plus human review.

## Security and adversarial review

Do not log narratives, credentials, tokens, protected identities, model bytes,
or sensitive training samples. Test duplicate/sybil complaints, false labels,
timestamp manipulation, dusting, benign high fan-out, spoofed token symbols,
bridge/mixer lookalikes, missing providers, and malformed narrative inputs.
Quarantine invalid evidence and preserve provenance. These controls reduce
risk; they do not guarantee resistance to every attack.

## Release checklist

1. Review environment values and secret delivery outside Git.
2. Back up production data and verify the restore procedure.
3. Apply migrations, then verify readiness and measured system status.
4. Run the regression, OpenAPI drift, configuration, and release checks.
5. Confirm worker/outbox consumption and provider coverage states.
6. Verify role-scoped status, metrics, drift, and retraining endpoints.
7. Record known external-provider, dataset-license, and ML-promotion limits in
   the release note; keep unsupported scopes shadow-only or unavailable.
