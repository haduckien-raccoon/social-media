from django.urls import path
from . import views
from apps.posts.views import *

urlpatterns = [
    path('health/', views.health_check, name='health_check'),
    path('', feed_view, name='home'),
]
