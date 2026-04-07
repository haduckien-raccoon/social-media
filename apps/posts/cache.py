"""Redis caching layer for post/comment/reaction data with graceful fallback.

Caches reaction summaries, post metadata and comment counts to reduce
database load on high-frequency read paths. All writes go through
invalidation helpers so cached data stays consistent.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from django.conf import settings

logger = logging.getLogger(__name__)

# Cache TTL defaults (seconds)
REACTION_SUMMARY_TTL = 300      # 5 minutes
POST_DETAIL_TTL = 120           # 2 minutes
COMMENT_COUNT_TTL = 300         # 5 minutes
ONLINE_USERS_TTL = 30           # 30 seconds (matched to presence TTL)

_PREFIX = "social:cache"

try:
    import redis as _redis_lib
except ImportError:
    _redis_lib = None


def _get_redis_client():
    """Return a shared Redis client or None if unavailable.

    Input: none.
    Output: redis.Redis instance or None.
    """
    if _redis_lib is None:
        return None
    redis_url = getattr(settings, "REDIS_URL", None)
    if not redis_url:
        return None
    try:
        client = _redis_lib.Redis.from_url(redis_url, decode_responses=True, socket_timeout=1)
        client.ping()
        return client
    except Exception:
        logger.warning("cache_redis_unavailable", extra={"event": "cache.redis_unavailable"})
        return None


_client = _get_redis_client()


def _safe_get(key: str) -> str | None:
    """Read from Redis; return None on failure.

    Input: cache key string.
    Output: cached value string or None.
    """
    if _client is None:
        return None
    try:
        return _client.get(key)
    except Exception:
        logger.warning("cache_get_failed", extra={"key": key})
        return None


def _safe_set(key: str, value: str, ttl: int) -> bool:
    """Write to Redis with TTL; return False on failure.

    Input: key, JSON string value, TTL in seconds.
    Output: True if written successfully.
    """
    if _client is None:
        return False
    try:
        _client.set(key, value, ex=ttl)
        return True
    except Exception:
        logger.warning("cache_set_failed", extra={"key": key})
        return False


def _safe_delete(*keys: str) -> bool:
    """Delete one or more keys from Redis.

    Input: one or more cache key strings.
    Output: True if deleted successfully.
    """
    if _client is None:
        return False
    try:
        _client.delete(*keys)
        return True
    except Exception:
        logger.warning("cache_delete_failed", extra={"keys": keys})
        return False


# ─── Reaction Summary Cache ──────────────────────────────────────────

def _post_reaction_key(post_id: int) -> str:
    return f"{_PREFIX}:post_reaction:{post_id}"


def _comment_reaction_key(comment_id: int) -> str:
    return f"{_PREFIX}:comment_reaction:{comment_id}"


def get_cached_post_reaction_summary(post_id: int) -> dict | None:
    """Fetch cached reaction summary for a post.

    Input: post_id (int).
    Output: dict like {"like": 5, "love": 2, ...} or None on cache miss.
    Example output: {"like": 5, "love": 2, "haha": 0, "wow": 1, "sad": 0, "angry": 0}
    """
    raw = _safe_get(_post_reaction_key(post_id))
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


def set_cached_post_reaction_summary(post_id: int, summary: dict) -> bool:
    """Cache reaction summary for a post.

    Input: post_id (int), summary dict mapping reaction_type to count.
    Output: True if cached successfully.
    Example input: post_id=1, summary={"like": 5, "love": 2, "haha": 0, ...}
    """
    return _safe_set(_post_reaction_key(post_id), json.dumps(summary), REACTION_SUMMARY_TTL)


def invalidate_post_reaction_cache(post_id: int) -> bool:
    """Remove cached reaction summary for a post after mutation.

    Input: post_id (int).
    Output: True if invalidated successfully.
    """
    return _safe_delete(_post_reaction_key(post_id))


def get_cached_comment_reaction_summary(comment_id: int) -> dict | None:
    """Fetch cached reaction summary for a comment.

    Input: comment_id (int).
    Output: dict like {"like": 3, ...} or None on cache miss.
    """
    raw = _safe_get(_comment_reaction_key(comment_id))
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


def set_cached_comment_reaction_summary(comment_id: int, summary: dict) -> bool:
    """Cache reaction summary for a comment.

    Input: comment_id (int), summary dict.
    Output: True if cached successfully.
    """
    return _safe_set(_comment_reaction_key(comment_id), json.dumps(summary), REACTION_SUMMARY_TTL)


def invalidate_comment_reaction_cache(comment_id: int) -> bool:
    """Remove cached reaction summary for a comment after mutation.

    Input: comment_id (int).
    Output: True if invalidated successfully.
    """
    return _safe_delete(_comment_reaction_key(comment_id))


# ─── Post Detail Cache ───────────────────────────────────────────────

def _post_detail_key(post_id: int) -> str:
    return f"{_PREFIX}:post_detail:{post_id}"


def get_cached_post_detail(post_id: int) -> dict | None:
    """Fetch cached serialized post detail.

    Input: post_id (int).
    Output: dict (serialized post) or None on cache miss.
    """
    raw = _safe_get(_post_detail_key(post_id))
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


def set_cached_post_detail(post_id: int, data: dict) -> bool:
    """Cache serialized post detail.

    Input: post_id (int), data dict (serialized PostSerializer output).
    Output: True if cached successfully.
    """
    return _safe_set(_post_detail_key(post_id), json.dumps(data, default=str), POST_DETAIL_TTL)


def invalidate_post_detail_cache(post_id: int) -> bool:
    """Remove cached post detail after post mutation.

    Input: post_id (int).
    Output: True if invalidated.
    """
    return _safe_delete(_post_detail_key(post_id))


# ─── Comment Count Cache ─────────────────────────────────────────────

def _comment_count_key(post_id: int) -> str:
    return f"{_PREFIX}:comment_count:{post_id}"


def get_cached_comment_count(post_id: int) -> int | None:
    """Fetch cached comment count for a post.

    Input: post_id (int).
    Output: int count or None on cache miss.
    """
    raw = _safe_get(_comment_count_key(post_id))
    if raw is None:
        return None
    try:
        return int(raw)
    except (ValueError, TypeError):
        return None


def set_cached_comment_count(post_id: int, count: int) -> bool:
    """Cache comment count for a post.

    Input: post_id (int), count (int).
    Output: True if cached successfully.
    """
    return _safe_set(_comment_count_key(post_id), str(count), COMMENT_COUNT_TTL)


def invalidate_comment_count_cache(post_id: int) -> bool:
    """Remove cached comment count for a post after comment mutation.

    Input: post_id (int).
    Output: True if invalidated.
    """
    return _safe_delete(_comment_count_key(post_id))


# ─── Bulk Invalidation ───────────────────────────────────────────────

def invalidate_post_caches(post_id: int) -> bool:
    """Invalidate all caches related to a post (detail, reactions, comments).

    Input: post_id (int).
    Output: True if all invalidations succeeded.
    """
    keys = [
        _post_detail_key(post_id),
        _post_reaction_key(post_id),
        _comment_count_key(post_id),
    ]
    return _safe_delete(*keys)
