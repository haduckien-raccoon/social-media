"""Shared utility helpers for posts API and realtime modules."""

from __future__ import annotations

import uuid


def resolve_request_id(request) -> str:
    """Resolve request id from HTTP context.

    Input: DRF/Django request.
    Output: non-empty request identifier string.
    """

    return (
        getattr(request, "request_id", None)
        or request.headers.get("X-Request-ID")
        or request.headers.get("X-Request-Id")
        or request.META.get("HTTP_X_REQUEST_ID")
        or str(uuid.uuid4())
    )


def resolve_ws_request_id(payload: dict | None = None) -> str:
    """Resolve request id for websocket actions.

    Input: websocket payload dict.
    Output: request id string.
    """

    payload = payload or {}
    return payload.get("request_id") or payload.get("requestId") or str(uuid.uuid4())


def serialize_user_brief(user) -> dict:
    """Build compact user payload for realtime events."""

    return {"id": user.id, "username": user.username}
