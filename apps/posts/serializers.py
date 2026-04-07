"""Serializers for posts realtime API."""

from __future__ import annotations

from django.contrib.auth import get_user_model
from rest_framework import serializers

from .constants import REACTION_VALUES
from .models import Comment
from .models import Post
from .models import PostAttachment

User = get_user_model()


class UserLiteSerializer(serializers.ModelSerializer):
    """Compact user serializer reused across API responses."""

    class Meta:
        model = User
        fields = ("id", "username")


class PostAttachmentSerializer(serializers.ModelSerializer):
    """Serialize post attachment metadata for list/detail and realtime events."""

    url = serializers.SerializerMethodField()
    name = serializers.CharField(source="original_name", read_only=True)
    preview_kind = serializers.CharField(read_only=True)
    size = serializers.IntegerField(source="size_bytes", read_only=True)
    type = serializers.CharField(source="attachment_type", read_only=True)

    class Meta:
        model = PostAttachment
        fields = (
            "id",
            "type",
            "url",
            "name",
            "size",
            "content_type",
            "preview_kind",
            "created_at",
        )

    def get_url(self, obj):
        request = self.context.get("request")
        if not obj.file:
            return ""
        url = obj.file.url
        if request is None:
            return url
        return request.build_absolute_uri(url)


class PostSerializer(serializers.ModelSerializer):
    """Serialize post payload with author info and counters."""

    author = UserLiteSerializer(read_only=True)
    attachments = PostAttachmentSerializer(many=True, read_only=True)

    class Meta:
        model = Post
        fields = (
            "id",
            "author",
            "content",
            "comments_count",
            "reactions_count",
            "attachments",
            "created_at",
            "updated_at",
        )


class CommentSerializer(serializers.ModelSerializer):
    """Serialize comment payload for list and realtime events."""

    author = UserLiteSerializer(read_only=True)

    class Meta:
        model = Comment
        fields = (
            "id",
            "post",
            "parent",
            "author",
            "content",
            "reactions_count",
            "is_deleted",
            "edited_at",
            "deleted_at",
            "created_at",
            "updated_at",
        )


class CreatePostSerializer(serializers.Serializer):
    """Validate create-post request body."""

    content = serializers.CharField(max_length=5000, required=False, allow_blank=True, default="")


class CreateCommentSerializer(serializers.Serializer):
    """Validate create-comment request body."""

    content = serializers.CharField(max_length=5000)
    parent_id = serializers.IntegerField(required=False, allow_null=True)


class UpdateCommentSerializer(serializers.Serializer):
    """Validate edit-comment request body."""

    content = serializers.CharField(max_length=5000)


class ReactionSerializer(serializers.Serializer):
    """Validate reaction upsert/toggle request body."""

    reaction_type = serializers.ChoiceField(choices=REACTION_VALUES)
