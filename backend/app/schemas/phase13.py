"""Operational monitoring and controlled-retraining request contracts."""

from datetime import datetime

from pydantic import BaseModel, Field, model_validator


class DriftEvaluationCreate(BaseModel):
    model_package_id: str = Field(min_length=1, max_length=36)
    cohort: dict[str, str] = Field(default_factory=dict)
    window_start: datetime
    window_end: datetime
    metric_name: str = Field(min_length=3, max_length=80)
    metric_value: float = Field(ge=0)
    sample_size: int = Field(ge=0)
    threshold: float = Field(ge=0)
    trigger_reason: str = Field(min_length=8, max_length=2000)

    @model_validator(mode="after")
    def valid_window(self):
        if self.window_end <= self.window_start:
            raise ValueError("window_end must be later than window_start")
        return self


class RetrainingRequestCreate(BaseModel):
    reason: str = Field(min_length=12, max_length=4000)
    drift_evaluation_id: str | None = Field(default=None, min_length=1, max_length=36)
    dataset_proposal: str = Field(min_length=3, max_length=500)
    scope: dict[str, str] = Field(default_factory=dict)
