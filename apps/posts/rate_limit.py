"""Rate limiting helpers for websocket actions."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass

from django.conf import settings

logger = logging.getLogger(__name__)

try:
    import redis
except ImportError:  # pragma: no cover
    redis = None


@dataclass
class RateLimitDecision:
    """Decision payload for websocket action rate limiting."""

    allowed: bool
    should_close: bool
    limit: int
    count: int
    violations: int
    window_seconds: int


class InMemoryRateLimitBackend:
    """In-memory fallback backend when Redis is unavailable."""

    def __init__(self):
        self._lock = threading.Lock()
        self._store: dict[str, tuple[int, float]] = {}

    def incr(self, key: str, ttl_seconds: int) -> int:
        with self._lock:
            now = time.monotonic()
            count, expires_at = self._store.get(key, (0, now + ttl_seconds))
            if expires_at <= now:
                count = 0
                expires_at = now + ttl_seconds

            count += 1
            self._store[key] = (count, expires_at)
            return count


class RedisRateLimitBackend:
    """Redis backend for distributed websocket rate limiting."""

    def __init__(self, client):
        self.client = client

    def incr(self, key: str, ttl_seconds: int) -> int:
        pipe = self.client.pipeline()
        pipe.incr(key)
        pipe.expire(key, ttl_seconds, nx=True)
        count, _ = pipe.execute()
        return int(count)


class WebSocketRateLimiter:
    """Apply per-action limits for each websocket connection."""

    def __init__(self):
        self.window_seconds = int(getattr(settings, "WS_RATE_WINDOW_SECONDS", 10))
        self.limit_all = int(getattr(settings, "WS_RATE_MAX_MESSAGES", 20))
        self.limit_typing = int(getattr(settings, "WS_RATE_TYPING_MAX", 8))
        self.limit_heartbeat = int(getattr(settings, "WS_RATE_HEARTBEAT_MAX", 15))
        self.close_threshold = int(getattr(settings, "WS_RATE_VIOLATION_CLOSE_THRESHOLD", 5))
        self.backend = self._build_backend()

    def _build_backend(self):
        redis_url = getattr(settings, "REDIS_URL", None)
        if redis is None or not redis_url:
            return InMemoryRateLimitBackend()

        try:
            client = redis.Redis.from_url(redis_url, decode_responses=True, socket_timeout=1)
            client.ping()
            return RedisRateLimitBackend(client)
        except Exception:
            logger.exception("Falling back to in-memory websocket rate limiting")
            return InMemoryRateLimitBackend()

    def _action_limit(self, action: str) -> int:
        if action in {"typing_start", "typing_stop"}:
            return self.limit_typing
        if action == "heartbeat":
            return self.limit_heartbeat
        return self.limit_all

    def check(self, *, connection_id: str, action: str) -> RateLimitDecision:
        """Check and update websocket rate-limit counters.

        Input: connection id and action name.
        Output: rate limit decision object.
        """

        action = action or "unknown"
        limit = self._action_limit(action)
        total_key = f"ws_rate_total:{connection_id}"
        rate_key = f"ws_rate:{connection_id}:{action}"
        violations_key = f"ws_rate:violations:{connection_id}"

        total_count = self.backend.incr(total_key, self.window_seconds)
        action_count = self.backend.incr(rate_key, self.window_seconds)

        total_exceeded = total_count > self.limit_all
        action_exceeded = action_count > limit
        if not total_exceeded and not action_exceeded:
            return RateLimitDecision(
                allowed=True,
                should_close=False,
                limit=self.limit_all,
                count=total_count,
                violations=0,
                window_seconds=self.window_seconds,
            )

        violations = self.backend.incr(violations_key, self.window_seconds * 3)
        should_close = violations >= self.close_threshold

        effective_limit = self.limit_all if total_exceeded else limit
        effective_count = total_count if total_exceeded else action_count

        return RateLimitDecision(
            allowed=False,
            should_close=should_close,
            limit=effective_limit,
            count=effective_count,
            violations=violations,
            window_seconds=self.window_seconds,
        )


ws_rate_limiter = WebSocketRateLimiter()
