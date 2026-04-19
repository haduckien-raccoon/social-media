from django.urls import path
from apps.notifications import views

urlpatterns = [
    path("", views.list_notifications, name="list_notifications"),
    path("unread-count/", views.unread_count, name="unread_count"),
    path("read-all/", views.mark_all_notifications_read, name="mark_all_notifications_read"),
    path("<int:notification_id>/open/", views.open_notification, name="open_notification"),
    path("<int:notification_id>/read/", views.mark_notification_read, name="mark_notification_read"),
    path("<int:notification_id>/seen/", views.mark_notification_seen, name="mark_notification_seen"),
    path("<int:notification_id>/delete/", views.delete_notification, name="delete_notification"),
    path("sse/", views.sse_notifications, name="sse_notifications"),
]
