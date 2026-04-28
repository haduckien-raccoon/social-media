from django.db import models
from apps.accounts.models import User


class MessageType(models.TextChoices):
    TEXT = "text", "Text"
    IMAGE = "image", "Image"
    FILE = "file", "File"


class ReactionType(models.TextChoices):
    LIKE = "like", "Like"
    LOVE = "love", "Love"
    HAHA = "haha", "Haha"
    WOW = "wow", "Wow"
    SAD = "sad", "Sad"
    ANGRY = "angry", "Angry"


class Conversation(models.Model):
    participants = models.ManyToManyField(
        User,
        through="ConversationParticipant",
        related_name="conversations"
    )

    last_message = models.ForeignKey(
        "Message",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+"
    )

    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)
    def __str__(self):
        return f"Conversation {self.pk}"

class ConversationParticipant(models.Model):
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE)
    user = models.ForeignKey(User, on_delete=models.CASCADE)

    last_read_at = models.DateTimeField(null=True, blank=True)
    is_muted = models.BooleanField(default=False)
    is_archived = models.BooleanField(default=False)

    class Meta:
        unique_together = ("conversation", "user")
    def __str__(self):
        return f"{self.user.username} in Conversation {self.conversation.pk}"
    
class Message(models.Model):
    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name="messages"
    )

    sender = models.ForeignKey(User, on_delete=models.CASCADE)
    content = models.TextField(blank=True)

    message_type = models.CharField(
        max_length=20,
        choices=MessageType.choices,
        default=MessageType.TEXT,
    )

    is_deleted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    def __str__(self):
        return f"Message {self.pk} in Conversation {self.conversation.pk} by {self.sender.username}"

class MessageAttachment(models.Model):
    message = models.ForeignKey(
        Message,
        on_delete=models.CASCADE,
        related_name="attachments"
    )
    file = models.FileField(upload_to="chat/")
    filename = models.CharField(max_length=255, blank=True, default="")
    content_type = models.CharField(max_length=100, blank=True, default="")
    file_size = models.BigIntegerField(default=0)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Attachment {self.pk} for Message {self.message.pk}"


class MessageReaction(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    message = models.ForeignKey(
        Message,
        on_delete=models.CASCADE,
        related_name="reactions",
    )
    reaction_type = models.CharField(max_length=20, choices=ReactionType.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("user", "message")

    def __str__(self):
        return f"{self.user.username} reacted {self.reaction_type} to Message {self.message.pk}"