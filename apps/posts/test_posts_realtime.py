import json
from unittest.mock import patch

from asgiref.sync import async_to_sync
from django.test import TestCase

from apps.accounts.models import User
from apps.posts.consumers import FeedConsumer, PostConsumer
from apps.posts.models import Comment, PostReaction
from apps.posts.services import (
    create_comment,
    create_post,
    delete_comment,
    share_post,
    toggle_post_reaction,
)


class PostRealtimeStatsServiceTests(TestCase):
    def setUp(self):
        self.author = User.objects.create_user(
            email="author_realtime@example.com",
            username="author_realtime",
            password="Password123!",
            is_active=True,
        )
        self.actor = User.objects.create_user(
            email="actor_realtime@example.com",
            username="actor_realtime",
            password="Password123!",
            is_active=True,
        )

    @patch("apps.posts.services.send_ws_message")
    def test_toggle_post_reaction_broadcasts_post_and_feed_stats(self, mocked_send_ws_message):
        post = create_post(user=self.author, content="origin", privacy="public")
        mocked_send_ws_message.reset_mock()

        result = toggle_post_reaction(self.actor, post, "like")

        self.assertEqual(result["status"], "added")
        self.assertEqual(result["total_count"], 1)

        self.assertEqual(mocked_send_ws_message.call_count, 2)

        first_group, first_type, first_payload = mocked_send_ws_message.call_args_list[0].args
        self.assertEqual(first_group, f"post_{post.id}")
        self.assertEqual(first_type, "post_event")
        self.assertEqual(first_payload["event"], "reaction")
        self.assertEqual(first_payload["post_id"], post.id)
        self.assertEqual(first_payload["total_count"], 1)
        self.assertEqual(first_payload["comment_count"], 0)
        self.assertEqual(first_payload["share_count"], 0)

        second_group, second_type, second_payload = mocked_send_ws_message.call_args_list[1].args
        self.assertEqual(second_group, "feed_global")
        self.assertEqual(second_type, "feed_update")
        self.assertEqual(second_payload["action"], "post_stats")
        self.assertEqual(second_payload["post_id"], post.id)
        self.assertEqual(second_payload["reaction_count"], 1)
        self.assertEqual(second_payload["comment_count"], 0)
        self.assertEqual(second_payload["share_count"], 0)

    @patch("apps.posts.services.send_ws_message")
    def test_create_comment_broadcasts_comment_and_feed_stats(self, mocked_send_ws_message):
        post = create_post(user=self.author, content="origin", privacy="public")
        mocked_send_ws_message.reset_mock()

        comment = create_comment(
            user=self.actor,
            post=post,
            content="new comment",
        )

        self.assertIsNotNone(comment.id)
        self.assertEqual(mocked_send_ws_message.call_count, 2)

        first_group, first_type, first_payload = mocked_send_ws_message.call_args_list[0].args
        self.assertEqual(first_group, f"post_{post.id}")
        self.assertEqual(first_type, "post_event")
        self.assertEqual(first_payload["event"], "comment_new")
        self.assertEqual(first_payload["post_id"], post.id)
        self.assertEqual(first_payload["comment_id"], comment.id)
        self.assertEqual(first_payload["comment_count"], 1)

        second_group, second_type, second_payload = mocked_send_ws_message.call_args_list[1].args
        self.assertEqual(second_group, "feed_global")
        self.assertEqual(second_type, "feed_update")
        self.assertEqual(second_payload["action"], "post_stats")
        self.assertEqual(second_payload["post_id"], post.id)
        self.assertEqual(second_payload["reaction_count"], 0)
        self.assertEqual(second_payload["comment_count"], 1)
        self.assertEqual(second_payload["share_count"], 0)

    @patch("apps.posts.services.send_ws_message")
    def test_delete_comment_broadcasts_deleted_ids_and_feed_stats(self, mocked_send_ws_message):
        post = create_post(user=self.author, content="origin", privacy="public")
        mocked_send_ws_message.reset_mock()
        root_comment = Comment.objects.create(user=self.actor, post=post, content="root")
        child_comment = Comment.objects.create(
            user=self.author,
            post=post,
            parent=root_comment,
            content="child",
        )

        delete_comment(self.author, root_comment)

        self.assertEqual(mocked_send_ws_message.call_count, 2)

        first_group, first_type, first_payload = mocked_send_ws_message.call_args_list[0].args
        self.assertEqual(first_group, f"post_{post.id}")
        self.assertEqual(first_type, "post_event")
        self.assertEqual(first_payload["event"], "comment_deleted")
        self.assertEqual(first_payload["comment_id"], root_comment.id)
        self.assertEqual(set(first_payload["deleted_ids"]), {root_comment.id, child_comment.id})
        self.assertEqual(first_payload["comment_count"], 0)

        second_group, second_type, second_payload = mocked_send_ws_message.call_args_list[1].args
        self.assertEqual(second_group, "feed_global")
        self.assertEqual(second_type, "feed_update")
        self.assertEqual(second_payload["action"], "post_stats")
        self.assertEqual(second_payload["post_id"], post.id)
        self.assertEqual(second_payload["reaction_count"], 0)
        self.assertEqual(second_payload["comment_count"], 0)
        self.assertEqual(second_payload["share_count"], 0)

    @patch("apps.posts.services.send_ws_message")
    def test_share_post_broadcasts_share_updated_and_feed_stats(self, mocked_send_ws_message):
        post = create_post(user=self.author, content="origin", privacy="public")
        mocked_send_ws_message.reset_mock()
        Comment.objects.create(user=self.actor, post=post, content="comment")
        PostReaction.objects.create(user=self.actor, post=post, reaction_type="like")

        new_post = share_post(self.actor, post, caption="share", privacy="public")

        self.assertIsNotNone(new_post.id)
        self.assertEqual(mocked_send_ws_message.call_count, 2)

        first_group, first_type, first_payload = mocked_send_ws_message.call_args_list[0].args
        self.assertEqual(first_group, f"post_{post.id}")
        self.assertEqual(first_type, "post_event")
        self.assertEqual(first_payload["event"], "share_updated")
        self.assertEqual(first_payload["post_id"], post.id)
        self.assertEqual(first_payload["reaction_count"], 1)
        self.assertEqual(first_payload["comment_count"], 1)
        self.assertEqual(first_payload["share_count"], 1)

        second_group, second_type, second_payload = mocked_send_ws_message.call_args_list[1].args
        self.assertEqual(second_group, "feed_global")
        self.assertEqual(second_type, "feed_update")
        self.assertEqual(second_payload["action"], "post_stats")
        self.assertEqual(second_payload["post_id"], post.id)
        self.assertEqual(second_payload["reaction_count"], 1)
        self.assertEqual(second_payload["comment_count"], 1)
        self.assertEqual(second_payload["share_count"], 1)


