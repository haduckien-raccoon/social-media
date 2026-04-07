"""Centralized event processing pipeline for realtime post/comment/reaction events.

Handles event validation, enrichment, idempotency deduplication and routing
to WebSocket groups via the channel layer. Provides batching support for
high-throughput scenarios.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

# ─── Event Type Constants ────────────────────────────────────────────

# Post lifecycle events
EVENT_POST_CREATED = "post.created"
EVENT_POST_UPDATED = "post.updated"
EVENT_POST_DELETED = "post.deleted"

# Comment lifecycle events
EVENT_COMMENT_CREATED = "comment.created"
EVENT_COMMENT_UPDATED = "comment.updated"
EVENT_COMMENT_DELETED = "comment.deleted"

# Reaction events
EVENT_REACTION_POST_UPDATED = "reaction.post.updated"
EVENT_REACTION_COMMENT_UPDATED = "reaction.comment.updated"

# Presence events
EVENT_PRESENCE_JOINED = "presence.joined"
EVENT_PRESENCE_LEFT = "presence.left"
EVENT_PRESENCE_SNAPSHOT = "presence.snapshot"

# Typing events
EVENT_TYPING_STARTED = "typing.started"
EVENT_TYPING_STOPPED = "typing.stopped"

# Error event
EVENT_ERROR = "error"

ALL_EVENT_TYPES = frozenset({
    EVENT_POST_CREATED, EVENT_POST_UPDATED, EVENT_POST_DELETED,
    EVENT_COMMENT_CREATED, EVENT_COMMENT_UPDATED, EVENT_COMMENT_DELETED,
    EVENT_REACTION_POST_UPDATED, EVENT_REACTION_COMMENT_UPDATED,
    EVENT_PRESENCE_JOINED, EVENT_PRESENCE_LEFT, EVENT_PRESENCE_SNAPSHOT,
    EVENT_TYPING_STARTED, EVENT_TYPING_STOPPED,
    EVENT_ERROR,
})

# Events that mutate data (require cache invalidation)
MUTATION_EVENTS = frozenset({
    EVENT_POST_CREATED, EVENT_POST_UPDATED, EVENT_POST_DELETED,
    EVENT_COMMENT_CREATED, EVENT_COMMENT_UPDATED, EVENT_COMMENT_DELETED,
    EVENT_REACTION_POST_UPDATED, EVENT_REACTION_COMMENT_UPDATED,
})

# Idempotency window (seconds) - events with same idempotency key within this
# window are considered duplicates and skipped.
IDEMPOTENCY_WINDOW = int(getattr(settings, "EVENT_IDEMPOTENCY_WINDOW", 60))


@dataclass
class RealtimeEvent:
    """Canonical envelope for a realtime event to be delivered over WebSocket.

    Fields:
        event_type: one of the EVENT_* constants
        post_id: target post room for routing
        data: payload data dict
        request_id: correlation id for tracing
        timestamp: ISO 8601 timestamp string
        idempotency_key: optional key for dedup (auto-generated if not set)
    """
    event_type: str
    post_id: int
    data: dict = field(default_factory=dict)
    request_id: str = ""
    timestamp: str = ""
    idempotency_key: str = ""

    def __post_init__(self):
        if not self.request_id:
            self.request_id = str(uuid.uuid4())
        if not self.timestamp:
            self.timestamp = timezone.now().isoformat()
        if not self.idempotency_key:
            self.idempotency_key = f"{self.event_type}:{self.post_id}:{self.request_id}"

    def to_dict(self) -> dict:
        """Serialize event to dict for WebSocket delivery.

        Input: none.
        Output: dict with event, post_id, data, ts, request_id keys.
        Example output:
            {
                "event": "post.created",
                "post_id": 1,
                "data": {"post": {...}},
                "ts": "2026-04-05T10:00:00+07:00",
                "request_id": "abc-123"
            }
        """
        return {
            "event": self.event_type,
            "post_id": self.post_id,
            "data": self.data,
            "ts": self.timestamp,
            "request_id": self.request_id,
        }


# ─── Idempotency Store ──────────────────────────────────────────────

try:
    import redis as _redis_lib
except ImportError:
    _redis_lib = None


def _get_idempotency_client():
    """Get Redis client for idempotency checks.

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
        return None


_idempotency_client = _get_idempotency_client()


def _check_idempotency(key: str) -> bool:
    """Check if event with given key has been processed recently.

    Input: idempotency key string.
    Output: True if already processed (duplicate), False if new.
    """
    if _idempotency_client is None:
        return False  # No dedup without Redis
    try:
        result = _idempotency_client.set(
            f"social:idemp:{key}", "1", ex=IDEMPOTENCY_WINDOW, nx=True
        )
        # SET NX returns True if key was set (new), None if key already exists (duplicate)
        return result is None
    except Exception:
        logger.warning("idempotency_check_failed", extra={"key": key})
        return False  # Allow processing on failure


