from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase

from apps.accounts.models import User
from apps.groups.models import GroupRole
from apps.groups.services import GroupMemberService, GroupPostService, GroupService


class GroupRegressionTests(TestCase):
	def setUp(self):
		self.owner = User.objects.create_user(
			email="owner_group_regression@example.com",
			username="owner_group_regression",
			password="Password123!",
			is_active=True,
		)
		self.member = User.objects.create_user(
			email="member_group_regression@example.com",
			username="member_group_regression",
			password="Password123!",
			is_active=True,
		)
		self.outsider = User.objects.create_user(
			email="outsider_group_regression@example.com",
			username="outsider_group_regression",
			password="Password123!",
			is_active=True,
		)
		self.group = GroupService.create_group(
			owner=self.owner,
			name="Regression Group",
			description="desc",
			is_private=True,
		)
		GroupMemberService.join_group(self.member, self.group)
		membership = self.group.members.get(user=self.member)
		membership.status = "approved"
		membership.role = GroupRole.MEMBER
		membership.save(update_fields=["status", "role"])

	def test_non_member_cannot_create_group_post(self):
		with self.assertRaises(PermissionDenied):
			GroupPostService.create_post_in_group(
				self.group,
				self.outsider,
				content="not allowed",
			)

	def test_group_post_rejects_empty_payload(self):
		with self.assertRaises(ValidationError):
			GroupPostService.create_post_in_group(
				self.group,
				self.member,
				content="   ",
				images=[],
				files=[],
			)

	def test_owner_cannot_leave_group(self):
		with self.assertRaises(PermissionDenied):
			GroupMemberService.leave_group(self.owner, self.group)
