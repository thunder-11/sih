"""Typed, provider-neutral blockchain observation contracts.

Provider adapters return raw response provenance alongside normalized transfer
candidates.  They never return fabricated transfers or turn provider failures
into an empty successful page.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


class ProviderError(RuntimeError):
    def __init__(self, code: str, message: str, *, retryable: bool, retry_after_seconds: int | None = None):
        self.code = code
        self.retryable = retryable
        self.retry_after_seconds = retry_after_seconds
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class TransferCandidate:
    chain: str
    tx_hash: str
    transfer_index: str
    from_address: str | None
    to_address: str | None
    asset_symbol: str
    asset_contract: str | None
    asset_decimals: int
    raw_amount: str
    event_time: datetime | None
    timestamp_precision: str
    block_height: str | None
    block_hash: str | None
    confirmations: int | None
    finality_state: str
    execution_status: str
    kind: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ProviderPage:
    provider: str
    chain: str
    address: str
    transfers: tuple[TransferCandidate, ...]
    raw_payload: Any
    source_uri: str
    next_cursor: str | None
    coverage_state: str
    fetched_at: datetime
    observed_height: str | None = None
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class BalanceSnapshot:
    provider: str
    chain: str
    address: str
    raw_amount: str
    decimals: int
    asset_symbol: str
    asset_contract: str | None
    fetched_at: datetime
    source_uri: str
