"""TronGrid adapter for native TRX and TRC-20 transfer observations."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from app.providers.contracts import BalanceSnapshot, ProviderError, ProviderPage, TransferCandidate
from app.providers.http import JsonHttpTransport, utc_now

BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def hex_to_tron_base58(hex_str: str | None) -> str | None:
    if not isinstance(hex_str, str):
        return hex_str
    s = hex_str.strip()
    if s.startswith("41") and len(s) == 42:
        try:
            raw_bytes = bytes.fromhex(s)
            checksum = hashlib.sha256(hashlib.sha256(raw_bytes).digest()).digest()[:4]
            full_bytes = raw_bytes + checksum
            num = int.from_bytes(full_bytes, "big")
            res = []
            while num > 0:
                num, rem = divmod(num, 58)
                res.append(BASE58_ALPHABET[rem])
            pad = 0
            for b in full_bytes:
                if b == 0:
                    pad += 1
                else:
                    break
            return "1" * pad + "".join(reversed(res))
        except Exception:
            return hex_str
    return hex_str


class TronGridProvider:
    chain = "TRON"
    provider_name = "trongrid"

    def __init__(self, *, api_key: str, base_url: str, transport: JsonHttpTransport, finality_confirmations: int = 19):
        self.api_key, self.base_url, self.transport = api_key, base_url.rstrip("/"), transport
        self.finality_confirmations = finality_confirmations

    @property
    def configured(self) -> bool:
        return bool(self.api_key and "placeholder" not in self.api_key.lower())

    def health(self) -> dict[str, object]:
        return {"provider": self.provider_name, "chain": self.chain,
                "state": "configured" if self.configured else "missing_credentials"}

    def _get(self, path: str, params: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
        payload = self.transport.get(f"{self.base_url}{path}", params=params, headers=headers)
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            raise ProviderError("PROVIDER_MALFORMED_RESPONSE", "TronGrid response did not contain data", retryable=False)
        return payload

    def fetch_address(self, address: str, *, cursor: str | None = None, page_size: int = 100) -> ProviderPage:
        if not self.configured:
            raise ProviderError("PROVIDER_CREDENTIALS_MISSING", "TRON provider credentials are missing", retryable=False)
        if page_size < 1 or page_size > 200:
            raise ProviderError("INVALID_PROVIDER_CURSOR", "TronGrid page size is invalid", retryable=False)
        params = {"limit": page_size, "only_confirmed": "true", "order_by": "block_timestamp,desc"}
        if cursor:
            params["fingerprint"] = cursor
        headers = {"TRON-PRO-API-KEY": self.api_key}
        native = self._get(f"/v1/accounts/{address}/transactions", params, headers)
        token = self._get(f"/v1/accounts/{address}/transactions/trc20", params, headers)
        candidates = self._parse_native(native) + self._parse_token(token)
        next_cursor = _fingerprint(token) or _fingerprint(native)
        return ProviderPage(provider=self.provider_name, chain=self.chain, address=address, transfers=tuple(candidates),
                            raw_payload={"native": native, "trc20": token}, source_uri=f"{self.base_url}/v1/accounts/{address}",
                            next_cursor=next_cursor, coverage_state="complete", fetched_at=utc_now())

    def balance(self, address: str) -> BalanceSnapshot:
        payload = self._get(f"/v1/accounts/{address}", {}, {"TRON-PRO-API-KEY": self.api_key})
        data = payload.get("data")
        if not isinstance(data, list) or not data or not isinstance(data[0], dict):
            raise ProviderError("PROVIDER_MALFORMED_RESPONSE", "TronGrid account response was invalid", retryable=False)
        raw = str(data[0].get("balance", ""))
        if not raw.isdigit():
            raise ProviderError("PROVIDER_MALFORMED_RESPONSE", "TRX balance was invalid", retryable=False)
        return BalanceSnapshot(self.provider_name, self.chain, address, raw, 6, "TRX", None, utc_now(), f"{self.base_url}/v1/accounts/{address}")

    def _parse_native(self, payload: dict[str, Any]) -> list[TransferCandidate]:
        result: list[TransferCandidate] = []
        for item in payload.get("data", []):
            contracts = (item.get("raw_data") or {}).get("contract") or [{}]
            for c_idx, contract in enumerate(contracts):
                parameter = ((contract.get("parameter") or {}).get("value") or {})
                amount = str(parameter.get("amount") or parameter.get("call_value") or "0")
                if not amount.isdigit() or amount == "0":
                    continue
                raw_sender = parameter.get("owner_address")
                raw_recipient = parameter.get("to_address") or parameter.get("contract_address")
                sender = hex_to_tron_base58(raw_sender)
                recipient = hex_to_tron_base58(raw_recipient)
                tx_hash = item.get("txID")
                timestamp = _timestamp(item.get("block_timestamp"))
                if not all(isinstance(v, str) and v for v in (sender, recipient, tx_hash)) or timestamp is None:
                    continue
                result.append(TransferCandidate(
                    chain=self.chain,
                    tx_hash=tx_hash,
                    transfer_index=f"native:{c_idx}",
                    from_address=sender,
                    to_address=recipient,
                    asset_symbol="TRX",
                    asset_contract=None,
                    asset_decimals=6,
                    raw_amount=amount,
                    event_time=timestamp,
                    timestamp_precision="millisecond",
                    block_height=str(item.get("block_number")) if item.get("block_number") is not None else None,
                    block_hash=item.get("block_hash"),
                    confirmations=None,
                    finality_state="finalized",
                    execution_status="successful",
                    kind="native",
                ))
        return result

    def _parse_token(self, payload: dict[str, Any]) -> list[TransferCandidate]:
        result: list[TransferCandidate] = []
        for index, item in enumerate(payload.get("data", [])):
            info = item.get("token_info") or {}
            amount = str(item.get("value", ""))
            timestamp = _timestamp(item.get("block_timestamp"))
            raw_sender, raw_recipient, tx_hash = item.get("from"), item.get("to"), item.get("transaction_id")
            sender = hex_to_tron_base58(raw_sender)
            recipient = hex_to_tron_base58(raw_recipient)
            decimals = info.get("decimals")
            if decimals is None or str(decimals).strip() == "" or str(decimals).lower() == "none":
                symbol = str(info.get("symbol") or "").upper()
                decimals = 6 if ("USDT" in symbol or "USDC" in symbol) else 18
            try:
                decimals = int(str(decimals))
            except (TypeError, ValueError):
                decimals = 6
            if not 0 <= decimals <= 36:
                decimals = 6
            result.append(TransferCandidate(
                chain=self.chain,
                tx_hash=tx_hash,
                transfer_index=f"trc20:{index}",
                from_address=sender,
                to_address=recipient,
                asset_symbol=str(info.get("symbol") or "TRC20"),
                asset_contract=str(info.get("address") or "") or None,
                asset_decimals=decimals,
                raw_amount=amount,
                event_time=timestamp,
                timestamp_precision="millisecond",
                block_height=str(item.get("block_number")) if item.get("block_number") is not None else None,
                block_hash=item.get("block_hash"),
                confirmations=None,
                finality_state="finalized",
                execution_status="successful",
                kind="token",
            ))
        return result


def _fingerprint(payload: dict[str, Any]) -> str | None:
    meta = payload.get("meta") or {}
    value = meta.get("fingerprint") if isinstance(meta, dict) else None
    return str(value) if value else None


def _timestamp(value: Any) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(str(value)) / 1000, tz=timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return None
