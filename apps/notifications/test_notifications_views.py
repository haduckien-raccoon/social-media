import json
from unittest.mock import patch

from django.test import RequestFactory, TestCase, override_settings

from apps.accounts.models import User
from apps.notifications.models import Notification
from apps.notifications.views import (
    delete_notification,
    list_notifications,
    mark_all_notifications_read,
    open_notification,
    unread_count,
)


class NotificationViewTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.redis_patcher = patch("apps.notifications.signals._get_redis_client", return_value=None)
        self.redis_patcher.start()
        self.addCleanup(self.redis_patcher.stop)
        self.actor = User.objects.create_user(
            email="actor-noti@example.com",
            username="actor_noti",
            password="Password123!",
            is_active=True,
            is_verified=True,
        )
        self.recipient = User.objects.create_user(
            email="recipient-noti@example.com",
            username="recipient_noti",
            password="Password123!",
            is_active=True,
            is_verified=True,
        )

    def test_list_notifications_returns_html_for_regular_request(self):
        request = self.factory.get("/notifications/")
        request.user = self.recipient

        response = list_notifications(request)

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response["Content-Type"])
        self.assertIn(b"notifications-card", response.content)

    def test_list_notifications_returns_json_for_ajax_request(self):
        Notification.objects.create(
            user=self.recipient,
            actor=self.actor,
            verb_code="friend_request",
            verb_text="actor sent you a friend request",
            link="/accounts/profile/actor_noti/",
        )

        request = self.factory.get(
            "/notifications/?page=1&page_size=20",
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        request.user = self.recipient

        response = list_notifications(request)

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content.decode("utf-8"))
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["unread_count"], 1)
        self.assertEqual(payload["results"][0]["verb_code"], "friend_request")
        self.assertEqual(payload["results"][0]["open_url"], f"/notifications/{payload['results'][0]['id']}/open/")

    def test_open_notification_marks_read_seen_and_redirects_to_relative_link(self):
        notification = Notification.objects.create(
            user=self.recipient,
            actor=self.actor,
            verb_code="comment_post",
            verb_text="actor commented",
            link="/posts/321/",
            is_read=False,
            is_seen=False,
        )

        request = self.factory.get(f"/notifications/{notification.id}/open/")
        request.user = self.recipient

        response = open_notification(request, notification.id)
        notification.refresh_from_db()

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/posts/321/")
        self.assertTrue(notification.is_read)
        self.assertTrue(notification.is_seen)

    def test_open_notification_falls_back_when_external_link(self):
        notification = Notification.objects.create(
            user=self.recipient,
            actor=self.actor,
            verb_code="system_alert",
            verb_text="external link",
            link="https://evil.example/phishing",
        )

        request = self.factory.get(f"/notifications/{notification.id}/open/")
        request.user = self.recipient

        response = open_notification(request, notification.id)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/notifications/")

    @override_settings(APP_BASE_URL="http://localhost:8080")
    def test_open_notification_accepts_absolute_app_url(self):
        notification = Notification.objects.create(
            user=self.recipient,
            actor=self.actor,
            verb_code="system_alert",
            verb_text="absolute app url",
            link="http://localhost:8080/groups/55/?tab=posts",
        )

        request = self.factory.get(f"/notifications/{notification.id}/open/")
        request.user = self.recipient

        response = open_notification(request, notification.id)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/groups/55/?tab=posts")

    def test_list_notifications_sanitizes_invalid_page_and_page_size(self):
        Notification.objects.create(
            user=self.recipient,
            actor=self.actor,
            verb_code="friend_request",
            verb_text="a",
        )
        Notification.objects.create(
            user=self.recipient,
            actor=self.actor,
            verb_code="friend_accept",
            verb_text="b",
        )

        request = self.factory.get(
            "/notifications/?page=-99&page_size=9999",
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        request.user = self.recipient

        response = list_notifications(request)
        payload = json.loads(response.content.decode("utf-8"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["page"], 1)
        self.assertEqual(payload["page_size"], 100)
        self.assertEqual(payload["count"], 2)

    def test_unread_count_reflects_friend_notifications(self):
        Notification.objects.create(
            user=self.recipient,
            actor=self.actor,
            verb_code="friend_request",
            verb_text="request",
            is_read=False,
        )
        Notification.objects.create(
            user=self.recipient,
            actor=self.actor,
            verb_code="friend_accept",
            verb_text="accept",
            is_read=False,
        )

        request = self.factory.get("/notifications/unread-count/")
        request.user = self.recipient
        response = unread_count(request)

        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(response.content, {"unread_count": 2})

    def test_mark_all_notifications_read_publishes_bulk_event(self):
        Notification.objects.create(
            user=self.recipient,
            actor=self.actor,
            verb_code="friend_request",
            verb_text="request",
            is_read=False,
        )
        Notification.objects.create(
            user=self.recipient,
            actor=self.actor,
            verb_code="friend_accept",
            verb_text="accept",
            is_read=False,
        )
        published_payloads = []

        def capture_publish(user_id, payload):
            published_payloads.append((user_id, payload))
            return True

        request = self.factory.post("/notifications/read-all/")
        request.user = self.recipient

        with patch("apps.notifications.views.publish_notification_payload", side_effect=capture_publish):
            response = mark_all_notifications_read(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Notification.objects.filter(user=self.recipient, is_read=False).count(), 0)
        self.assertEqual(published_payloads, [(self.recipient.id, {"event": "bulk_read", "user_id": self.recipient.id, "unread_count": 0})])

    def test_delete_notification_publishes_unread_count_when_unread_item_removed(self):
        notification = Notification.objects.create(
            user=self.recipient,
            actor=self.actor,
            verb_code="friend_request",
            verb_text="request",
            is_read=False,
        )
        published_payloads = []

        def capture_publish(user_id, payload):
            published_payloads.append((user_id, payload))
            return True

        request = self.factory.post(f"/notifications/{notification.id}/delete/")
        request.user = self.recipient

        with patch("apps.notifications.views.publish_notification_payload", side_effect=capture_publish):
            response = delete_notification(request, notification.id)

        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(response.content, {"ok": True, "deleted": True, "unread_count": 0})
        self.assertEqual(published_payloads, [(self.recipient.id, {"event": "unread_count", "user_id": self.recipient.id, "unread_count": 0})])
