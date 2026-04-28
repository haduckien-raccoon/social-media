import jwt
from http.cookies import SimpleCookie
from urllib.parse import parse_qs
from django.conf import settings
from django.shortcuts import redirect
from django.contrib.auth.models import AnonymousUser
from django.utils import timezone
from channels.db import database_sync_to_async
from channels.middleware import BaseMiddleware
from django.utils.deprecation import MiddlewareMixin

from apps.accounts.models import RefreshToken, User
from apps.middleware.utils import decode_access_token, generate_access_token


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


def _get_cookie_from_scope(scope):
    headers = dict(scope.get("headers", []))
    cookie_header = headers.get(b"cookie", b"").decode("utf-8")
    cookie = SimpleCookie()
    cookie.load(cookie_header)
    return cookie


@database_sync_to_async
def _get_user_from_tokens(access_token, refresh_token):
    if access_token:
        payload = decode_access_token(access_token)
        if payload and payload.get("user_id"):
            user = User.objects.filter(id=payload["user_id"]).first()
            if user:
                return user

    if refresh_token:
        refresh = (
            RefreshToken.objects.filter(
                token=refresh_token,
                is_revoked=False,
                expires_at__gt=timezone.now(),
            )
            .select_related("user")
            .first()
        )
        if refresh:
            return refresh.user

    return AnonymousUser()


class JWTAuthMiddlewareStack(BaseMiddleware):
    async def __call__(self, scope, receive, send):
        cookie = _get_cookie_from_scope(scope)
        access = cookie.get("access")
        refresh = cookie.get("refresh")
        query_string = scope.get("query_string", b"").decode("utf-8")
        query_params = parse_qs(query_string)
        token_param = query_params.get("token", [None])[0]

        access_token_value = token_param or (access.value if access else None)
        refresh_token_value = refresh.value if refresh else None

        scope["user"] = await _get_user_from_tokens(
            access_token_value,
            refresh_token_value,
        )
        return await super().__call__(scope, receive, send)


def jwt_auth_middleware_stack(inner):
    return JWTAuthMiddlewareStack(inner)
