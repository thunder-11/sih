"""Canonical cache keys with mandatory tenant and provider isolation."""

from __future__ import annotations

import hashlib
import json


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]


def transaction_cache_key(
    *,
    chain: str,
    wallet_address: str,
    provider: str,
    case_id: str,
    query: dict | None = None,
) -> str:
    if not all((chain, wallet_address, provider, case_id)):
        raise ValueError("chain, wallet_address, provider, and case_id are required")
    query_json = json.dumps(query or {}, sort_keys=True, separators=(",", ":"), default=str)
    return ":".join((
        "sih26183", "tx", chain.upper(), provider.lower(), case_id,
        _digest(wallet_address.strip()), _digest(query_json),
    ))


def registry_cache_key(*, registry: str, version: str, chain: str) -> str:
    if not all((registry, version, chain)):
        raise ValueError("registry, version, and chain are required")
    return f"sih26183:registry:{registry.lower()}:{version}:{chain.upper()}"


def graph_cache_key(*, case_id: str, trace_id: str, report_event_id: str | None, filters: dict) -> str:
    """Non-authoritative graph-view key bound to case, trace, report, and filters."""
    if not case_id or not trace_id:
        raise ValueError("case_id and trace_id are required")
    scope = json.dumps({"report_event_id": report_event_id, "filters": filters}, sort_keys=True, separators=(",", ":"), default=str)
    return ":".join(("sih26183", "graph", case_id, trace_id, _digest(scope)))
