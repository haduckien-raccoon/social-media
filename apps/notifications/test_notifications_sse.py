from datetime import datetime
import json
from unittest.mock import patch

from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, TestCase, override_settings

from apps.accounts.models import User
from apps.notifications.models import Notification
from apps.notifications.signals import _get_redis_client as get_signal_redis_client
from apps.notifications.views import _get_redis_client as get_stream_redis_client
from apps.notifications.views import sse_notifications


class _FakePubSub:
    def __init__(self, messages):
        self.messages = list(messages)
        self.subscribed_channel = None

    def subscribe(self, channel):
        self.subscribed_channel = channel

    def get_message(self, timeout=0):
        if not self.messages:
            return None
        next_message = self.messages.pop(0)
        if isinstance(next_message, Exception):
            raise next_message
        return next_message

    def unsubscribe(self, channel):
        self.subscribed_channel = None

    def close(self):
        pass


class _FakeRedisClient:
    def __init__(self, pubsub):
        self._pubsub = pubsub

    def pubsub(self, ignore_subscribe_messages=True):
        return self._pubsub


class _FailingRedisClient:
    def publish(self, channel, payload):
        raise RuntimeError("redis unavailable")


class _CapturingRedisClient:
    def __init__(self):
        self.published_messages = []

    def publish(self, channel, payload):
        self.published_messages.append((channel, payload))
        return 1


class NotificationSSETests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.actor = User.objects.create_user(
            email="actor@example.com",
            username="actor",
            password="Password123!",
            is_active=True,
        )
        self.recipient = User.objects.create_user(
            email="recipient@example.com",
            username="recipient",
            password="Password123!",
            is_active=True,
        )

    def test_sse_requires_authentication(self):
        request = self.factory.get("/notifications/sse/")
        request.user = AnonymousUser()

        response = sse_notifications(request)
        self.assertEqual(response.status_code, 403)

    def test_sse_returns_degraded_stream_when_redis_unavailable(self):
        request = self.factory.get("/notifications/sse/")
        request.user = self.recipient

        with patch("apps.notifications.views._get_redis_client", return_value=None):
            response = sse_notifications(request)
            stream = iter(response.streaming_content)
            first_chunk = next(stream).decode()

        self.assertIn("event: connected", first_chunk)
        self.assertIn('"degraded": true', first_chunk)

    def test_sse_streams_notification_messages(self):
        request = self.factory.get("/notifications/sse/")
        request.user = self.recipient

        fake_pubsub = _FakePubSub(
            [
                {"type": "message", "data": '{"id": 1, "verb_text": "hello"}'},
                RuntimeError("force-break"),
            ]
        )
        fake_client = _FakeRedisClient(fake_pubsub)

        with patch("apps.notifications.views._get_redis_client", return_value=fake_client):
            response = sse_notifications(request)
            stream = iter(response.streaming_content)
            connected_chunk = next(stream).decode()
            notification_chunk = next(stream).decode()

        self.assertIn("event: connected", connected_chunk)
        self.assertIn("event: notification", notification_chunk)
        self.assertIn('"verb_text": "hello"', notification_chunk)

    def test_notification_signal_publish_failure_does_not_crash(self):
        with patch("apps.notifications.signals._get_redis_client", return_value=_FailingRedisClient()):
            notif = Notification.objects.create(
                user=self.recipient,
                actor=self.actor,
                verb_code="friend_request",
                verb_text="actor sent request",
            )
        self.assertIsNotNone(notif.id)

    def test_notification_signal_payload_contains_open_url_and_iso_timestamps(self):
        redis_client = _CapturingRedisClient()

        with patch("apps.notifications.signals._get_redis_client", return_value=redis_client):
            notif = Notification.objects.create(
                user=self.recipient,
                actor=self.actor,
                verb_code="friend_request",
                verb_text="actor sent request",
                link="/accounts/profile/actor/",
            )

        self.assertEqual(len(redis_client.published_messages), 1)
        channel, raw_payload = redis_client.published_messages[0]
        payload = json.loads(raw_payload)

        self.assertEqual(channel, f"notify_user_{self.recipient.id}_notifications")
        self.assertEqual(payload["id"], notif.id)
        self.assertEqual(payload["open_url"], f"/notifications/{notif.id}/open/")
        self.assertEqual(payload["link"], "/accounts/profile/actor/")
        self.assertEqual(payload["event"], "created")

        # Raises ValueError if format is invalid.
        datetime.fromisoformat(payload["created_at"])
        datetime.fromisoformat(payload["updated_at"])

    @override_settings(
        REDIS_HOST="redis-host",
        REDIS_PORT=6380,
        REDIS_DB=2,
        REDIS_SOCKET_TIMEOUT=0.5,
        REDIS_SOCKET_CONNECT_TIMEOUT=0.6,
    )
    def test_stream_redis_client_uses_runtime_settings(self):
        sentinel_client = object()
        with patch("apps.notifications.views.redis.Redis", return_value=sentinel_client) as redis_class:
            client = get_stream_redis_client()

        self.assertIs(client, sentinel_client)
        redis_class.assert_called_once_with(
            host="redis-host",
            port=6380,
            db=2,
            decode_responses=True,
            socket_timeout=0.5,
            socket_connect_timeout=0.6,
            retry_on_timeout=False,
            health_check_interval=30,
        )

    @override_settings(
        REDIS_HOST="redis-host-2",
        REDIS_PORT=6381,
        REDIS_DB=3,
        REDIS_SOCKET_TIMEOUT=0.7,
        REDIS_SOCKET_CONNECT_TIMEOUT=0.8,
    )
    def test_signal_redis_client_uses_runtime_settings(self):
        sentinel_client = object()
        with patch("apps.notifications.signals.redis.Redis", return_value=sentinel_client) as redis_class:
            client = get_signal_redis_client()

        self.assertIs(client, sentinel_client)
        redis_class.assert_called_once_with(
            host="redis-host-2",
            port=6381,
            db=3,
            decode_responses=True,
            socket_timeout=0.7,
            socket_connect_timeout=0.8,
            retry_on_timeout=False,
            health_check_interval=30,
        )
