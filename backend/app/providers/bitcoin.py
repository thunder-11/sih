"""Blockstream Esplora adapter retaining Bitcoin I/O without false allocation."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.providers.contracts import BalanceSnapshot, ProviderError, ProviderPage, TransferCandidate
from app.providers.http import JsonHttpTransport, utc_now


class EsploraBitcoinProvider:
    chain = "BTC"
    provider_name = "blockstream_esplora"

    def __init__(self, *, base_url: str, transport: JsonHttpTransport, finality_confirmations: int = 6):
        self.base_url, self.transport, self.finality_confirmations = base_url.rstrip("/"), transport, finality_confirmations

    def fetch_address(self, address: str, *, cursor: str | None = None, page_size: int = 25) -> ProviderPage:
        # Esplora's confirmed-history endpoint has a fixed 25 record page.
        path = f"/address/{address}/txs/chain" + (f"/{cursor}" if cursor else "")
        payload = self.transport.get(f"{self.base_url}{path}")
        if not isinstance(payload, list):
            raise ProviderError("PROVIDER_MALFORMED_RESPONSE", "Esplora history response was not a list", retryable=False)
        transfers: list[TransferCandidate] = []
        warnings: list[str] = []
        for tx in payload:
            parsed, warning = _parse_transaction(tx)
            transfers.extend(parsed)
            if warning:
                warnings.append(warning)
        next_cursor = str(payload[-1].get("txid")) if len(payload) == 25 and payload else None
        return ProviderPage(self.provider_name, self.chain, address, tuple(transfers), payload,
                            f"{self.base_url}{path}", next_cursor, "complete", utc_now(), warnings=tuple(sorted(set(warnings))))

    def balance(self, address: str) -> BalanceSnapshot:
        payload = self.transport.get(f"{self.base_url}/address/{address}")
        stats = payload.get("chain_stats") if isinstance(payload, dict) else None
        if not isinstance(stats, dict):
            raise ProviderError("PROVIDER_MALFORMED_RESPONSE", "Esplora address response was invalid", retryable=False)
        value = int(stats.get("funded_txo_sum", 0)) - int(stats.get("spent_txo_sum", 0))
        return BalanceSnapshot(self.provider_name, self.chain, address, str(value), 8, "BTC", None, utc_now(),
                               f"{self.base_url}/address/{address}")

    def health(self) -> dict[str, object]:
        return {"provider": self.provider_name, "chain": self.chain, "state": "configured"}


def _parse_transaction(tx: Any) -> tuple[list[TransferCandidate], str | None]:
    if not isinstance(tx, dict):
        raise ProviderError("PROVIDER_MALFORMED_RESPONSE", "Esplora transaction was invalid", retryable=False)
    txid, vin, vout, status = tx.get("txid"), tx.get("vin"), tx.get("vout"), tx.get("status")
    if not isinstance(txid, str) or not isinstance(vin, list) or not isinstance(vout, list) or not isinstance(status, dict):
        raise ProviderError("PROVIDER_MALFORMED_RESPONSE", "Esplora transaction fields were missing", retryable=False)
    if not status.get("confirmed"):
        return [], "pending_bitcoin_transaction_retained_in_raw_observation"
    event_time = _timestamp(status.get("block_time"))
    if event_time is None:
        raise ProviderError("PROVIDER_MALFORMED_RESPONSE", "Confirmed Bitcoin transaction was missing block time", retryable=False)
    senders = [((item.get("prevout") or {}).get("scriptpubkey_address")) for item in vin]
    senders = [sender for sender in senders if isinstance(sender, str) and sender]
    # A multi-input Bitcoin transaction cannot be safely allocated to a single sender.
    if len(set(senders)) != 1:
        return [], "bitcoin_multi_input_unallocated"
    sender = senders[0]
    candidates: list[TransferCandidate] = []
    for index, output in enumerate(vout):
        recipient, raw = output.get("scriptpubkey_address"), output.get("value")
        if not isinstance(recipient, str) or not recipient or not isinstance(raw, int) or raw < 0:
            continue
        candidates.append(TransferCandidate("BTC", txid, f"vout:{index}", sender, recipient, "BTC", None, 8,
                                            str(raw), event_time, "second", str(status.get("block_height")) if status.get("block_height") is not None else None,
                                            status.get("block_hash"), None, "confirmed", "successful", "bitcoin_output",
                                            {"output_index": index, "allocation": "single_input"}))
    return candidates, None


def _timestamp(value: Any) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return None