class PostRealtimeSocketContractTests(TestCase):
    def test_feed_consumer_sends_post_stats_shape(self):
        consumer = FeedConsumer()
        captured = {}

        async def fake_send(text_data=None, bytes_data=None, close=False):
            captured["text_data"] = text_data

        consumer.send = fake_send
        async_to_sync(consumer.feed_update)(
            {
                "data": {
                    "action": "post_stats",
                    "post_id": 11,
                    "reaction_count": 2,
                    "comment_count": 3,
                    "share_count": 4,
                }
            }
        )

        payload = json.loads(captured["text_data"])
        self.assertEqual(payload["action"], "post_stats")
        self.assertEqual(payload["post_id"], 11)
        self.assertEqual(payload["reaction_count"], 2)
        self.assertEqual(payload["comment_count"], 3)
        self.assertEqual(payload["share_count"], 4)

    def test_post_consumer_sends_share_updated_shape(self):
        consumer = PostConsumer()
        captured = {}

        async def fake_send(text_data=None, bytes_data=None, close=False):
            captured["text_data"] = text_data

        consumer.send = fake_send
        async_to_sync(consumer.post_event)(
            {
                "data": {
                    "event": "share_updated",
                    "post_id": 22,
                    "reaction_count": 1,
                    "comment_count": 2,
                    "share_count": 3,
                }
            }
        )

        payload = json.loads(captured["text_data"])
        self.assertEqual(payload["event"], "share_updated")
        self.assertEqual(payload["post_id"], 22)
        self.assertEqual(payload["reaction_count"], 1)
        self.assertEqual(payload["comment_count"], 2)
        self.assertEqual(payload["share_count"], 3)
