import logging
import json
import time

import redis
from django.conf import settings
from django.db.models.signals import post_delete, post_save
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


def notification_channel(user_id: int) -> str:
    return f"notify_user_{user_id}_notifications"


def serialize_notification(instance: Notification, event: str) -> dict:
    return {
        "event": event,
        "id": instance.pk,
        "user_id": instance.user_id,
        "actor": instance.actor.username if instance.actor else None,
        "verb_code": instance.verb_code,
        "verb_text": instance.verb_text,
        "reaction_type": instance.reaction_type,
        "target_repr": instance.target_repr,
        "link": instance.link,
        "open_url": f"/notifications/{instance.pk}/open/",
        "is_seen": instance.is_seen,
        "is_read": instance.is_read,
        "published_at_ms": int(time.time() * 1000),
        "created_at": instance.created_at.isoformat(),
        "updated_at": instance.updated_at.isoformat(),
    }


def publish_notification_payload(user_id: int, payload: dict) -> bool:
    redis_client = _get_redis_client()
    if redis_client is None:
        return False

    try:
        redis_client.publish(notification_channel(user_id), json.dumps(payload))
        return True
    except Exception as exc:
        logger.warning("Redis publish failed for notification user %s: %s", user_id, exc)
        return False


def publish_notification_event(instance: Notification, event: str) -> bool:
    return publish_notification_payload(instance.user_id, serialize_notification(instance, event))


@receiver(post_save, sender=Notification)
def notify_handler(sender, instance: Notification, created, **kwargs):
    event = "created" if created else "updated"
    publish_notification_event(instance, event)


@receiver(post_delete, sender=Notification)
def notify_delete_handler(sender, instance: Notification, **kwargs):
    payload = serialize_notification(instance, "deleted")
    publish_notification_payload(instance.user_id, payload)
