"""Custom authentication classes shared by API and realtime modules."""

from __future__ import annotations

import jwt
from django.conf import settings
from django.contrib.auth import get_user_model
from rest_framework import authentication
from rest_framework import exceptions

User = get_user_model()


class CookieJWTAuthentication(authentication.BaseAuthentication):
    """Authenticate API requests via access token from HTTP cookie.

    Input: DRF request object.
    Output: (user, None) when token is valid, otherwise None.
    Raises: AuthenticationFailed for malformed/expired tokens.
    """

    def authenticate(self, request):
        token = request.COOKIES.get("access")
        if not token:
            return None

        try:
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
        except jwt.ExpiredSignatureError as exc:
            raise exceptions.AuthenticationFailed("Access token expired") from exc
        except jwt.InvalidTokenError as exc:
            raise exceptions.AuthenticationFailed("Invalid access token") from exc

        user_id = payload.get("user_id")
        if not user_id:
            raise exceptions.AuthenticationFailed("Invalid access token payload")

        try:
            user = User.objects.get(id=user_id, is_active=True)
        except User.DoesNotExist as exc:
            raise exceptions.AuthenticationFailed("User not found") from exc

        return user, None
