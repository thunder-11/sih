"""Portable storage types that preserve forensic values exactly."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from sqlalchemy.types import DateTime, String, TypeDecorator


class UtcTimestamp(TypeDecorator):
    """Store an aware timestamp as a canonical UTC ISO-8601 string.

    SQLite otherwise drops timezone information. PostgreSQL deployments still get
    an unambiguous, byte-stable representation that is suitable for evidence
    manifests and deterministic tests.
    """

    impl = String(35)
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(DateTime(timezone=True))
        return dialect.type_descriptor(String(35))

    def process_bind_param(self, value: datetime | None, dialect):
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamps must be timezone-aware")
        normalized = value.astimezone(timezone.utc)
        if dialect.name == "postgresql":
            return normalized
        return normalized.isoformat(timespec="microseconds").replace("+00:00", "Z")

    def process_result_value(self, value: str | None, dialect):
        if value is None:
            return None
        if isinstance(value, datetime):
            if value.tzinfo is None:
                return value.replace(tzinfo=timezone.utc)
            return value.astimezone(timezone.utc)
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


class ExactDecimal(TypeDecorator):
    """Store arbitrary precision decimal values without binary float conversion."""

    impl = String(100)
    cache_ok = True

    def process_bind_param(self, value: Decimal | str | int | None, dialect):
        if value is None:
            return None
        try:
            decimal_value = value if isinstance(value, Decimal) else Decimal(str(value))
        except InvalidOperation as exc:
            raise ValueError(f"invalid exact decimal: {value!r}") from exc
        if not decimal_value.is_finite():
            raise ValueError("exact decimal must be finite")
        return format(decimal_value, "f")

    def process_result_value(self, value: str | None, dialect):
        return None if value is None else Decimal(value)
