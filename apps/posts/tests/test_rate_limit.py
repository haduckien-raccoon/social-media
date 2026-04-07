import json
import logging
from unittest.mock import patch

from asgiref.sync import async_to_sync
from channels.testing import WebsocketCommunicator
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.test import TransactionTestCase
from django.test import override_settings

from apps.accounts.services import create_jwt_pair_for_user
from apps.core.logging_utils import JSONLogFormatter
from apps.core.logging_utils import RequestContextFilter
from apps.core.logging_utils import clear_log_context
from apps.core.logging_utils import set_log_context
from apps.posts.models import Post
from apps.posts.rate_limit import WebSocketRateLimiter
from config.asgi import application

User = get_user_model()


@override_settings(
    REDIS_URL="",
    WS_RATE_WINDOW_SECONDS=10,
    WS_RATE_MAX_MESSAGES=5,
    WS_RATE_TYPING_MAX=2,
    WS_RATE_HEARTBEAT_MAX=3,
    WS_RATE_VIOLATION_CLOSE_THRESHOLD=2,
)
class WebSocketRateLimiterTests(TestCase):
    def test_typing_limit_and_close_threshold(self):
        limiter = WebSocketRateLimiter()

        first = limiter.check(connection_id="c1", action="typing_start")
        second = limiter.check(connection_id="c1", action="typing_start")
        third = limiter.check(connection_id="c1", action="typing_start")
        fourth = limiter.check(connection_id="c1", action="typing_start")

        self.assertTrue(first.allowed)
        self.assertTrue(second.allowed)
        self.assertFalse(third.allowed)
        self.assertFalse(third.should_close)
        self.assertFalse(fourth.allowed)
        self.assertTrue(fourth.should_close)


class StructuredLoggingTests(TestCase):
    def test_json_formatter_contains_required_fields(self):
        logger = logging.getLogger("apps.tests.logging")
        record = logger.makeRecord(
            name="apps.tests.logging",
            level=logging.INFO,
            fn=__file__,
            lno=10,
            msg="test_message",
            args=(),
            exc_info=None,
            extra={"event": "test.event", "latency_ms": 12.5},
        )

        set_log_context(request_id="req-1", user_id=7, action="GET")
        try:
            RequestContextFilter().filter(record)
            payload = json.loads(JSONLogFormatter().format(record))
        finally:
            clear_log_context()

        self.assertEqual(payload["request_id"], "req-1")
        self.assertEqual(payload["user_id"], 7)
        self.assertEqual(payload["event"], "test.event")
        self.assertEqual(payload["latency_ms"], 12.5)


@override_settings(
    REDIS_URL="",
    WS_RATE_WINDOW_SECONDS=10,
    WS_RATE_MAX_MESSAGES=1,
    WS_RATE_TYPING_MAX=1,
    WS_RATE_HEARTBEAT_MAX=1,
    WS_RATE_VIOLATION_CLOSE_THRESHOLD=2,
    CHANNEL_LAYERS={
        "default": {
            "BACKEND": "channels.layers.InMemoryChannelLayer",
        }
    },
)
class WebSocketRateLimitIntegrationTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.user = User.objects.create_user(
            email="ratelimit@example.com",
            username="ratelimit-user",
            password="123456",
            is_active=True,
        )
        self.post = Post.objects.create(author=self.user, content="post")
        self.access, _ = create_jwt_pair_for_user(self.user)

    def test_ws_rate_limit_exceeded_returns_error(self):
        async def scenario():
            with patch("apps.posts.consumers.ws_rate_limiter", WebSocketRateLimiter()):
                ws = WebsocketCommunicator(application, f"/ws/realtime/?access={self.access}")
                connected, _ = await ws.connect()
                self.assertTrue(connected)

                await ws.send_json_to({"action": "subscribe_post", "post_id": self.post.id})
                await ws.receive_json_from(timeout=2)

                await ws.send_json_to({"action": "subscribe_post", "post_id": self.post.id})
                payload = await ws.receive_json_from(timeout=2)
                self.assertEqual(payload["event"], "error")
                self.assertEqual(payload["data"]["code"], "rate_limited")

                await ws.disconnect()

        async_to_sync(scenario)()
