"""HTTP middleware for request-id propagation and structured access logs."""

from __future__ import annotations

import logging
import time
import uuid

from .logging_utils import clear_log_context
from .logging_utils import set_log_context

logger = logging.getLogger("apps.request")


class RequestContextMiddleware:
    """Attach request id and user context to logs for each HTTP request."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        started_at = time.perf_counter()
        request_id = request.headers.get("X-Request-ID") or request.headers.get("X-Request-Id") or str(uuid.uuid4())

        request.request_id = request_id
        set_log_context(request_id=request_id)

        try:
            response = self.get_response(request)
        except Exception:
            latency_ms = round((time.perf_counter() - started_at) * 1000, 2)
            logger.exception(
                "request_failed",
                extra={
                    "event": "request.failed",
                    "action": request.method,
                    "latency_ms": latency_ms,
                },
            )
            clear_log_context()
            raise

        user_id = getattr(getattr(request, "user", None), "id", None)
        latency_ms = round((time.perf_counter() - started_at) * 1000, 2)
        set_log_context(user_id=user_id)

        logger.info(
            "request_completed",
            extra={
                "event": "request.completed",
                "action": request.method,
                "latency_ms": latency_ms,
            },
        )

        response["X-Request-ID"] = request_id
        clear_log_context()
        return response
