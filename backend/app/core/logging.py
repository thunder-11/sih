"""Structured logging that omits known secret values."""

import json
import logging
from datetime import datetime, timezone

from app.utils.redaction import redact


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key in ("request_id", "correlation_id", "case_id", "run_id"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        return json.dumps(redact(payload), ensure_ascii=True, default=str)


def configure_logging(level: str) -> None:
    root = logging.getLogger()
    root.setLevel(level)
    if not root.handlers:
        root.addHandler(logging.StreamHandler())
    for handler in root.handlers:
        handler.setFormatter(JsonFormatter())
