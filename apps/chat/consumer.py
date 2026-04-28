import base64
import binascii
import json
import logging
from typing import cast

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.accounts.models import User
from apps.chat.models import Conversation, ConversationParticipant, Message
from apps.chat.service import (
	create_message,
	get_unread_count,
	mark_conversation_read,
	serialize_message,
	toggle_message_reaction,
)


logger = logging.getLogger(__name__)


class ChatConsumer(AsyncWebsocketConsumer):
	async def connect(self):
		scope_user = self.scope.get("user")
		if not scope_user or not getattr(scope_user, "is_authenticated", False):
			await self.close(code=4401)
			return
		self.user = cast(User, scope_user)

		url_route = self.scope.get("url_route") or {}
		url_kwargs = url_route.get("kwargs", {}) if isinstance(url_route, dict) else {}
		conversation_id_raw = url_kwargs.get("conversation_id")
		if conversation_id_raw is None:
			await self.close(code=4400)
			return

		conversation_id_value = str(conversation_id_raw)
		if not conversation_id_value.isdigit():
			await self.close(code=4400)
			return

		self.conversation_id = int(conversation_id_value)

		if not await self._is_conversation_member():
			await self.close(code=4403)
			return

		self.group_name = f"chat_conversation_{self.conversation_id}"
		await self.channel_layer.group_add(self.group_name, self.channel_name)
		await self.accept()

	async def disconnect(self, close_code):
		group_name = getattr(self, "group_name", None)
		if group_name:
			await self.channel_layer.group_discard(group_name, self.channel_name)

	async def receive(self, text_data=None, bytes_data=None):
		if not text_data:
			await self._send_error("Text payload is required.")
			return

		try:
			payload = json.loads(text_data)
		except json.JSONDecodeError:
			await self._send_error("Invalid JSON payload.")
			return

		action = payload.get("action")
		try:
			if action == "send_message":
				await self._handle_send_message(payload)
			elif action == "mark_read":
				await self._handle_mark_read()
			elif action == "toggle_reaction":
				await self._handle_toggle_reaction(payload)
			else:
				await self._send_error("Unsupported action.")
		except (ValidationError, PermissionDenied) as exc:
			await self._send_error(str(exc))
		except Exception:
			logger.exception("Unexpected websocket error in chat consumer")
			await self._send_error("Internal server error.")

	async def _handle_send_message(self, payload):
		content = payload.get("content", "")
		attachments = self._decode_ws_attachments(payload.get("attachments") or [])
		message = await self._create_message(content, attachments)
		await self.channel_layer.group_send(
			self.group_name,
			{
				"type": "chat_event",
				"data": {
					"event": "message_new",
					"conversation_id": self.conversation_id,
					"message": serialize_message(message),
				},
			},
		)

	async def _handle_mark_read(self):
		payload = await self._mark_read()
		await self.channel_layer.group_send(
			self.group_name,
			{
				"type": "chat_event",
				"data": payload,
			},
		)

	async def _handle_toggle_reaction(self, payload):
		result = await self._toggle_message_reaction(payload.get("message_id"), payload.get("reaction"))
		await self.channel_layer.group_send(
			self.group_name,
			{
				"type": "chat_event",
				"data": {
					"event": "message_reaction",
					**result,
				},
			},
		)

	def _decode_ws_attachments(self, raw_attachments):
		uploaded_files = []
		for attachment in raw_attachments:
			if not isinstance(attachment, dict):
				raise ValidationError("Invalid attachment payload.")

			encoded_content = attachment.get("content_base64")
			if not encoded_content:
				raise ValidationError("Attachment payload is missing content_base64.")

			try:
				binary_content = base64.b64decode(encoded_content, validate=True)
			except (binascii.Error, ValueError):
				raise ValidationError("Attachment content is not valid base64.")

			file_name = attachment.get("name") or "attachment.bin"
			content_type = attachment.get("content_type") or "application/octet-stream"
			uploaded_files.append(
				SimpleUploadedFile(file_name, binary_content, content_type=content_type)
			)

		return uploaded_files

	async def chat_event(self, event):
		await self.send(text_data=json.dumps(event["data"]))

	async def _send_error(self, message):
		await self.send(text_data=json.dumps({"event": "error", "detail": message}))

	@database_sync_to_async
	def _is_conversation_member(self):
		return ConversationParticipant.objects.filter(
			conversation_id=self.conversation_id,
			user_id=self.user.pk,
		).exists()

	@database_sync_to_async
	def _create_message(self, content, attachments):
		conversation = Conversation.objects.filter(id=self.conversation_id).first()
		if not conversation:
			raise ValidationError("Conversation does not exist.")
		return create_message(
			self.user,
			conversation,
			content=content,
			attachments=attachments,
			broadcast=False,
		)

	@database_sync_to_async
	def _mark_read(self):
		conversation = Conversation.objects.filter(id=self.conversation_id).first()
		if not conversation:
			raise ValidationError("Conversation does not exist.")
		participant = mark_conversation_read(self.user, conversation, broadcast=False)
		return {
			"event": "conversation_read",
			"conversation_id": conversation.id,
			"reader_id": self.user.id,
			"last_read_at": participant.last_read_at.isoformat() if participant.last_read_at else None,
			"unread_count": get_unread_count(conversation, self.user),
		}

	@database_sync_to_async
	def _toggle_message_reaction(self, message_id, reaction_type):
		try:
			message_id_int = int(message_id)
		except (TypeError, ValueError):
			raise ValidationError("message_id must be an integer.")

		message = Message.objects.select_related("conversation").filter(id=message_id_int).first()
		if not message:
			raise ValidationError("Message does not exist.")

		if message.conversation.pk != self.conversation_id:
			raise ValidationError("Message does not belong to this conversation.")

		return toggle_message_reaction(self.user, message, reaction_type, broadcast=False)
