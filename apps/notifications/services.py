from apps.notifications.models import *

def create_notification(actor, recipient, verb_code, target, verb_text=""):
    """
    Docstring for create_notification
    
    :param actor: Description
    :param recipient: Description
    :param verb_code: Description
    :param target: Description
    :param verb_text: Description
    """
    if actor == recipient:
        return None
    
    target_repr = ""
    if hasattr(target, '__str__'):
        target_repr = target.content[:50]+ "..." if len(target.content) > 50 else target.content
    
    if verb_code == "like_post":
        notif, created = Notification.objects.get_or_create(
            user=recipient,
            actor=actor,
            verb_code=verb_code,
            target=target,
            defaults={'verb_text': f"{actor.username} liked your post: '{target_repr}'"}
        )

        if not created:
            notif.created_at = timezone.now()
            notif.is_read = False
            notif.save()
            
    elif verb_code == "comment_post" or verb_code == "reply_comment" or verb_code == "share_post" or verb_code == "mention_user":
        notif = Notification.objects.create(
            user=recipient,
            actor=actor,
            verb_code=verb_code,
            target=target,
            verb_text=f"{actor.username} commented on your post: '{target_repr}'" if verb_code == "comment_post" else f"{actor.username} replied to your comment: '{target_repr}'"
        )
    else:
        notif = Notification.objects.create(
            user=recipient,
            actor=actor,
            verb_code=verb_code,
            target=target,
            verb_text=verb_text
        )
    return notif

def mark_notification_as_read(notification: Notification):
    """
    Docstring for mark_notification_as_read
    
    :param notification: Description
    """
    notification.is_read = True
    notification.save()
    return notification

def mark_all_notifications_as_read(user: User):
    """
    Docstring for mark_all_notifications_as_read
    
    :param user: Description
    """
    notifications = Notification.objects.filter(user=user, is_read=False)
    notifications.update(is_read=True)
    return notifications

def delete_notification(notification: Notification):
    """
    Docstring for delete_notification
    
    :param notification: Description
    """
    notification.delete()
    return True
    
def delete_all_notifications(user: User):
    """
    Docstring for delete_all_notifications
    
    :param user: Description
    """
    notifications = Notification.objects.filter(user=user)
    notifications.delete()
    return True