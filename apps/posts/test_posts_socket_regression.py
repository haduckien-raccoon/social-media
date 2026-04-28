import json
from unittest.mock import AsyncMock

from asgiref.sync import async_to_sync
from django.test import TestCase

from apps.posts.consumers import FeedConsumer, PostConsumer


class PostSocketRegressionTests(TestCase):
	def test_feed_connect_joins_global_group(self):
		consumer = FeedConsumer()
		consumer.scope = {}
		consumer.channel_layer = AsyncMock()
		consumer.channel_name = "test-feed-channel"
		consumer.accept = AsyncMock()

		async_to_sync(consumer.connect)()

		consumer.channel_layer.group_add.assert_awaited_once_with(
			"feed_global",
			"test-feed-channel",
		)
		consumer.accept.assert_awaited_once()

	def test_post_connect_joins_post_group_from_route(self):
		consumer = PostConsumer()
		consumer.scope = {"url_route": {"kwargs": {"post_id": 42}}}
		consumer.channel_layer = AsyncMock()
		consumer.channel_name = "test-post-channel"
		consumer.accept = AsyncMock()

		async_to_sync(consumer.connect)()

		consumer.channel_layer.group_add.assert_awaited_once_with(
			"post_42",
			"test-post-channel",
		)
		consumer.accept.assert_awaited_once()

	def test_post_event_forwards_nested_payload_without_mutation(self):
		consumer = PostConsumer()
		captured = {}

		async def fake_send(text_data=None, bytes_data=None, close=False):
			captured["text_data"] = text_data

		consumer.send = fake_send
		payload = {
			"event": "comment_new",
			"post_id": 42,
			"comment": {"id": 7, "content": "hello"},
		}

		async_to_sync(consumer.post_event)({"data": payload})

		self.assertEqual(json.loads(captured["text_data"]), payload)
