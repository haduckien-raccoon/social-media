from datetime import timedelta

import jwt
from django.conf import settings
from django.http import HttpResponse
from django.test import RequestFactory, TestCase
from django.utils import timezone

from apps.accounts.models import RefreshToken, User
from apps.middleware.jwt_auth import JWTAuthMiddleware


class JWTAuthMiddlewareTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = User.objects.create_user(
            email="middleware@example.com",
            username="middleware_user",
            password="Password123!",
            is_active=True,
            is_verified=True,
        )
        self.get_response = lambda request: HttpResponse("ok")

    def _build_middleware(self):
        return JWTAuthMiddleware(self.get_response)

    def _create_refresh_token(self, token_value="refresh-token-value"):
        return RefreshToken.objects.create(
            user=self.user,
            token=token_value,
            is_revoked=False,
            expires_at=timezone.now() + timedelta(days=7),
        )

    def test_refresh_without_access_does_not_redirect_and_sets_new_access_cookie(self):
        refresh_token = self._create_refresh_token()
        request = self.factory.post("/posts/create/")
        request.COOKIES["refresh"] = refresh_token.token

        response = self._build_middleware()(request)

        self.assertEqual(response.status_code, 200)
        self.assertIn("access", response.cookies)
        self.assertEqual(request.user.id, self.user.id)

    def test_expired_access_with_valid_refresh_continues_request(self):
        refresh_token = self._create_refresh_token("refresh-token-2")
        expired_access = jwt.encode(
            {
                "user_id": self.user.id,
                "exp": timezone.now() - timedelta(minutes=1),
            },
            settings.SECRET_KEY,
            algorithm="HS256",
        )

        request = self.factory.post("/posts/create/")
        request.COOKIES["access"] = expired_access
        request.COOKIES["refresh"] = refresh_token.token

        response = self._build_middleware()(request)

        self.assertEqual(response.status_code, 200)
        self.assertIn("access", response.cookies)
        self.assertEqual(request.user.id, self.user.id)

    def test_invalid_refresh_redirects_to_login(self):
        request = self.factory.get("/posts/create/")
        request.COOKIES["refresh"] = "missing-token"

        response = self._build_middleware()(request)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/accounts/login/")
