"""Strict report-receipt timestamp parsing and timezone validation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.errors import ApplicationError


ISO_WITH_OFFSET = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.(?P<fraction>\d+))?(?:Z|[+-]\d{2}:\d{2})$"
)


@dataclass(frozen=True, slots=True)
class ParsedTimestamp:
    utc: datetime
    original: str
    offset: str
    precision: str
    iana_timezone: str | None


def parse_report_timestamp(value: str, *, iana_timezone: str | None, future_skew_seconds: int,
                           now: datetime | None = None) -> ParsedTimestamp:
    match = ISO_WITH_OFFSET.fullmatch(value)
    if not match:
        raise ApplicationError(
            code="INVALID_REPORT_TIMESTAMP", message="Report time must be ISO-8601 with Z or an explicit offset",
            status_code=422, field_errors=[{"field": "victim_reported_at", "message": "Timezone offset is required", "type": "value_error"}],
        )
    fraction = match.group("fraction") or ""
    if len(fraction) > 6:
        raise ApplicationError(
            code="UNSUPPORTED_TIMESTAMP_PRECISION", message="Report time supports at most microsecond precision",
            status_code=422, field_errors=[{"field": "victim_reported_at", "message": "More than 6 fractional digits", "type": "value_error"}],
        )
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    offset = parsed.strftime("%z")
    offset = "Z" if offset == "+0000" else f"{offset[:3]}:{offset[3:]}"
    if iana_timezone:
        try:
            zone = ZoneInfo(iana_timezone)
        except ZoneInfoNotFoundError as exc:
            raise ApplicationError(code="INVALID_REPORT_TIMEZONE", message="Unknown IANA timezone", status_code=422) from exc
        expected = parsed.astimezone(zone).utcoffset()
        if expected != parsed.utcoffset():
            raise ApplicationError(code="REPORT_TIMEZONE_MISMATCH", message="IANA timezone does not match timestamp offset", status_code=422)
    utc_value = parsed.astimezone(timezone.utc)
    reference = now or datetime.now(timezone.utc)
    if utc_value > reference + timedelta(seconds=future_skew_seconds):
        raise ApplicationError(code="REPORT_TIMESTAMP_IN_FUTURE", message="Report time exceeds the allowed clock skew", status_code=422)
    precision = "microsecond" if len(fraction) == 6 else (f"fractional_{len(fraction)}" if fraction else "second")
    return ParsedTimestamp(utc_value, value, offset, precision, iana_timezone)
