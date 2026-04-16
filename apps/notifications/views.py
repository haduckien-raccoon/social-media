import json
import redis
from django.core.paginator import Paginator
from django.http import (
    StreamingHttpResponse,
    HttpResponseForbidden,
    JsonResponse,
    HttpResponseBadRequest,
)
from django.views.decorators.http import require_GET, require_POST
from django.contrib.auth.decorators import login_required, permission_required
from django.views.decorators.csrf import csrf_exempt
from apps.accounts.models import User
from apps.notifications.models import Notification

redis_client = redis.Redis(host="localhost", port=6379, db=0, decode_responses=True)


@require_GET
# @login_required
def list_notifications(request):
    """
    GET /notifications/?page=1&page_size=20&unread_only=0
    """
    page = int(request.GET.get("page", 1))
    page_size = int(request.GET.get("page_size", 20))
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
@require_POST
# @login_required
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


@require_POST
# @login_required
def mark_all_notifications_read(request):
    """
    POST /notifications/read-all/
    """
    updated = Notification.objects.filter(user=request.user, is_read=False).update(
        is_read=True,
        is_seen=True,
    )
    return JsonResponse({"ok": True, "updated": updated})


@require_POST
# @login_required
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


@require_POST
# @login_required
def delete_notification(request, notification_id: int):
    """
    POST /notifications/<id>/delete/
    """
    deleted, _ = Notification.objects.filter(id=notification_id, user=request.user).delete()
    return JsonResponse({"ok": True, "deleted": deleted > 0})


@require_GET
# @login_required
def unread_count(request):
    """
    GET /notifications/unread-count/
    """
    count = Notification.objects.filter(user=request.user, is_read=False).count()
    return JsonResponse({"unread_count": count})


@require_GET
def sse_notifications(request):
    if not request.user.is_authenticated:
        return HttpResponseForbidden("Authentication required")

    channel = f"notify_user_{request.user.id}_notifications"

    def stream():
        pubsub = redis_client.pubsub()
        pubsub.subscribe(channel)
        yield b"event: connected\ndata: {}\n\n"

        try:
            for message in pubsub.listen():
                if message["type"] != "message":
                    continue
                yield f"event: notification\ndata: {message['data']}\n\n".encode()
        finally:
            pubsub.unsubscribe(channel)
            pubsub.close()

    response = StreamingHttpResponse(stream(), content_type="text/event-stream")
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response