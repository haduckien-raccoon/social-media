from django.db import models
from django.conf import settings
from django.utils import timezone
from apps.accounts.models import User
from apps.core.models import *
import uuid
import os
from django.core.exceptions import ValidationError

# =====================
# ENUMS / CHOICES
# =====================
class PostPrivacy(models.TextChoices):
    PUBLIC = "public", "Public"
    FRIENDS = "friends", "Friends"
    ONLY_ME = "only_me", "Only Me"

class ReactionType(models.TextChoices):
    LIKE = "like", "Like"
    LOVE = "love", "Love"
    HAHA = "haha", "Haha"
    WOW = "wow", "Wow"
    SAD = "sad", "Sad"
    ANGRY = "angry", "Angry"

class ContentStatus(models.TextChoices):
    NORMAL = "normal", "Normal"
    FLAGGED = "flagged", "Flagged"
    BLOCKED = "blocked", "Blocked"
    DELETED = "deleted", "Deleted"

class ReportTargetType(models.TextChoices):
    POST = "post", "Post"
    COMMENT = "comment", "Comment"

# =====================
# POST MODELS
# =====================
class Post(models.Model):
    author = models.ForeignKey(User, on_delete=models.CASCADE, related_name="posts")
    content = models.TextField(blank=True)
    privacy = models.CharField(max_length=20, choices=PostPrivacy.choices, default=PostPrivacy.PUBLIC)
    status = models.CharField(max_length=20, choices=ContentStatus.choices, default=ContentStatus.NORMAL)

    # Settings
    is_comment_enabled = models.BooleanField(default=True)
    hide_reaction_count = models.BooleanField(default=False)
    hide_comment_count = models.BooleanField(default=False)

    # AI & Moderation
    risk_score = models.FloatField(default=0)
    is_deleted = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    hashtags = models.ManyToManyField("Hashtag", through="PostHashtag", related_name="posts", blank=True)

    def soft_delete(self):
        self.is_deleted = True
        self.status = ContentStatus.DELETED
        self.save(update_fields=["is_deleted", "status"])

    def __str__(self):
        return f"Post {self.id} by {self.author}"

class PostImage(models.Model):
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="images")
    image = models.ImageField(upload_to="posts/images/")
    order = models.PositiveIntegerField(default=0)

class PostFile(models.Model):
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="files")
    file = models.FileField(upload_to="posts/files/")
    filename = models.CharField(max_length=255)

class PostTagUser(models.Model):
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="tagged_users")
    user = models.ForeignKey(User, on_delete=models.CASCADE)

class Hashtag(models.Model):
    tag = models.CharField(max_length=50, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"#{self.tag}"

class PostHashtag(models.Model):
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="post_hashtags")
    hashtag = models.ForeignKey(Hashtag, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("post", "hashtag")

class Location(models.Model):
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="locations")
    name = models.CharField(max_length=255)
    latitude = models.FloatField()
    longitude = models.FloatField()

# =====================
# COMMENT (MAX DEPTH = 7)
# =====================
class Comment(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="comments")
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="comments")
    parent = models.ForeignKey("self", null=True, blank=True, related_name="replies", on_delete=models.CASCADE)
    level = models.PositiveSmallIntegerField(default=1)
    content = models.TextField()

    status = models.CharField(max_length=20, choices=ContentStatus.choices, default=ContentStatus.NORMAL)
    risk_score = models.FloatField(default=0)
    is_deleted = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self):
        if self.parent and self.parent.level >= 7:
            raise ValidationError("Max comment depth is 7")

    def save(self, *args, **kwargs):
        if self.parent:
            self.level = self.parent.level + 1
        super().save(*args, **kwargs)

    def soft_delete(self):
        self.is_deleted = True
        self.status = ContentStatus.DELETED
        self.save(update_fields=["is_deleted", "status"])

class CommentImage(models.Model):
    comment = models.ForeignKey(Comment, on_delete=models.CASCADE, related_name="images")
    image = models.ImageField(upload_to="comments/images/")
    order = models.PositiveIntegerField(default=0)

class CommentFile(models.Model):
    comment = models.ForeignKey(Comment, on_delete=models.CASCADE, related_name="files")
    file = models.FileField(upload_to="comments/files/")
    filename = models.CharField(max_length=255)

# =====================
# REACTION (POST + COMMENT)
# =====================
class PostReaction(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="reactions")
    reaction_type = models.CharField(max_length=20, choices=ReactionType.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("user", "post")

class CommentReaction(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    comment = models.ForeignKey(Comment, on_delete=models.CASCADE, related_name="reactions")
    reaction_type = models.CharField(max_length=20, choices=ReactionType.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("user", "comment")

# =====================
# REPORT
# =====================
class ReportReason(models.Model):
    name = models.CharField(max_length=255)
    is_system = models.BooleanField(default=True)

class Report(models.Model):
    reporter = models.ForeignKey(User, on_delete=models.CASCADE)
    target_type = models.CharField(max_length=10, choices=ReportTargetType.choices)
    target_id = models.PositiveIntegerField()
    reason = models.ForeignKey(ReportReason, on_delete=models.SET_NULL, null=True, blank=True)
    custom_reason = models.TextField(blank=True)
    handled_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="handled_reports")
    status = models.CharField(max_length=20, default="pending")
    created_at = models.DateTimeField(auto_now_add=True)
    handled_at = models.DateTimeField(null=True, blank=True)

# =====================
# SHARE POST
# =====================
class PostShare(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    original_post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="shares")
    new_post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="shared_post")
    created_at = models.DateTimeField(auto_now_add=True)
    caption = models.TextField(blank=True)
    privacy = models.CharField(max_length=20, choices=PostPrivacy.choices, default=PostPrivacy.PUBLIC)

class Mention(models.Model):
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="mentions")
    mentioned_user = models.ForeignKey(User, on_delete=models.CASCADE)
    comment = models.ForeignKey(Comment, on_delete=models.CASCADE, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
