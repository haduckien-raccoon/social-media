"""Business services for post/comment/reaction/following-feed workflows."""

from __future__ import annotations

import logging
import os
from typing import Iterable

from django.conf import settings
from django.db import transaction
from django.db.models import Count
from django.db.models import F
from django.db.models import Q
from django.utils import timezone

from apps.friends.models import Friendship

from .constants import POST_ATTACHMENT_TYPE_AUDIO
from .constants import POST_ATTACHMENT_TYPE_FILE
from .constants import POST_ATTACHMENT_TYPE_IMAGE
from .constants import REACTION_VALUES
from .exceptions import PostsNotFoundError
from .exceptions import PostsPermissionDeniedError
from .exceptions import PostsValidationError
from .models import Comment
from .models import CommentReaction
from .models import Post
from .models import PostAttachment
from .models import PostReaction
from .realtime import publish_feed_event
from .realtime import publish_post_event
from .serializers import CommentSerializer
from .serializers import PostSerializer
from .utils import serialize_user_brief

logger = logging.getLogger(__name__)


def _post_queryset():
    """Return optimized base queryset for Post API and realtime payloads."""

    return Post.objects.select_related("author").prefetch_related("attachments")


def _allowed_set(values: Iterable[str]) -> set[str]:
    return {str(value).strip().lower() for value in values if str(value).strip()}


def _resolve_attachment_type(*, content_type: str, extension: str) -> str:
    """Resolve attachment type from MIME/extension.

    Input: detected MIME and extension.
    Output: one of image/audio/file categories.
    """

    image_mimes = _allowed_set(getattr(settings, "POST_ALLOWED_IMAGE_CONTENT_TYPES", []))
    audio_mimes = _allowed_set(getattr(settings, "POST_ALLOWED_AUDIO_CONTENT_TYPES", []))

    image_ext = _allowed_set(getattr(settings, "POST_ALLOWED_IMAGE_EXTENSIONS", []))
    audio_ext = _allowed_set(getattr(settings, "POST_ALLOWED_AUDIO_EXTENSIONS", []))
    file_ext = _allowed_set(getattr(settings, "POST_ALLOWED_FILE_EXTENSIONS", []))

    if content_type in image_mimes or extension in image_ext:
        return POST_ATTACHMENT_TYPE_IMAGE
    if content_type in audio_mimes or extension in audio_ext:
        return POST_ATTACHMENT_TYPE_AUDIO
    if extension in file_ext:
        return POST_ATTACHMENT_TYPE_FILE

    raise PostsValidationError(f"Unsupported attachment type: {extension or content_type}")


def _validate_attachments(attachments) -> list[dict]:
    """Validate uploaded attachments and return normalized metadata.

    Input: iterable of uploaded files.
    Output: list of dict metadata consumed by create service.
    Raises: PostsValidationError for count/type/size violations.
    """

    if not attachments:
        return []

    max_attachments = int(getattr(settings, "POST_MAX_ATTACHMENTS", 4))
    if len(attachments) > max_attachments:
        raise PostsValidationError(f"Maximum {max_attachments} attachments are allowed per post")

    max_size_mb = int(getattr(settings, "POST_ATTACHMENT_MAX_SIZE_MB", 20))
    max_bytes = max_size_mb * 1024 * 1024

    normalized = []
    for upload in attachments:
        original_name = (getattr(upload, "name", "") or "").strip()
        if not original_name:
            raise PostsValidationError("Attachment filename is required")

        size_bytes = int(getattr(upload, "size", 0) or 0)
        if size_bytes <= 0:
            raise PostsValidationError(f"Attachment {original_name} is empty")
        if size_bytes > max_bytes:
            raise PostsValidationError(
                f"Attachment {original_name} exceeds {max_size_mb}MB limit"
            )

        content_type = (getattr(upload, "content_type", "") or "").lower().strip()
        extension = os.path.splitext(original_name)[1].lower().replace(".", "")
        attachment_type = _resolve_attachment_type(content_type=content_type, extension=extension)

        normalized.append(
            {
                "upload": upload,
                "attachment_type": attachment_type,
                "original_name": original_name[:255],
                "content_type": content_type[:128],
                "size_bytes": size_bytes,
            }
        )

    return normalized


def _accepted_friend_ids(user_id: int) -> set[int]:
    """Return accepted friend ids of a user in either direction."""

    rows = Friendship.objects.filter(
        status="accepted",
    ).filter(
        Q(from_user_id=user_id) | Q(to_user_id=user_id)
    ).values_list("from_user_id", "to_user_id")

    friend_ids: set[int] = set()
    for from_user_id, to_user_id in rows:
        friend_ids.add(to_user_id if from_user_id == user_id else from_user_id)

    return friend_ids


