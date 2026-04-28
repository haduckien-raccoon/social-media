from __future__ import annotations

from typing import Iterable

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Count
from django.utils import timezone

from apps.accounts.models import User
from apps.chat.models import (
	Conversation,
	ConversationParticipant,
	Message,
	MessageAttachment,
	MessageReaction,
	MessageType,
	ReactionType,
)


MAX_ATTACHMENT_SIZE_BYTES = 20 * 1024 * 1024


def send_ws_message(group_name, message_type, data):
	"""Broadcast payload to a websocket group."""
	channel_layer = get_channel_layer()
	if channel_layer:
		async_to_sync(channel_layer.group_send)(
			group_name,
			{
				"type": message_type,
				"data": data,
			},
		)


def conversation_group_name(conversation_id: int) -> str:
	return f"chat_conversation_{conversation_id}"


def ensure_conversation_member(user: User, conversation: Conversation) -> ConversationParticipant:
	participant = ConversationParticipant.objects.filter(
		conversation=conversation,
		user=user,
	).first()
	if not participant:
		raise PermissionDenied("You are not a participant of this conversation.")
	return participant


def _safe_file_url(file_field) -> str:
	try:
		return file_field.url
	except Exception:
		return ""


def _get_avatar_url(user: User) -> str:
	if hasattr(user, "profile") and getattr(user.profile, "avatar", None):
		try:
			return user.profile.avatar.url
		except Exception:
			pass
	return f"https://ui-avatars.com/api/?name={user.username}"


def _get_full_name(user: User) -> str:
	if hasattr(user, "profile"):
		full_name = (getattr(user.profile, "full_name", "") or "").strip()
		if full_name:
			return full_name
	return user.username


def _validate_attachments(attachments: Iterable) -> list:
	attachment_list = list(attachments or [])
	for attachment in attachment_list:
		file_size = getattr(attachment, "size", None)
		if file_size is None:
			raise ValidationError("Attachment is missing file size.")
		if file_size >= MAX_ATTACHMENT_SIZE_BYTES:
			raise ValidationError("Each attachment must be under 20MB.")
	return attachment_list


def _infer_message_type(attachments: list) -> str:
	if not attachments:
		return MessageType.TEXT

	if all(
		(getattr(attachment, "content_type", "") or "").startswith("image/")
		for attachment in attachments
	):
		return MessageType.IMAGE
	return MessageType.FILE


def _reaction_summary_for_message(message: Message) -> dict:
	summary_rows = (
		MessageReaction.objects.filter(message=message)
		.values("reaction_type")
		.annotate(total=Count("id"))
	)
	return {row["reaction_type"]: row["total"] for row in summary_rows}


def _serialize_attachment(attachment: MessageAttachment) -> dict:
	filename = attachment.filename or attachment.file.name.rsplit("/", 1)[-1]
	return {
		"id": attachment.id,
		"url": _safe_file_url(attachment.file),
		"name": filename,
		"content_type": attachment.content_type,
		"size": attachment.file_size,
	}


def serialize_message(message: Message, viewer: User | None = None) -> dict:
	attachments = list(message.attachments.all())
	seen_by_user_ids = list(
		ConversationParticipant.objects.filter(
			conversation=message.conversation,
			last_read_at__isnull=False,
			last_read_at__gte=message.created_at,
		).values_list("user_id", flat=True)
	)

	current_user_reaction = None
	if viewer and getattr(viewer, "is_authenticated", False):
		current_user_reaction = (
			MessageReaction.objects.filter(message=message, user=viewer)
			.values_list("reaction_type", flat=True)
			.first()
		)

	return {
		"id": message.id,
		"conversation_id": message.conversation_id,
		"sender_id": message.sender_id,
		"sender_username": message.sender.username,
		"sender_full_name": _get_full_name(message.sender),
		"sender_avatar": _get_avatar_url(message.sender),
		"content": message.content,
		"message_type": message.message_type,
		"attachments": [_serialize_attachment(attachment) for attachment in attachments],
		"created_at": message.created_at.isoformat(),
		"is_deleted": message.is_deleted,
		"seen_by_user_ids": seen_by_user_ids,
		"reaction_summary": _reaction_summary_for_message(message),
		"current_user_reaction": current_user_reaction,
	}


