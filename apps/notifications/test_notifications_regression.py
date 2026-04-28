from django.test import RequestFactory, TestCase, override_settings

from apps.accounts.models import User
from apps.notifications.models import Notification
from apps.notifications.views import _normalize_notification_link, open_notification


class NotificationRegressionTests(TestCase):
	def setUp(self):
		self.factory = RequestFactory()
		self.user = User.objects.create_user(
			email="notification_regression@example.com",
			username="notification_regression",
			password="Password123!",
			is_active=True,
		)
		self.actor = User.objects.create_user(
			email="notification_actor_regression@example.com",
			username="notification_actor_regression",
			password="Password123!",
			is_active=True,
		)

	@override_settings(APP_BASE_URL="http://localhost:8080")
	def test_normalize_notification_link_preserves_same_origin_query(self):
		link = _normalize_notification_link("http://localhost:8080/posts/5/?from=notify")

		self.assertEqual(link, "/posts/5/?from=notify")

	def test_normalize_notification_link_rejects_external_absolute_url(self):
		link = _normalize_notification_link("https://example.com/phishing")

		self.assertEqual(link, "/notifications/")

	def test_open_missing_notification_returns_json_404_for_ajax(self):
		request = self.factory.get(
			"/notifications/999/open/",
			HTTP_X_REQUESTED_WITH="XMLHttpRequest",
		)
		request.user = self.user

		response = open_notification(request, 999)

		self.assertEqual(response.status_code, 404)

	def test_open_notification_ajax_returns_sanitized_redirect(self):
		notification = Notification.objects.create(
			user=self.user,
			actor=self.actor,
			verb_code="friend_request",
			verb_text="actor sent request",
			link="https://example.com/phishing",
		)
		request = self.factory.get(
			f"/notifications/{notification.id}/open/",
			HTTP_X_REQUESTED_WITH="XMLHttpRequest",
		)
		request.user = self.user

		response = open_notification(request, notification.id)

		self.assertEqual(response.status_code, 200)
		self.assertJSONEqual(
			response.content,
			{
				"ok": True,
				"id": notification.id,
				"redirect_to": "/notifications/",
			},
		)
