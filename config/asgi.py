"""
ASGI config for config project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.1/howto/deployment/asgi/
"""

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

from channels.routing import ProtocolTypeRouter, URLRouter
from django.core.asgi import get_asgi_application
from apps.middleware.jwt_auth import jwt_auth_middleware_stack

# Ensure Django app registry is fully initialized before importing consumers/routing.
django_asgi_app = get_asgi_application()

import apps.chat.routing
import apps.posts.routing


websocket_urlpatterns = (
    apps.posts.routing.websocket_urlpatterns + apps.chat.routing.websocket_urlpatterns
)

application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": jwt_auth_middleware_stack(
        URLRouter(
            websocket_urlpatterns
        )
    ),
})