def find_direct_conversation(user: User, target_user: User) -> Conversation | None:
	if user.pk == target_user.pk:
		raise ValidationError("Cannot create direct conversation with yourself.")

	user_conversation_ids = ConversationParticipant.objects.filter(user=user).values_list("conversation_id", flat=True)
	target_conversation_ids = ConversationParticipant.objects.filter(user=target_user).values_list("conversation_id", flat=True)

	return (
		Conversation.objects.filter(id__in=user_conversation_ids).filter(id__in=target_conversation_ids)
		.annotate(participant_count=Count("participants", distinct=True))
		.filter(participant_count=2)
		.order_by("-updated_at")
		.first()
	)


@transaction.atomic
def get_or_create_direct_conversation(user: User, target_user: User) -> tuple[Conversation, bool]:
	existing_conversation = find_direct_conversation(user, target_user)
	if existing_conversation:
		return existing_conversation, False

	new_conversation = create_conversation(user, [target_user.pk])
	return new_conversation, True


@transaction.atomic
def create_conversation(creator: User, participant_ids: Iterable[int]) -> Conversation:
	normalized_user_ids = {creator.id}
	for raw_user_id in participant_ids:
		try:
			normalized_user_ids.add(int(raw_user_id))
		except (TypeError, ValueError):
			continue

	existing_user_ids = set(User.objects.filter(id__in=normalized_user_ids).values_list("id", flat=True))
	if existing_user_ids != normalized_user_ids:
		raise ValidationError("One or more participants do not exist.")

	conversation = Conversation.objects.create()
	ConversationParticipant.objects.bulk_create(
		[
			ConversationParticipant(conversation=conversation, user_id=user_id)
			for user_id in normalized_user_ids
		]
	)
	return conversation


def get_unread_count(conversation: Conversation, user: User) -> int:
	participant = ensure_conversation_member(user, conversation)
	unread_query = Message.objects.filter(
		conversation=conversation,
		is_deleted=False,
	).exclude(sender=user)

	if participant.last_read_at:
		unread_query = unread_query.filter(created_at__gt=participant.last_read_at)
	return unread_query.count()


def list_conversations_for_user(user: User) -> list[dict]:
	conversations = list(
		Conversation.objects.filter(participants=user)
		.select_related("last_message", "last_message__sender")
		.prefetch_related("participants", "participants__profile")
		.order_by("-updated_at")
	)
	conversation_ids = [conversation.id for conversation in conversations]
	participant_map = {
		row["conversation_id"]: row["last_read_at"]
		for row in ConversationParticipant.objects.filter(
			user=user,
			conversation_id__in=conversation_ids,
		).values("conversation_id", "last_read_at")
	}

	results = []
	for conversation in conversations:
		participants = [
			{
				"id": participant.id,
				"username": participant.username,
				"full_name": _get_full_name(participant),
				"avatar": _get_avatar_url(participant),
			}
			for participant in conversation.participants.exclude(id=user.id)
		]

		last_message = conversation.last_message
		last_message_payload = None
		if last_message and not last_message.is_deleted:
			preview = last_message.content
			if len(preview) > 80:
				preview = f"{preview[:80]}..."

			last_read_at = participant_map.get(conversation.id)
			last_message_payload = {
				"id": last_message.id,
				"sender_id": last_message.sender_id,
				"sender_username": last_message.sender.username,
				"sender_full_name": _get_full_name(last_message.sender),
				"sender_avatar": _get_avatar_url(last_message.sender),
				"preview": preview,
				"message_type": last_message.message_type,
				"created_at": last_message.created_at.isoformat(),
				"is_read_by_me": bool(last_read_at and last_message.created_at <= last_read_at),
			}

		results.append(
			{
				"id": conversation.id,
				"participants": participants,
				"updated_at": conversation.updated_at.isoformat(),
				"created_at": conversation.created_at.isoformat(),
				"unread_count": get_unread_count(conversation, user),
				"last_message": last_message_payload,
			}
		)

	return results


