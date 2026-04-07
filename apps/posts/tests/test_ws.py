from asgiref.sync import async_to_sync
from asgiref.sync import sync_to_async
from channels.testing import WebsocketCommunicator
from django.contrib.auth import get_user_model
from django.test import TransactionTestCase
from django.test import override_settings

from apps.accounts.services import create_jwt_pair_for_user
from apps.friends.models import Friendship
from apps.posts.models import Post
from apps.posts.services import create_comment
from apps.posts.services import create_post
from apps.posts.services import set_comment_reaction
from apps.posts.services import set_post_reaction
from config.asgi import application

User = get_user_model()


@override_settings(
    CHANNEL_LAYERS={
        "default": {
            "BACKEND": "channels.layers.InMemoryChannelLayer",
        }
    }
)
class PostsWebSocketTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.user_one = User.objects.create_user(
            email="ws1@example.com",
            username="ws-user-1",
            password="123456",
            is_active=True,
        )
        self.user_two = User.objects.create_user(
            email="ws2@example.com",
            username="ws-user-2",
            password="123456",
            is_active=True,
        )
        self.post = Post.objects.create(author=self.user_one, content="ws post")

        self.user_one_access, _ = create_jwt_pair_for_user(self.user_one)
        self.user_two_access, _ = create_jwt_pair_for_user(self.user_two)

    async def _connect(self, token: str):
        communicator = WebsocketCommunicator(application, f"/ws/realtime/?access={token}")
        connected, _ = await communicator.connect()
        self.assertTrue(connected)
        return communicator

    async def _receive_until(self, communicator, event_name: str, attempts: int = 8):
        for _ in range(attempts):
            payload = await communicator.receive_json_from(timeout=2)
            if payload.get("event") == event_name:
                return payload
        self.fail(f"Did not receive event {event_name}")

    def test_presence_join_leave_events(self):
        async def scenario():
            ws_one = await self._connect(self.user_one_access)
            ws_two = await self._connect(self.user_two_access)

            await ws_one.send_json_to({"action": "subscribe_post", "post_id": self.post.id, "request_id": "r1"})
            snapshot_one = await self._receive_until(ws_one, "presence.snapshot")
            self.assertEqual(snapshot_one["post_id"], self.post.id)

            await ws_two.send_json_to({"action": "subscribe_post", "post_id": self.post.id, "request_id": "r2"})
            await self._receive_until(ws_two, "presence.snapshot")

            joined_payload = await self._receive_until(ws_one, "presence.joined")
            self.assertEqual(joined_payload["data"]["user"]["id"], self.user_two.id)

            await ws_two.send_json_to({"action": "unsubscribe_post", "post_id": self.post.id, "request_id": "r3"})
            left_payload = await self._receive_until(ws_one, "presence.left")
            self.assertEqual(left_payload["data"]["user"]["id"], self.user_two.id)

            await ws_one.disconnect()
            await ws_two.disconnect()

        async_to_sync(scenario)()

    def test_typing_event(self):
        async def scenario():
            ws_one = await self._connect(self.user_one_access)
            ws_two = await self._connect(self.user_two_access)

            await ws_one.send_json_to({"action": "subscribe_post", "post_id": self.post.id})
            await self._receive_until(ws_one, "presence.snapshot")

            await ws_two.send_json_to({"action": "subscribe_post", "post_id": self.post.id})
            await self._receive_until(ws_two, "presence.snapshot")
            await self._receive_until(ws_one, "presence.joined")

            await ws_two.send_json_to({"action": "typing_start", "post_id": self.post.id, "request_id": "typing-1"})
            typing_payload = await self._receive_until(ws_one, "typing.started")
            self.assertEqual(typing_payload["data"]["user"]["id"], self.user_two.id)

            await ws_one.disconnect()
            await ws_two.disconnect()

        async_to_sync(scenario)()

    def test_comment_and_reaction_events_sync_between_sender_and_receiver(self):
        async def scenario():
            ws_one = await self._connect(self.user_one_access)
            ws_two = await self._connect(self.user_two_access)

            await ws_one.send_json_to({"action": "subscribe_post", "post_id": self.post.id, "request_id": "sub-1"})
            await self._receive_until(ws_one, "presence.snapshot")

            await ws_two.send_json_to({"action": "subscribe_post", "post_id": self.post.id, "request_id": "sub-2"})
            await self._receive_until(ws_two, "presence.snapshot")
            await self._receive_until(ws_one, "presence.joined")

            comment = await sync_to_async(create_comment)(
                actor=self.user_one,
                post_id=self.post.id,
                content="hello realtime",
                request_id="comment-create",
            )

            sender_comment_event = await self._receive_until(ws_one, "comment.created")
            receiver_comment_event = await self._receive_until(ws_two, "comment.created")
            self.assertEqual(sender_comment_event["data"]["comment"]["id"], comment.id)
            self.assertEqual(receiver_comment_event["data"]["comment"]["id"], comment.id)

            await sync_to_async(set_post_reaction)(
                actor=self.user_one,
                post_id=self.post.id,
                reaction_type="like",
                request_id="post-react",
            )
            await self._receive_until(ws_one, "reaction.post.updated")
            await self._receive_until(ws_two, "reaction.post.updated")

            await sync_to_async(set_comment_reaction)(
                actor=self.user_two,
                comment_id=comment.id,
                reaction_type="love",
                request_id="comment-react",
            )
            sender_comment_reaction = await self._receive_until(ws_one, "reaction.comment.updated")
            receiver_comment_reaction = await self._receive_until(ws_two, "reaction.comment.updated")
            self.assertEqual(sender_comment_reaction["data"]["target_id"], comment.id)
            self.assertEqual(receiver_comment_reaction["data"]["target_id"], comment.id)

            await ws_one.disconnect()
            await ws_two.disconnect()

        async_to_sync(scenario)()

    def test_following_feed_receives_post_created_event(self):
        async def scenario():
            await sync_to_async(Friendship.objects.create)(
                from_user=self.user_one,
                to_user=self.user_two,
                status="accepted",
            )

            ws_receiver = await self._connect(self.user_two_access)
            await ws_receiver.send_json_to({"action": "subscribe_feed", "request_id": "feed-sub"})
            await self._receive_until(ws_receiver, "feed.snapshot")

            await sync_to_async(create_post)(
                author=self.user_one,
                content="feed event post",
                request_id="feed-create",
            )

            feed_event = await self._receive_until(ws_receiver, "post.created.following")
            self.assertEqual(feed_event["data"]["actor"]["id"], self.user_one.id)
            self.assertEqual(feed_event["data"]["post"]["content"], "feed event post")

            await ws_receiver.disconnect()

        async_to_sync(scenario)()

    def test_following_feed_receives_comment_and_reaction_events(self):
        async def scenario():
            await sync_to_async(Friendship.objects.create)(
                from_user=self.user_one,
                to_user=self.user_two,
                status="accepted",
            )

            ws_receiver = await self._connect(self.user_two_access)
            await ws_receiver.send_json_to({"action": "subscribe_feed", "request_id": "feed-sub"})
            await self._receive_until(ws_receiver, "feed.snapshot")

            comment = await sync_to_async(create_comment)(
                actor=self.user_one,
                post_id=self.post.id,
                content="feed comment event",
                request_id="feed-comment-create",
            )

            created_event = await self._receive_until(ws_receiver, "comment.created.following")
            self.assertEqual(created_event["post_id"], self.post.id)
            self.assertEqual(created_event["data"]["comment"]["id"], comment.id)

            await sync_to_async(set_post_reaction)(
                actor=self.user_one,
                post_id=self.post.id,
                reaction_type="like",
                request_id="feed-post-react",
            )
            post_reaction_event = await self._receive_until(ws_receiver, "reaction.post.updated.following")
            self.assertEqual(post_reaction_event["data"]["target"], "post")
            self.assertEqual(post_reaction_event["data"]["target_id"], self.post.id)

            await sync_to_async(set_comment_reaction)(
                actor=self.user_two,
                comment_id=comment.id,
                reaction_type="love",
                request_id="feed-comment-react",
            )
            comment_reaction_event = await self._receive_until(
                ws_receiver,
                "reaction.comment.updated.following",
            )
            self.assertEqual(comment_reaction_event["data"]["target"], "comment")
            self.assertEqual(comment_reaction_event["data"]["target_id"], comment.id)

            await ws_receiver.disconnect()

        async_to_sync(scenario)()
