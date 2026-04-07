"""Presence and typing state storage using Redis heartbeat TTL."""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from threading import Lock

from django.conf import settings

logger = logging.getLogger(__name__)

try:
    import redis
except ImportError:  # pragma: no cover - handled by fallback backend.
    redis = None


class InMemoryPresenceBackend:
    """Fallback backend for tests/local when Redis is unavailable."""

    def __init__(self):
        self._lock = Lock()
        self._connections = {}
        self._user_connections = defaultdict(set)
        self._typing_expiry = {}
        self._typing_throttle_expiry = {}

    def _now(self) -> float:
        return time.monotonic()

    def _cleanup(self):
        now = self._now()

        expired_connections = [
            key for key, (_, expires_at) in self._connections.items() if expires_at <= now
        ]
        for post_id, connection_id in expired_connections:
            user_id, _ = self._connections.pop((post_id, connection_id), (None, None))
            if user_id is None:
                continue
            user_key = (post_id, user_id)
            self._user_connections[user_key].discard(connection_id)
            if not self._user_connections[user_key]:
                self._user_connections.pop(user_key, None)

        expired_typing = [key for key, expires_at in self._typing_expiry.items() if expires_at <= now]
        for key in expired_typing:
            self._typing_expiry.pop(key, None)

        expired_throttle = [
            key for key, expires_at in self._typing_throttle_expiry.items() if expires_at <= now
        ]
        for key in expired_throttle:
            self._typing_throttle_expiry.pop(key, None)

    def subscribe(self, post_id: int, user_id: int, connection_id: str, ttl: int, grace: int) -> bool:
        with self._lock:
            self._cleanup()
            user_key = (post_id, user_id)
            joined = len(self._user_connections[user_key]) == 0

            self._user_connections[user_key].add(connection_id)
            self._connections[(post_id, connection_id)] = (user_id, self._now() + ttl)
            return joined

    def heartbeat(self, post_id: int, user_id: int, connection_id: str, ttl: int, grace: int) -> bool:
        return self.subscribe(post_id, user_id, connection_id, ttl=ttl, grace=grace)

    def unsubscribe(self, post_id: int, user_id: int, connection_id: str) -> bool:
        with self._lock:
            self._cleanup()
            self._connections.pop((post_id, connection_id), None)

            user_key = (post_id, user_id)
            self._user_connections[user_key].discard(connection_id)
            if not self._user_connections[user_key]:
                self._user_connections.pop(user_key, None)
                return True
            return False

    def online_user_ids(self, post_id: int) -> list[int]:
        with self._lock:
            self._cleanup()
            user_ids = [
                user_id
                for (candidate_post_id, user_id), conn_ids in self._user_connections.items()
                if candidate_post_id == post_id and len(conn_ids) > 0
            ]
            return sorted(set(user_ids))

    def start_typing(self, post_id: int, user_id: int, ttl: int, throttle_seconds: int) -> bool:
        with self._lock:
            self._cleanup()
            now = self._now()
            typing_key = (post_id, user_id)
            throttle_key = (post_id, user_id)

            self._typing_expiry[typing_key] = now + ttl

            throttle_expires = self._typing_throttle_expiry.get(throttle_key)
            if throttle_expires and throttle_expires > now:
                return False

            self._typing_throttle_expiry[throttle_key] = now + throttle_seconds
            return True

    def stop_typing(self, post_id: int, user_id: int):
        with self._lock:
            self._typing_expiry.pop((post_id, user_id), None)


class RedisPresenceBackend:
    """Redis-based backend used in production for multi-instance realtime presence."""

    def __init__(self, redis_client):
        self.redis = redis_client
        self.prefix = "presence"

    def _connection_key(self, post_id: int, connection_id: str) -> str:
        return f"{self.prefix}:post:{post_id}:connection:{connection_id}"

    def _user_connections_key(self, post_id: int, user_id: int) -> str:
        return f"{self.prefix}:post:{post_id}:user:{user_id}:connections"

    def _typing_key(self, post_id: int, user_id: int) -> str:
        return f"{self.prefix}:typing:post:{post_id}:user:{user_id}"

    def _typing_throttle_key(self, post_id: int, user_id: int) -> str:
        return f"{self.prefix}:typing_throttle:post:{post_id}:user:{user_id}"

    def _cleanup_user_connections(self, post_id: int, user_id: int):
        user_key = self._user_connections_key(post_id, user_id)
        connection_ids = self.redis.smembers(user_key)
        if not connection_ids:
            return

        stale_connection_ids = [
            connection_id
            for connection_id in connection_ids
            if not self.redis.exists(self._connection_key(post_id, connection_id))
        ]
        if stale_connection_ids:
            self.redis.srem(user_key, *stale_connection_ids)

    def _user_connection_count(self, post_id: int, user_id: int) -> int:
        self._cleanup_user_connections(post_id, user_id)
        return int(self.redis.scard(self._user_connections_key(post_id, user_id)))

    def subscribe(self, post_id: int, user_id: int, connection_id: str, ttl: int, grace: int) -> bool:
        joined = self._user_connection_count(post_id, user_id) == 0

        user_key = self._user_connections_key(post_id, user_id)
        connection_key = self._connection_key(post_id, connection_id)

        pipe = self.redis.pipeline()
        pipe.sadd(user_key, connection_id)
        pipe.expire(user_key, ttl + grace)
        pipe.set(connection_key, user_id, ex=ttl)
        pipe.execute()
        return joined

    def heartbeat(self, post_id: int, user_id: int, connection_id: str, ttl: int, grace: int) -> bool:
        return self.subscribe(post_id, user_id, connection_id, ttl=ttl, grace=grace)

    def unsubscribe(self, post_id: int, user_id: int, connection_id: str) -> bool:
        user_key = self._user_connections_key(post_id, user_id)
        connection_key = self._connection_key(post_id, connection_id)

        pipe = self.redis.pipeline()
        pipe.srem(user_key, connection_id)
        pipe.delete(connection_key)
        pipe.execute()

        left = self._user_connection_count(post_id, user_id) == 0
        if left:
            self.redis.delete(user_key)
        return left

    def online_user_ids(self, post_id: int) -> list[int]:
        user_ids = []
        pattern = self._user_connections_key(post_id, "*")
        for key in self.redis.scan_iter(match=pattern):
            parts = key.split(":")
            if len(parts) < 6:
                continue

            user_id = int(parts[4])
            if self._user_connection_count(post_id, user_id) > 0:
                user_ids.append(user_id)

        return sorted(set(user_ids))

    def start_typing(self, post_id: int, user_id: int, ttl: int, throttle_seconds: int) -> bool:
        typing_key = self._typing_key(post_id, user_id)
        throttle_key = self._typing_throttle_key(post_id, user_id)

        pipe = self.redis.pipeline()
        pipe.set(typing_key, "1", ex=ttl)
        pipe.set(throttle_key, "1", ex=throttle_seconds, nx=True)
        _, should_broadcast = pipe.execute()
        return bool(should_broadcast)

    def stop_typing(self, post_id: int, user_id: int):
        self.redis.delete(self._typing_key(post_id, user_id))


