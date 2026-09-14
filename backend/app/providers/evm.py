"""Etherscan V2-compatible adapters for Ethereum, BSC, and Polygon."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.providers.contracts import BalanceSnapshot, ProviderError, ProviderPage, TransferCandidate
from app.providers.http import JsonHttpTransport, utc_now


CHAIN_IDS = {"ETH": "1", "BSC": "56", "POLYGON": "137"}
NATIVE_ASSETS = {"ETH": "ETH", "BSC": "BNB", "POLYGON": "MATIC"}


class EvmScanProvider:
    provider_name = "etherscan_v2"

    def __init__(self, *, chain: str, api_key: str, base_url: str, transport: JsonHttpTransport,
                 finality_confirmations: int = 12):
        if chain not in CHAIN_IDS:
            raise ValueError(f"unsupported EVM chain {chain}")
        self.chain = chain
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.transport = transport
        self.finality_confirmations = finality_confirmations

    @property
    def configured(self) -> bool:
        return bool(self.api_key and "placeholder" not in self.api_key.lower())

    def fetch_address(self, address: str, *, cursor: str | None = None, page_size: int = 100) -> ProviderPage:
        if not self.configured:
            raise ProviderError("PROVIDER_CREDENTIALS_MISSING", f"{self.chain} provider credentials are missing", retryable=False)
        page = int(cursor or "1")
        if page < 1 or page_size < 1 or page_size > 1000:
            raise ProviderError("INVALID_PROVIDER_CURSOR", "Invalid provider page request", retryable=False)
        payloads: dict[str, Any] = {}
        candidates: list[TransferCandidate] = []
        for action, kind in (("txlist", "native"), ("tokentx", "token"), ("txlistinternal", "internal")):
            payload = self._request(action, address, page, page_size)
            payloads[action] = payload
            candidates.extend(self._parse(payload, kind))
        full_page = any(len(_records(payload)) >= page_size for payload in payloads.values())
        return ProviderPage(provider=self.provider_name, chain=self.chain, address=address,
                            transfers=tuple(candidates), raw_payload=payloads,
                            source_uri=f"{self.base_url}/api", next_cursor=str(page + 1) if full_page else None,
                            coverage_state="complete", fetched_at=utc_now(), warnings=())

    def balance(self, address: str) -> BalanceSnapshot:
        payload = self._request("balance", address, 1, 1)
        result = payload.get("result")
        if not isinstance(result, str) or not result.isdigit():
            raise ProviderError("PROVIDER_MALFORMED_RESPONSE", "EVM balance result was invalid", retryable=False)
        return BalanceSnapshot(provider=self.provider_name, chain=self.chain, address=address, raw_amount=result,
                               decimals=18, asset_symbol=NATIVE_ASSETS[self.chain], asset_contract=None,
                               fetched_at=utc_now(), source_uri=f"{self.base_url}/api")

    def health(self) -> dict[str, object]:
        return {"provider": self.provider_name, "chain": self.chain,
                "state": "configured" if self.configured else "missing_credentials"}

    def _request(self, action: str, address: str, page: int, page_size: int) -> dict[str, Any]:
        payload = self.transport.get(f"{self.base_url}/api" if not self.base_url.endswith("/api") else self.base_url, params={
            "chainid": CHAIN_IDS[self.chain], "module": "account", "action": action, "address": address,
            "page": page, "offset": page_size, "sort": "desc", "apikey": self.api_key,
        })
        if not isinstance(payload, dict):
            raise ProviderError("PROVIDER_MALFORMED_RESPONSE", "EVM response was not an object", retryable=False)
        message = str(payload.get("message", ""))
        result = payload.get("result")
        if str(payload.get("status", "")) == "0" and not (isinstance(result, list) and not result):
            retryable = "rate limit" in message.lower() or "temporarily" in message.lower()
            raise ProviderError("PROVIDER_RATE_LIMITED" if retryable else "PROVIDER_REJECTED_RESPONSE", message or "EVM provider rejected request", retryable=retryable)
        return payload

    def _parse(self, payload: dict[str, Any], kind: str) -> list[TransferCandidate]:
        records = _records(payload)
        candidates: list[TransferCandidate] = []
        for item in records:
            if not isinstance(item, dict):
                raise ProviderError("PROVIDER_MALFORMED_RESPONSE", "EVM transfer item was invalid", retryable=False)
            if kind == "native" and str(item.get("isError", "0")) != "0":
                continue
            raw_amount = str(item.get("value", ""))
            if not raw_amount.isdigit():
                raise ProviderError("PROVIDER_MALFORMED_RESPONSE", "EVM transfer value was invalid", retryable=False)
            timestamp = _unix_time(item.get("timeStamp"))
            if timestamp is None:
                raise ProviderError("PROVIDER_MALFORMED_RESPONSE", "EVM transfer timestamp was invalid", retryable=False)
            tx_hash = str(item.get("hash", ""))
            sender, recipient = str(item.get("from", "")).lower(), str(item.get("to", "")).lower()
            if not tx_hash or not sender or not recipient:
                raise ProviderError("PROVIDER_MALFORMED_RESPONSE", "EVM transfer participants were missing", retryable=False)
            decimals = 18 if kind != "token" else _integer(item.get("tokenDecimal"), "token decimal", maximum=36)
            confirmations = _optional_integer(item.get("confirmations"))
            transfer_index = (f"log:{item.get('logIndex', item.get('transactionIndex', '0'))}" if kind == "token"
                              else f"{kind}:{item.get('traceId', item.get('transactionIndex', '0'))}")
            candidates.append(TransferCandidate(
                chain=self.chain, tx_hash=tx_hash, transfer_index=transfer_index, from_address=sender, to_address=recipient,
                asset_symbol=str(item.get("tokenSymbol") or NATIVE_ASSETS[self.chain]),
                asset_contract=(str(item.get("contractAddress")).lower() if kind == "token" and item.get("contractAddress") else None),
                asset_decimals=decimals, raw_amount=raw_amount, event_time=timestamp, timestamp_precision="second",
                block_height=str(item.get("blockNumber")) if item.get("blockNumber") is not None else None,
                block_hash=str(item.get("blockHash")) if item.get("blockHash") else None, confirmations=confirmations,
                finality_state="finalized" if confirmations is not None and confirmations >= self.finality_confirmations else "confirmed",
                execution_status="successful", kind=kind, metadata={"provider_action": kind},
            ))
        return candidates


def _records(payload: dict[str, Any]) -> list[Any]:
    result = payload.get("result", [])
    if not isinstance(result, list):
        raise ProviderError("PROVIDER_MALFORMED_RESPONSE", "EVM result was not a list", retryable=False)
    return result


def _unix_time(value: Any) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(str(value)), tz=timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return None


def _integer(value: Any, label: str, *, maximum: int) -> int:
    try:
        result = int(str(value))
    except (TypeError, ValueError) as exc:
        raise ProviderError("PROVIDER_MALFORMED_RESPONSE", f"EVM {label} was invalid", retryable=False) from exc
    if not 0 <= result <= maximum:
        raise ProviderError("PROVIDER_MALFORMED_RESPONSE", f"EVM {label} was out of range", retryable=False)
    return result


def _optional_integer(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(str(value))
    except ValueError:
        return None
