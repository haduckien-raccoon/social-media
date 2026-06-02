from django.urls import path
from . import views

app_name = 'custom_admin'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('users/', views.user_management_list, name='user_list'),
    path('users/<int:user_id>/', views.user_management_detail, name='user_detail'),
    path('users/<int:user_id>/toggle-ban/', views.user_management_toggle_ban, name='user_toggle_ban'),
    path('users/<int:user_id>/toggle-deleted/', views.user_management_toggle_deleted, name='user_toggle_deleted'),
    path('users/<int:user_id>/role/', views.user_management_set_role, name='user_set_role'),
    path('users/<int:user_id>/reset-password/', views.user_management_reset_password, name='user_reset_password'),
    path('users/<int:user_id>/activities/', views.user_management_activities, name='user_activities'),
    path('content/posts/', views.content_post_list, name='content_posts'),
    path('content/posts/<int:post_id>/action/', views.content_post_action, name='content_post_action'),
    path('content/comments/', views.content_comment_list, name='content_comments'),
    path('content/comments/<int:comment_id>/action/', views.content_comment_action, name='content_comment_action'),
    path('content/media/', views.content_media_list, name='content_media'),
    path('content/media/action/', views.content_media_action, name='content_media_action'),
    path('content/logs/', views.content_moderation_logs, name='content_logs'),
    path('hashtags/', views.hashtag_list, name='hashtag_list'),
    path('hashtags/<int:tag_id>/', views.hashtag_detail, name='hashtag_detail'),
    path('hashtags/<int:tag_id>/delete/', views.hashtag_delete, name='hashtag_delete'),
    path('reports/', views.report_list, name='report_list'),
    path('reports/<int:report_id>/', views.report_detail, name='report_detail'),
    path('reports/<int:report_id>/action/', views.report_action, name='report_action'),
    # Trong apps/admin/urls.py
    path('system/', views.system_management, name='system_management'),
    path('system/metrics/', views.get_system_metrics, name='system_metrics_api'),
    # apps/admin/urls.py
    path('notifications/', views.mass_notification, name='mass_notification'),
]