def _create_redis_backend() -> RedisPresenceBackend | None:
    if redis is None:
        logger.warning("redis package is missing, using in-memory presence fallback")
        return None

    redis_url = getattr(settings, "REDIS_URL", None)
    if not redis_url:
        logger.warning("REDIS_URL is not set, using in-memory presence fallback")
        return None

    try:
        client = redis.Redis.from_url(redis_url, decode_responses=True, socket_timeout=1)
        client.ping()
        return RedisPresenceBackend(client)
    except Exception:
        logger.exception("Failed to connect Redis, using in-memory presence fallback")
        return None


class PresenceStore:
    """Facade over Redis presence backend with safe in-memory fallback."""

    def __init__(self):
        self._fallback_backend = InMemoryPresenceBackend()
        self._redis_backend = _create_redis_backend()

    def _backend(self):
        return self._redis_backend or self._fallback_backend

    def subscribe(self, post_id: int, user_id: int, connection_id: str) -> bool:
        """Track a connection in a post room; returns True if user just became online."""

        ttl = int(getattr(settings, "PRESENCE_TTL_SECONDS", 30))
        grace = int(getattr(settings, "PRESENCE_GRACE_SECONDS", 30))
        try:
            return self._backend().subscribe(post_id, user_id, connection_id, ttl=ttl, grace=grace)
        except Exception:
            logger.exception("Presence subscribe failed, fallback in-memory")
            return self._fallback_backend.subscribe(post_id, user_id, connection_id, ttl=ttl, grace=grace)

    def heartbeat(self, post_id: int, user_id: int, connection_id: str) -> bool:
        """Refresh heartbeat TTL; returns True if heartbeat recovered an offline user."""

        ttl = int(getattr(settings, "PRESENCE_TTL_SECONDS", 30))
        grace = int(getattr(settings, "PRESENCE_GRACE_SECONDS", 30))
        try:
            return self._backend().heartbeat(post_id, user_id, connection_id, ttl=ttl, grace=grace)
        except Exception:
            logger.exception("Presence heartbeat failed, fallback in-memory")
            return self._fallback_backend.heartbeat(post_id, user_id, connection_id, ttl=ttl, grace=grace)

    def unsubscribe(self, post_id: int, user_id: int, connection_id: str) -> bool:
        """Remove connection from room; returns True when user is fully offline."""

        try:
            return self._backend().unsubscribe(post_id, user_id, connection_id)
        except Exception:
            logger.exception("Presence unsubscribe failed, fallback in-memory")
            return self._fallback_backend.unsubscribe(post_id, user_id, connection_id)

    def get_online_user_ids(self, post_id: int) -> list[int]:
        """Get current online user ids in a post room."""

        try:
            return self._backend().online_user_ids(post_id)
        except Exception:
            logger.exception("Presence online snapshot failed, fallback in-memory")
            return self._fallback_backend.online_user_ids(post_id)

    def start_typing(self, post_id: int, user_id: int) -> bool:
        """Mark user typing with throttle; returns True when event should be broadcast."""

        ttl = int(getattr(settings, "TYPING_TTL_SECONDS", 6))
        throttle_seconds = int(getattr(settings, "TYPING_THROTTLE_SECONDS", 1))

        try:
            return self._backend().start_typing(
                post_id,
                user_id,
                ttl=ttl,
                throttle_seconds=throttle_seconds,
            )
        except Exception:
            logger.exception("Typing start failed, fallback in-memory")
            return self._fallback_backend.start_typing(
                post_id,
                user_id,
                ttl=ttl,
                throttle_seconds=throttle_seconds,
            )

    def stop_typing(self, post_id: int, user_id: int):
        """Clear typing state for a user in a post room."""

        try:
            self._backend().stop_typing(post_id, user_id)
        except Exception:
            logger.exception("Typing stop failed, fallback in-memory")
            self._fallback_backend.stop_typing(post_id, user_id)


presence_store = PresenceStore()
