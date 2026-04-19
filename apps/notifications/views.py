import json
import logging
import time
import redis
from urllib.parse import urlparse
from django.conf import settings
from django.core.paginator import Paginator
from django.http import (
    StreamingHttpResponse,
    HttpResponseForbidden,
    JsonResponse,
)
from django.views.decorators.http import require_GET, require_POST
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.views.decorators.csrf import csrf_exempt
from apps.notifications.models import Notification

logger = logging.getLogger(__name__)


def _get_redis_client():
    try:
        return redis.Redis(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            db=settings.REDIS_DB,
            decode_responses=True,
            socket_timeout=settings.REDIS_SOCKET_TIMEOUT,
            socket_connect_timeout=settings.REDIS_SOCKET_CONNECT_TIMEOUT,
            retry_on_timeout=False,
            health_check_interval=30,
        )
    except Exception:
        return None


def _parse_int(value, default, min_value=1, max_value=200):
    try:
        parsed_value = int(value)
    except (TypeError, ValueError):
        return default
    if parsed_value < min_value:
        return min_value
    if parsed_value > max_value:
        return max_value
    return parsed_value


def _normalize_notification_link(raw_link):
    if not raw_link:
        return "/notifications/"

    link = str(raw_link).strip()
    if not link:
        return "/notifications/"

    parsed = urlparse(link)

    # Relative path (recommended in this project)
    if not parsed.scheme and not parsed.netloc:
        return link if link.startswith("/") else f"/{link}"

    # Absolute URL is accepted only when it points back to this app.
    if parsed.scheme in {"http", "https"}:
        app_base = urlparse(getattr(settings, "APP_BASE_URL", "http://127.0.0.1:8080"))
        if parsed.netloc == app_base.netloc:
            path = parsed.path or "/"
            if parsed.query:
                path = f"{path}?{parsed.query}"
            return path

    return "/notifications/"


@login_required
@require_GET
def list_notifications(request):
    """
    GET /notifications/?page=1&page_size=20&unread_only=0
    """
    wants_json = request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.GET.get("format") == "json"
    if not wants_json:
        return render(request, "notifications/list.html")

    page = _parse_int(request.GET.get("page", 1), default=1, min_value=1, max_value=100000)
    page_size = _parse_int(request.GET.get("page_size", 20), default=20, min_value=1, max_value=100)
    unread_only = request.GET.get("unread_only", "0") == "1"

    qs = Notification.objects.filter(user=request.user).select_related("actor")
    if unread_only:
        qs = qs.filter(is_read=False)

    paginator = Paginator(qs, page_size)
    page_obj = paginator.get_page(page)

    items = []
    for n in page_obj.object_list:
        items.append(
            {
                "id": n.id,
                "actor": n.actor.username,
                "verb_code": n.verb_code,
                "verb_text": n.verb_text,
                "reaction_type": n.reaction_type,
                "target_repr": n.target_repr,
                "link": n.link,
                "is_seen": n.is_seen,
                "is_read": n.is_read,
                "created_at": n.created_at.isoformat(),
                "updated_at": n.updated_at.isoformat(),
                "open_url": f"/notifications/{n.id}/open/",
            }
        )

    return JsonResponse(
        {
            "count": paginator.count,
            "num_pages": paginator.num_pages,
            "page": page_obj.number,
            "page_size": page_size,
            "results": items,
            "unread_count": Notification.objects.filter(user=request.user, is_read=False).count(),
        }
    )


@csrf_exempt
@login_required
@require_POST
def mark_notification_read(request, notification_id: int):
    """
    POST /notifications/<id>/read/
    """
    try:
        n = Notification.objects.get(id=notification_id, user=request.user)
    except Notification.DoesNotExist:
        return JsonResponse({"detail": "Notification not found"}, status=404)

    n.is_read = True
    n.is_seen = True
    n.save(update_fields=["is_read", "is_seen", "updated_at"])
    return JsonResponse({"ok": True, "id": n.id})


@login_required
@require_POST
def mark_all_notifications_read(request):
    """
    POST /notifications/read-all/
    """
    updated = Notification.objects.filter(user=request.user, is_read=False).update(
        is_read=True,
        is_seen=True,
    )
    return JsonResponse({"ok": True, "updated": updated})


@login_required
@require_POST
def mark_notification_seen(request, notification_id: int):
    """
    POST /notifications/<id>/seen/
    """
    try:
        n = Notification.objects.get(id=notification_id, user=request.user)
    except Notification.DoesNotExist:
        return JsonResponse({"detail": "Notification not found"}, status=404)

    n.is_seen = True
    n.save(update_fields=["is_seen", "updated_at"])
    return JsonResponse({"ok": True, "id": n.id})


@login_required
@require_POST
def delete_notification(request, notification_id: int):
    """
    POST /notifications/<id>/delete/
    """
    deleted, _ = Notification.objects.filter(id=notification_id, user=request.user).delete()
    return JsonResponse({"ok": True, "deleted": deleted > 0})


@login_required
@require_GET
def unread_count(request):
    """
    GET /notifications/unread-count/
    """
    count = Notification.objects.filter(user=request.user, is_read=False).count()
    return JsonResponse({"unread_count": count})


@login_required
@require_GET
def open_notification(request, notification_id: int):
    """
    GET /notifications/<id>/open/
    Mark read+seen then redirect to its resource link.
    """
    notification = Notification.objects.filter(id=notification_id, user=request.user).first()
    if notification is None:
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JsonResponse({"detail": "Notification not found"}, status=404)
        return redirect("/notifications/")

    if not notification.is_read or not notification.is_seen:
        notification.is_read = True
        notification.is_seen = True
        notification.save(update_fields=["is_read", "is_seen", "updated_at"])

    redirect_to = _normalize_notification_link(notification.link)

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse({"ok": True, "id": notification.id, "redirect_to": redirect_to})

    return redirect(redirect_to)


@require_GET
def sse_notifications(request):
    if not request.user.is_authenticated:
        return HttpResponseForbidden("Authentication required")

    channel = f"notify_user_{request.user.id}_notifications"
    redis_client = _get_redis_client()

    def stream():
        if redis_client is None:
            yield b'event: connected\ndata: {"degraded": true}\n\n'
            while True:
                yield b"event: keepalive\ndata: {}\n\n"
                time.sleep(15)
            return

        try:
            pubsub = redis_client.pubsub(ignore_subscribe_messages=True)
            pubsub.subscribe(channel)
            yield b"event: connected\ndata: {}\n\n"
        except Exception as exc:
            logger.warning("SSE Redis subscribe failed for user %s: %s", request.user.id, exc)
            yield b'event: connected\ndata: {"degraded": true}\n\n'
            while True:
                yield b"event: keepalive\ndata: {}\n\n"
                time.sleep(15)
            return

        try:
            while True:
                try:
                    message = pubsub.get_message(timeout=15.0)
                except Exception as exc:
                    logger.warning("SSE Redis read failed for user %s: %s", request.user.id, exc)
                    yield b'event: error\ndata: {"detail":"redis_unavailable"}\n\n'
                    break

                if not message:
                    yield b"event: keepalive\ndata: {}\n\n"
                    continue

                if message["type"] != "message":
                    continue
                yield f"event: notification\ndata: {message['data']}\n\n".encode()
        finally:
            try:
                pubsub.unsubscribe(channel)
                pubsub.close()
            except Exception:
                pass

    response = StreamingHttpResponse(stream(), content_type="text/event-stream")
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response
