# SIH26183 Persistence and Durable Processing

## Runtime policy

PostgreSQL is the authoritative store in staging and production. SQLite exists only for explicit development and test fixtures. Deployed configuration validation rejects a SQLite `DATABASE_URL`. Database schema changes are applied through Alembic before application rollout; application startup creates tables only in development and test for the current local fixture compatibility path.

Redis may cache provider responses and versioned registries, but cached data is never evidence or the source of truth. Every transaction cache key includes chain, canonical wallet digest, provider, case, and query digest. Entity/registry keys include registry version and chain. A cache miss or Redis outage falls back to authoritative storage/provider behavior and must not change an investigative conclusion.

The relational store is also authoritative for graph evidence. `graph_snapshots` are immutable case revisions and `graph_projection_checkpoints` record rebuild state. Neo4j or another graph engine is an optional derived projection that must be fully rebuildable from normalized transactions, address/entity assertions, trace paths, and snapshots.

## Temporal and forensic data rules

Provider and transaction observations keep three independent UTC timestamps:

- `event_time`: when the blockchain event occurred.
- `available_time`: when that event became available to the system or provider.
- `ingested_at`: when this platform recorded the observation.

Naive timestamps are rejected. UTC values are stored canonically with microsecond precision so SQLite tests and PostgreSQL deployments preserve the same instant. Transaction/token values use exact decimal strings plus the provider's raw integer amount. Fiat values record currency, valuation source, and valuation time. Block height, block hash, confirmation count, and finality state preserve chain context.

The exact victim report time is an immutable `report_events` revision and stores both its UTC instant and reported timezone. Evidence receives an explicit `pre_report`, `at_report`, or `post_report` temporal class. Later graph and ML phases must use both event-time and available-time cutoffs and may not infer a baseline feature from evidence unavailable at prediction time.

## Schema coverage

The baseline revision manages the 12 compatibility tables already used by the frontend. The Phase 2 revision adds 57 tables covering every PRD §17.2 persistence group:

| Group | Principal tables |
| --- | --- |
| Tenant, identity, intake and cases | `agencies`, `user_agency_scopes`, `user_sessions`, `api_clients`, `victims`, `complaint_records`, `case_complaints`, `complaint_wallets`, `case_notes`, `case_events`, `report_events` |
| Chains, evidence and normalized value flow | `networks`, `address_records`, `assets`, `provider_observations`, `normalized_transactions`, `bitcoin_outpoints`, `evidence_objects`, `evidence_snapshots`, `evidence_manifests` |
| Entities, protocols, traces and graphs | `entities`, `entity_address_assertions`, `protocol_contracts`, `cross_chain_links`, `analysis_runs`, `analysis_run_events`, `trace_paths`, `graph_snapshots`, `clusters`, `cluster_memberships`, `graph_projection_checkpoints` |
| Rules, ML lineage and human review | `rule_findings`, `risk_results`, the `ml_*` dataset/label/feature/split/experiment/model/prediction/explanation/drift/retraining tables, and `analyst_reviews` |
| Operations and outputs | `alert_recipients`, `alert_deliveries`, `alert_triggers`, `deposit_decisions`, `monitoring_subscriptions`, `report_revisions`, `audit_events`, `background_jobs`, `outbox_events`, `policy_settings` |

These are storage contracts only. The new ML dataset and model tables do not import, execute, or depend on the legacy ML implementation; the new ML pipeline remains scheduled for Phases 7–9.

## Immutable revisions

Report events, provider observations, normalized transactions, address assertions, analysis progress events, trace paths, graph/evidence snapshots, risk results, ML predictions, analyst reviews, report revisions, and audit events are append-only. ORM update and delete operations fail. Corrections create a new revision linked to the same case or parent report. Database accounts used by the application should receive insert/select privileges for these tables and no direct update/delete privileges in production.

## Durable job and outbox semantics

`background_jobs` is a durable, lease-based queue. The pair `(operation, idempotency_key)` is unique. Claims use row locks with skip-locked behavior on PostgreSQL. A failed retryable job moves to `retrying` with a bounded delay; exhausted or permanent failures move to `failed`. Expired worker leases can be reclaimed by the later worker service.

Creating a job writes an `outbox_events` record in the same database transaction. The dispatcher publishes pending records with at-least-once delivery, and every event carries a unique deduplication key. Consumers must deduplicate this key. Delivery failures persist an attempt count and exponential retry time. The caller owns commit/rollback so domain writes, the job, and its outbox event succeed or fail together.

## Migration commands

Run from `backend` with `DATABASE_URL` set:

```text
alembic upgrade head
alembic downgrade base
```

Fresh deployments run both revisions from `base` through `head`. For an existing database whose legacy tables predate Alembic, first back it up, verify it matches the baseline schema, run `alembic stamp 20260912_0000`, and then run `alembic upgrade head`. Migration tests cover both fresh installation and this stamped adoption path. Downgrading to `20260912_0000` removes only Phase 2 tables and retains the legacy compatibility schema.

## Backup and recovery expectations

PostgreSQL backups must cover all authoritative tables and the Alembic revision. Evidence object storage is content-addressed by digest and backed up independently. Redis and graph projections are rebuilt after recovery. A restore is valid only after stored digests are verified and projection checkpoints are regenerated from the restored relational evidence.
