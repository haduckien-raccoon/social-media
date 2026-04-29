"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.contrib import admin
from django.urls import path, include

from django.conf import settings
from django.conf.urls.static import static
from django.views.static import serve
from django.urls import re_path
from django.contrib.staticfiles.urls import staticfiles_urlpatterns

handler404 = 'apps.core.views.error_404_view'
# handler500 = 'apps.core.views.error_500_view'
handler403 = 'apps.core.views.error_403_view'

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("apps.core.urls")),
    path("accounts/", include("apps.accounts.urls")),
    path('friends/', include('apps.friends.urls')),
    path("posts/", include("apps.posts.urls")),
    path("chat/", include("apps.chat.urls")),
    path("search/", include("apps.search.urls")),
    path("groups/", include("apps.groups.urls")),
    path("notifications/", include("apps.notifications.urls")),
] + [
    re_path(r"^images/(?P<path>.*)$", serve, {"document_root": settings.IMAGES_ROOT}),
    re_path(r"^media/(?P<path>.*)$", serve, {"document_root": settings.MEDIA_ROOT}),
] + static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

if settings.DEBUG:
    urlpatterns += staticfiles_urlpatterns()