"""ASGI entrypoint with HTTP + WebSocket routing."""

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

from channels.routing import ProtocolTypeRouter, URLRouter
from django.core.asgi import get_asgi_application

http_application = get_asgi_application()
# Import websocket routes only after Django app registry is initialized.
from apps.posts.routing import websocket_urlpatterns
from apps.posts.ws_auth import JwtCookieAuthMiddleware

application = ProtocolTypeRouter(
    {
        "http": http_application,
        "websocket": JwtCookieAuthMiddleware(URLRouter(websocket_urlpatterns)),
    }
)
