"""Realtime websocket consumer for post rooms, presence and typing events."""

from __future__ import annotations

import logging
import time
import uuid

from asgiref.sync import sync_to_async
from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.contrib.auth import get_user_model

from apps.core.logging_utils import clear_log_context
from apps.core.logging_utils import set_log_context

from .models import Post
from .presence import presence_store
from .rate_limit import ws_rate_limiter
from .realtime import build_event
from .realtime import feed_group_name
from .realtime import post_group_name
from .utils import serialize_user_brief
from .utils import resolve_ws_request_id

logger = logging.getLogger(__name__)
User = get_user_model()


@database_sync_to_async
def _post_exists(post_id: int) -> bool:
    return Post.objects.filter(id=post_id).exists()


@database_sync_to_async
def _users_payload(user_ids: list[int]) -> list[dict]:
    user_map = {
        row["id"]: {"id": row["id"], "username": row["username"]}
        for row in User.objects.filter(id__in=user_ids).values("id", "username")
    }
    return [user_map[user_id] for user_id in user_ids if user_id in user_map]


class RealtimeConsumer(AsyncJsonWebsocketConsumer):
    """Handle websocket actions for post subscription, presence and typing."""

    async def connect(self):
        user = self.scope.get("user")
        if not user or not user.is_authenticated:
            await self.close(code=4401)
            return

        self.user = user
        self.connection_id = str(uuid.uuid4())
        self.subscribed_posts = set()
        self.subscribed_feeds = set()

        set_log_context(user_id=self.user.id, connection_id=self.connection_id, event="ws.connected")
        logger.info("ws_connected")
        clear_log_context()
        await self.accept()

    async def disconnect(self, code):
        for feed_id in list(getattr(self, "subscribed_feeds", set())):
            await self._unsubscribe_feed(feed_id, request_id=None, notify_client=False)
        for post_id in list(getattr(self, "subscribed_posts", set())):
            await self._unsubscribe_post(post_id, request_id=None)
        set_log_context(user_id=getattr(self, "user", None) and self.user.id, connection_id=getattr(self, "connection_id", None), event="ws.disconnected")
        logger.info("ws_disconnected", extra={"action": "disconnect"})
        clear_log_context()

    async def receive_json(self, content, **kwargs):
        action = content.get("action")
        request_id = resolve_ws_request_id(content)
        started_at = time.perf_counter()

        set_log_context(
            request_id=request_id,
            user_id=self.user.id,
            connection_id=self.connection_id,
            action=action or "unknown",
        )

        decision = await sync_to_async(ws_rate_limiter.check)(
            connection_id=self.connection_id,
            action=action or "unknown",
        )
        if not decision.allowed:
            logger.warning(
                "ws_rate_limited",
                extra={
                    "event": "ws.rate_limited",
                    "error_code": "rate_limited",
                    "latency_ms": round((time.perf_counter() - started_at) * 1000, 2),
                },
            )
            await self._send_error(
                "Rate limit exceeded",
                request_id=request_id,
                code="rate_limited",
                details={
                    "action": action,
                    "limit": decision.limit,
                    "count": decision.count,
                    "window_seconds": decision.window_seconds,
                    "violations": decision.violations,
                },
            )
            if decision.should_close:
                await self.close(code=4408)
            clear_log_context()
            return

        try:
            if action == "subscribe_post":
                await self._handle_subscribe(content, request_id)
                return

            if action == "unsubscribe_post":
                await self._handle_unsubscribe(content, request_id)
                return

            if action == "subscribe_feed":
                await self._handle_subscribe_feed(request_id)
                return

            if action == "unsubscribe_feed":
                await self._handle_unsubscribe_feed(request_id)
                return

            if action == "heartbeat":
                await self._handle_heartbeat(content, request_id)
                return

            if action == "typing_start":
                await self._handle_typing_start(content, request_id)
                return

            if action == "typing_stop":
                await self._handle_typing_stop(content, request_id)
                return

            await self._send_error("Unsupported action", request_id=request_id, code="unsupported_action")
        except Exception:
            logger.exception(
                "ws_action_failed",
                extra={"event": "ws.action_failed", "error_code": "ws_action_failed"},
            )
            await self._send_error("WebSocket action failed", request_id=request_id, code="internal_error")
        finally:
            logger.info(
                "ws_action_processed",
                extra={
                    "event": "ws.action_processed",
                    "latency_ms": round((time.perf_counter() - started_at) * 1000, 2),
                },
            )
            clear_log_context()

    async def _handle_subscribe(self, content: dict, request_id: str | None):
        post_id = self._extract_post_id(content)
        if post_id is None:
            await self._send_error("post_id is required", request_id=request_id)
            return

        if not await _post_exists(post_id):
            await self._send_error("Post not found", post_id=post_id, request_id=request_id)
            return

        joined = await sync_to_async(presence_store.subscribe)(post_id, self.user.id, self.connection_id)
        if joined and post_id not in self.subscribed_posts:
            await self.channel_layer.group_send(
                post_group_name(post_id),
                {
                    "type": "broadcast.event",
                    "payload": build_event(
                        "presence.joined",
                        post_id,
                        {"user": serialize_user_brief(self.user)},
                        request_id=request_id,
                    ),
                },
            )

        if post_id not in self.subscribed_posts:
            await self.channel_layer.group_add(post_group_name(post_id), self.channel_name)
            self.subscribed_posts.add(post_id)

        viewers = await self._current_viewers(post_id)
        await self.send_json(
            build_event(
                "presence.snapshot",
                post_id,
                {"viewers": viewers},
                request_id=request_id,
            )
        )

    async def _handle_subscribe_feed(self, request_id: str | None):
        feed_id = self.user.id
        if feed_id in self.subscribed_feeds:
            await self.send_json(
                build_event(
                    "feed.snapshot",
                    0,
                    {"subscribed": True, "user_id": feed_id},
                    request_id=request_id,
                )
            )
            return

        await self.channel_layer.group_add(feed_group_name(feed_id), self.channel_name)
        self.subscribed_feeds.add(feed_id)
        await self.send_json(
            build_event(
                "feed.snapshot",
                0,
                {"subscribed": True, "user_id": feed_id},
                request_id=request_id,
            )
        )

    async def _handle_unsubscribe_feed(self, request_id: str | None):
        feed_id = self.user.id
        if feed_id not in self.subscribed_feeds:
            await self._send_error(
                "Feed subscription is not active",
                request_id=request_id,
                code="feed_not_subscribed",
            )
            return
        await self._unsubscribe_feed(feed_id, request_id=request_id, notify_client=True)

    async def _handle_unsubscribe(self, content: dict, request_id: str | None):
        post_id = self._extract_post_id(content)
        if post_id is None:
            await self._send_error("post_id is required", request_id=request_id)
            return

        if post_id not in self.subscribed_posts:
            await self._send_error("Not subscribed to post", post_id=post_id, request_id=request_id)
            return

        await self._unsubscribe_post(post_id, request_id=request_id)

    async def _handle_heartbeat(self, content: dict, request_id: str | None):
        post_id = self._extract_post_id(content)
        targets = [post_id] if post_id is not None else list(self.subscribed_posts)

        if not targets:
            await self._send_error("No subscribed posts for heartbeat", request_id=request_id)
            return

        for target_post_id in targets:
            if target_post_id not in self.subscribed_posts:
                continue

            rejoined = await sync_to_async(presence_store.heartbeat)(
                target_post_id,
                self.user.id,
                self.connection_id,
            )
            if rejoined:
                await self.channel_layer.group_send(
                    post_group_name(target_post_id),
                    {
                        "type": "broadcast.event",
                        "payload": build_event(
                            "presence.joined",
                            target_post_id,
                            {"user": serialize_user_brief(self.user)},
                            request_id=request_id,
                        ),
                    },
                )

    async def _handle_typing_start(self, content: dict, request_id: str | None):
        post_id = self._extract_post_id(content)
        if post_id is None:
            await self._send_error("post_id is required", request_id=request_id)
            return

        if post_id not in self.subscribed_posts:
            await self._send_error("Subscribe post before typing", post_id=post_id, request_id=request_id)
            return

        should_broadcast = await sync_to_async(presence_store.start_typing)(post_id, self.user.id)
        if not should_broadcast:
            return

        await self.channel_layer.group_send(
            post_group_name(post_id),
            {
                "type": "broadcast.event",
                "payload": build_event(
                    "typing.started",
                    post_id,
                    {"user": serialize_user_brief(self.user)},
                    request_id=request_id,
                ),
            },
        )

    async def _handle_typing_stop(self, content: dict, request_id: str | None):
        post_id = self._extract_post_id(content)
        if post_id is None:
            await self._send_error("post_id is required", request_id=request_id)
            return

        if post_id not in self.subscribed_posts:
            await self._send_error("Subscribe post before typing", post_id=post_id, request_id=request_id)
            return

        await sync_to_async(presence_store.stop_typing)(post_id, self.user.id)

        await self.channel_layer.group_send(
            post_group_name(post_id),
            {
                "type": "broadcast.event",
                "payload": build_event(
                    "typing.stopped",
                    post_id,
                    {"user": serialize_user_brief(self.user)},
                    request_id=request_id,
                ),
            },
        )

    async def _unsubscribe_post(self, post_id: int, request_id: str | None):
        left = await sync_to_async(presence_store.unsubscribe)(post_id, self.user.id, self.connection_id)

        await self.channel_layer.group_discard(post_group_name(post_id), self.channel_name)
        self.subscribed_posts.discard(post_id)

        if left:
            await self.channel_layer.group_send(
                post_group_name(post_id),
                {
                    "type": "broadcast.event",
                    "payload": build_event(
                        "presence.left",
                        post_id,
                        {"user": serialize_user_brief(self.user)},
                        request_id=request_id,
                    ),
                },
            )

    async def _unsubscribe_feed(
        self,
        feed_id: int,
        request_id: str | None,
        notify_client: bool = True,
    ):
        await self.channel_layer.group_discard(feed_group_name(feed_id), self.channel_name)
        self.subscribed_feeds.discard(feed_id)
        if notify_client:
            await self.send_json(
                build_event(
                    "feed.snapshot",
                    0,
                    {"subscribed": False, "user_id": feed_id},
                    request_id=request_id,
                )
            )

    async def _current_viewers(self, post_id: int) -> list[dict]:
        user_ids = await sync_to_async(presence_store.get_online_user_ids)(post_id)
        return await _users_payload(user_ids)

    async def _send_error(
        self,
        message: str,
        post_id: int | None = None,
        request_id: str | None = None,
        code: str = "invalid_request",
        details: dict | None = None,
    ):
        await self.send_json(
            build_event(
                "error",
                post_id or 0,
                {"message": message, "code": code, "details": details or {}},
                request_id=request_id,
            )
        )

    def _extract_post_id(self, content: dict) -> int | None:
        post_id = content.get("post_id")
        if post_id is None:
            return None

        try:
            return int(post_id)
        except (TypeError, ValueError):
            return None

    async def broadcast_event(self, event):
        """Forward server-side group events to websocket client."""

        await self.send_json(event["payload"])
