from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class AwareModel(BaseModel):
    @model_validator(mode="after")
    def timezone_aware_datetimes(self):
        for name in type(self).model_fields:
            value = getattr(self, name, None)
            if isinstance(value, datetime) and (value.tzinfo is None or value.utcoffset() is None):
                raise ValueError(f"{name} must include an explicit UTC offset")
        return self


class DatasetSourceInput(AwareModel):
    source_name: str = Field(min_length=2, max_length=150)
    source_uri: str | None = None
    source_kind: Literal["authorized", "public_research", "provider_observation", "synthetic"]
    owner: str = Field(min_length=2, max_length=150)
    license_name: str = Field(min_length=2, max_length=150)
    permitted_purpose: str = Field(min_length=3, max_length=200)
    chains: list[str] = Field(min_length=1)
    coverage_start: datetime | None = None
    coverage_end: datetime | None = None
    collection_method: str = Field(min_length=3, max_length=120)
    identity_keys: list[str] = Field(min_length=1)
    label_meaning: str | None = None
    availability_semantics: str = Field(min_length=3)
    quality_limits: list[str] = Field(default_factory=list)
    deletion_constraints: str | None = None
    acquired_at: datetime
    content_hash: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    provenance: dict = Field(default_factory=dict)


class DatasetCreate(AwareModel):
    version: str = Field(min_length=3, max_length=80)
    purpose: str = Field(min_length=3, max_length=80)
    data_mode: Literal["live", "research", "synthetic"]
    task_types: list[str] = Field(min_length=1)
    period_start: datetime
    period_end: datetime
    retention_policy: str = Field(min_length=3, max_length=80)
    access_scope: list[str] = Field(min_length=1)
    manifest: dict = Field(default_factory=dict)
    sources: list[DatasetSourceInput] = Field(min_length=1)


class LabelCreate(AwareModel):
    subject_type: Literal["wallet", "transfer", "pattern", "complaint"]
    subject_id: str = Field(min_length=1, max_length=100)
    task: Literal["wallet_risk", "transfer_risk", "pattern_multilabel", "complaint_typology"]
    target_class: str = Field(min_length=2, max_length=80)
    group_key: str = Field(min_length=2, max_length=120)
    observation_window_start: datetime
    observation_window_end: datetime
    label: Literal["positive", "negative", "unknown", "disputed", "censored"]
    maturity: Literal["immature", "mature", "censored"]
    known_at: datetime
    evidence_snapshot_ids: list[str] = Field(default_factory=list)
    source_name: str = Field(min_length=2, max_length=150)
    license_name: str = Field(min_length=2, max_length=150)
    source_confidence: Decimal = Field(ge=0, le=1)
    rationale: str = Field(min_length=3)
    maturation_days: int = Field(default=90, ge=0, le=3650)


class LabelReviewCreate(AwareModel):
    decision: Literal["confirm", "reject", "uncertain"]
    reason: str = Field(min_length=3)


class FeatureMaterializeRequest(AwareModel):
    subject_address_id: str
    temporal_mode: Literal["report_baseline", "post_report", "retrospective_context"]
    report_time: datetime | None = None
    event_cutoff: datetime
    knowledge_cutoff: datetime
    exclude_complaint_id: str | None = None


class SplitCreate(AwareModel):
    dataset_snapshot_id: str
    version: str = Field(min_length=3, max_length=80)
    label_cutoff: datetime
    purge_days: int = Field(default=30, ge=0, le=3650)
    embargo_days: int = Field(default=7, ge=0, le=3650)
