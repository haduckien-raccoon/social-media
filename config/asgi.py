"""
ASGI config for config project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.1/howto/deployment/asgi/
"""

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

from channels.routing import ProtocolTypeRouter, URLRouter
from django.conf import settings
from django.contrib.staticfiles.handlers import ASGIStaticFilesHandler
from django.core.asgi import get_asgi_application

# Ensure Django app registry is fully initialized before importing consumers/routing.
django_asgi_app = get_asgi_application()
if settings.DEBUG:
    # Serve static files in development when running via ASGI server (uvicorn/daphne).
    django_asgi_app = ASGIStaticFilesHandler(django_asgi_app)

from apps.middleware.jwt_auth import jwt_auth_middleware_stack
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
