from django.urls import path
from .views import *

app_name = "friends"

urlpatterns = [
    # Dashboard chính
    path("", friend_dashboard_view, name="index"),
    
    # Trang xem tất cả
    path("requests/", all_requests_view, name="all_requests"),
    path("suggestions/", all_suggestions_view, name="all_suggestions"),
    path("my-friends/", all_friends_view, name="all_friends"),
    path("sent-requests/", all_sent_requests_view, name="all_sent_requests"), # 4. Lời mời đã gửi (Mới)

    # Action AJAX
    path("api/send/<int:user_id>/", send_request_ajax, name="api_send_request"),
    path("api/cancel/<int:request_id>/", cancel_request_ajax, name="api_cancel_request"),
    path("api/sent-status/<int:request_id>/", sent_request_status_ajax, name="api_sent_request_status"),

    # Action thường (Form Submit)
    path("accept/<int:request_id>/", accept_request_view, name="accept_request"),
    path("reject/<int:request_id>/", reject_request_view, name="reject_request"),
    path("unfriend/<int:user_id>/", unfriend_view, name="unfriend"),
]
