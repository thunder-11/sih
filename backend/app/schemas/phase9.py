"""Phase 9 inference, review, and registry transition contracts."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class PredictionCreate(BaseModel):
    analysis_run_id: str = Field(min_length=1, max_length=36)
    feature_snapshot_id: str = Field(min_length=1, max_length=36)
    purpose: Literal["investigator_support", "deposit_advisory"] = "investigator_support"


class ReviewCreate(BaseModel):
    disposition: Literal["confirm", "reject", "uncertain", "request_evidence", "adjust_priority", "override"]
    reason: str = Field(min_length=8, max_length=4000)
    evidence_snapshot_ids: list[str] = Field(default_factory=list, max_length=100)
    operational_priority: Literal["low", "normal", "high", "urgent"] | None = None
    expires_at: datetime | None = None

    @model_validator(mode="after")
    def override_requires_priority(self):
        if self.disposition in {"adjust_priority", "override"} and self.operational_priority is None:
            raise ValueError("operational_priority is required for an operational override")
        return self


class LifecycleTransition(BaseModel):
    transition: Literal["shadow", "canary", "production", "rollback", "retired", "blocked"]
    reason: str = Field(min_length=8, max_length=4000)
    traffic_percent: int = Field(default=0, ge=0, le=100)
    prior_package_id: str | None = None
