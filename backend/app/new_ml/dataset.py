"""Reproducible dataset manifests and source-governance checks."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ApplicationError
from app.new_ml.contracts import TASKS
from app.persistence.models import DatasetSnapshot, DatasetSource


SENSITIVE_KEYS = {"victim_name", "victim_phone", "victim_email", "phone", "email", "password", "private_key",
                  "seed_phrase", "mnemonic", "complaint_text", "narrative", "officer_name"}
HASH_RE = re.compile(r"^[0-9a-f]{64}$")
SUPPORTED_CHAINS = {"BTC", "ETH", "TRON", "BSC", "POLYGON"}


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def reject_sensitive_metadata(value: Any, path: str = "manifest") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).strip().lower()
            if normalized in SENSITIVE_KEYS or any(token in normalized for token in
                                                   ("victim", "phone", "secret", "password", "private_key",
                                                    "seed_phrase", "mnemonic", "complaint_text", "narrative")):
                raise ApplicationError(code="ML_DATA_PRIVACY_VIOLATION", message="Sensitive data is not allowed in ML manifests",
                                       status_code=422, details={"field": f"{path}.{key}"})
            reject_sensitive_metadata(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            reject_sensitive_metadata(item, f"{path}[{index}]")


def create_dataset(session: Session, *, version: str, purpose: str, data_mode: str, task_types: list[str],
                   period_start, period_end, retention_policy: str, access_scope: list[str],
                   manifest: dict, sources: list[dict]) -> DatasetSnapshot:
    if period_end <= period_start:
        raise ApplicationError(code="INVALID_DATASET_PERIOD", message="Dataset period_end must be after period_start", status_code=422)
    unknown_tasks = sorted(set(task_types) - set(TASKS))
    if unknown_tasks:
        raise ApplicationError(code="INVALID_ML_TASK", message="Dataset contains unsupported ML tasks", status_code=422,
                               details={"tasks": unknown_tasks})
    if data_mode not in {"live", "research", "synthetic"}:
        raise ApplicationError(code="INVALID_DATA_MODE", message="ML dataset mode must be live, research, or synthetic", status_code=422)
    reject_sensitive_metadata(manifest)
    seen_hashes: dict[str, str] = {}
    normalized_sources = []
    for source in sources:
        reject_sensitive_metadata(source, "sources")
        content_hash = source["content_hash"].lower()
        if not HASH_RE.fullmatch(content_hash):
            raise ApplicationError(code="INVALID_SOURCE_HASH", message="Source content_hash must be SHA-256", status_code=422)
        identity = digest({key: value for key, value in source.items() if key != "quality_limits"})
        if content_hash in seen_hashes and seen_hashes[content_hash] != identity:
            raise ApplicationError(code="ML_SOURCE_CONFLICT", message="The same content hash has conflicting provenance",
                                   status_code=409, details={"content_hash": content_hash})
        chains = sorted({item.upper() for item in source["chains"]})
        if set(chains) - SUPPORTED_CHAINS:
            raise ApplicationError(code="INVALID_SOURCE_CHAIN", message="Source declares unsupported chain coverage", status_code=422)
        if data_mode != "synthetic" and source["source_kind"] == "synthetic":
            raise ApplicationError(code="SYNTHETIC_DATA_ISOLATION_REQUIRED",
                                   message="Synthetic sources require a synthetic dataset partition", status_code=422)
        if source["source_kind"] == "public_research" and source["license_name"].strip().lower() in {"unknown", "none", ""}:
            raise ApplicationError(code="SOURCE_LICENSE_REQUIRED", message="Public research sources require reviewed license terms", status_code=422)
        if source["coverage_start"] and source["coverage_end"] and source["coverage_end"] <= source["coverage_start"]:
            raise ApplicationError(code="INVALID_SOURCE_COVERAGE", message="Source coverage_end must follow coverage_start", status_code=422)
        if source["source_kind"] == "public_research" and source["provenance"].get("independently_acquired") is not True:
            raise ApplicationError(code="INDEPENDENT_ACQUISITION_REQUIRED",
                                   message="Public research data must attest fresh acquisition from its source", status_code=422)
        if data_mode == "live" and source["source_kind"] not in {"authorized", "provider_observation"}:
            raise ApplicationError(code="LIVE_SOURCE_NOT_AUTHORIZED", message="Live datasets require authorized evidence sources", status_code=422)
        prior = session.execute(select(DatasetSource).where(DatasetSource.content_hash == content_hash).limit(1)).scalar_one_or_none()
        if prior and (prior.source_name != source["source_name"] or prior.license_name != source["license_name"]
                      or prior.provenance != source["provenance"]):
            raise ApplicationError(code="ML_SOURCE_CONFLICT", message="Stored content hash has conflicting provenance",
                                   status_code=409, details={"content_hash": content_hash})
        source = {**source, "chains": chains}
        seen_hashes[content_hash] = identity
        normalized_sources.append({**source, "content_hash": content_hash})
    snapshot_material = {"version": version, "purpose": purpose, "data_mode": data_mode,
                         "task_types": sorted(task_types), "period_start": period_start.isoformat(),
                         "period_end": period_end.isoformat(), "retention_policy": retention_policy,
                         "access_scope": sorted(access_scope), "manifest": manifest,
                         "sources": sorted(normalized_sources, key=lambda item: (item["source_name"], item["content_hash"]))}
    snapshot_hash = digest(snapshot_material)
    existing = session.execute(select(DatasetSnapshot).where(DatasetSnapshot.version == version)).scalar_one_or_none()
    by_hash = session.execute(select(DatasetSnapshot).where(DatasetSnapshot.snapshot_hash == snapshot_hash)).scalar_one_or_none()
    existing = existing or by_hash
    if existing:
        if existing.snapshot_hash != snapshot_hash:
            raise ApplicationError(code="DATASET_VERSION_CONFLICT", message="Dataset version already identifies different content", status_code=409)
        return existing
    snapshot = DatasetSnapshot(version=version, purpose=purpose, data_mode=data_mode, task_types=sorted(task_types),
                               manifest={**manifest, "synthetic_excluded_from_quality_claims": data_mode == "synthetic"},
                               snapshot_hash=snapshot_hash, period_start=period_start, period_end=period_end,
                               retention_policy=retention_policy, access_scope=sorted(access_scope))
    session.add(snapshot); session.flush()
    for source in normalized_sources:
        session.add(DatasetSource(dataset_snapshot_id=snapshot.id, **source))
    session.flush()
    return snapshot
