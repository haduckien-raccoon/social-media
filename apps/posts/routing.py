"""WebSocket routing for realtime post features."""

from django.urls import path

from .consumers import RealtimeConsumer

websocket_urlpatterns = [
    path("ws/realtime/", RealtimeConsumer.as_asgi()),
]
