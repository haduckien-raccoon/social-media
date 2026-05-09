# services.py
# from django.contrib.auth import get_user_model
from django.utils import timezone
from django.db.models import Count
from .models import SearchHistory
from apps.accounts.models import User
from apps.posts.models import Hashtag
# User = get_user_model()

def get_user_history(user, limit=10):
    """Lấy danh sách lịch sử, mix cả User và Keyword"""
    histories = SearchHistory.objects.filter(user=user).select_related('target_user')[:limit]
    
    results = []
    for h in histories:
        # Chuẩn hóa dữ liệu để trả về cho Frontend dễ xử lý
        if h.target_user:
            # Nếu là User: Trả về tên, avatar, id
            results.append({
                'type': 'user',
                'target_id': h.target_user.id,
                'name': h.target_user.username, # Hoặc h.target_user.get_full_name()
                # Giả sử bạn có field avatar, nếu không có thì dùng ảnh mặc định
                'avatar': h.target_user.profile.avatar.url if hasattr(h.target_user, 'profile') and h.target_user.profile.avatar else '/images/avatars/normal.jpg',
                'time': h.updated_at
            })
        elif h.query:
            # Nếu là Text: Trả về chuỗi text
            results.append({
                'type': 'query',
                'text': h.query,
                'time': h.updated_at
            })
    return results

def save_keyword(user, keyword):
    """Lưu lịch sử tìm kiếm dạng Text"""
    clean_keyword = keyword.strip()
    if not clean_keyword:
        return None 
        
    obj, created = SearchHistory.objects.update_or_create(
        user=user,
        query=clean_keyword,
        target_user=None, # Đảm bảo không dính dáng đến user
        defaults={'updated_at': timezone.now()} # Update thời gian nếu đã có
    )
    return obj

def save_profile_click(user, target_user_id):
    """Lưu lịch sử khi Click vào một User"""
    try:
        target = User.objects.get(pk=target_user_id)
        # Không lưu nếu tự tìm chính mình
        if user.id == target.id:
            return None

        obj, created = SearchHistory.objects.update_or_create(
            user=user,
            target_user=target,
            defaults={
                'query': None, # Đảm bảo query null
                'updated_at': timezone.now()
            }
        )
        return obj
    except User.DoesNotExist:
        return None


def search_hashtags(query, limit=10):
    """Tìm hashtag theo từ khóa."""
    keyword = (query or "").strip().lstrip("#").lower()
    if not keyword:
        return []

    qs = (
        Hashtag.objects
        .filter(tag__icontains=keyword)
        .annotate(post_count=Count("posts", distinct=True))
        .order_by("-post_count", "tag")
    )

    if limit is not None:
        qs = qs[:limit]

    results = []
    for tag in qs:
        results.append({
            "id": tag.id,
            "tag": tag.tag,
            "post_count": tag.post_count,
        })
    return results