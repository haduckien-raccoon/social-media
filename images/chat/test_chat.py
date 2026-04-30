import json
import tempfile
from unittest.mock import Mock

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, TestCase, override_settings

from apps.accounts.models import User
from apps.chat.models import MessageReaction
from apps.chat.service import (
	MAX_ATTACHMENT_SIZE_BYTES,
	create_conversation,
	create_message,
	get_unread_count,
	mark_conversation_read,
	serialize_message,
	toggle_message_reaction,
)
from apps.chat.views import (
	chat_page_view,
	mark_read_view,
	search_friends_view,
	send_message_view,
	start_chat_with_friend_view,
	toggle_message_reaction_view,
)
from apps.friends.models import Friend


@override_settings(MEDIA_ROOT=tempfile.gettempdir())
class ChatServiceTests(TestCase):
	def setUp(self):
		self.alice = User.objects.create_user(
			email="alice_chat@example.com",
			username="alice_chat",
			password="Password123!",
			is_active=True,
		)
		self.bob = User.objects.create_user(
			email="bob_chat@example.com",
			username="bob_chat",
			password="Password123!",
			is_active=True,
		)
		self.charlie = User.objects.create_user(
			email="charlie_chat@example.com",
			username="charlie_chat",
			password="Password123!",
			is_active=True,
		)
		self.conversation = create_conversation(self.alice, [self.bob.id])

	def _fake_file(self, name="doc.txt", content_type="text/plain", data=b"hello"):
		return SimpleUploadedFile(name, data, content_type=content_type)

	def test_create_conversation_contains_creator_and_participant(self):
		participant_ids = set(self.conversation.participants.values_list("id", flat=True))
		self.assertEqual(participant_ids, {self.alice.id, self.bob.id})

	def test_create_message_requires_content_or_attachment(self):
		with self.assertRaises(ValidationError):
			create_message(self.alice, self.conversation, content="", attachments=[])

	def test_create_message_accepts_text_and_attachment_under_limit(self):
		message = create_message(
			self.alice,
			self.conversation,
			content="Xin chao",
			attachments=[self._fake_file(name="manual.pdf", content_type="application/pdf")],
		)

		self.assertEqual(message.sender_id, self.alice.id)
		self.assertEqual(message.attachments.count(), 1)
		attachment = message.attachments.first()
		self.assertEqual(attachment.filename, "manual.pdf")
		self.assertEqual(attachment.content_type, "application/pdf")

	def test_create_message_rejects_attachment_over_20mb(self):
		oversize_file = Mock()
		oversize_file.name = "video.mp4"
		oversize_file.content_type = "video/mp4"
		oversize_file.size = MAX_ATTACHMENT_SIZE_BYTES + 1

		with self.assertRaises(ValidationError):
			create_message(
				self.alice,
				self.conversation,
				content="",
				attachments=[oversize_file],
			)

	def test_non_member_cannot_send_message(self):
		with self.assertRaises(PermissionDenied):
			create_message(self.charlie, self.conversation, content="No permission")

	def test_mark_read_updates_last_read_and_unread_count(self):
		create_message(self.bob, self.conversation, content="Tin nhan 1")
		self.assertEqual(get_unread_count(self.conversation, self.alice), 1)

		participant = mark_conversation_read(self.alice, self.conversation)

		self.assertIsNotNone(participant.last_read_at)
		self.assertEqual(get_unread_count(self.conversation, self.alice), 0)

	def test_toggle_message_reaction_lifecycle(self):
		message = create_message(self.alice, self.conversation, content="Can react")

		first = toggle_message_reaction(self.bob, message, "like")
		self.assertEqual(first["status"], "added")
		self.assertEqual(first["reaction_summary"]["like"], 1)

		second = toggle_message_reaction(self.bob, message, "wow")
		self.assertEqual(second["status"], "changed")
		self.assertEqual(second["reaction_summary"], {"wow": 1})

		third = toggle_message_reaction(self.bob, message, "wow")
		self.assertEqual(third["status"], "removed")
		self.assertEqual(third["reaction_summary"], {})
		self.assertEqual(MessageReaction.objects.filter(message=message).count(), 0)

	def test_serialize_message_contains_seen_and_reaction_data(self):
		message = create_message(self.alice, self.conversation, content="payload")
		toggle_message_reaction(self.bob, message, "love")
		mark_conversation_read(self.bob, self.conversation)

		payload = serialize_message(message, viewer=self.bob)
		self.assertEqual(payload["current_user_reaction"], "love")
		self.assertEqual(payload["reaction_summary"]["love"], 1)
		self.assertIn(self.bob.id, payload["seen_by_user_ids"])


