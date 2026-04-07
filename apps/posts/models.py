"""Data models for posts, comments and reactions."""

from __future__ import annotations

import os
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from .constants import POST_ATTACHMENT_TYPE_CHOICES
from .constants import POST_ATTACHMENT_TYPE_FILE
from .constants import REACTION_CHOICES


def _post_attachment_upload_to(instance: "PostAttachment", filename: str) -> str:
    """Build deterministic upload path grouped by post id/date.

    Input: attachment instance and original filename.
    Output: relative media path for FileField.
    """

    extension = os.path.splitext(filename)[1].lower()
    extension = extension[:10] if extension else ""
    return f"posts/{instance.post_id or 'new'}/{uuid.uuid4().hex}{extension}"


class Post(models.Model):
    """Top-level feed post created by a user."""

    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="posts",
    )
    content = models.TextField()
    comments_count = models.PositiveIntegerField(default=0)
    reactions_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["author", "created_at"], name="post_author_created_idx"),
            models.Index(fields=["created_at"], name="post_created_idx"),
        ]

    def __str__(self):
        return f"Post(id={self.id}, author={self.author_id})"


class PostAttachment(models.Model):
    """Attachment uploaded with a post (image/audio/other file)."""

    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="attachments")
    attachment_type = models.CharField(max_length=16, choices=POST_ATTACHMENT_TYPE_CHOICES)
    file = models.FileField(upload_to=_post_attachment_upload_to)
    original_name = models.CharField(max_length=255)
    content_type = models.CharField(max_length=128, blank=True)
    size_bytes = models.PositiveBigIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["post", "created_at"], name="post_attach_post_created_idx"),
            models.Index(fields=["post", "attachment_type"], name="post_attach_type_idx"),
        ]

    @property
    def preview_kind(self) -> str:
        """Return client preview hint for current attachment."""

        if self.attachment_type == POST_ATTACHMENT_TYPE_FILE:
            return "download"
        return self.attachment_type

    def __str__(self):
        return f"PostAttachment(post={self.post_id}, type={self.attachment_type}, id={self.id})"


class Comment(models.Model):
    """Comment on post with support for one-level replies."""

    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="comments",
    )
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="replies",
    )
    content = models.TextField()
    reactions_count = models.PositiveIntegerField(default=0)
    is_deleted = models.BooleanField(default=False)
    edited_at = models.DateTimeField(null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["post", "created_at"], name="comment_post_created_idx"),
            models.Index(fields=["post", "parent", "created_at"], name="cmt_post_parent_created_idx"),
            models.Index(fields=["author", "created_at"], name="comment_author_created_idx"),
        ]

    def clean(self):
        if self.parent_id is None:
            return

        if self.parent_id == self.id:
            raise ValidationError("Comment cannot reply to itself")

        if self.parent and self.parent.post_id != self.post_id:
            raise ValidationError("Reply must belong to the same post")

        if self.parent and self.parent.parent_id is not None:
            raise ValidationError("Only one-level replies are supported")

    def save(self, *args, **kwargs):
        """Validate reply constraints before persisting comment."""

        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"Comment(id={self.id}, post={self.post_id}, parent={self.parent_id})"


class PostReaction(models.Model):
    """Single reaction of one user on one post."""

    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="post_reactions")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="post_reactions",
    )
    reaction_type = models.CharField(max_length=16, choices=REACTION_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["post", "user"], name="uniq_post_reaction_user"),
        ]
        indexes = [
            models.Index(fields=["post", "reaction_type"], name="post_reaction_aggregate_idx"),
            models.Index(fields=["post", "created_at"], name="post_reaction_created_idx"),
        ]

    def __str__(self):
        return f"PostReaction(post={self.post_id}, user={self.user_id}, type={self.reaction_type})"


class CommentReaction(models.Model):
    """Single reaction of one user on one comment."""

    comment = models.ForeignKey(Comment, on_delete=models.CASCADE, related_name="comment_reactions")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="comment_reactions",
    )
    reaction_type = models.CharField(max_length=16, choices=REACTION_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["comment", "user"], name="uniq_comment_reaction_user"),
        ]
        indexes = [
            models.Index(fields=["comment", "reaction_type"], name="comment_reaction_aggregate_idx"),
            models.Index(fields=["comment", "created_at"], name="comment_reaction_created_idx"),
        ]

    def __str__(self):
        return (
            f"CommentReaction(comment={self.comment_id}, user={self.user_id}, "
            f"type={self.reaction_type})"
        )
