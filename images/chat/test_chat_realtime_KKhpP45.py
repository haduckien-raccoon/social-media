import base64
import json
import tempfile
from unittest.mock import AsyncMock, patch

from asgiref.sync import async_to_sync
from django.test import TestCase, override_settings

from apps.accounts.models import User
from apps.chat.consumer import ChatConsumer
from apps.chat.models import Message
from apps.chat.service import (
	create_conversation,
	create_message,
	mark_conversation_read,
	toggle_message_reaction,
)


@override_settings(MEDIA_ROOT=tempfile.gettempdir())
class ChatRealtimeServiceTests(TestCase):
	def setUp(self):
		self.alice = User.objects.create_user(
			email="alice_realtime_chat@example.com",
			username="alice_realtime_chat",
			password="Password123!",
			is_active=True,
		)
		self.bob = User.objects.create_user(
			email="bob_realtime_chat@example.com",
			username="bob_realtime_chat",
			password="Password123!",
			is_active=True,
		)
		self.conversation = create_conversation(self.alice, [self.bob.id])

	@patch("apps.chat.service.send_ws_message")
	def test_create_message_broadcasts_message_new_event(self, mocked_send_ws_message):
		message = create_message(self.alice, self.conversation, content="hello realtime")

		self.assertIsNotNone(message.id)
		self.assertEqual(mocked_send_ws_message.call_count, 1)

		group_name, message_type, payload = mocked_send_ws_message.call_args.args
		self.assertEqual(group_name, f"chat_conversation_{self.conversation.id}")
		self.assertEqual(message_type, "chat_event")
		self.assertEqual(payload["event"], "message_new")
		self.assertEqual(payload["conversation_id"], self.conversation.id)
		self.assertEqual(payload["message"]["id"], message.id)

	@patch("apps.chat.service.send_ws_message")
	def test_mark_read_broadcasts_conversation_read_event(self, mocked_send_ws_message):
		create_message(self.bob, self.conversation, content="unread")
		mocked_send_ws_message.reset_mock()

		participant = mark_conversation_read(self.alice, self.conversation)
		self.assertIsNotNone(participant.last_read_at)
		self.assertEqual(mocked_send_ws_message.call_count, 1)

		group_name, message_type, payload = mocked_send_ws_message.call_args.args
		self.assertEqual(group_name, f"chat_conversation_{self.conversation.id}")
		self.assertEqual(message_type, "chat_event")
		self.assertEqual(payload["event"], "conversation_read")
		self.assertEqual(payload["reader_id"], self.alice.id)
		self.assertEqual(payload["unread_count"], 0)

	@patch("apps.chat.service.send_ws_message")
	def test_toggle_reaction_broadcasts_message_reaction_event(self, mocked_send_ws_message):
		message = create_message(self.alice, self.conversation, content="react me")
		mocked_send_ws_message.reset_mock()

		result = toggle_message_reaction(self.bob, message, "love")

		self.assertEqual(result["status"], "added")
		self.assertEqual(mocked_send_ws_message.call_count, 1)

		group_name, message_type, payload = mocked_send_ws_message.call_args.args
		self.assertEqual(group_name, f"chat_conversation_{self.conversation.id}")
		self.assertEqual(message_type, "chat_event")
		self.assertEqual(payload["event"], "message_reaction")
		self.assertEqual(payload["message_id"], message.id)
		self.assertEqual(payload["reaction_summary"], {"love": 1})


class ChatConsumerContractTests(TestCase):
	def test_chat_consumer_forwards_chat_event_payload(self):
		consumer = ChatConsumer()
		captured = {}

		async def fake_send(text_data=None, bytes_data=None, close=False):
			captured["text_data"] = text_data

		consumer.send = fake_send
		async_to_sync(consumer.chat_event)(
			{
				"data": {
					"event": "message_new",
					"conversation_id": 10,
					"message": {"id": 88},
				}
			}
		)

		payload = json.loads(captured["text_data"])
		self.assertEqual(payload["event"], "message_new")
		self.assertEqual(payload["conversation_id"], 10)
		self.assertEqual(payload["message"]["id"], 88)


@override_settings(MEDIA_ROOT=tempfile.gettempdir())
class ChatConsumerActionTests(TestCase):
	def setUp(self):
		self.alice = User.objects.create_user(
			email="alice_ws_action@example.com",
			username="alice_ws_action",
			password="Password123!",
			is_active=True,
		)
		self.bob = User.objects.create_user(
			email="bob_ws_action@example.com",
			username="bob_ws_action",
			password="Password123!",
			is_active=True,
		)
		self.conversation = create_conversation(self.alice, [self.bob.id])

	def _build_consumer(self):
		consumer = ChatConsumer()
		consumer.user = self.alice
		consumer.conversation_id = self.conversation.id
		return consumer

	def _capture_send(self, consumer):
		captured = {}

		async def fake_send(text_data=None, bytes_data=None, close=False):
			captured["text_data"] = text_data

		consumer.send = fake_send
		return captured

	def test_receive_rejects_invalid_json(self):
		consumer = self._build_consumer()
		captured = self._capture_send(consumer)

		async_to_sync(consumer.receive)(text_data="{invalid-json")
		payload = json.loads(captured["text_data"])

		self.assertEqual(payload["event"], "error")
		self.assertIn("Invalid JSON payload", payload["detail"])

	def test_receive_rejects_unsupported_action(self):
		consumer = self._build_consumer()
		captured = self._capture_send(consumer)

		async_to_sync(consumer.receive)(text_data=json.dumps({"action": "unsupported"}))
		payload = json.loads(captured["text_data"])

		self.assertEqual(payload["event"], "error")
		self.assertIn("Unsupported action", payload["detail"])

	@patch("apps.chat.consumer.ChatConsumer._create_message", new_callable=AsyncMock)
	def test_receive_send_message_decodes_attachments(self, mocked_create_message):
		consumer = self._build_consumer()
		message = Message.objects.create(
			conversation=self.conversation,
			sender=self.alice,
			content="Hello websocket",
		)
		mocked_create_message.return_value = message
		payload = {
			"action": "send_message",
			"content": "Hello websocket",
			"attachments": [
				{
					"name": "note.txt",
					"content_type": "text/plain",
					"content_base64": base64.b64encode(b"hello").decode("utf-8"),
				}
			],
		}

		async_to_sync(consumer.receive)(text_data=json.dumps(payload))
		mocked_create_message.assert_awaited_once()

		content_arg, attachments = mocked_create_message.call_args.args
		self.assertEqual(content_arg, "Hello websocket")
		self.assertEqual(len(attachments), 1)
		self.assertEqual(attachments[0].name, "note.txt")
		self.assertEqual(attachments[0].content_type, "text/plain")

	def test_receive_rejects_invalid_attachment_base64(self):
		consumer = self._build_consumer()
		captured = self._capture_send(consumer)
		payload = {
			"action": "send_message",
			"content": "Bad attachment",
			"attachments": [
				{
					"name": "note.txt",
					"content_type": "text/plain",
					"content_base64": "@@@not-base64@@@",
				}
			],
		}

		async_to_sync(consumer.receive)(text_data=json.dumps(payload))
		payload = json.loads(captured["text_data"])

		self.assertEqual(payload["event"], "error")
		self.assertIn("Attachment content is not valid base64", payload["detail"])