@override_settings(MEDIA_ROOT=tempfile.gettempdir())
class ChatViewTests(TestCase):
	def setUp(self):
		self.factory = RequestFactory()
		self.alice = User.objects.create_user(
			email="alice_view_chat@example.com",
			username="alice_view_chat",
			password="Password123!",
			is_active=True,
		)
		self.bob = User.objects.create_user(
			email="bob_view_chat@example.com",
			username="bob_view_chat",
			password="Password123!",
			is_active=True,
		)
		self.charlie = User.objects.create_user(
			email="charlie_view_chat@example.com",
			username="charlie_view_chat",
			password="Password123!",
			is_active=True,
		)
		self.conversation = create_conversation(self.alice, [self.bob.id])

	def _fake_file(self, name="image.jpg", content_type="image/jpeg", data=b"img"):
		return SimpleUploadedFile(name, data, content_type=content_type)

	def test_send_message_view_returns_created_payload(self):
		request = self.factory.post(
			f"/chat/conversations/{self.conversation.id}/messages/send/",
			data={
				"content": "Hello from view",
				"attachments": self._fake_file(name="note.txt", content_type="text/plain"),
			},
		)
		request.user = self.alice

		response = send_message_view(request, self.conversation.id)
		payload = json.loads(response.content.decode("utf-8"))

		self.assertEqual(response.status_code, 201)
		self.assertEqual(payload["message"]["content"], "Hello from view")
		self.assertEqual(len(payload["message"]["attachments"]), 1)

	def test_send_message_view_denies_non_participant(self):
		request = self.factory.post(
			f"/chat/conversations/{self.conversation.id}/messages/send/",
			data={"content": "forbidden"},
		)
		request.user = self.charlie

		response = send_message_view(request, self.conversation.id)
		self.assertEqual(response.status_code, 403)

	def test_mark_read_view_returns_zero_unread_after_mark(self):
		create_message(self.bob, self.conversation, content="Unread for alice")

		request = self.factory.post(f"/chat/conversations/{self.conversation.id}/read/")
		request.user = self.alice

		response = mark_read_view(request, self.conversation.id)
		payload = json.loads(response.content.decode("utf-8"))

		self.assertEqual(response.status_code, 200)
		self.assertEqual(payload["unread_count"], 0)
		self.assertIsNotNone(payload["last_read_at"])

	def test_toggle_message_reaction_view_returns_reaction_state(self):
		message = create_message(self.alice, self.conversation, content="React from view")
		request = self.factory.post(
			f"/chat/messages/{message.id}/reaction/",
			data={"reaction": "wow"},
		)
		request.user = self.bob

		response = toggle_message_reaction_view(request, message.id)
		payload = json.loads(response.content.decode("utf-8"))

		self.assertEqual(response.status_code, 200)
		self.assertEqual(payload["status"], "added")
		self.assertEqual(payload["reaction_summary"], {"wow": 1})


@override_settings(MEDIA_ROOT=tempfile.gettempdir())
class ChatFriendDiscoveryTests(TestCase):
	def setUp(self):
		self.factory = RequestFactory()
		self.alice = User.objects.create_user(
			email="alice_friend_search@example.com",
			username="alice_friend_search",
			password="Password123!",
			is_active=True,
		)
		self.bob = User.objects.create_user(
			email="bob_friend_search@example.com",
			username="bob_friend_search",
			password="Password123!",
			is_active=True,
		)
		self.charlie = User.objects.create_user(
			email="charlie_friend_search@example.com",
			username="charlie_friend_search",
			password="Password123!",
			is_active=True,
		)

		Friend.objects.create(user=self.alice, friend=self.bob)
		Friend.objects.create(user=self.bob, friend=self.alice)

	def test_search_friends_view_returns_only_friends(self):
		request = self.factory.get("/chat/api/friends/search/?q=bob")
		request.user = self.alice

		response = search_friends_view(request)
		payload = json.loads(response.content.decode("utf-8"))

		self.assertEqual(response.status_code, 200)
		self.assertEqual(len(payload["results"]), 1)
		self.assertEqual(payload["results"][0]["id"], self.bob.id)

	def test_start_chat_with_friend_creates_then_reuses_direct_conversation(self):
		request_one = self.factory.post(f"/chat/api/friends/{self.bob.id}/start/")
		request_one.user = self.alice
		response_one = start_chat_with_friend_view(request_one, self.bob.id)
		payload_one = json.loads(response_one.content.decode("utf-8"))

		request_two = self.factory.post(f"/chat/api/friends/{self.bob.id}/start/")
		request_two.user = self.alice
		response_two = start_chat_with_friend_view(request_two, self.bob.id)
		payload_two = json.loads(response_two.content.decode("utf-8"))

		self.assertEqual(response_one.status_code, 200)
		self.assertEqual(response_two.status_code, 200)
		self.assertEqual(payload_one["conversation"]["id"], payload_two["conversation"]["id"])

	def test_start_chat_with_non_friend_returns_403(self):
		request = self.factory.post(f"/chat/api/friends/{self.charlie.id}/start/")
		request.user = self.alice

		response = start_chat_with_friend_view(request, self.charlie.id)
		self.assertEqual(response.status_code, 403)

	def test_chat_page_view_renders_html_and_initial_messages(self):
		conversation = create_conversation(self.alice, [self.bob.id])
		create_message(self.bob, conversation, content="Tin nhan dau tien")

		request = self.factory.get(f"/chat/?conversation_id={conversation.id}")
		request.user = self.alice

		response = chat_page_view(request)
		self.assertEqual(response.status_code, 200)
		self.assertIn(b"Chat chung", response.content)
