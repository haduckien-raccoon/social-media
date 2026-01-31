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