import jwt
from django.conf import settings
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
]


class JWTAuthMiddleware(MiddlewareMixin):
    def process_request(self, request):
        if any(request.path.startswith(path) for path in PUBLIC_PATHS):
            return None

        access = request.COOKIES.get("access")
        refresh = request.COOKIES.get("refresh")

        if not access and not refresh:
            return redirect("/accounts/login/")

        # Keep request flow intact (including POST): refresh token in-place instead of redirecting.
        if refresh and not access:
            return self._refresh_access_token(request, refresh)

        if access and not refresh:
            return self._authenticate_access(request, access)

        return self._authenticate_access(request, access, refresh, require_refresh=True)

    def process_response(self, request, response):
        new_access_token = getattr(request, "_new_access_token", None)
        if not new_access_token:
            return response

        response.set_cookie(
            "access",
            new_access_token,
            httponly=True,
            max_age=15 * 60,
            samesite="Lax",
            secure=getattr(settings, "SESSION_COOKIE_SECURE", False),
        )
        return response

    def _authenticate_access(self, request, access, refresh=None, require_refresh=True):
        try:
            payload = jwt.decode(access, settings.SECRET_KEY, algorithms=["HS256"])
            user_id = payload.get("user_id")
            user = User.objects.get(id=user_id)

            if require_refresh:
                if not refresh:
                    return redirect("/accounts/login/")
                if not RefreshToken.objects.filter(
                    user=user,
                    token=refresh,
                    is_revoked=False,
                    expires_at__gt=timezone.now(),
                ).exists():
                    return redirect("/accounts/login/")

            request.user = user
            request._cached_user = user
            return None

        except jwt.ExpiredSignatureError:
            if refresh:
                return self._refresh_access_token(request, refresh)
            return redirect("/accounts/login/")
        except Exception:
            return redirect("/accounts/login/")

    def _refresh_access_token(self, request, refresh):
        try:
            refresh_token = RefreshToken.objects.get(
                token=refresh,
                is_revoked=False,
                expires_at__gt=timezone.now(),
            )

            user = refresh_token.user
            request.user = user
            request._cached_user = user
            request._new_access_token = generate_access_token(user)
            return None

        except RefreshToken.DoesNotExist:
            return redirect("/accounts/login/")
        except Exception:
            return redirect("/accounts/login/")