def _feed_subscriber_ids_for_author(author_id: int) -> set[int]:
    """Return user ids whose feed should receive new post event.

    Input: author id.
    Output: accepted friends + author id for self-feed.
    """

    viewer_ids = _accepted_friend_ids(author_id)
    viewer_ids.add(author_id)
    return viewer_ids


def _publish_following_room_event(
    *,
    event_name: str,
    post_id: int,
    author_id: int,
    data: dict,
    request_id: str | None = None,
) -> None:
    """Fanout one event to all feed rooms that can view an author's post.

    Input: event name, post id, author id, payload and optional request id.
    Output: none (best-effort publish to feed websocket groups).
    """

    viewer_ids = _feed_subscriber_ids_for_author(author_id)
    for viewer_id in viewer_ids:
        publish_feed_event(
            event_name=event_name,
            user_id=viewer_id,
            post_id=post_id,
            data=data,
            request_id=request_id,
        )


def list_posts_query():
    """Fetch newest posts with related author and attachments.

    Input: none.
    Output: queryset of Post objects.
    """

    return _post_queryset().all()


def list_following_feed_query(*, viewer):
    """Fetch feed posts authored by accepted friends + self.

    Input: authenticated viewer user.
    Output: queryset ordered by newest first.
    """

    visible_author_ids = _accepted_friend_ids(viewer.id)
    visible_author_ids.add(viewer.id)

    return _post_queryset().filter(author_id__in=visible_author_ids)


def get_post(post_id: int) -> Post:
    """Fetch a post by id.

    Input: post id.
    Output: Post instance.
    Raises: PostsNotFoundError when post does not exist.
    """

    try:
        return _post_queryset().get(id=post_id)
    except Post.DoesNotExist as exc:
        raise PostsNotFoundError("Post not found") from exc


def create_post(
    *,
    author,
    content: str,
    attachments=None,
    request_id: str | None = None,
) -> Post:
    """Create post with optional attachments and broadcast realtime events.

    Input: author user, text content, optional uploaded files.
    Output: created Post with author and attachments loaded.
    Raises: PostsValidationError for invalid content or attachment.
    """

    normalized_content = (content or "").strip()
    normalized_attachments = _validate_attachments(list(attachments or []))

    if not normalized_content and not normalized_attachments:
        raise PostsValidationError("Post must include content or at least one attachment")

    with transaction.atomic():
        post = Post.objects.create(author=author, content=normalized_content)

        for item in normalized_attachments:
            PostAttachment.objects.create(
                post=post,
                attachment_type=item["attachment_type"],
                file=item["upload"],
                original_name=item["original_name"],
                content_type=item["content_type"],
                size_bytes=item["size_bytes"],
            )

        post = _post_queryset().get(id=post.id)
        post_payload = PostSerializer(post).data
        feed_viewer_ids = _feed_subscriber_ids_for_author(author.id)

        def _emit_post_events() -> None:
            publish_post_event(
                "post.created",
                post.id,
                {
                    "post": post_payload,
                    "actor": serialize_user_brief(author),
                },
                request_id=request_id,
            )

            for viewer_id in feed_viewer_ids:
                publish_feed_event(
                    event_name="post.created.following",
                    user_id=viewer_id,
                    post_id=post.id,
                    data={
                        "post": post_payload,
                        "actor": serialize_user_brief(author),
                        "viewer_id": viewer_id,
                    },
                    request_id=request_id,
                )

        transaction.on_commit(_emit_post_events)

    return post


def list_post_comments(post_id: int):
    """Get comment queryset for a post.

    Input: post id.
    Output: queryset of Comment ordered by created_at.
    Raises: PostsNotFoundError when post does not exist.
    """

    post_exists = Post.objects.filter(id=post_id).exists()
    if not post_exists:
        raise PostsNotFoundError("Post not found")

    return (
        Comment.objects.select_related("author", "parent")
        .filter(post_id=post_id)
        .order_by("created_at")
    )


