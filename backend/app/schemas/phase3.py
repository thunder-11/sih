"""Phase 3 identity, intake, and case workflow schemas."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


Chain = Literal["BTC", "ETH", "TRON", "BSC", "POLYGON"]
CaseStatus = Literal["new", "investigating", "escalated_to_vasp", "frozen", "closed"]


class WalletValidationRequest(BaseModel):
    address: str = Field(min_length=3, max_length=160)
    chain: Chain | None = None


class IngestionRequest(BaseModel):
    address: str = Field(min_length=8, max_length=160)
    chain: Chain
    cursor: str | None = Field(default=None, max_length=300)
    page_size: int | None = Field(default=None, ge=1, le=1000)


class SuspectWallet(BaseModel):
    address: str = Field(min_length=3, max_length=160)
    chain: Chain | None = Field(default=None, validation_alias=AliasChoices("chain", "network"))
    token_contract: str | None = None
    token_symbol: str | None = None
    incident_tx_hash: str | None = None
    wallet_role: str = "reported"


class ComplaintIntake(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    complaint_source: str = Field(default="manual", validation_alias=AliasChoices("complaint_source", "source_platform"))
    external_complaint_id: str = Field(validation_alias=AliasChoices("external_complaint_id", "ncrp_ref"), min_length=1, max_length=150)
    victim_name: str | None = None
    victim_phone: str | None = None
    victim_details: dict = Field(default_factory=dict)
    fraud_typology: str | None = None
    reported_loss_amount: Decimal = Field(default=Decimal("0"), validation_alias=AliasChoices("reported_loss_amount", "amount_lost"), ge=0)
    loss_currency: str = Field(default="UNKNOWN", max_length=12)
    incident_timestamp: str | None = None
    filed_at: str | None = None
    complaint_text: str | None = Field(default=None, validation_alias=AliasChoices("complaint_text", "narrative_text"), max_length=100_000)
    suspect_wallets: list[SuspectWallet] = Field(default_factory=list, max_length=20)
    victim_reported_at: str | None = None
    report_timezone: str | None = None
    report_timestamp_source: str = "direct_api_receipt"
    receipt_reference: str | None = None
    report_verification_status: Literal["unverified", "asserted", "verified"] = "unverified"
    existing_case_id: str | None = None
    auto_start: bool = True
    data_mode: Literal["live", "fixture"] | None = None


class ReportEventCreate(BaseModel):
    reported_at: str
    report_timezone: str | None = None
    source: str
    channel: str
    receipt_reference: str | None = None
    verification_status: Literal["unverified", "asserted", "verified"] = "unverified"


class WalletAssociationRequest(BaseModel):
    wallets: list[SuspectWallet] = Field(min_length=1, max_length=20)
    auto_start: bool = True


class ReportEventCorrection(ReportEventCreate):
    reason: str = Field(min_length=3, max_length=2000)
    expected_revision: int = Field(ge=1)


class CaseUpdate(BaseModel):
    status: CaseStatus | None = None
    assigned_officer_id: str | None = None
    reason: str = Field(min_length=3, max_length=2000)
    revision: int = Field(ge=1)
    external_action_reference: str | None = None


class CaseNoteCreate(BaseModel):
    content: str = Field(min_length=1, max_length=20_000)
    evidence_ids: list[str] = Field(default_factory=list, max_length=100)


class AttachmentMetadataCreate(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    mime_type: str = Field(min_length=1, max_length=120)
    size_bytes: int = Field(ge=0, le=100_000_000)
    sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    storage_reference: str = Field(min_length=1, max_length=2000)


class CaseAccessGrantCreate(BaseModel):
    user_id: str
    permission: Literal["read", "write"] = "read"
