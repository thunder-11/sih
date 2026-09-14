# SIH26183 Backend Architecture Foundation

This Phase 1 structure is the migration base for the implementation plan. `main.py` remains a compatibility import for the existing `uvicorn main:app` command. The application composition root is `app/main.py`.

## Dependency Direction

API routes validate HTTP input and call controllers. Controllers orchestrate application services. Services use repository and provider interfaces. Repositories own database access. Provider adapters own external blockchain APIs. Deterministic analytics remains separate from the new ML subsystem. Jobs and integrations expose stable boundaries for the durable infrastructure introduced in later phases.

| Package | Responsibility |
| --- | --- |
| `app/api` | Route composition, HTTP contracts, and versioned endpoints |
| `app/controllers` | Request orchestration without provider or storage details |
| `app/services` | Business use cases independent of HTTP |
| `app/repositories` | Persistence interfaces and database implementations |
| `app/providers` | Network/provider adapters and normalized provider pages |
| `app/analytics` | Deterministic graph, attribution, typology, and risk logic |
| `app/jobs` | Durable job states, queue tasks, retries, and progress events |
| `app/integrations` | NCRP, SAHYOG, partner, notification, and storage adapters |
| `app/security` | Authentication, authorization, scopes, and security dependencies |
| `app/core` | Typed configuration, errors, structured logging, and shared policies |
| `app/schemas` | Canonical request and response models |
| `app/utils` | Small side-effect-free utilities |
| `app/persistence` | Exact forensic records, append-only revisions, and rebuildable graph projection contracts |
| `app/cache` | Redis-compatible cache boundaries and tenant/provider-isolated keys |

The existing `auth`, `routers`, and `services` modules remain temporary compatibility adapters so the current frontend contracts continue working during phased migration. New domain work belongs in `app`; later phases migrate each legacy handler behind controllers and repositories without changing the frontend unexpectedly.

Phase 6 deterministic analytics live in `app/analytics/deterministic.py`; sourced
entity attribution, conservative clustering, and qualified correlation live in
`app/services`. They consume normalized evidence and do not import legacy risk,
tracing, or ML implementations. Policy and confidence semantics are documented
in `ANALYTICS.md`.

Phase 7's independent data and feature boundary lives under `app/new_ml`. It is
limited to fresh manifests, human labels, causal features, and frozen split
membership; model training and inference are intentionally absent until later
phases. See `NEW_ML_DATA_PLATFORM.md`.

## Runtime Modes

`DATA_MODE=fixture` requires `DEMO_ENABLED=true` and is limited to development or test operation. `DATA_MODE=live` never falls back to generated transactions. Production startup rejects fixture data, demo mode, wildcard CORS, placeholder/default JWT secrets, unsupported chains, invalid trace limits, and missing credentials for enabled chains.

Readiness reports only configured/missing provider state. It never returns credential values. The application seeds data only when fixture mode is explicitly enabled.
Trace requests no longer create a synthetic origin wallet or guess TRON when the case lacks a validated network.

## Phase 2 Storage Boundaries

PostgreSQL is authoritative outside explicit local/test fixture mode. The additive Phase 2 schema preserves the current frontend-facing legacy schema while new services move to normalized records with exact values, UTC event/available/ingestion timestamps, provider provenance, and chain finality. Immutable evidence and result records are corrected through new revisions rather than mutation.

The database-backed job queue and transactional outbox provide durable, idempotent work requests and at-least-once event delivery. Transport workers can later publish outbox envelopes to Celery/Redis without placing transport state inside domain services. Cache keys include chain, wallet digest, provider, case, and query dimensions. Graph databases are derived projections; immutable relational graph snapshots remain authoritative and can rebuild them.

Migration and recovery details are documented in `PERSISTENCE.md`.

## API Conventions Established in Phase 1

- Existing frontend success wrappers remain available during migration.
- Paginated lists also expose canonical `items`, `total`, `page`, and `page_size` fields.
- Errors use `error.code`, `error.message`, `error.details`, `error.request_id`, `error.retryable`, and validation `field_errors`.
- Responses include `X-Request-ID` and `X-Correlation-ID`.
- OpenAPI documents the shared error schema and all compatibility routes.
- Liveness and readiness are available at `/health/live` and `/health/ready`.

## Adding a Blockchain Provider

Implement `app.providers.base.BlockchainProvider`, keep provider-specific response parsing inside that adapter, return provenance and pagination metadata, register credentials in typed settings, expose only readiness state, and add adapter contract fixtures. Business services must consume normalized records rather than provider payloads. Live provider failure must return partial or unavailable coverage and must never invoke fixture generation.

## Local Verification

Install `requirements-dev.txt`, run `python -m pytest` from `backend`, then run `npm run lint` and `npm run build` from `frontend`. Tests use an in-memory SQLite fixture database and do not read local secret values or call blockchain providers.
