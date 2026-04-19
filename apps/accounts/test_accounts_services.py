from django.test import SimpleTestCase, TestCase, override_settings

from apps.accounts.models import User, UserProfile
from apps.accounts.services import build_absolute_url, login_user, register_user


class AccountServiceUrlTests(SimpleTestCase):
    @override_settings(APP_BASE_URL="http://example.test:9000/")
    def test_build_absolute_url_uses_app_base_url(self):
        result = build_absolute_url("/accounts/verify-email?token=abc")
        self.assertEqual(result, "http://example.test:9000/accounts/verify-email?token=abc")

    @override_settings(APP_BASE_URL="http://example.test:9000")
    def test_build_absolute_url_handles_path_without_leading_slash(self):
        result = build_absolute_url("accounts/reset-password/?token=abc")
        self.assertEqual(result, "http://example.test:9000/accounts/reset-password/?token=abc")


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class AccountPasswordFlowTests(TestCase):
    def test_create_user_auto_creates_profile_via_signal(self):
        user = User.objects.create_user(
            email="signal@example.com",
            username="signal_user",
            password="Secret123!",
            is_active=True,
            is_verified=True,
        )
        self.assertTrue(UserProfile.objects.filter(user=user).exists())

    def test_register_user_hashes_password(self):
        user, error = register_user("user_register", "register@example.com", "Secret123!")

        self.assertIsNone(error)
        self.assertIsNotNone(user)
        user.refresh_from_db()
        self.assertNotEqual(user.password, "Secret123!")
        self.assertTrue(user.check_password("Secret123!"))
        self.assertTrue(UserProfile.objects.filter(user=user).exists())

    def test_login_user_works_with_hashed_password(self):
        user = User.objects.create_user(
            email="login@example.com",
            username="user_login",
            password="Secret123!",
            is_active=True,
            is_verified=True,
        )

        logged_in_user, error = login_user(user.email, "Secret123!")

        self.assertIsNone(error)
        self.assertEqual(logged_in_user.id, user.id)

    def test_login_user_migrates_legacy_plaintext_password(self):
        user = User.objects.create(
            email="legacy@example.com",
            username="legacy_user",
            password="Legacy123!",
            is_active=True,
            is_verified=True,
        )

        logged_in_user, error = login_user(user.email, "Legacy123!")

        self.assertIsNone(error)
        self.assertEqual(logged_in_user.id, user.id)
        user.refresh_from_db()
        self.assertNotEqual(user.password, "Legacy123!")
        self.assertTrue(user.check_password("Legacy123!"))
