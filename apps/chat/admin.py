from django.contrib import admin

from apps.chat.models import (
	Conversation,
	ConversationParticipant,
	Message,
	MessageAttachment,
	MessageReaction,
)


class ConversationParticipantInline(admin.TabularInline):
	model = ConversationParticipant
	extra = 0


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
	list_display = ("id", "last_message", "updated_at", "created_at")
	inlines = [ConversationParticipantInline]


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
	list_display = ("id", "conversation", "sender", "message_type", "created_at")
	list_filter = ("message_type", "created_at")
	search_fields = ("content", "sender__username", "sender__email")


@admin.register(MessageAttachment)
class MessageAttachmentAdmin(admin.ModelAdmin):
	list_display = ("id", "message", "filename", "content_type", "file_size", "uploaded_at")


@admin.register(MessageReaction)
class MessageReactionAdmin(admin.ModelAdmin):
	list_display = ("id", "message", "user", "reaction_type", "created_at")
	list_filter = ("reaction_type", "created_at")
