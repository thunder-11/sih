"""Bounded, process-local operational measurements.

This module deliberately reports only measurements observed by the running
process. It is not a substitute for a durable metrics backend; deployments
should scrape or export these values before a process is replaced.
"""

from __future__ import annotations

from collections import Counter, deque
from threading import Lock


class OperationalMetrics:
    def __init__(self, max_samples: int = 2048) -> None:
        self._lock = Lock()
        self._max_samples = max_samples
        self._requests = Counter()
        self._latencies_ms: deque[float] = deque(maxlen=max_samples)

    def record_request(self, status_code: int, latency_ms: float) -> None:
        with self._lock:
            self._requests["total"] += 1
            self._requests[f"status_{status_code // 100}xx"] += 1
            self._latencies_ms.append(max(0.0, latency_ms))

    def snapshot(self) -> dict:
        with self._lock:
            samples = sorted(self._latencies_ms)
            def percentile(fraction: float) -> float | None:
                if not samples:
                    return None
                index = min(len(samples) - 1, int((len(samples) - 1) * fraction))
                return round(samples[index], 3)
            return {
                "measurement_scope": "current_process_since_start",
                "request_counts": dict(self._requests),
                "latency_ms": {
                    "sample_size": len(samples),
                    "p50": percentile(0.50),
                    "p95": percentile(0.95),
                    "p99": percentile(0.99),
                },
            }


operational_metrics = OperationalMetrics()
