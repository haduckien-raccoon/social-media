"""JWT middleware for template pages and API endpoints."""

from __future__ import annotations

import jwt
from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import redirect
from django.utils import timezone
from django.utils.deprecation import MiddlewareMixin

from apps.accounts.models import RefreshToken, User
from apps.middleware.utils import generate_access_token


PUBLIC_PATHS = [
    "/accounts/login/",
    "/accounts/register/",
    "/accounts/verify-email/",
    "/accounts/verify-email",
    "/accounts/forgot-password/",
    "/accounts/reset-password/",
    "/accounts/reset-password",
    "/admin",
    "/static/",
    "/media/",
    "/favicon.ico",
]


class JWTAuthMiddleware(MiddlewareMixin):
    """Authenticate requests using access/refresh cookies.

    Input: Django HTTP request.
    Output: None when authentication succeeds, otherwise response.
    """

    def process_request(self, request):
        if self._is_api_request(request):
            return None

        if self._is_public_path(request.path):
            return None

        access = request.COOKIES.get("access")
        refresh = request.COOKIES.get("refresh")

        if not access and not refresh:
            return self._unauthorized_response(request, "Missing authentication cookies")

        if refresh and not access:
            return self._refresh_access_token(request, refresh)

        if access and not refresh:
            return self._unauthorized_response(request, "Invalid token pair")

        return self._authenticate_access(request, access, refresh)

    def _is_public_path(self, path: str) -> bool:
        return any(path.startswith(prefix) for prefix in PUBLIC_PATHS)

    def _is_api_request(self, request) -> bool:
        return request.path.startswith("/api/")

    def _unauthorized_response(self, request, message: str):
        if self._is_api_request(request):
            return JsonResponse({"detail": message}, status=401)
        return redirect("/accounts/login/")

    def _authenticate_access(self, request, access: str, refresh: str):
        try:
            payload = jwt.decode(access, settings.SECRET_KEY, algorithms=["HS256"])
            user_id = payload.get("user_id")
            user = User.objects.get(id=user_id)

            refresh_exists = RefreshToken.objects.filter(
                user=user,
                token=refresh,
                is_revoked=False,
                expires_at__gt=timezone.now(),
            ).exists()
            if not refresh_exists:
                return self._unauthorized_response(request, "Refresh token revoked or expired")

            request.user = user
            return None
        except jwt.ExpiredSignatureError:
            return self._refresh_access_token(request, refresh)
        except Exception:
            return self._unauthorized_response(request, "Invalid access token")

    def _refresh_access_token(self, request, refresh: str):
        try:
            rt = RefreshToken.objects.get(
                token=refresh,
                is_revoked=False,
                expires_at__gt=timezone.now(),
            )

            user = rt.user
            new_access = generate_access_token(user)
            request.user = user

            if self._is_api_request(request):
                response = JsonResponse({"detail": "Access token refreshed"}, status=200)
            else:
                response = redirect(request.path)

            response.set_cookie(
                "access",
                new_access,
                httponly=True,
                max_age=5 * 60,
                samesite="Lax",
            )
            response.set_cookie(
                "email",
                user.email,
                max_age=7 * 24 * 60 * 60,
                samesite="Lax",
            )
            return response
        except RefreshToken.DoesNotExist:
            return self._unauthorized_response(request, "Refresh token not found")
        except Exception:
            return self._unauthorized_response(request, "Failed to refresh token")
