import json
import tempfile

from asgiref.sync import async_to_sync
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, TestCase, override_settings

from apps.accounts.models import User, UserProfile
from apps.friends.models import Friend
from apps.notifications.models import Notification
from apps.posts.consumers import FeedConsumer, PostConsumer
from apps.posts.models import Comment, PostTagUser
from apps.posts.services import (
    create_comment,
    create_post,
    list_people_tag,
    share_post,
    toggle_comment_reaction,
    toggle_post_reaction,
    update_post,
)
from apps.posts.views import create_post_view, edit_post_view


@override_settings(MEDIA_ROOT=tempfile.gettempdir())
class PostServiceTests(TestCase):
    def setUp(self):
        self.author = User.objects.create_user(
            email="author@example.com",
            username="author",
            password="Password123!",
            is_active=True,
        )
        self.friend = User.objects.create_user(
            email="friend@example.com",
            username="friend",
            password="Password123!",
            is_active=True,
        )
        self.other_user = User.objects.create_user(
            email="other@example.com",
            username="other",
            password="Password123!",
            is_active=True,
        )

        Friend.objects.get_or_create(user=self.author, friend=self.friend)
        Friend.objects.get_or_create(user=self.friend, friend=self.author)

    def _fake_image(self, name="test.jpg"):
        return SimpleUploadedFile(name, b"fake-image-bytes", content_type="image/jpeg")

    def _fake_file(self, name="test.txt"):
        return SimpleUploadedFile(name, b"file-content", content_type="text/plain")

    def test_create_post_view_get_handles_missing_profile_relations(self):
        request = RequestFactory().get("/posts/create/")
        request.user = self.author

        response = create_post_view(request)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(UserProfile.objects.filter(user=self.author).exists())
        self.assertTrue(UserProfile.objects.filter(user=self.friend).exists())

    def test_edit_post_view_get_handles_missing_profile_relations(self):
        post = create_post(user=self.author, content="seed", privacy="public")
        request = RequestFactory().get(f"/posts/{post.id}/edit/")
        request.user = self.author

        response = edit_post_view(request, post.id)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(UserProfile.objects.filter(user=self.author).exists())
        self.assertTrue(UserProfile.objects.filter(user=self.friend).exists())

    def test_create_post_accepts_content_only(self):
        post = create_post(
            user=self.author,
            content="hello world",
            privacy="public",
            images=[],
            files=[],
        )
        self.assertEqual(post.content, "hello world")

    def test_create_post_accepts_media_only(self):
        post = create_post(
            user=self.author,
            content="",
            privacy="public",
            images=[self._fake_image()],
            files=[],
        )
        self.assertEqual(post.images.count(), 1)

    def test_create_post_rejects_empty_content_and_media(self):
        with self.assertRaises(ValidationError):
            create_post(
                user=self.author,
                content="",
                privacy="public",
                images=[],
                files=[],
            )

    def test_create_post_tags_only_friends_and_creates_notification(self):
        post = create_post(
            user=self.author,
            content="tagging",
            privacy="public",
            tagged_users=[str(self.friend.id), str(self.other_user.id), "invalid"],
        )

        tagged_ids = set(PostTagUser.objects.filter(post=post).values_list("user_id", flat=True))
        self.assertEqual(tagged_ids, {self.friend.id})
        self.assertTrue(
            Notification.objects.filter(
                user=self.friend,
                actor=self.author,
                verb_code="mention_in_post",
                object_id=post.id,
            ).exists()
        )
        self.assertFalse(
            Notification.objects.filter(
                user=self.other_user,
                actor=self.author,
                verb_code="mention_in_post",
                object_id=post.id,
            ).exists()
        )

    def test_create_post_accepts_tags_with_images_and_files(self):
        post = create_post(
            user=self.author,
            content="",
            privacy="public",
            images=[self._fake_image("img.jpg")],
            files=[self._fake_file("doc.txt")],
            tagged_users=[str(self.friend.id)],
        )

        self.assertEqual(post.images.count(), 1)
        self.assertEqual(post.files.count(), 1)
        self.assertEqual(
            set(PostTagUser.objects.filter(post=post).values_list("user_id", flat=True)),
            {self.friend.id},
        )
        self.assertTrue(
            Notification.objects.filter(
                user=self.friend,
                actor=self.author,
                verb_code="mention_in_post",
                object_id=post.id,
            ).exists()
        )

    def test_update_post_syncs_tags_without_duplicate_and_notifies_new_tag(self):
        second_friend = User.objects.create_user(
            email="friend2@example.com",
            username="friend2",
            password="Password123!",
            is_active=True,
        )
        Friend.objects.get_or_create(user=self.author, friend=second_friend)
        Friend.objects.get_or_create(user=second_friend, friend=self.author)

        post = create_post(
            user=self.author,
            content="before",
            privacy="public",
            tagged_users=[str(self.friend.id)],
        )
        Notification.objects.all().delete()

        update_post(
            post,
            content="after",
            tagged_users=[str(self.friend.id), str(second_friend.id), str(second_friend.id)],
        )

        tagged_ids = list(
            PostTagUser.objects.filter(post=post).values_list("user_id", flat=True).order_by("user_id")
        )
        self.assertEqual(tagged_ids, [self.friend.id, second_friend.id])
        self.assertTrue(
            Notification.objects.filter(
                user=second_friend,
                actor=self.author,
                verb_code="mention_in_post",
                object_id=post.id,
            ).exists()
        )
        self.assertFalse(
            Notification.objects.filter(
                user=self.friend,
                actor=self.author,
                verb_code="mention_in_post",
                object_id=post.id,
            ).exists()
        )

    def test_toggle_post_reaction_supports_wow_lifecycle(self):
        post = create_post(user=self.author, content="post", privacy="public")

        first = toggle_post_reaction(self.friend, post, "wow")
        self.assertEqual(first["status"], "added")
        self.assertEqual(first["total_count"], 1)

        second = toggle_post_reaction(self.friend, post, "wow")
        self.assertEqual(second["status"], "removed")
        self.assertEqual(second["total_count"], 0)

        third = toggle_post_reaction(self.friend, post, "like")
        self.assertEqual(third["status"], "added")
        self.assertEqual(third["total_count"], 1)

        notif = Notification.objects.get(
            user=self.author,
            actor=self.friend,
            verb_code="react_post",
            object_id=post.id,
        )
        self.assertEqual(notif.reaction_type, "like")

    def test_toggle_comment_reaction_supports_wow_lifecycle(self):
        post = create_post(user=self.author, content="post", privacy="public")
        comment = create_comment(
            user=self.author,
            post=post,
            content="comment",
        )

        first = toggle_comment_reaction(self.friend, comment, "wow")
        self.assertEqual(first["status"], "added")
        self.assertEqual(first["count"], 1)

        second = toggle_comment_reaction(self.friend, comment, "wow")
        self.assertEqual(second["status"], "removed")
        self.assertEqual(second["count"], 0)

        third = toggle_comment_reaction(self.friend, comment, "love")
        self.assertEqual(third["status"], "added")
        self.assertEqual(third["count"], 1)

        notif = Notification.objects.get(
            user=self.author,
            actor=self.friend,
            verb_code="react_comment",
            object_id=comment.id,
        )
        self.assertEqual(notif.reaction_type, "love")

    def test_toggle_post_reaction_notifies_post_author_and_tagged_users(self):
        tagged_friend = User.objects.create_user(
            email="tagged_friend@example.com",
            username="tagged_friend",
            password="Password123!",
            is_active=True,
        )
        Friend.objects.get_or_create(user=self.author, friend=tagged_friend)
        Friend.objects.get_or_create(user=tagged_friend, friend=self.author)

        post = create_post(
            user=self.author,
            content="post with tags",
            privacy="public",
            tagged_users=[str(self.friend.id), str(tagged_friend.id)],
        )
        Notification.objects.all().delete()

        toggle_post_reaction(self.other_user, post, "wow")

        recipients = set(
            Notification.objects.filter(
                actor=self.other_user,
                verb_code="react_post",
                object_id=post.id,
            ).values_list("user_id", flat=True)
        )
        self.assertEqual(recipients, {self.author.id, self.friend.id, tagged_friend.id})

    def test_toggle_post_reaction_does_not_notify_actor_when_actor_is_tagged(self):
        post = create_post(
            user=self.author,
            content="post with friend tag",
            privacy="public",
            tagged_users=[str(self.friend.id)],
        )
        Notification.objects.all().delete()

        toggle_post_reaction(self.friend, post, "wow")

        recipients = set(
            Notification.objects.filter(
                actor=self.friend,
                verb_code="react_post",
                object_id=post.id,
            ).values_list("user_id", flat=True)
        )
        self.assertEqual(recipients, {self.author.id})

    def test_create_comment_notifies_post_author_and_tagged_users(self):
        tagged_friend = User.objects.create_user(
            email="tagged_comment@example.com",
            username="tagged_comment",
            password="Password123!",
            is_active=True,
        )
        Friend.objects.get_or_create(user=self.author, friend=tagged_friend)
        Friend.objects.get_or_create(user=tagged_friend, friend=self.author)

        post = create_post(
            user=self.author,
            content="post with tags",
            privacy="public",
            tagged_users=[str(self.friend.id), str(tagged_friend.id)],
        )
        Notification.objects.all().delete()

        create_comment(user=self.other_user, post=post, content="new comment")

        recipients = set(
            Notification.objects.filter(
                actor=self.other_user,
                verb_code="comment_post",
                object_id=post.id,
            ).values_list("user_id", flat=True)
        )
        self.assertEqual(recipients, {self.author.id, self.friend.id, tagged_friend.id})

    def test_create_comment_creates_post_and_reply_notifications(self):
        post = create_post(user=self.author, content="post", privacy="public")
        create_comment(user=self.friend, post=post, content="first comment")
        self.assertTrue(
            Notification.objects.filter(
                user=self.author,
                actor=self.friend,
                verb_code="comment_post",
                object_id=post.id,
            ).exists()
        )

        Notification.objects.all().delete()
        parent = create_comment(user=self.author, post=post, content="parent")
        create_comment(user=self.friend, post=post, content="reply", parent=parent)
        self.assertTrue(
            Notification.objects.filter(
                user=self.author,
                actor=self.friend,
                verb_code="reply_comment",
                object_id=parent.id,
            ).exists()
        )

    def test_share_post_creates_notification(self):
        post = create_post(user=self.author, content="origin", privacy="public")
        share_post(self.friend, post, caption="share", privacy="public")

        self.assertTrue(
            Notification.objects.filter(
                user=self.author,
                actor=self.friend,
                verb_code="share_post",
                object_id=post.id,
            ).exists()
        )

    def test_list_people_tag_works_bidirectional(self):
        one_way_friend = User.objects.create_user(
            email="oneway@example.com",
            username="oneway",
            password="Password123!",
            is_active=True,
        )
        Friend.objects.create(user=self.author, friend=one_way_friend)

        people = list_people_tag(one_way_friend)
        people_ids = {user.id for user in people}
        self.assertIn(self.author.id, people_ids)


class PostWebSocketContractTests(TestCase):
    def test_feed_consumer_sends_event_data_shape(self):
        consumer = FeedConsumer()
        captured = {}

        async def fake_send(text_data=None, bytes_data=None, close=False):
            captured["text_data"] = text_data

        consumer.send = fake_send
        async_to_sync(consumer.feed_update)({"data": {"action": "new_post", "post_id": 1}})

        payload = json.loads(captured["text_data"])
        self.assertEqual(payload["action"], "new_post")
        self.assertEqual(payload["post_id"], 1)

    def test_post_consumer_sends_event_data_shape(self):
        consumer = PostConsumer()
        captured = {}

        async def fake_send(text_data=None, bytes_data=None, close=False):
            captured["text_data"] = text_data

        consumer.send = fake_send
        async_to_sync(consumer.post_event)(
            {"data": {"event": "reaction", "reaction_type": "wow", "total_count": 1}}
        )

        payload = json.loads(captured["text_data"])
        self.assertEqual(payload["event"], "reaction")
        self.assertEqual(payload["reaction_type"], "wow")
        self.assertEqual(payload["total_count"], 1)
