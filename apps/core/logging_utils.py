"""Structured logging helpers and request context propagation."""

from __future__ import annotations

import contextvars
import json
import logging
from datetime import datetime
from datetime import timezone

_LOG_CONTEXT = contextvars.ContextVar("log_context", default={})


def set_log_context(**values):
    """Merge key/value pairs into current log context."""

    context = dict(_LOG_CONTEXT.get())
    context.update({k: v for k, v in values.items() if v is not None})
    _LOG_CONTEXT.set(context)


def clear_log_context():
    """Clear per-request log context."""

    _LOG_CONTEXT.set({})


def get_log_context() -> dict:
    """Return copy of current log context."""

    return dict(_LOG_CONTEXT.get())


class RequestContextFilter(logging.Filter):
    """Inject request context fields into log records."""

    context_keys = (
        "request_id",
        "user_id",
        "post_id",
        "connection_id",
        "action",
        "event",
        "error_code",
        "latency_ms",
    )

    def filter(self, record: logging.LogRecord) -> bool:
        context = get_log_context()
        for key in self.context_keys:
            if hasattr(record, key):
                continue
            setattr(record, key, context.get(key))
        return True


class JSONLogFormatter(logging.Formatter):
    """Render logs as one-line JSON records for production observability."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", None),
            "user_id": getattr(record, "user_id", None),
            "post_id": getattr(record, "post_id", None),
            "connection_id": getattr(record, "connection_id", None),
            "action": getattr(record, "action", None),
            "event": getattr(record, "event", None),
            "error_code": getattr(record, "error_code", None),
            "latency_ms": getattr(record, "latency_ms", None),
        }

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=True)
