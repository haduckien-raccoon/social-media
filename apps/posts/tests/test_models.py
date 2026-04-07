from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError
from django.test import TestCase
from django.test import override_settings

from apps.posts.models import Comment
from apps.posts.models import CommentReaction
from apps.posts.models import Post
from apps.posts.models import PostAttachment
from apps.posts.models import PostReaction

User = get_user_model()


@override_settings(MEDIA_ROOT="/tmp/kien-test-media")
class PostModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="model@example.com",
            username="model-user",
            password="123456",
            is_active=True,
        )
        self.post = Post.objects.create(author=self.user, content="hello")

    def test_unique_post_reaction_constraint(self):
        PostReaction.objects.create(post=self.post, user=self.user, reaction_type="like")

        with self.assertRaises(IntegrityError):
            PostReaction.objects.create(post=self.post, user=self.user, reaction_type="love")

    def test_unique_comment_reaction_constraint(self):
        comment = Comment.objects.create(post=self.post, author=self.user, content="comment")
        CommentReaction.objects.create(comment=comment, user=self.user, reaction_type="like")

        with self.assertRaises(IntegrityError):
            CommentReaction.objects.create(comment=comment, user=self.user, reaction_type="love")

    def test_reply_depth_validation(self):
        root = Comment.objects.create(post=self.post, author=self.user, content="root")
        child = Comment.objects.create(post=self.post, author=self.user, content="child", parent=root)

        with self.assertRaises(ValidationError):
            Comment.objects.create(post=self.post, author=self.user, content="nested", parent=child)

    def test_post_attachment_preview_kind(self):
        image_file = SimpleUploadedFile("sample.png", b"png-data", content_type="image/png")
        attachment = PostAttachment.objects.create(
            post=self.post,
            attachment_type="image",
            file=image_file,
            original_name="sample.png",
            content_type="image/png",
            size_bytes=len(b"png-data"),
        )

        self.assertEqual(attachment.preview_kind, "image")
