from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class DirectoryLabel(BaseModel):
    chain: str = Field(min_length=2, max_length=20)
    address: str = Field(min_length=3, max_length=160)
    label: str = Field(min_length=1, max_length=150)
    confidence: Decimal = Field(ge=0, le=1)
    source: str = Field(min_length=3, max_length=150)
    evidence_uri: str | None = None
    valid_from: datetime
    valid_to: datetime | None = None

    @model_validator(mode="after")
    def validity(self):
        if self.valid_to is not None and self.valid_to <= self.valid_from:
            raise ValueError("valid_to must be after valid_from")
        return self


class DirectoryEntity(BaseModel):
    canonical_name: str = Field(min_length=2, max_length=200)
    legal_name: str | None = Field(default=None, max_length=200)
    entity_type: Literal["vasp", "exchange", "mixer", "bridge", "swap", "dex", "protocol", "issuer", "foundation", "treasury", "other"]
    jurisdiction: str | None = Field(default=None, max_length=100)
    fiu_status: Literal["registered", "not_registered", "unknown"] = "unknown"
    fiu_source: str | None = None
    fiu_as_of: datetime | None = None
    contact_email: str | None = Field(default=None, max_length=255)
    contact_source: str | None = None
    contact_as_of: datetime | None = None
    labels: list[DirectoryLabel] = Field(default_factory=list, max_length=1000)


class DirectoryImportRequest(BaseModel):
    source_name: str = Field(min_length=3, max_length=150)
    source_uri: str | None = None
    reviewed: bool = False
    entities: list[DirectoryEntity] = Field(min_length=1, max_length=1000)


class AnalyticsRequest(BaseModel):
    trace_id: str | None = None
