from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path("demo/realtime/", views.realtime_demo, name="realtime_demo"),
]
