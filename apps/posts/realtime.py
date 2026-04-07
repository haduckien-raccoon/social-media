"""Utilities for publishing realtime events to websocket groups."""

from __future__ import annotations

import logging
import uuid

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.utils import timezone

logger = logging.getLogger(__name__)


def post_group_name(post_id: int) -> str:
    """Return deterministic channel group name for a post room."""

    return f"post_{post_id}"


def feed_group_name(user_id: int) -> str:
    """Return deterministic channel group name for a user's following feed."""

    return f"feed_{user_id}"


def build_event(event_name: str, post_id: int, data: dict, request_id: str | None = None) -> dict:
    """Build canonical event envelope for websocket clients.

    Input: event name, post id, payload data, optional request id.
    Output: serialized event dict ready to send over websocket.
    """

    return {
        "event": event_name,
        "post_id": post_id,
        "data": data,
        "ts": timezone.now().isoformat(),
        "request_id": request_id or str(uuid.uuid4()),
    }


def publish_post_event(event_name: str, post_id: int, data: dict, request_id: str | None = None) -> dict:
    """Send event to all websocket subscribers of the post room.

    Input: event metadata and payload.
    Output: event envelope (even when layer is unavailable).
    """

    payload = build_event(event_name, post_id, data, request_id=request_id)
    channel_layer = get_channel_layer()
    if channel_layer is None:
        logger.warning("Channel layer unavailable, skip realtime publish", extra={"event": payload})
        return payload

    try:
        async_to_sync(channel_layer.group_send)(
            post_group_name(post_id),
            {
                "type": "broadcast.event",
                "payload": payload,
            },
        )
    except Exception:
        logger.exception(
            "Failed to publish realtime event",
            extra={"event_name": event_name, "post_id": post_id, "request_id": payload["request_id"]},
        )

    return payload


def publish_feed_event(
    *,
    event_name: str,
    user_id: int,
    post_id: int,
    data: dict,
    request_id: str | None = None,
) -> dict:
    """Publish an event to one user's feed websocket room.

    Input: event metadata, target user id, post id and payload.
    Output: canonical event envelope.
    """

    payload = build_event(event_name, post_id, data, request_id=request_id)
    channel_layer = get_channel_layer()
    if channel_layer is None:
        logger.warning("Channel layer unavailable, skip feed realtime publish", extra={"event": payload})
        return payload

    try:
        async_to_sync(channel_layer.group_send)(
            feed_group_name(user_id),
            {
                "type": "broadcast.event",
                "payload": payload,
            },
        )
    except Exception:
        logger.exception(
            "Failed to publish feed realtime event",
            extra={
                "event_name": event_name,
                "user_id": user_id,
                "post_id": post_id,
                "request_id": payload["request_id"],
            },
        )

    return payload