# ─── Event Processor ─────────────────────────────────────────────────

class EventProcessor:
    """Central pipeline for validating, enriching and dispatching realtime events.

    Usage:
        processor = EventProcessor()
        event = RealtimeEvent(
            event_type=EVENT_POST_CREATED,
            post_id=1,
            data={"post": {...}},
        )
        processor.process(event)

    The processor:
    1. Validates event type is known
    2. Checks idempotency (skip duplicates)
    3. Dispatches to channel layer group for WebSocket delivery
    4. Logs structured event metadata for observability
    """

    def __init__(self):
        self._batch: list[RealtimeEvent] = []

    def validate(self, event: RealtimeEvent) -> bool:
        """Validate event structure and type.

        Input: RealtimeEvent instance.
        Output: True if valid.
        Raises: ValueError for invalid events.
        """
        if event.event_type not in ALL_EVENT_TYPES:
            raise ValueError(f"Unknown event type: {event.event_type}")
        if not isinstance(event.post_id, int) or event.post_id < 0:
            raise ValueError(f"Invalid post_id: {event.post_id}")
        return True

    def is_duplicate(self, event: RealtimeEvent) -> bool:
        """Check if event is a duplicate via idempotency store.

        Input: RealtimeEvent instance.
        Output: True if duplicate (should be skipped).
        """
        return _check_idempotency(event.idempotency_key)

    def process(self, event: RealtimeEvent) -> bool:
        """Validate, deduplicate and dispatch a single event.

        Input: RealtimeEvent instance.
        Output: True if event was dispatched, False if skipped.
        Example:
            event = RealtimeEvent(EVENT_POST_CREATED, post_id=1, data={...})
            dispatched = processor.process(event)  # True
        """
        started_at = time.perf_counter()

        try:
            self.validate(event)
        except ValueError as exc:
            logger.warning(
                "event_validation_failed",
                extra={
                    "event": "event.validation_failed",
                    "event_type": event.event_type,
                    "error": str(exc),
                },
            )
            return False

        if self.is_duplicate(event):
            logger.info(
                "event_duplicate_skipped",
                extra={
                    "event": "event.duplicate_skipped",
                    "event_type": event.event_type,
                    "idempotency_key": event.idempotency_key,
                },
            )
            return False

        dispatched = self._dispatch(event)

        latency_ms = round((time.perf_counter() - started_at) * 1000, 2)
        logger.info(
            "event_processed",
            extra={
                "event": "event.processed",
                "event_type": event.event_type,
                "post_id": event.post_id,
                "request_id": event.request_id,
                "latency_ms": latency_ms,
                "dispatched": dispatched,
            },
        )
        return dispatched

    def add_to_batch(self, event: RealtimeEvent):
        """Queue event for batch processing.

        Input: RealtimeEvent instance.
        Output: none.
        """
        self._batch.append(event)

    def flush_batch(self) -> int:
        """Process all queued events and clear the batch.

        Input: none.
        Output: number of events successfully dispatched.
        Example: count = processor.flush_batch()  # 5
        """
        dispatched = 0
        for event in self._batch:
            if self.process(event):
                dispatched += 1
        self._batch.clear()
        return dispatched

    def _dispatch(self, event: RealtimeEvent) -> bool:
        """Send event to channel layer group for WebSocket broadcast.

        Input: RealtimeEvent instance.
        Output: True if sent successfully.
        """
        from asgiref.sync import async_to_sync
        from channels.layers import get_channel_layer

        from .realtime import post_group_name

        channel_layer = get_channel_layer()
        if channel_layer is None:
            logger.warning(
                "channel_layer_unavailable",
                extra={"event": "event.channel_layer_unavailable"},
            )
            return False

        try:
            async_to_sync(channel_layer.group_send)(
                post_group_name(event.post_id),
                {
                    "type": "broadcast.event",
                    "payload": event.to_dict(),
                },
            )
            return True
        except Exception:
            logger.exception(
                "event_dispatch_failed",
                extra={
                    "event": "event.dispatch_failed",
                    "event_type": event.event_type,
                    "post_id": event.post_id,
                },
            )
            return False

    def is_mutation_event(self, event: RealtimeEvent) -> bool:
        """Check if event is a data mutation event requiring cache invalidation.

        Input: RealtimeEvent instance.
        Output: True if event mutates data.
        """
        return event.event_type in MUTATION_EVENTS


# Module-level singleton
event_processor = EventProcessor()
