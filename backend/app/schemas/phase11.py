from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ReportRevisionCreate(BaseModel):
    graph_snapshot_id: str | None = None
    risk_result_id: str | None = None
    prediction_id: str | None = None


class NoticeReview(BaseModel):
    status: Literal["reviewed", "rejected", "ready_for_dispatch"]
    reason: str = Field(min_length=8, max_length=2000)


class NoticeDispatch(BaseModel):
    reason: str = Field(min_length=8, max_length=2000)
    simulate: bool = False


class PolicyCreate(BaseModel):
    policy_name: str = Field(min_length=2, max_length=120)
    version: str = Field(min_length=1, max_length=80)
    effective_at: datetime
    thresholds: dict = Field(default_factory=dict)
    preferences: dict = Field(default_factory=dict)
    change_reason: str = Field(min_length=8, max_length=2000)
