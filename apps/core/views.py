"""Core template views for home and realtime demo pages."""

from __future__ import annotations

import jwt
from django.conf import settings
from django.shortcuts import render

from apps.accounts.models import User
from apps.posts.constants import REACTION_VALUES


def _resolve_current_user(request):
    """Resolve current user from request.user first, then JWT cookie fallback."""

    request_user = getattr(request, "user", None)
    if request_user is not None and getattr(request_user, "is_authenticated", False):
        return request_user

    access_token = request.COOKIES.get("access")
    if not access_token:
        return None

    try:
        payload = jwt.decode(
            access_token,
            settings.SECRET_KEY,
            algorithms=["HS256"],
        )
        user_id = payload.get("user_id")
        if not user_id:
            return None
        return User.objects.get(id=user_id)
    except (jwt.InvalidTokenError, User.DoesNotExist):
        return None


def home(request):
    """Render the modernized home landing page."""

    current_user = _resolve_current_user(request)
    return render(
        request,
        "home.html",
        {
            "current_user": current_user,
            "is_authenticated": bool(current_user),
        },
    )


def realtime_demo(request):
    """Render realtime demo UI page for post/comment/reaction/presence."""

    current_user = _resolve_current_user(request)
    return render(
        request,
        "demo/realtime.html",
        {
            "current_user": current_user,
            "is_authenticated": bool(current_user),
            "reaction_values": REACTION_VALUES,
            "api_base": "/api/v1",
            "ws_path": "/ws/realtime/",
        },
    )
