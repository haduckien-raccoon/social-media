# # apps/friends/templatetags/friend_tags.py
# from django import template
# from apps.friends.services import get_friend_status
# from apps.friends.models import FriendRequest

# register = template.Library()

# @register.simple_tag
# def check_relation(user, target_user):
#     return get_friend_status(user, target_user)

# @register.simple_tag
# def get_request_id(from_user, to_user):
#     req = FriendRequest.objects.filter(from_user=from_user, to_user=to_user, status='pending').first()
#     print("Debug get_request_id:", from_user, to_user, req)
#     return req.id if req else None

# @register.filter
# def get_avatar(user):
#     """Lấy avatar an toàn, trả về ảnh mặc định nếu không có"""
#     try:
#         if hasattr(user, 'profile') and user.profile.avatar:
#             return user.profile.avatar.url
#     except Exception:
#         pass
#     return "/images/avatars/normal.jpg"
# # ---------------------
# apps/friends/templatetags/friend_tags.py
from django import template
from apps.friends.services import get_friend_status
from apps.friends.models import FriendRequest

register = template.Library()


@register.simple_tag
def check_relation(user, target_user):
    return get_friend_status(user, target_user)


@register.simple_tag
def get_request_id(from_user, to_user):
    to_user_id = getattr(to_user, "id", to_user)
    req = FriendRequest.objects.filter(
        from_user=from_user,
        to_user_id=to_user_id,
        status="pending",
    ).first()
    return req.id if req else None


@register.filter
def get_avatar(user):
    """Support both Django User objects and Neo4jSuggestedUser DTOs."""
    try:
        avatar = getattr(user, "avatar", None)
        if avatar:
            return avatar
    except Exception:
        pass

    try:
        if hasattr(user, "profile") and user.profile.avatar:
            return user.profile.avatar.url
    except Exception:
        pass

    return "/images/avatars/normal.jpg"