def create_comment(
    *,
    actor,
    post_id: int,
    content: str,
    parent_id: int | None = None,
    request_id: str | None = None,
) -> Comment:
    """Create comment/reply, update counter, and emit comment.created event.

    Input: actor user, post id, content, optional parent id.
    Output: created Comment instance with author relation.
    Raises: PostsNotFoundError or PostsValidationError for invalid hierarchy.
    """

    normalized_content = (content or "").strip()
    if not normalized_content:
        raise PostsValidationError("Comment content cannot be empty")

    with transaction.atomic():
        try:
            post = Post.objects.select_for_update().get(id=post_id)
        except Post.DoesNotExist as exc:
            raise PostsNotFoundError("Post not found") from exc

        parent = None
        if parent_id is not None:
            try:
                parent = Comment.objects.select_related("post", "parent").get(id=parent_id, post_id=post.id)
            except Comment.DoesNotExist as exc:
                raise PostsValidationError("Parent comment not found") from exc

            if parent.parent_id is not None:
                raise PostsValidationError("Only one-level replies are supported")

            if parent.is_deleted:
                raise PostsValidationError("Cannot reply to a deleted comment")

        comment = Comment.objects.create(
            post=post,
            author=actor,
            parent=parent,
            content=normalized_content,
        )

        Post.objects.filter(id=post.id).update(comments_count=F("comments_count") + 1)
        post.refresh_from_db(fields=["comments_count"])

        comment_with_author = Comment.objects.select_related("author").get(id=comment.id)
        comment_payload = CommentSerializer(comment_with_author).data

        event_payload = {
            "comment": comment_payload,
            "comments_count": post.comments_count,
            "actor": serialize_user_brief(actor),
        }

        def _emit_comment_created() -> None:
            publish_post_event(
                "comment.created",
                post.id,
                event_payload,
                request_id=request_id,
            )
            _publish_following_room_event(
                event_name="comment.created.following",
                post_id=post.id,
                author_id=post.author_id,
                data=event_payload,
                request_id=request_id,
            )

        transaction.on_commit(_emit_comment_created)

    return comment_with_author


def update_comment(
    *,
    actor,
    comment_id: int,
    content: str,
    request_id: str | None = None,
) -> Comment:
    """Update own comment within edit window and broadcast comment.updated.

    Input: actor user, comment id, new content.
    Output: updated Comment instance.
    Raises: PostsNotFoundError/PostsPermissionDeniedError/PostsValidationError.
    """

    normalized_content = (content or "").strip()
    if not normalized_content:
        raise PostsValidationError("Comment content cannot be empty")

    with transaction.atomic():
        try:
            comment = Comment.objects.select_related("author", "post").select_for_update().get(id=comment_id)
        except Comment.DoesNotExist as exc:
            raise PostsNotFoundError("Comment not found") from exc

        if comment.author_id != actor.id:
            raise PostsPermissionDeniedError("You can only edit your own comment")

        if comment.is_deleted:
            raise PostsValidationError("Deleted comment cannot be edited")

        edit_window = timezone.timedelta(minutes=getattr(settings, "COMMENT_EDIT_WINDOW_MINUTES", 15))
        if timezone.now() - comment.created_at > edit_window:
            raise PostsValidationError("Comment edit window has expired")

        comment.content = normalized_content
        comment.edited_at = timezone.now()
        comment.save(update_fields=["content", "edited_at", "updated_at"])

        comment_payload = CommentSerializer(comment).data
        event_payload = {
            "comment": comment_payload,
            "actor": serialize_user_brief(actor),
        }

        def _emit_comment_updated() -> None:
            publish_post_event(
                "comment.updated",
                comment.post_id,
                event_payload,
                request_id=request_id,
            )
            _publish_following_room_event(
                event_name="comment.updated.following",
                post_id=comment.post_id,
                author_id=comment.post.author_id,
                data=event_payload,
                request_id=request_id,
            )

        transaction.on_commit(_emit_comment_updated)

    return comment


def soft_delete_comment(*, actor, comment_id: int, request_id: str | None = None) -> Comment:
    """Soft delete own comment, decrement counter, and emit comment.deleted.

    Input: actor user and comment id.
    Output: mutated Comment instance.
    Raises: PostsNotFoundError/PostsPermissionDeniedError.
    """

    with transaction.atomic():
        try:
            comment = Comment.objects.select_related("author", "post").select_for_update().get(id=comment_id)
        except Comment.DoesNotExist as exc:
            raise PostsNotFoundError("Comment not found") from exc

        if comment.author_id != actor.id:
            raise PostsPermissionDeniedError("You can only delete your own comment")

        if comment.is_deleted:
            return comment

        comment.is_deleted = True
        comment.deleted_at = timezone.now()
        comment.content = "[deleted]"
        comment.save(update_fields=["is_deleted", "deleted_at", "content", "updated_at"])

        Post.objects.filter(id=comment.post_id, comments_count__gt=0).update(comments_count=F("comments_count") - 1)
        comment.post.refresh_from_db(fields=["comments_count"])

        event_payload = {
            "comment_id": comment.id,
            "parent_id": comment.parent_id,
            "comments_count": comment.post.comments_count,
            "actor": serialize_user_brief(actor),
        }

        def _emit_comment_deleted() -> None:
            publish_post_event(
                "comment.deleted",
                comment.post_id,
                event_payload,
                request_id=request_id,
            )
            _publish_following_room_event(
                event_name="comment.deleted.following",
                post_id=comment.post_id,
                author_id=comment.post.author_id,
                data=event_payload,
                request_id=request_id,
            )

        transaction.on_commit(_emit_comment_deleted)

    return comment


