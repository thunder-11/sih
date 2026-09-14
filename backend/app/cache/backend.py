"""Cache abstractions; Redis remains non-authoritative acceleration only."""

from __future__ import annotations

import json
from typing import Any, Protocol


class CacheClient(Protocol):
    def get(self, key: str) -> bytes | str | None: ...
    def setex(self, key: str, ttl_seconds: int, value: str) -> Any: ...
    def delete(self, key: str) -> Any: ...


class JsonCache:
    """Small adapter compatible with a redis-py client and test doubles."""

    def __init__(self, client: CacheClient):
        self.client = client

    def get(self, key: str) -> dict | list | None:
        raw = self.client.get(key)
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return json.loads(raw)

    def set(self, key: str, value: dict | list, *, ttl_seconds: int) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
        self.client.setex(key, ttl_seconds, encoded)

    def delete(self, key: str) -> None:
        self.client.delete(key)
