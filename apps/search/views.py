# views.py
from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required
import json
from . import services
from django.db.models import Q
from apps.accounts.models import *
from apps.friends.services import *

# @login_required
def search_page_view(request):
    """Render trang HTML tìm kiếm"""
    return render(request, 'search/search.html')

# @login_required
@require_http_methods(["GET"])
def api_get_history(request):
    """API trả về JSON lịch sử để JS hiển thị"""
    data = services.get_user_history(request.user)
    print("Lịch sử tìm kiếm:", data)
    return JsonResponse({'results': data})

# @login_required
@require_http_methods(["POST"])
def api_save_history(request):
    """API lưu lịch sử (Dùng cho cả khi enter text hoặc click user)"""
    try:
        data = json.loads(request.body)
        action_type = data.get('type') # 'query' hoặc 'user'
        
        if action_type == 'query':
            keyword = data.get('value')
            services.save_keyword(request.user, keyword)
            
        elif action_type == 'user':
            target_id = data.get('value')
            services.save_profile_click(request.user, target_id)
        
        print("Lưu lịch sử tìm kiếm thành công.")
            
        return JsonResponse({'status': 'success'})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
    
@require_http_methods(["GET"])
def api_search_users(request):
    """
    API tìm kiếm User.
    Params:
    - q: Từ khóa
    - limit: Số lượng giới hạn (Mặc định 5, nếu 'all' thì lấy hết)
    """
    q = request.GET.get('q', '').strip()
    limit = request.GET.get('limit', '5') # Mặc định lấy 5
    
    if not q:
        return JsonResponse({'results': []})

    # Query tìm kiếm (Username hoặc Email)
    search_query = Q(username__icontains=q) | Q(email__icontains=q)
    
    # Lấy QuerySet
    users_qs = User.objects.filter(search_query).exclude(id=request.user.id)

    #Nếu bị chặn thì không hiện ra kết quả

    users_qs = filter_blocked_users(users_qs, request.user)

    #Nếu bị xóa, bị ban, bị unactivate, chưa verified thì không hiện ra kết quả
    #is_deleted, is_banned, is_active, is_verified
    users_qs = users_qs.filter(is_deleted=False, is_banned=False, is_active=True, is_verified=True)
    
    # Xử lý giới hạn số lượng
    if limit != 'all':
        try:
            limit_num = int(limit)
            users_qs = users_qs[:limit_num]
        except ValueError:
            users_qs = users_qs[:5]

    results = []
    for u in users_qs:
        # Xử lý Avatar an toàn
        avatar_url = '/images/avatars/normal.jpg' # Ảnh mặc định
        if hasattr(u, 'profile') and u.profile.avatar:
            avatar_url = u.profile.avatar.url
        
        # Xử lý Tên hiển thị
        display_name = u.profile.full_name
        if not display_name:
            display_name = u.username
        # Nếu bạn có trường full_name trong profile, hãy uncomment dòng dưới:
        # if hasattr(u, 'profile') and u.profile.full_name:
        #     display_name = u.profile.full_name
        count_mutual = len(get_friend_list(request.user, limit=None))

        results.append({
            'id': u.id,
            'username': u.username,
            'full_name': display_name,
            'avatar': avatar_url,
            # Thêm email hoặc bio nếu muốn hiện ở trang kết quả chi tiết
            'email': u.email,
            'mutual_friends_count': count_mutual
        })
    
    return JsonResponse({'results': results})


@require_http_methods(["GET"])
def api_search_hashtags(request):
    """
    API tìm kiếm hashtag.
    Params:
    - q: Từ khóa
    - limit: Số lượng giới hạn (Mặc định 10, nếu 'all' thì lấy hết)
    """
    q = request.GET.get('q', '').strip()
    limit = request.GET.get('limit', '10')

    if not q:
        return JsonResponse({'results': []})

    if limit == 'all':
        limit_num = None
    else:
        try:
            limit_num = int(limit)
        except ValueError:
            limit_num = 10

    results = services.search_hashtags(q, limit=limit_num)
    return JsonResponse({'results': results})