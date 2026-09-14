"""Stable job states shared by APIs and future queue workers."""

from enum import StrEnum


class JobState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    PARTIAL = "partial"
    COMPLETE = "complete"
    FAILED = "failed"
    CANCELLED = "cancelled"
    RETRYING = "retrying"
    UNAVAILABLE = "unavailable"
