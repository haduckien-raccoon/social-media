from django.contrib.auth import get_user_model
from django.test import Client
from django.test import TestCase
from django.urls import reverse

from apps.accounts.services import create_jwt_pair_for_user
from apps.friends.models import Friendship

User = get_user_model()


class UIDemoRouteTests(TestCase):
    """UI route/render regression tests for demo pages."""

    def setUp(self):
        self.user = User.objects.create_user(
            email="ui@example.com",
            username="ui-user",
            password="123456",
            is_active=True,
        )
        self.friend = User.objects.create_user(
            email="friend@example.com",
            username="friend-user",
            password="123456",
            is_active=True,
        )

    def _auth_client(self) -> Client:
        access, refresh = create_jwt_pair_for_user(self.user)
        client = Client()
        client.cookies["access"] = access
        client.cookies["refresh"] = refresh
        return client

    def test_public_auth_pages_render(self):
        urls = [
            reverse("login"),
            reverse("register"),
            reverse("forgot_password"),
        ]

        for url in urls:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200, msg=f"Expected 200 for {url}")

    def test_home_requires_jwt_cookie(self):
        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    def test_home_renders_with_jwt_cookie(self):
        client = self._auth_client()
        response = client.get(reverse("home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Realtime Social Demo")
        self.assertContains(response, "Open Realtime Demo")

    def test_friends_page_renders_with_jwt_cookie(self):
        Friendship.objects.create(from_user=self.friend, to_user=self.user, status="pending")
        client = self._auth_client()
        response = client.get(reverse("friends:list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Pending Requests")
        self.assertContains(response, self.friend.username)

    def test_realtime_demo_requires_auth(self):
        response = self.client.get(reverse("realtime_demo"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    def test_realtime_demo_route_and_context(self):
        client = self._auth_client()
        response = client.get(reverse("realtime_demo"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Realtime Social Feed")
        self.assertContains(response, "/ws/realtime/")
        self.assertEqual(response.context["api_base"], "/api/v1")
        self.assertEqual(response.context["ws_path"], "/ws/realtime/")

    def test_api_posts_available_for_demo_cookie_auth(self):
        client = self._auth_client()
        response = client.get("/api/v1/posts")
        self.assertEqual(response.status_code, 200)
