from django.contrib.contenttypes.models import ContentType
from apps.notifications.models import Notification
from apps.accounts.models import User


def _build_target_repr(target):
    if target is None:
        return ""
    if hasattr(target, "content"):
        text = str(target.content)
    elif hasattr(target, "title"):
        text = str(target.title)
    elif hasattr(target, "username"):
        text = str(target.username)
    else:
        text = str(target)
    return text[:80] + "..." if len(text) > 80 else text


def _build_verb_text(actor, verb_code, target_repr="", reaction_type=None):
    if verb_code == "react_post":
        return f"{actor.username} reacted to your post ({reaction_type or 'like'}): '{target_repr}'"
    if verb_code == "comment_post":
        return f"{actor.username} commented on your post: '{target_repr}'"
    if verb_code == "share_post":
        return f"{actor.username} shared your post: '{target_repr}'"
    if verb_code == "mention_in_post":
        return f"{actor.username} mentioned you in a post: '{target_repr}'"
    if verb_code == "react_comment":
        return f"{actor.username} reacted to your comment ({reaction_type or 'like'}): '{target_repr}'"
    if verb_code == "reply_comment":
        return f"{actor.username} replied to your comment: '{target_repr}'"
    if verb_code == "mention_in_comment":
        return f"{actor.username} mentioned you in a comment: '{target_repr}'"
    if verb_code == "friend_request":
        return f"{actor.username} sent you a friend request"
    if verb_code == "friend_accept":
        return f"{actor.username} accepted your friend request"
    if verb_code == "follow_user":
        return f"{actor.username} started following you"
    if verb_code == "group_invite":
        return f"{actor.username} invited you to a group"
    if verb_code == "group_join_request":
        return f"{actor.username} requested to join your group"
    if verb_code == "group_request_accept":
        return f"{actor.username} accepted your group join request"
    if verb_code == "post_in_group":
        return f"{actor.username} posted in your group: '{target_repr}'"
    if verb_code == "system_alert":
        return f"System alert: {target_repr}"
    return f"{actor.username} sent a notification"


def create_notification(
    actor: User,
    recipient: User,
    verb_code: str,
    target=None,
    reaction_type: str | None = None,
    verb_text: str = "",
    link: str | None = None,
):
    if actor == recipient and verb_code != "system_alert":
        return None

    target_repr = _build_target_repr(target)

    content_type = None
    object_id = None
    if target is not None:
        content_type = ContentType.objects.get_for_model(target.__class__)
        object_id = target.pk

    final_verb_text = verb_text or _build_verb_text(
        actor=actor,
        verb_code=verb_code,
        target_repr=target_repr,
        reaction_type=reaction_type,
    )

    # Gộp/Update cho reaction để tránh spam (react_post, react_comment)
    if verb_code in ("react_post", "react_comment") and content_type and object_id:
        notif, created = Notification.objects.get_or_create(
            user=recipient,
            actor=actor,
            verb_code=verb_code,
            content_type=content_type,
            object_id=object_id,
            defaults={
                "reaction_type": reaction_type,
                "verb_text": final_verb_text,
                "target_repr": target_repr,
                "link": link,
                "is_seen": False,
                "is_read": False,
            },
        )
        if not created:
            notif.reaction_type = reaction_type
            notif.verb_text = final_verb_text
            notif.target_repr = target_repr
            notif.link = link
            notif.is_seen = False
            notif.is_read = False
            # save() sẽ cập nhật updated_at => notification tự nổi lên đầu
            notif.save(
                update_fields=[
                    "reaction_type",
                    "verb_text",
                    "target_repr",
                    "link",
                    "is_seen",
                    "is_read",
                    "updated_at",
                ]
            )
        return notif

    return Notification.objects.create(
        user=recipient,
        actor=actor,
        verb_code=verb_code,
        reaction_type=reaction_type,
        verb_text=final_verb_text,
        content_type=content_type,
        object_id=object_id,
        target_repr=target_repr,
        link=link,
    )


def mark_notification_as_read(notification: Notification):
    notification.is_read = True
    notification.is_seen = True
    notification.save(update_fields=["is_read", "is_seen", "updated_at"])
    return notification


def mark_all_notifications_as_read(user: User):
    return Notification.objects.filter(user=user, is_read=False).update(is_read=True, is_seen=True)


def mark_notification_as_seen(notification: Notification):
    notification.is_seen = True
    notification.save(update_fields=["is_seen", "updated_at"])
    return notification


def delete_notification(notification: Notification):
    notification.delete()
    return True


def delete_all_notifications(user: User):
    Notification.objects.filter(user=user).delete()
    return True


def get_unread_notification_count(user: User):
    return Notification.objects.filter(user=user, is_read=False).count()