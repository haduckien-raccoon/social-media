from django.db.models import Q, Count
# from django.contrib.auth import get_user_model
from .models import FriendRequest, Friend
from apps.accounts.models import User
from apps.notifications.services import create_notification

# -------------------------------
# 1. Helper Check Status
# -------------------------------
def get_friend_status(user, target_user):
    if user.id == target_user.id: return "self"
    
    # Check đã là bạn chưa
    if Friend.objects.filter(user=user, friend=target_user).exists(): return "accepted"
    
    # Check User gửi lời mời -> Target
    req = FriendRequest.objects.filter(from_user=user, to_user=target_user, status='pending').first()
    if req: return "pending_sent"
    
    # Check Target gửi lời mời -> User
    req = FriendRequest.objects.filter(from_user=target_user, to_user=user, status='pending').first()
    if req: return "pending_received"
    
    return "none"

# -------------------------------
# 2. Lists & Suggestions (ĐÃ FIX LỖI 500 & FIELD ERROR)
# -------------------------------

# --- Lists ---
def get_friend_list(user, limit=None):
    queryset = Friend.objects.filter(user=user).select_related('friend')
    if limit:
        return [f.friend for f in queryset[:limit]]
    return [f.friend for f in queryset]


def get_pending_requests(user, limit=None):
    queryset = FriendRequest.objects.filter(to_user=user, status='pending').select_related('from_user')
    if limit:
        return queryset[:limit]
    return queryset

#tìm những người mà mình đang gửi lời mới kết bạn để show ra UI
def get_sent_pending_requests(user, limit=None):
    queryset = FriendRequest.objects.filter(from_user=user, status='pending').select_related('to_user')
    if limit:
        return queryset[:limit]
    return queryset

def get_friend_suggestions(user, limit=10):
    # 1. Lấy danh sách bạn bè & request pending (để loại trừ)
    my_friend_ids = list(Friend.objects.filter(user=user).values_list('friend_id', flat=True))
    
    # Những người mình đã gửi hoặc họ đã gửi cho mình (status='pending')
    pending_ids = list(FriendRequest.objects.filter(
        Q(from_user=user) | Q(to_user=user),
        status='pending'
    ).values_list('to_user_id', 'from_user_id'))
    
    # Flatten list pending_ids (vì values_list trả về tuple)
    pending_flat = set()
    for item in pending_ids:
        if item[0] != user.id: pending_flat.add(item[0])
        if item[1] != user.id: pending_flat.add(item[1])

    exclude_ids = set(my_friend_ids + list(pending_flat) + [user.id])

    # 2. Tìm bạn chung
    candidates = (
        Friend.objects
        .filter(user__id__in=my_friend_ids)     # Lấy bạn của bạn tôi
        .exclude(friend__id__in=exclude_ids)    # Trừ đi tôi, bạn tôi, và những người đang pending
        .values('friend')
        .annotate(mutual_count=Count('friend'))
        .order_by('-mutual_count')
    )

    if limit:
        candidates = candidates[:limit]

    suggestion_users = []
    suggested_ids = []

    for c in candidates:
        try:
            u = User.objects.get(id=c['friend'])
            u.mutual_count = c['mutual_count']
            suggestion_users.append(u)
            suggested_ids.append(u.id)
        except User.DoesNotExist:
            continue

    # 3. Bổ sung random nếu thiếu
    if limit and len(suggestion_users) < limit:
        need_more = limit - len(suggestion_users)
        random_users = User.objects.exclude(id__in=exclude_ids.union(suggested_ids)).order_by('?')[:need_more]
        for r in random_users:
            r.mutual_count = 0
            suggestion_users.append(r)

    return suggestion_users

# --- Actions (Update hàm send để trả về object request phục vụ AJAX) ---
def send_friend_request(from_user, to_user):
    if from_user == to_user: return None, "Cannot add yourself."
    if Friend.objects.filter(user=from_user, friend=to_user).exists(): return None, "Already friends."

    existing, created = FriendRequest.objects.get_or_create(
        from_user=from_user, to_user=to_user,
        defaults={'status': 'pending'}
    )
    
    if not created:
        if existing.status == 'pending': return None, "Request already sent."
        if existing.status == 'accepted': return None, "Already friends."
        if existing.status == 'rejected': 
            existing.status = 'pending'
            existing.save()
            create_notification(
                actor=from_user,
                recipient=to_user,
                verb_code="friend_request",
                target=from_user,
                link=f"/accounts/profile/{from_user.username}/",
            )
            return existing, "Request sent again." # Trả về existing request object

    create_notification(
        actor=from_user,
        recipient=to_user,
        verb_code="friend_request",
        target=from_user,
        link=f"/accounts/profile/{from_user.username}/",
    )
    return existing, "Request sent." # Trả về new request object

def accept_friend_request(user, request_id):
    try:
        # user ở đây là người nhận (to_user) đang bấm chấp nhận
        req = FriendRequest.objects.get(id=request_id, to_user=user, status='pending')
        req.status = 'accepted'
        req.save()
        
        # Tạo quan hệ 2 chiều trong bảng Friend
        Friend.objects.get_or_create(user=req.from_user, friend=req.to_user)
        Friend.objects.get_or_create(user=req.to_user, friend=req.from_user)

        create_notification(
            actor=user,
            recipient=req.from_user,
            verb_code="friend_accept",
            target=user,
            link=f"/accounts/profile/{user.username}/",
        )
        
        return True, "Friend request accepted."
    except FriendRequest.DoesNotExist:
        return False, "Request invalid or not found."

def reject_friend_request(user, request_id):
    try:
        req = FriendRequest.objects.get(id=request_id, to_user=user, status='pending')
        req.status = 'rejected'
        req.save()
        return True, "Friend request rejected."
    except FriendRequest.DoesNotExist:
        return False, "Request invalid."

def unfriend_user(user, target_user):
    # Xóa 2 chiều trong bảng Friend
    Friend.objects.filter(user=user, friend=target_user).delete()
    Friend.objects.filter(user=target_user, friend=user).delete()
    
    # Xóa sạch các request cũ để reset trạng thái
    FriendRequest.objects.filter(
        Q(from_user=user, to_user=target_user) | Q(from_user=target_user, to_user=user)
    ).delete()
    
    return True, "Unfriended successfully."

def cancel_friend_request(user, request_id):
    try:
        # user ở đây là người gửi (from_user) muốn hủy
        FriendRequest.objects.filter(id=request_id, from_user=user, status='pending').delete()
        return True, "Request cancelled."
    except Exception:
        return False, "Error cancelling request."

def get_friend_status_detail(user, target_user):
    if user == target_user:
        return {"status": "self"}

    if Friend.objects.filter(user=user, friend=target_user).exists():
        return {"status": "accepted"}

    sent = FriendRequest.objects.filter(
        from_user=user,
        to_user=target_user,
        status='pending'
    ).first()
    if sent:
        return {
            "status": "pending_sent",
            "request_id": sent.id
        }

    received = FriendRequest.objects.filter(
        from_user=target_user,
        to_user=user,
        status='pending'
    ).first()
    if received:
        return {
            "status": "pending_received",
            "request_id": received.id
        }

    return {"status": "none"}
