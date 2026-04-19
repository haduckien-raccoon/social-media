import tempfile

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from apps.accounts.models import User
from apps.friends.models import Friend
from apps.groups.models import GroupPost, GroupRole
from apps.groups.services import GroupMemberService, GroupPostService, GroupService
from apps.notifications.models import Notification


@override_settings(MEDIA_ROOT=tempfile.gettempdir())
class GroupPostsAndNotificationTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            email="owner@example.com",
            username="owner",
            password="Password123!",
            is_active=True,
        )
        self.member = User.objects.create_user(
            email="member@example.com",
            username="member",
            password="Password123!",
            is_active=True,
        )
        self.tagged_friend = User.objects.create_user(
            email="tagged@example.com",
            username="tagged",
            password="Password123!",
            is_active=True,
        )
        self.group = GroupService.create_group(
            owner=self.owner,
            name="Test Group",
            description="desc",
            is_private=True,
        )
        GroupMemberService.join_group(self.member, self.group)
        membership = self.group.members.get(user=self.member)
        membership.status = "approved"
        membership.role = GroupRole.MEMBER
        membership.save(update_fields=["status", "role"])

        Friend.objects.get_or_create(user=self.member, friend=self.tagged_friend)
        Friend.objects.get_or_create(user=self.tagged_friend, friend=self.member)

    def _fake_image(self):
        return SimpleUploadedFile("group.jpg", b"group-image", content_type="image/jpeg")

    def _fake_file(self):
        return SimpleUploadedFile("group.txt", b"group-file", content_type="text/plain")

    def test_join_group_creates_join_request_notification(self):
        new_user = User.objects.create_user(
            email="new@example.com",
            username="newbie",
            password="Password123!",
            is_active=True,
        )

        GroupMemberService.join_group(new_user, self.group)
        self.assertTrue(
            Notification.objects.filter(
                user=self.owner,
                actor=new_user,
                verb_code="group_join_request",
            ).exists()
        )

    def test_approve_member_creates_accept_notification(self):
        pending_user = User.objects.create_user(
            email="pending@example.com",
            username="pending",
            password="Password123!",
            is_active=True,
        )
        membership = GroupMemberService.join_group(pending_user, self.group)
        Notification.objects.all().delete()

        GroupMemberService.approve_member(self.owner, membership)
        membership.refresh_from_db()

        self.assertEqual(membership.status, "approved")
        self.assertTrue(
            Notification.objects.filter(
                user=pending_user,
                actor=self.owner,
                verb_code="group_request_accept",
            ).exists()
        )

    def test_create_post_in_group_accepts_media_only(self):
        post = GroupPostService.create_post_in_group(
            self.group,
            self.member,
            content="",
            images=[self._fake_image()],
            files=[],
            tagged_users=[str(self.tagged_friend.id)],
        )

        context = GroupPost.objects.get(post=post, group=self.group)
        self.assertEqual(context.status, "pending")
        self.assertEqual(post.images.count(), 1)
        self.assertTrue(
            Notification.objects.filter(
                user=self.owner,
                actor=self.member,
                verb_code="post_in_group",
                object_id=post.id,
            ).exists()
        )
        self.assertTrue(
            Notification.objects.filter(
                user=self.tagged_friend,
                actor=self.member,
                verb_code="mention_in_post",
                object_id=post.id,
            ).exists()
        )

    def test_create_post_in_group_accepts_tagged_post_with_images_and_files(self):
        Notification.objects.all().delete()

        post = GroupPostService.create_post_in_group(
            self.group,
            self.member,
            content="",
            images=[self._fake_image()],
            files=[self._fake_file()],
            tagged_users=[str(self.tagged_friend.id)],
        )

        self.assertEqual(post.images.count(), 1)
        self.assertEqual(post.files.count(), 1)
        self.assertTrue(
            Notification.objects.filter(
                user=self.tagged_friend,
                actor=self.member,
                verb_code="mention_in_post",
                object_id=post.id,
            ).exists()
        )

    def test_create_post_in_group_owner_auto_approved(self):
        post = GroupPostService.create_post_in_group(
            self.group,
            self.owner,
            content="owner post",
            images=[],
            files=[],
        )
        context = GroupPost.objects.get(post=post, group=self.group)
        self.assertEqual(context.status, "approved")

    def test_create_post_in_group_rejects_empty_post(self):
        with self.assertRaises(ValidationError):
            GroupPostService.create_post_in_group(
                self.group,
                self.member,
                content="",
                images=[],
                files=[],
            )