def get_messages_for_conversation(
	user: User,
	conversation: Conversation,
	*,
	limit: int | None = 50,
	before_id: int | None = None,
) -> tuple[list[dict], int]:
	ensure_conversation_member(user, conversation)

	if limit is None:
		safe_limit = None
	else:
		safe_limit = max(1, min(int(limit or 50), 100))

	message_query = (
		Message.objects.filter(conversation=conversation, is_deleted=False)
		.select_related("sender", "conversation")
		.prefetch_related("attachments")
		.order_by("-created_at")
	)
	if before_id:
		message_query = message_query.filter(id__lt=before_id)

	if safe_limit is None:
		messages = list(message_query)
	else:
		messages = list(message_query[:safe_limit])
	messages.reverse()

	payload = [serialize_message(message, viewer=user) for message in messages]
	unread_count = get_unread_count(conversation, user)
	return payload, unread_count


@transaction.atomic
def create_message(
	user: User,
	conversation: Conversation,
	*,
	content: str = "",
	attachments: Iterable = (),
	broadcast: bool = True,
) -> Message:
	ensure_conversation_member(user, conversation)

	normalized_content = (content or "").strip()
	attachment_list = _validate_attachments(attachments)
	if not normalized_content and not attachment_list:
		raise ValidationError("Message must include content or attachments.")

	message = Message.objects.create(
		conversation=conversation,
		sender=user,
		content=normalized_content,
		message_type=_infer_message_type(attachment_list),
	)

	for attachment in attachment_list:
		MessageAttachment.objects.create(
			message=message,
			file=attachment,
			filename=getattr(attachment, "name", "") or "",
			content_type=getattr(attachment, "content_type", "") or "",
			file_size=int(getattr(attachment, "size", 0) or 0),
		)

	conversation.last_message = message
	conversation.updated_at = timezone.now()
	conversation.save(update_fields=["last_message", "updated_at"])

	if broadcast:
		send_ws_message(
			conversation_group_name(conversation.id),
			"chat_event",
			{
				"event": "message_new",
				"conversation_id": conversation.id,
				"message": serialize_message(message),
			},
		)
	return message


@transaction.atomic
def mark_conversation_read(
	user: User,
	conversation: Conversation,
	*,
	read_at=None,
	broadcast: bool = True,
) -> ConversationParticipant:
	participant = ensure_conversation_member(user, conversation)
	read_timestamp = read_at or timezone.now()

	if participant.last_read_at and read_timestamp < participant.last_read_at:
		read_timestamp = participant.last_read_at

	participant.last_read_at = read_timestamp
	participant.save(update_fields=["last_read_at"])

	if broadcast:
		send_ws_message(
			conversation_group_name(conversation.id),
			"chat_event",
			{
				"event": "conversation_read",
				"conversation_id": conversation.id,
				"reader_id": user.id,
				"last_read_at": read_timestamp.isoformat(),
				"unread_count": get_unread_count(conversation, user),
			},
		)
	return participant


@transaction.atomic
def toggle_message_reaction(
	user: User,
	message: Message,
	reaction_type: str,
	*,
	broadcast: bool = True,
) -> dict:
	ensure_conversation_member(user, message.conversation)

	normalized_reaction = (reaction_type or "").strip().lower()
	valid_reactions = {choice[0] for choice in ReactionType.choices}
	if normalized_reaction not in valid_reactions:
		raise ValidationError("Invalid reaction type.")

	existing_reaction = MessageReaction.objects.filter(message=message, user=user).first()
	if existing_reaction and existing_reaction.reaction_type == normalized_reaction:
		existing_reaction.delete()
		status = "removed"
		current_user_reaction = None
	elif existing_reaction:
		existing_reaction.reaction_type = normalized_reaction
		existing_reaction.save(update_fields=["reaction_type"])
		status = "changed"
		current_user_reaction = normalized_reaction
	else:
		MessageReaction.objects.create(
			message=message,
			user=user,
			reaction_type=normalized_reaction,
		)
		status = "added"
		current_user_reaction = normalized_reaction

	reaction_summary = _reaction_summary_for_message(message)
	result = {
		"status": status,
		"conversation_id": message.conversation_id,
		"message_id": message.id,
		"user_id": user.id,
		"reaction_type": current_user_reaction,
		"reaction_summary": reaction_summary,
	}

	if broadcast:
		send_ws_message(
			conversation_group_name(message.conversation_id),
			"chat_event",
			{
				"event": "message_reaction",
				**result,
			},
		)
	return result
