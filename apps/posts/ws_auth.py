"""ASGI middleware to authenticate websocket using JWT cookie/query token."""

from __future__ import annotations

from urllib.parse import parse_qs

import jwt
from channels.db import database_sync_to_async
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser

User = get_user_model()


def _parse_cookies(cookie_header: str) -> dict:
    cookies = {}
    for token in cookie_header.split(";"):
        token = token.strip()
        if not token or "=" not in token:
            continue
        key, value = token.split("=", 1)
        cookies[key.strip()] = value.strip()
    return cookies


def _extract_token_from_scope(scope) -> str | None:
    headers = dict(scope.get("headers", []))
    cookie_header = headers.get(b"cookie", b"").decode("utf-8", errors="ignore")
    cookies = _parse_cookies(cookie_header)
    access_token = cookies.get("access")
    if access_token:
        return access_token

    query_string = scope.get("query_string", b"").decode("utf-8", errors="ignore")
    if query_string:
        query_params = parse_qs(query_string)
        access_values = query_params.get("access") or query_params.get("token")
        if access_values:
            return access_values[0]

    return None


@database_sync_to_async
def _get_user_from_token(token: str):
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
    except jwt.InvalidTokenError:
        return AnonymousUser()

    user_id = payload.get("user_id")
    if not user_id:
        return AnonymousUser()

    try:
        return User.objects.get(id=user_id, is_active=True)
    except User.DoesNotExist:
        return AnonymousUser()


class JwtCookieAuthMiddleware:
    """Attach authenticated user to websocket scope from access JWT token."""

    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        token = _extract_token_from_scope(scope)
        if token:
            scope["user"] = await _get_user_from_token(token)
        else:
            scope["user"] = AnonymousUser()

        return await self.inner(scope, receive, send)