def _aggregate_reaction_summary(queryset) -> dict:
    summary = {reaction: 0 for reaction in REACTION_VALUES}
    for row in queryset.values("reaction_type").annotate(count=Count("id")):
        summary[row["reaction_type"]] = row["count"]
    return summary


def set_post_reaction(
    *,
    actor,
    post_id: int,
    reaction_type: str,
    request_id: str | None = None,
) -> dict:
    """Upsert/toggle post reaction and broadcast reaction.post.updated.

    Input: actor user, post id, reaction type.
    Output: event payload containing action and summary.
    Raises: PostsNotFoundError/PostsValidationError.
    """

    if reaction_type not in REACTION_VALUES:
        raise PostsValidationError("Invalid reaction type")

    with transaction.atomic():
        try:
            post = Post.objects.select_for_update().get(id=post_id)
        except Post.DoesNotExist as exc:
            raise PostsNotFoundError("Post not found") from exc

        existing = PostReaction.objects.select_for_update().filter(post_id=post.id, user_id=actor.id).first()

        action = "created"
        current_reaction = reaction_type

        if existing is None:
            PostReaction.objects.create(post=post, user=actor, reaction_type=reaction_type)
            Post.objects.filter(id=post.id).update(reactions_count=F("reactions_count") + 1)
        elif existing.reaction_type == reaction_type:
            existing.delete()
            Post.objects.filter(id=post.id, reactions_count__gt=0).update(reactions_count=F("reactions_count") - 1)
            action = "removed"
            current_reaction = None
        else:
            existing.reaction_type = reaction_type
            existing.save(update_fields=["reaction_type", "updated_at"])
            action = "updated"

        post.refresh_from_db(fields=["reactions_count"])
        summary = _aggregate_reaction_summary(PostReaction.objects.filter(post_id=post.id))

        payload = {
            "target": "post",
            "target_id": post.id,
            "action": action,
            "current_reaction": current_reaction,
            "reactions_count": post.reactions_count,
            "summary": summary,
            "actor": serialize_user_brief(actor),
        }

        def _emit_post_reaction_updated() -> None:
            publish_post_event(
                "reaction.post.updated",
                post.id,
                payload,
                request_id=request_id,
            )
            _publish_following_room_event(
                event_name="reaction.post.updated.following",
                post_id=post.id,
                author_id=post.author_id,
                data=payload,
                request_id=request_id,
            )

        transaction.on_commit(_emit_post_reaction_updated)

    return payload


def set_comment_reaction(
    *,
    actor,
    comment_id: int,
    reaction_type: str,
    request_id: str | None = None,
) -> dict:
    """Upsert/toggle comment reaction and broadcast reaction.comment.updated.

    Input: actor user, comment id, reaction type.
    Output: event payload containing action and summary.
    Raises: PostsNotFoundError/PostsValidationError.
    """

    if reaction_type not in REACTION_VALUES:
        raise PostsValidationError("Invalid reaction type")

    with transaction.atomic():
        try:
            comment = Comment.objects.select_related("post").select_for_update().get(id=comment_id)
        except Comment.DoesNotExist as exc:
            raise PostsNotFoundError("Comment not found") from exc

        existing = CommentReaction.objects.select_for_update().filter(comment_id=comment.id, user_id=actor.id).first()

        action = "created"
        current_reaction = reaction_type

        if existing is None:
            CommentReaction.objects.create(comment=comment, user=actor, reaction_type=reaction_type)
            Comment.objects.filter(id=comment.id).update(reactions_count=F("reactions_count") + 1)
        elif existing.reaction_type == reaction_type:
            existing.delete()
            Comment.objects.filter(id=comment.id, reactions_count__gt=0).update(reactions_count=F("reactions_count") - 1)
            action = "removed"
            current_reaction = None
        else:
            existing.reaction_type = reaction_type
            existing.save(update_fields=["reaction_type", "updated_at"])
            action = "updated"

        comment.refresh_from_db(fields=["reactions_count"])
        summary = _aggregate_reaction_summary(CommentReaction.objects.filter(comment_id=comment.id))

        payload = {
            "target": "comment",
            "target_id": comment.id,
            "post_id": comment.post_id,
            "action": action,
            "current_reaction": current_reaction,
            "reactions_count": comment.reactions_count,
            "summary": summary,
            "actor": serialize_user_brief(actor),
        }

        def _emit_comment_reaction_updated() -> None:
            publish_post_event(
                "reaction.comment.updated",
                comment.post_id,
                payload,
                request_id=request_id,
            )
            _publish_following_room_event(
                event_name="reaction.comment.updated.following",
                post_id=comment.post_id,
                author_id=comment.post.author_id,
                data=payload,
                request_id=request_id,
            )

        transaction.on_commit(_emit_comment_reaction_updated)

    return payload
