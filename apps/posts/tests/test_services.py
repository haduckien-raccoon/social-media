from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.test import override_settings
from django.utils import timezone

from apps.friends.models import Friendship
from apps.posts.exceptions import PostsPermissionDeniedError
from apps.posts.exceptions import PostsValidationError
from apps.posts.models import Comment
from apps.posts.models import Post
from apps.posts.models import PostAttachment
from apps.posts.services import create_comment
from apps.posts.services import create_post
from apps.posts.services import list_following_feed_query
from apps.posts.services import set_post_reaction
from apps.posts.services import soft_delete_comment
from apps.posts.services import update_comment

User = get_user_model()


@override_settings(MEDIA_ROOT="/tmp/kien-test-media")
class PostServiceTests(TestCase):
    def setUp(self):
        self.author = User.objects.create_user(
            email="author@example.com",
            username="author",
            password="123456",
            is_active=True,
        )
        self.viewer = User.objects.create_user(
            email="viewer@example.com",
            username="viewer",
            password="123456",
            is_active=True,
        )
        self.third_user = User.objects.create_user(
            email="third@example.com",
            username="third",
            password="123456",
            is_active=True,
        )
        self.post = Post.objects.create(author=self.author, content="post")

    def test_reaction_toggle_behaviour(self):
        first = set_post_reaction(actor=self.viewer, post_id=self.post.id, reaction_type="like")
        self.post.refresh_from_db()
        self.assertEqual(first["action"], "created")
        self.assertEqual(self.post.reactions_count, 1)

        second = set_post_reaction(actor=self.viewer, post_id=self.post.id, reaction_type="like")
        self.post.refresh_from_db()
        self.assertEqual(second["action"], "removed")
        self.assertEqual(self.post.reactions_count, 0)

        third = set_post_reaction(actor=self.viewer, post_id=self.post.id, reaction_type="love")
        self.post.refresh_from_db()
        self.assertEqual(third["action"], "created")
        self.assertEqual(self.post.reactions_count, 1)

    def test_one_level_reply_rule(self):
        root = create_comment(actor=self.author, post_id=self.post.id, content="root")
        reply = create_comment(actor=self.viewer, post_id=self.post.id, content="reply", parent_id=root.id)

        with self.assertRaises(PostsValidationError):
            create_comment(actor=self.author, post_id=self.post.id, content="nested", parent_id=reply.id)

    def test_comment_edit_window_15_minutes(self):
        comment = create_comment(actor=self.author, post_id=self.post.id, content="before edit")

        Comment.objects.filter(id=comment.id).update(
            created_at=timezone.now() - timedelta(minutes=16),
        )

        with self.assertRaises(PostsValidationError):
            update_comment(actor=self.author, comment_id=comment.id, content="after 16 minutes")

    def test_comment_edit_permission(self):
        comment = create_comment(actor=self.author, post_id=self.post.id, content="author-only")

        with self.assertRaises(PostsPermissionDeniedError):
            update_comment(actor=self.viewer, comment_id=comment.id, content="not allowed")

    def test_soft_delete_comment(self):
        comment = create_comment(actor=self.author, post_id=self.post.id, content="to be deleted")
        self.post.refresh_from_db()
        self.assertEqual(self.post.comments_count, 1)

        deleted = soft_delete_comment(actor=self.author, comment_id=comment.id)
        self.assertTrue(deleted.is_deleted)
        self.assertEqual(deleted.content, "[deleted]")

        self.post.refresh_from_db()
        self.assertEqual(self.post.comments_count, 0)

    def test_create_post_with_attachments(self):
        file_one = SimpleUploadedFile("cat.png", b"image-bytes", content_type="image/png")
        file_two = SimpleUploadedFile("voice.mp3", b"audio-bytes", content_type="audio/mpeg")

        post = create_post(
            author=self.author,
            content="Attachment post",
            attachments=[file_one, file_two],
            request_id="req-post-attachment",
        )

        attachments = list(PostAttachment.objects.filter(post=post).order_by("id"))
        self.assertEqual(len(attachments), 2)
        self.assertEqual(attachments[0].attachment_type, "image")
        self.assertEqual(attachments[1].attachment_type, "audio")

    def test_create_post_rolls_back_on_invalid_attachment(self):
        invalid_file = SimpleUploadedFile("virus.exe", b"bad", content_type="application/octet-stream")

        with self.assertRaises(PostsValidationError):
            create_post(author=self.author, content="", attachments=[invalid_file])

        self.assertEqual(Post.objects.count(), 1)
        self.assertEqual(PostAttachment.objects.count(), 0)

    def test_following_feed_contains_accepted_friends_and_self(self):
        Friendship.objects.create(from_user=self.viewer, to_user=self.author, status="accepted")
        viewer_post = create_post(author=self.viewer, content="viewer post")
        stranger_post = create_post(author=self.third_user, content="third post")

        feed_posts = list(list_following_feed_query(viewer=self.author))
        feed_ids = {post.id for post in feed_posts}

        self.assertIn(self.post.id, feed_ids)
        self.assertIn(viewer_post.id, feed_ids)
        self.assertNotIn(stranger_post.id, feed_ids)

    def test_post_created_following_fanout_targets_only_accepted_network(self):
        Friendship.objects.create(from_user=self.author, to_user=self.viewer, status="accepted")

        with patch("apps.posts.services.publish_feed_event") as mock_publish:
            with self.captureOnCommitCallbacks(execute=True):
                post = create_post(author=self.author, content="fanout test", request_id="req-fanout")

        target_ids = {call.kwargs["user_id"] for call in mock_publish.call_args_list}
        self.assertIn(self.author.id, target_ids)
        self.assertIn(self.viewer.id, target_ids)
        self.assertNotIn(self.third_user.id, target_ids)
        self.assertTrue(any(call.kwargs["post_id"] == post.id for call in mock_publish.call_args_list))
