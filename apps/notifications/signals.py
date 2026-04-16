import json
import redis
from django.db.models.signals import post_save
from django.dispatch import receiver
from apps.notifications.models import Notification

redis_client = redis.Redis(host="localhost", port=6379, db=0, decode_responses=True)


@receiver(post_save, sender=Notification)
def notify_handler(sender, instance: Notification, created, **kwargs):
    # push cả create + update (đổi reaction, mark read...)
    event = "created" if created else "updated"
    channel = f"notify_user_{instance.user.id}_notifications"

    payload = {
        "event": event,
        "id": instance.pk,
        "actor": instance.actor.username if instance.actor else None,
        "verb_code": instance.verb_code,
        "verb_text": instance.verb_text,
        "reaction_type": instance.reaction_type,
        "target_repr": instance.target_repr,
        "link": instance.link,
        "is_seen": instance.is_seen,
        "is_read": instance.is_read,
        "created_at": instance.created_at.strftime("%Y-%m-%d %H:%M:%S"),
        "updated_at": instance.updated_at.strftime("%Y-%m-%d %H:%M:%S"),
    }

    redis_client.publish(channel, json.dumps(payload))