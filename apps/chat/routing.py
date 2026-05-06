from django.urls import re_path

from apps.chat.consumer import ChatConsumer, ChatInboxConsumer


websocket_urlpatterns = [
	re_path(r"ws/chat/inbox/$", ChatInboxConsumer.as_asgi()),
	re_path(r"ws/chat/(?P<conversation_id>\d+)/$", ChatConsumer.as_asgi()),
]
