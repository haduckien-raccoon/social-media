from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt
from apps.accounts.models import User
from .services import *
import json

# Helper redirect
def action_redirect(request):
    return redirect(request.META.get('HTTP_REFERER', '/friends/'))

# -------------------------------
# 1. MAIN DASHBOARD (Hiện 10 item mỗi loại)
# -------------------------------
def friend_dashboard_view(request):
    user = request.user
    # Limit 10 items
    friends = get_friend_list(user, limit=10)
    pending_requests = get_pending_requests(user, limit=10)
    suggestions = get_friend_suggestions(user, limit=10)
    sent_requests = get_sent_pending_requests(user, limit=10)

    context = {
        "friends": friends,
        "pending_requests": pending_requests,
        "suggestions": suggestions,
        "sent_requests": sent_requests, # Truyền vào context
        "total_friends": Friend.objects.filter(user=user).count(),
        "total_sent": FriendRequest.objects.filter(from_user=user, status='pending').count(),
        "total_received": FriendRequest.objects.filter(to_user=user, status='pending').count(),
    }
    return render(request, "friends/friend_dashboard.html", context)

# -------------------------------
# 2. SUB-PAGES (SEE ALL)
# -------------------------------
def all_requests_view(request):
    requests = get_pending_requests(request.user) # Không limit
    return render(request, "friends/list_requests.html", {"requests": requests})

def all_suggestions_view(request):
    suggestions = get_friend_suggestions(request.user, limit=50) # Lấy nhiều hơn
    return render(request, "friends/list_suggestions.html", {"suggestions": suggestions})

def all_friends_view(request):
    friends = get_friend_list(request.user) # Không limit
    return render(request, "friends/list_friends.html", {"friends": friends})

def all_sent_requests_view(request):
    sent_requests = get_sent_pending_requests(request.user)
    return render(request, "friends/list_sent_requests.html", {"sent_requests": sent_requests})
# -------------------------------
# 3. ACTIONS (Hỗ trợ AJAX)
# -------------------------------

@csrf_exempt
def send_request_ajax(request, user_id):
    """Gửi kết bạn bằng AJAX, trả về JSON để đổi nút"""
    if request.method == "POST":
        target = get_object_or_404(User, id=user_id)
        req_obj, msg = send_friend_request(request.user, target)
        
        if req_obj:
            return JsonResponse({
                "status": "success", 
                "message": msg, 
                "request_id": req_obj.id, # Trả về ID để dùng cho nút Cancel
                "new_action": "cancel"
            })
        else:
            return JsonResponse({"status": "error", "message": msg}, status=400)
    return JsonResponse({"status": "error", "message": "Invalid method"}, status=405)

@csrf_exempt
def cancel_request_ajax(request, request_id):
    """Hủy kết bạn bằng AJAX"""
    if request.method == "POST":
        # Logic cancel nằm trong services
        success, msg = cancel_friend_request(request.user, request_id)
        if success:
             return JsonResponse({
                "status": "success", 
                "message": msg,
                "new_action": "send"
            })
        return JsonResponse({"status": "error", "message": msg}, status=400)
    return JsonResponse({"status": "error", "message": "Invalid method"}, status=405)


def sent_request_status_ajax(request, request_id):
    request_obj = FriendRequest.objects.filter(id=request_id, from_user=request.user).select_related("to_user").first()
    if request_obj:
        return JsonResponse({"status": request_obj.status, "request_id": request_obj.id})
    return JsonResponse({"status": "not_found", "request_id": request_id})

# Giữ lại các view cũ cho Accept/Reject/Unfriend (dùng Form submit truyền thống hoặc sửa thành AJAX nếu muốn)
def accept_request_view(request, request_id):
    if request.method == "POST":
        accept_friend_request(request.user, request_id)
    return action_redirect(request)

def reject_request_view(request, request_id):
    if request.method == "POST":
        reject_friend_request(request.user, request_id)
    return action_redirect(request)

def unfriend_view(request, user_id):
    if request.method == "POST":
        target = get_object_or_404(User, id=user_id)
        unfriend_user(request.user, target)
    return action_redirect(request)
