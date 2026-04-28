from django.test import TestCase

from apps.accounts.models import User
from apps.friends.models import Friend, FriendRequest
from apps.friends.services import (
	accept_friend_request,
	cancel_friend_request,
	get_friend_status_detail,
	send_friend_request,
	unfriend_user,
)


class FriendRegressionTests(TestCase):
	def setUp(self):
		self.alice = User.objects.create_user(
			email="alice_friend_regression@example.com",
			username="alice_friend_regression",
			password="Password123!",
			is_active=True,
		)
		self.bob = User.objects.create_user(
			email="bob_friend_regression@example.com",
			username="bob_friend_regression",
			password="Password123!",
			is_active=True,
		)

	def test_send_friend_request_rejects_self_request(self):
		request_obj, message = send_friend_request(self.alice, self.alice)

		self.assertIsNone(request_obj)
		self.assertEqual(message, "Cannot add yourself.")
		self.assertFalse(FriendRequest.objects.exists())

	def test_cancel_friend_request_removes_pending_request(self):
		request_obj, _ = send_friend_request(self.alice, self.bob)

		success, message = cancel_friend_request(self.alice, request_obj.id)

		self.assertTrue(success)
		self.assertEqual(message, "Request cancelled.")
		self.assertFalse(FriendRequest.objects.filter(id=request_obj.id).exists())

	def test_unfriend_removes_friendship_and_old_requests(self):
		request_obj, _ = send_friend_request(self.alice, self.bob)
		accept_friend_request(self.bob, request_obj.id)

		success, message = unfriend_user(self.alice, self.bob)

		self.assertTrue(success)
		self.assertEqual(message, "Unfriended successfully.")
		self.assertFalse(Friend.objects.filter(user=self.alice, friend=self.bob).exists())
		self.assertFalse(Friend.objects.filter(user=self.bob, friend=self.alice).exists())
		self.assertEqual(get_friend_status_detail(self.alice, self.bob), {"status": "none"})
