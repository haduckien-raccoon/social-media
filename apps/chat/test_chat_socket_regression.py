import json
import tempfile
from unittest.mock import AsyncMock

from asgiref.sync import async_to_sync
from django.test import TransactionTestCase, override_settings

from apps.accounts.models import User
from apps.chat.consumer import ChatConsumer
from apps.chat.models import Message
from apps.chat.service import create_conversation


@override_settings(MEDIA_ROOT=tempfile.gettempdir())
class ChatSocketRegressionTests(TransactionTestCase):
	def setUp(self):
		self.alice = User.objects.create_user(
			email="alice_chat_socket_regression@example.com",
			username="alice_chat_socket_regression",
			password="Password123!",
			is_active=True,
		)
		self.bob = User.objects.create_user(
			email="bob_chat_socket_regression@example.com",
			username="bob_chat_socket_regression",
			password="Password123!",
			is_active=True,
		)
		self.charlie = User.objects.create_user(
			email="charlie_chat_socket_regression@example.com",
			username="charlie_chat_socket_regression",
			password="Password123!",
			is_active=True,
		)
		self.conversation = create_conversation(self.alice, [self.bob.id])

	def _build_connected_consumer(self, user=None):
		consumer = ChatConsumer()
		consumer.user = user or self.alice
		consumer.conversation_id = self.conversation.id
		consumer.group_name = f"chat_conversation_{self.conversation.id}"
		consumer.channel_layer = AsyncMock()
		consumer.channel_name = "test-chat-channel"
		return consumer

	def test_send_message_action_serializes_message_before_group_send(self):
		consumer = self._build_connected_consumer()

		async_to_sync(consumer.receive)(
			text_data=json.dumps(
				{
					"action": "send_message",
					"content": "Socket message",
				}
			)
		)

		message = Message.objects.get(conversation=self.conversation)
		consumer.channel_layer.group_send.assert_awaited_once()
		group_name, event = consumer.channel_layer.group_send.await_args.args
		self.assertEqual(group_name, f"chat_conversation_{self.conversation.id}")
		self.assertEqual(event["type"], "chat_event")
		self.assertEqual(event["data"]["event"], "message_new")
		self.assertEqual(event["data"]["message"]["id"], message.id)
		self.assertEqual(event["data"]["message"]["content"], "Socket message")

	def test_toggle_reaction_action_rejects_message_from_other_conversation(self):
		other_conversation = create_conversation(self.alice, [self.charlie.id])
		message = Message.objects.create(
			conversation=other_conversation,
			sender=self.alice,
			content="wrong room",
		)
		consumer = self._build_connected_consumer()
		captured = {}

		async def fake_send(text_data=None, bytes_data=None, close=False):
			captured["text_data"] = text_data

		consumer.send = fake_send

		async_to_sync(consumer.receive)(
			text_data=json.dumps(
				{
					"action": "toggle_reaction",
					"message_id": message.id,
					"reaction": "like",
				}
			)
		)

		payload = json.loads(captured["text_data"])
		self.assertEqual(payload["event"], "error")
		self.assertIn("Message does not belong", payload["detail"])

	def test_connect_rejects_non_member(self):
		consumer = ChatConsumer()
		consumer.scope = {
			"user": self.charlie,
			"url_route": {"kwargs": {"conversation_id": str(self.conversation.id)}},
		}
		consumer.channel_layer = AsyncMock()
		consumer.channel_name = "test-chat-channel"
		consumer.close = AsyncMock()
		consumer.accept = AsyncMock()

		async_to_sync(consumer.connect)()

		consumer.close.assert_awaited_once_with(code=4403)
		consumer.accept.assert_not_awaited()
