import json
import logging
import redis
from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver
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


@receiver(post_save, sender=Notification)
def notify_handler(sender, instance: Notification, created, **kwargs):
    # push cả create + update (đổi reaction, mark read...)
    event = "created" if created else "updated"
    channel = f"notify_user_{instance.user.id}_notifications"
    open_url = f"/notifications/{instance.pk}/open/"

    payload = {
        "event": event,
        "id": instance.pk,
        "actor": instance.actor.username if instance.actor else None,
        "verb_code": instance.verb_code,
        "verb_text": instance.verb_text,
        "reaction_type": instance.reaction_type,
        "target_repr": instance.target_repr,
        "link": instance.link,
        "open_url": open_url,
        "is_seen": instance.is_seen,
        "is_read": instance.is_read,
        "created_at": instance.created_at.isoformat(),
        "updated_at": instance.updated_at.isoformat(),
    }

    redis_client = _get_redis_client()
    if redis_client is None:
        return

    try:
        redis_client.publish(channel, json.dumps(payload))
    except Exception as exc:
        logger.warning("Redis publish failed for notification %s: %s", instance.pk, exc)
