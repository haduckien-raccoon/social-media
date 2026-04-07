from django.contrib import admin

from .models import Comment
from .models import CommentReaction
from .models import Post
from .models import PostAttachment
from .models import PostReaction


@admin.register(Post)
class PostAdmin(admin.ModelAdmin):
    list_display = ("id", "author", "comments_count", "reactions_count", "created_at")
    search_fields = ("author__username", "content")
    list_filter = ("created_at",)


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = ("id", "post", "author", "parent", "is_deleted", "created_at")
    search_fields = ("author__username", "content")
    list_filter = ("is_deleted", "created_at")


@admin.register(PostReaction)
class PostReactionAdmin(admin.ModelAdmin):
    list_display = ("id", "post", "user", "reaction_type", "created_at")
    list_filter = ("reaction_type", "created_at")


@admin.register(CommentReaction)
class CommentReactionAdmin(admin.ModelAdmin):
    list_display = ("id", "comment", "user", "reaction_type", "created_at")
    list_filter = ("reaction_type", "created_at")


@admin.register(PostAttachment)
class PostAttachmentAdmin(admin.ModelAdmin):
    list_display = ("id", "post", "attachment_type", "original_name", "size_bytes", "created_at")
    list_filter = ("attachment_type", "created_at")
    search_fields = ("post__id", "original_name", "content_type")
