"""Small resilient HTTP transport shared by provider adapters."""

from __future__ import annotations

from datetime import datetime, timezone
import random
import time
from typing import Any

import httpx

from app.providers.contracts import ProviderError


class JsonHttpTransport:
    def __init__(self, *, connect_timeout_seconds: float, request_timeout_seconds: float,
                 max_attempts: int, client: httpx.Client | Any | None = None,
                 sleep: Any = time.sleep, random_source: Any = random.random):
        self.connect_timeout_seconds = connect_timeout_seconds
        self.request_timeout_seconds = request_timeout_seconds
        self.max_attempts = max_attempts
        self.client = client or httpx.Client(timeout=httpx.Timeout(request_timeout_seconds, connect=connect_timeout_seconds))
        self.sleep = sleep
        self.random_source = random_source

    def get(self, url: str, *, params: dict[str, Any] | None = None,
            headers: dict[str, str] | None = None) -> Any:
        for attempt in range(1, self.max_attempts + 1):
            try:
                response = self.client.get(url, params=params, headers=headers)
            except (httpx.TimeoutException, httpx.NetworkError, OSError) as exc:
                if attempt == self.max_attempts:
                    raise ProviderError("PROVIDER_NETWORK_UNAVAILABLE", str(exc), retryable=True) from exc
                self._backoff(attempt)
                continue
            if response.status_code == 429:
                retry_after = _retry_after(response.headers.get("Retry-After"))
                if attempt == self.max_attempts:
                    raise ProviderError("PROVIDER_RATE_LIMITED", "Provider rate limit reached", retryable=True,
                                        retry_after_seconds=retry_after)
                self.sleep(retry_after if retry_after is not None else self._delay(attempt))
                continue
            if response.status_code >= 500:
                if attempt == self.max_attempts:
                    raise ProviderError("PROVIDER_UNAVAILABLE", f"Provider returned HTTP {response.status_code}", retryable=True)
                self._backoff(attempt)
                continue
            if response.status_code >= 400:
                raise ProviderError("PROVIDER_REQUEST_REJECTED", f"Provider returned HTTP {response.status_code}", retryable=False)
            try:
                return response.json()
            except ValueError as exc:
                raise ProviderError("PROVIDER_MALFORMED_RESPONSE", "Provider response was not valid JSON", retryable=False) from exc
        raise AssertionError("unreachable")

    def _delay(self, attempt: int) -> float:
        return min(30.0, (2 ** (attempt - 1)) + self.random_source())

    def _backoff(self, attempt: int) -> None:
        self.sleep(self._delay(attempt))


def _retry_after(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return max(0, int(value))
    except ValueError:
        return None


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
