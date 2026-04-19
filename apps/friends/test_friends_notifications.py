from django.test import TestCase

from apps.accounts.models import User
from apps.friends.models import Friend, FriendRequest
from apps.friends.services import accept_friend_request, send_friend_request
from apps.notifications.models import Notification


class FriendNotificationTests(TestCase):
    def setUp(self):
        self.sender = User.objects.create_user(
            email="sender@example.com",
            username="sender",
            password="Password123!",
            is_active=True,
        )
        self.receiver = User.objects.create_user(
            email="receiver@example.com",
            username="receiver",
            password="Password123!",
            is_active=True,
        )

    def test_send_friend_request_creates_notification(self):
        request_obj, message = send_friend_request(self.sender, self.receiver)

        self.assertIsNotNone(request_obj)
        self.assertEqual(request_obj.status, FriendRequest.STATUS_PENDING)
        self.assertEqual(message, "Request sent.")

        self.assertTrue(
            Notification.objects.filter(
                user=self.receiver,
                actor=self.sender,
                verb_code="friend_request",
            ).exists()
        )

    def test_accept_friend_request_creates_notification_and_friendship(self):
        request_obj, _ = send_friend_request(self.sender, self.receiver)
        Notification.objects.all().delete()

        success, message = accept_friend_request(self.receiver, request_obj.id)
        self.assertTrue(success)
        self.assertEqual(message, "Friend request accepted.")

        self.assertTrue(Friend.objects.filter(user=self.sender, friend=self.receiver).exists())
        self.assertTrue(Friend.objects.filter(user=self.receiver, friend=self.sender).exists())
        self.assertTrue(
            Notification.objects.filter(
                user=self.sender,
                actor=self.receiver,
                verb_code="friend_accept",
            ).exists()
        )
