from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import User, UserProfile


@receiver(post_save, sender=User)
def ensure_user_profile_exists(sender, instance, **kwargs):
    """
    Keep profile relation stable across the whole app.
    This prevents template/runtime failures when code accesses `user.profile`.
    """
    UserProfile.objects.get_or_create(user=instance)
