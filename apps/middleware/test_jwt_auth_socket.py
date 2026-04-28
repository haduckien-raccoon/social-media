from datetime import timedelta

from asgiref.sync import async_to_sync
from django.test import TransactionTestCase
from django.utils import timezone

from apps.accounts.models import RefreshToken, User
from apps.middleware.jwt_auth import _get_user_from_tokens
from apps.middleware.utils import generate_access_token


class JWTAuthSocketTests(TransactionTestCase):
	def setUp(self):
		self.user = User.objects.create_user(
			email="socket_auth@example.com",
			username="socket_auth_user",
			password="Password123!",
			is_active=True,
			is_verified=True,
		)

	def test_socket_auth_accepts_access_token_from_query_param_flow(self):
		access_token = generate_access_token(self.user)

		resolved_user = async_to_sync(_get_user_from_tokens)(access_token, None)

		self.assertEqual(resolved_user.id, self.user.id)
		self.assertTrue(resolved_user.is_authenticated)

	def test_socket_auth_falls_back_to_valid_refresh_cookie(self):
		refresh_token = RefreshToken.objects.create(
			user=self.user,
			token="socket-refresh-token",
			is_revoked=False,
			expires_at=timezone.now() + timedelta(days=7),
		)

		resolved_user = async_to_sync(_get_user_from_tokens)(None, refresh_token.token)

		self.assertEqual(resolved_user.id, self.user.id)
		self.assertTrue(resolved_user.is_authenticated)

	def test_socket_auth_returns_anonymous_for_revoked_refresh(self):
		refresh_token = RefreshToken.objects.create(
			user=self.user,
			token="revoked-socket-refresh-token",
			is_revoked=True,
			expires_at=timezone.now() + timedelta(days=7),
		)

		resolved_user = async_to_sync(_get_user_from_tokens)(None, refresh_token.token)

		self.assertFalse(resolved_user.is_authenticated)
