from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.test import override_settings
from rest_framework.test import APIClient

from apps.accounts.services import create_jwt_pair_for_user
from apps.friends.models import Friendship
from apps.posts.models import Comment
from apps.posts.models import Post

User = get_user_model()


@override_settings(MEDIA_ROOT="/tmp/kien-test-media")
class PostsApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="api@example.com",
            username="api-user",
            password="123456",
            is_active=True,
        )
        self.other_user = User.objects.create_user(
            email="api2@example.com",
            username="api-user-2",
            password="123456",
            is_active=True,
        )

        self.client = APIClient()
        access, _ = create_jwt_pair_for_user(self.user)
        self.client.cookies["access"] = access

    def test_create_post_and_comment_via_api(self):
        post_resp = self.client.post("/api/v1/posts", {"content": "hello api"}, format="json")
        self.assertEqual(post_resp.status_code, 201)
        post_id = post_resp.data["id"]

        comment_resp = self.client.post(
            f"/api/v1/posts/{post_id}/comments",
            {"content": "first"},
            format="json",
        )
        self.assertEqual(comment_resp.status_code, 201)
        self.assertEqual(comment_resp.data["content"], "first")

    def test_create_post_with_attachment_multipart(self):
        image = SimpleUploadedFile("photo.png", b"photo-bytes", content_type="image/png")
        response = self.client.post(
            "/api/v1/posts",
            {"content": "media post", "attachments": [image]},
            format="multipart",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(len(response.data["attachments"]), 1)
        self.assertEqual(response.data["attachments"][0]["type"], "image")
        self.assertIn("preview_kind", response.data["attachments"][0])
        self.assertTrue(response.data["attachments"][0]["url"].endswith(".png"))

    def test_feed_endpoint_returns_only_self_and_accepted_friends(self):
        Friendship.objects.create(from_user=self.user, to_user=self.other_user, status="accepted")
        own_post = Post.objects.create(author=self.user, content="mine")
        friend_post = Post.objects.create(author=self.other_user, content="friend")
        outsider = User.objects.create_user(
            email="outsider@example.com",
            username="outsider",
            password="123456",
            is_active=True,
        )
        outsider_post = Post.objects.create(author=outsider, content="outsider")

        response = self.client.get("/api/v1/feed")
        self.assertEqual(response.status_code, 200)
        result_ids = {row["id"] for row in response.data["results"]}
        self.assertIn(own_post.id, result_ids)
        self.assertIn(friend_post.id, result_ids)
        self.assertNotIn(outsider_post.id, result_ids)

    def test_comment_permission_enforced(self):
        post = Post.objects.create(author=self.user, content="post")
        comment = Comment.objects.create(post=post, author=self.user, content="owner")

        other_client = APIClient()
        other_access, _ = create_jwt_pair_for_user(self.other_user)
        other_client.cookies["access"] = other_access

        resp = other_client.patch(
            f"/api/v1/comments/{comment.id}",
            {"content": "hijack"},
            format="json",
        )
        self.assertEqual(resp.status_code, 403)

    def test_api_requires_auth(self):
        anon_client = APIClient()
        resp = anon_client.get("/api/v1/posts")
        self.assertIn(resp.status_code, (401, 403))
