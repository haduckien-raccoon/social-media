from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import user_passes_test
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q, Count, Subquery, OuterRef
from django.db.models.functions import Coalesce
from django.utils import timezone
from django.urls import reverse
from apps.accounts.models import User
from apps.admin.models import SystemConfig
from django.core.mail import send_mail
from django.conf import settings
from apps.notifications.services import create_notification # Sử dụng service có sẵn của bạn
from django.db import transaction
from apps.posts.models import (
    Post,
    Comment,
    PostImage,
    PostFile,
    CommentImage,
    CommentFile,
    Hashtag,
    ContentStatus,
    Report,
    ReportReason,
)
from apps.moderation.models import ContentModerationLog, ModerationTargetType, ModerationAction
import string
import random
from apps.notifications.services import create_notification
from django.db.models.functions import TruncDate
from datetime import timedelta
import json
import psutil
from dotenv import load_dotenv
load_dotenv()

def is_admin(user):
    return user.is_authenticated and user.is_staff

def generate_random_password(length=12):
    characters = string.ascii_letters + string.digits + string.punctuation
    return ''.join(random.choice(characters) for _ in range(length))

# Thêm hàm view này vào views.py của bạn
@user_passes_test(is_admin, login_url='/accounts/login/')
def dashboard(request):
    """ View tổng quan hệ thống (Dashboard Analytics) """
    today = timezone.now().date()
    thirty_days_ago = today - timedelta(days=30)
    seven_days_ago = today - timedelta(days=7)

    # 1. USER METRICS (Dựa vào ngày tạo và lần đăng nhập cuối)
    total_users = User.objects.count()
    new_users_today = User.objects.filter(date_joined__date=today).count()
    
    # DAU (Daily Active Users): User đăng nhập trong hôm nay
    dau = User.objects.filter(last_login__date=today).count()
    # MAU (Monthly Active Users): User đăng nhập trong 30 ngày qua
    mau = User.objects.filter(last_login__date__gte=thirty_days_ago).count()

    # 2. CONTENT METRICS
    total_posts = Post.objects.count()
    posts_today = Post.objects.filter(created_at__date=today).count()
    pending_reports = Report.objects.filter(status='pending').count()

    # 3. BIỂU ĐỒ: Tăng trưởng User trong 7 ngày qua
    users_growth_data = (
        User.objects.filter(date_joined__date__gte=seven_days_ago)
        .annotate(date=TruncDate('date_joined'))
        .values('date')
        .annotate(count=Count('id'))
        .order_by('date')
    )
    
    # 4. BIỂU ĐỒ: Số bài viết mới trong 7 ngày qua
    posts_growth_data = (
        Post.objects.filter(created_at__date__gte=seven_days_ago)
        .annotate(date=TruncDate('created_at'))
        .values('date')
        .annotate(count=Count('id'))
        .order_by('date')
    )

    # Xử lý dữ liệu thô thành format JSON để đưa vào Chart.js
    dates_labels = [(seven_days_ago + timedelta(days=i)).strftime('%d/%m') for i in range(8)]
    
    # Tạo dictionary mặc định đếm = 0 cho các ngày
    user_counts_dict = {label: 0 for label in dates_labels}
    post_counts_dict = {label: 0 for label in dates_labels}

    for entry in users_growth_data:
        date_str = entry['date'].strftime('%d/%m')
        if date_str in user_counts_dict:
            user_counts_dict[date_str] = entry['count']

    for entry in posts_growth_data:
        date_str = entry['date'].strftime('%d/%m')
        if date_str in post_counts_dict:
            post_counts_dict[date_str] = entry['count']

    context = {
        'total_users': total_users,
        'new_users_today': new_users_today,
        'dau': dau,
        'mau': mau,
        'total_posts': total_posts,
        'posts_today': posts_today,
        'pending_reports': pending_reports,
        
        # Dữ liệu JSON cho biểu đồ
        'chart_labels': json.dumps(dates_labels),
        'chart_users': json.dumps(list(user_counts_dict.values())),
        'chart_posts': json.dumps(list(post_counts_dict.values())),
    }
    
    return render(request, 'admin/dashboard.html', context)

import os
import platform
from django.conf import settings
from django.db import connection
from django.core.cache import cache

@user_passes_test(is_admin, login_url='/accounts/login/')
def system_management(request):
    # 1. XỬ LÝ CẬP NHẬT CẤU HÌNH (CONFIG)
    if request.method == "POST":
        for key, value in request.POST.items():
            if key.startswith('config_'):
                config_key = key.replace('config_', '')
                config_obj = SystemConfig.objects.filter(key=config_key).first()
                if config_obj:
                    if config_obj.data_type == 'bool':
                        config_obj.value = 'True' if value == 'on' else 'False'
                    else:
                        config_obj.value = value
                    config_obj.save()
        
        for config_obj in SystemConfig.objects.filter(data_type='bool'):
            if f'config_{config_obj.key}' not in request.POST:
                config_obj.value = 'False'
                config_obj.save()
                
        messages.success(request, "Đã cập nhật cấu hình hệ thống thành công!")
        return redirect('custom_admin:system_management')

    configs = SystemConfig.objects.all().order_by('key')

    # 2. LẤY TRẠNG THÁI SERVER TĨNH (OS, DB, Cache)
    db_status = "Online" if connection.is_usable() else "Offline"
    try:
        cache.set('ping', 'pong', 5)
        cache_status = "Online" if cache.get('ping') == 'pong' else "Error"
    except Exception:
        cache_status = "Offline"

    server_status = {
        "os": platform.system() + " " + platform.release(),
        "python": platform.python_version(),
        "db_status": db_status,
        "cache_status": cache_status,
    }

    # 3. ĐỌC FILE LOGS (Để hiển thị ở tab Server Logs)
    log_type = request.GET.get('log', 'access') # Mặc định mở access log
    log_file_path = os.path.join(settings.BASE_DIR, 'logs', f'{log_type}.log')
    log_content = ""
    
    if os.path.exists(log_file_path):
        with open(log_file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            log_content = "".join(lines[-200:]) # Đọc 200 thao tác/lỗi mới nhất
    else:
        log_content = f"Đang chờ hệ thống ghi nhận log đầu tiên vào: {log_file_path}"

    context = {
        'configs': configs,
        'server_status': server_status,
        'log_content': log_content,
        'log_type': log_type,
    }
    return render(request, 'admin/system/index.html', context)

@user_passes_test(is_admin, login_url='/accounts/login/')
def get_system_metrics(request):
    """
    API lấy thông số phần cứng Server (CPU, RAM, Disk, Swap, Network)
    """
    try:
        # Lấy CPU usage (%) và số nhân (cores)
        cpu_percent = psutil.cpu_percent(interval=0.1)
        cpu_cores = psutil.cpu_count(logical=True)
        
        # Lấy RAM (đổi sang GB)
        mem = psutil.virtual_memory()
        ram_percent = mem.percent
        ram_used_gb = round(mem.used / (1024**3), 2)
        ram_total_gb = round(mem.total / (1024**3), 2)

        # Lấy Swap Memory (RAM ảo)
        swap = psutil.swap_memory()
        swap_percent = swap.percent

        # Lấy Disk (Ổ cứng phân vùng chứa code)
        disk = psutil.disk_usage('/')
        disk_percent = disk.percent
        disk_used_gb = round(disk.used / (1024**3), 2)
        disk_total_gb = round(disk.total / (1024**3), 2)

        # Trả về JSON
        return JsonResponse({
            'status': 'ok',
            'timestamp': timezone.now().strftime('%H:%M:%S'),
            'cpu': cpu_percent,
            'cpu_cores': cpu_cores,
            'ram': ram_percent,
            'ram_used': ram_used_gb,
            'ram_total': ram_total_gb,
            'swap': swap_percent,
            'disk': disk_percent,
            'disk_used': disk_used_gb,
            'disk_total': disk_total_gb
        })
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

@user_passes_test(is_admin, login_url='/accounts/login/')
def user_management_list(request):
    """ Xem danh sách user (filter theo email, trạng thái, ngày tạo) """
    query = request.GET.get('q', '')
    status = request.GET.get('status', '')
    
    users = User.objects.all().order_by('-date_joined')
    
    if query:
        users = users.filter(Q(email__icontains=query) | Q(username__icontains=query))
    if status == 'active':
        users = users.filter(is_active=True, is_banned=False)
    elif status == 'banned':
        users = users.filter(is_banned=True)
        
    return render(request, 'admin/users/list.html', {
        'users': users,
        'query': query,
        'status': status
    })

@user_passes_test(is_admin, login_url='/accounts/login/')
def user_management_detail(request, user_id):
    """ Xem chi tiết profile user """
    user = get_object_or_404(User, id=user_id)
    return render(request, 'admin/users/detail.html', {'target_user': user})

@user_passes_test(is_admin, login_url='/accounts/login/')
def user_management_toggle_ban(request, user_id):
    """ Khóa / mở khóa tài khoản (ban / unban) """
    if request.method == 'POST':
        user = get_object_or_404(User, id=user_id)
        if user == request.user:
            messages.error(request, "Không thể khóa tài khoản của chính mình!")
            return redirect('custom_admin:user_detail', user_id=user.id)
            
        user.is_banned = not user.is_banned
        user.save()
        status_msg = "mở khóa" if not user.is_banned else "khóa"
        messages.success(request, f"Đã {status_msg} tài khoản {user.email}.")
    return redirect('custom_admin:user_detail', user_id=user_id)

@user_passes_test(is_admin, login_url='/accounts/login/')
def user_management_set_role(request, user_id):
    """ Phân quyền (user / moderator / admin) """
    if request.method == 'POST':
        user = get_object_or_404(User, id=user_id)
        role = request.POST.get('role')
        
        if role == 'admin':
            user.is_staff = True
            user.is_superuser = True # Giữ sync nếu cần Django admin mặc định
        else: # user basic
            user.is_staff = False
            user.is_superuser = False
            
        user.save()
        messages.success(request, f"Đã cập nhật quyền của {user.email} thành {role}.")
    return redirect('custom_admin:user_detail', user_id=user_id)

@user_passes_test(is_admin, login_url='/accounts/login/')
def user_management_reset_password(request, user_id):
    """ Reset password """
    if request.method == 'POST':
        user = get_object_or_404(User, id=user_id)
        new_password = generate_random_password()
        user.set_password(new_password)
        user.save()
        messages.success(request, f"Mật khẩu mới của {user.email} là: {new_password}. Vui lòng sao chép lại.")
    return redirect('custom_admin:user_detail', user_id=user_id)

@user_passes_test(is_admin, login_url='/accounts/login/')
def user_management_activities(request, user_id):
    """ Xem lịch sử hoạt động (login, post, report...) """
    # Hiện tại base database chỉ có login info + report
    user = get_object_or_404(User, id=user_id)
    
    try:
        from apps.posts.models import Report
        reports_made = Report.objects.filter(reporter=user).order_by('-created_at')
        reports_handled = Report.objects.filter(handled_by=user).order_by('-handled_at')
    except ImportError:
        reports_made = []
        reports_handled = []
        
    return render(request, 'admin/users/activities.html', {
        'target_user': user,
        'reports_made': reports_made,
        'reports_handled': reports_handled,
    })


def _log_moderation_action(actor, target_type, target_id, action, reason=""):
    ContentModerationLog.objects.create(
        actor=actor,
        target_type=target_type,
        target_id=target_id,
        action=action,
        reason=reason or "",
    )


def _redirect_back(request, fallback_name):
    next_url = request.POST.get("next") or request.GET.get("next") or request.META.get("HTTP_REFERER")
    return redirect(next_url or reverse(fallback_name))


@user_passes_test(is_admin, login_url='/accounts/login/')
def content_post_list(request):
    query = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()
    deleted = request.GET.get("deleted", "").strip()

    posts = (
        Post.objects
        .select_related("author")
        .prefetch_related("hashtags")
        .order_by("-created_at")
    )

    if query:
        query_filter = Q(content__icontains=query) | Q(author__username__icontains=query)
        if query.isdigit():
            query_filter |= Q(id=int(query))
        posts = posts.filter(query_filter)

    if status:
        posts = posts.filter(status=status)

    if deleted == "1":
        posts = posts.filter(is_deleted=True)
    elif deleted == "0":
        posts = posts.filter(is_deleted=False)

    paginator = Paginator(posts, 20)
    page_obj = paginator.get_page(request.GET.get("page", 1))

    post_ids = [post.id for post in page_obj.object_list]
    log_counts = (
        ContentModerationLog.objects
        .filter(target_type=ModerationTargetType.POST, target_id__in=post_ids)
        .values("target_id")
        .annotate(count=Count("id"))
    )
    violation_map = {row["target_id"]: row["count"] for row in log_counts}
    for post in page_obj.object_list:
        post.violation_count = violation_map.get(post.id, 0)

    return render(request, "admin/content/posts.html", {
        "posts": page_obj,
        "query": query,
        "status": status,
        "deleted": deleted,
        "status_choices": ContentStatus.choices,
    })


@user_passes_test(is_admin, login_url='/accounts/login/')
def content_post_action(request, post_id):
    if request.method != "POST":
        return _redirect_back(request, "custom_admin:content_posts")

    post = get_object_or_404(Post, id=post_id)
    action = request.POST.get("action", "").strip()
    reason = request.POST.get("reason", "").strip()

    if action == ModerationAction.HIDE:
        post.status = ContentStatus.BLOCKED
        post.is_deleted = True
        post.save(update_fields=["status", "is_deleted", "updated_at"])
    elif action == ModerationAction.DELETE:
        post.status = ContentStatus.DELETED
        post.is_deleted = True
        post.save(update_fields=["status", "is_deleted", "updated_at"])
    elif action == ModerationAction.RESTORE:
        post.status = ContentStatus.NORMAL
        post.is_deleted = False
        post.save(update_fields=["status", "is_deleted", "updated_at"])
    elif action == ModerationAction.FLAG:
        post.status = ContentStatus.FLAGGED
        post.save(update_fields=["status", "updated_at"])
    elif action == ModerationAction.UNFLAG:
        post.status = ContentStatus.NORMAL
        post.save(update_fields=["status", "updated_at"])
    else:
        messages.error(request, "Hành động không hợp lệ.")
        return _redirect_back(request, "custom_admin:content_posts")

    _log_moderation_action(request.user, ModerationTargetType.POST, post.id, action, reason)
    messages.success(request, "Đã cập nhật trạng thái bài viết.")
    return _redirect_back(request, "custom_admin:content_posts")


@user_passes_test(is_admin, login_url='/accounts/login/')
def content_comment_list(request):
    query = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()
    deleted = request.GET.get("deleted", "").strip()

    comments = (
        Comment.objects
        .select_related("user", "post")
        .order_by("-created_at")
    )

    if query:
        query_filter = Q(content__icontains=query) | Q(user__username__icontains=query)
        if query.isdigit():
            query_filter |= Q(id=int(query)) | Q(post__id=int(query))
        comments = comments.filter(query_filter)

    if status:
        comments = comments.filter(status=status)

    if deleted == "1":
        comments = comments.filter(is_deleted=True)
    elif deleted == "0":
        comments = comments.filter(is_deleted=False)

    paginator = Paginator(comments, 20)
    page_obj = paginator.get_page(request.GET.get("page", 1))

    comment_ids = [comment.id for comment in page_obj.object_list]
    log_counts = (
        ContentModerationLog.objects
        .filter(target_type=ModerationTargetType.COMMENT, target_id__in=comment_ids)
        .values("target_id")
        .annotate(count=Count("id"))
    )
    violation_map = {row["target_id"]: row["count"] for row in log_counts}
    for comment in page_obj.object_list:
        comment.violation_count = violation_map.get(comment.id, 0)

    return render(request, "admin/content/comments.html", {
        "comments": page_obj,
        "query": query,
        "status": status,
        "deleted": deleted,
        "status_choices": ContentStatus.choices,
    })


@user_passes_test(is_admin, login_url='/accounts/login/')
def content_comment_action(request, comment_id):
    if request.method != "POST":
        return _redirect_back(request, "custom_admin:content_comments")

    comment = get_object_or_404(Comment, id=comment_id)
    action = request.POST.get("action", "").strip()
    reason = request.POST.get("reason", "").strip()

    if action == ModerationAction.HIDE:
        comment.status = ContentStatus.BLOCKED
        comment.is_deleted = True
        comment.save(update_fields=["status", "is_deleted", "updated_at"])
    elif action == ModerationAction.DELETE:
        comment.status = ContentStatus.DELETED
        comment.is_deleted = True
        comment.save(update_fields=["status", "is_deleted", "updated_at"])
    elif action == ModerationAction.RESTORE:
        comment.status = ContentStatus.NORMAL
        comment.is_deleted = False
        comment.save(update_fields=["status", "is_deleted", "updated_at"])
    elif action == ModerationAction.FLAG:
        comment.status = ContentStatus.FLAGGED
        comment.save(update_fields=["status", "updated_at"])
    elif action == ModerationAction.UNFLAG:
        comment.status = ContentStatus.NORMAL
        comment.save(update_fields=["status", "updated_at"])
    else:
        messages.error(request, "Hành động không hợp lệ.")
        return _redirect_back(request, "custom_admin:content_comments")

    _log_moderation_action(request.user, ModerationTargetType.COMMENT, comment.id, action, reason)
    messages.success(request, "Đã cập nhật trạng thái bình luận.")
    return _redirect_back(request, "custom_admin:content_comments")


@user_passes_test(is_admin, login_url='/accounts/login/')
def content_media_list(request):
    media_type = request.GET.get("type", "all")
    query = request.GET.get("q", "").strip()

    media_items = []
    page_obj = None

    def build_item(item_type, obj, *, post=None, comment=None, url="", filename=""):
        return {
            "type": item_type,
            "id": obj.id,
            "post": post,
            "comment": comment,
            "url": url,
            "filename": filename,
        }

    if media_type == "post_image":
        qs = PostImage.objects.select_related("post", "post__author").order_by("-id")
        if query and query.isdigit():
            qs = qs.filter(post__id=int(query))
        page_obj = Paginator(qs, 20).get_page(request.GET.get("page", 1))
        media_items = [build_item("post_image", img, post=img.post, url=img.image.url) for img in page_obj.object_list]
    elif media_type == "comment_image":
        qs = CommentImage.objects.select_related("comment", "comment__user", "comment__post").order_by("-id")
        if query and query.isdigit():
            qs = qs.filter(comment__id=int(query))
        page_obj = Paginator(qs, 20).get_page(request.GET.get("page", 1))
        media_items = [build_item("comment_image", img, comment=img.comment, url=img.image.url) for img in page_obj.object_list]
    elif media_type == "post_file":
        qs = PostFile.objects.select_related("post", "post__author").order_by("-id")
        if query and query.isdigit():
            qs = qs.filter(post__id=int(query))
        page_obj = Paginator(qs, 20).get_page(request.GET.get("page", 1))
        media_items = [build_item("post_file", f, post=f.post, url=f.file.url, filename=f.filename) for f in page_obj.object_list]
    elif media_type == "comment_file":
        qs = CommentFile.objects.select_related("comment", "comment__user", "comment__post").order_by("-id")
        if query and query.isdigit():
            qs = qs.filter(comment__id=int(query))
        page_obj = Paginator(qs, 20).get_page(request.GET.get("page", 1))
        media_items = [build_item("comment_file", f, comment=f.comment, url=f.file.url, filename=f.filename) for f in page_obj.object_list]
    else:
        max_items = 200
        post_images = PostImage.objects.select_related("post", "post__author").order_by("-id")[:max_items]
        comment_images = CommentImage.objects.select_related("comment", "comment__user", "comment__post").order_by("-id")[:max_items]
        post_files = PostFile.objects.select_related("post", "post__author").order_by("-id")[:max_items]
        comment_files = CommentFile.objects.select_related("comment", "comment__user", "comment__post").order_by("-id")[:max_items]

        media_items = [
            build_item("post_image", img, post=img.post, url=img.image.url) for img in post_images
        ] + [
            build_item("comment_image", img, comment=img.comment, url=img.image.url) for img in comment_images
        ] + [
            build_item("post_file", f, post=f.post, url=f.file.url, filename=f.filename) for f in post_files
        ] + [
            build_item("comment_file", f, comment=f.comment, url=f.file.url, filename=f.filename) for f in comment_files
        ]

        media_items.sort(key=lambda item: item["id"], reverse=True)
        paginator = Paginator(media_items, 20)
        page_obj = paginator.get_page(request.GET.get("page", 1))
        media_items = list(page_obj.object_list)

    return render(request, "admin/content/media.html", {
        "media_items": media_items,
        "page_obj": page_obj,
        "media_type": media_type,
        "query": query,
    })


@user_passes_test(is_admin, login_url='/accounts/login/')
def content_media_action(request):
    if request.method != "POST":
        return _redirect_back(request, "custom_admin:content_media")

    media_type = request.POST.get("media_type", "").strip()
    media_id = request.POST.get("media_id", "").strip()
    reason = request.POST.get("reason", "").strip()

    model_map = {
        "post_image": PostImage,
        "comment_image": CommentImage,
        "post_file": PostFile,
        "comment_file": CommentFile,
    }
    model = model_map.get(media_type)
    if not model or not media_id.isdigit():
        messages.error(request, "Dữ liệu không hợp lệ.")
        return _redirect_back(request, "custom_admin:content_media")

    obj = get_object_or_404(model, id=int(media_id))
    obj.delete()

    _log_moderation_action(request.user, media_type, int(media_id), ModerationAction.DELETE, reason)
    messages.success(request, "Đã xóa media.")
    return _redirect_back(request, "custom_admin:content_media")


@user_passes_test(is_admin, login_url='/accounts/login/')
def content_moderation_logs(request):
    target_type = request.GET.get("type", "").strip()
    logs = ContentModerationLog.objects.select_related("actor")

    if target_type:
        logs = logs.filter(target_type=target_type)

    paginator = Paginator(logs, 30)
    page_obj = paginator.get_page(request.GET.get("page", 1))

    return render(request, "admin/content/logs.html", {
        "logs": page_obj,
        "target_type": target_type,
        "target_types": ModerationTargetType.choices,
    })


@user_passes_test(is_admin, login_url='/accounts/login/')
def hashtag_list(request):
    query = request.GET.get("q", "").strip()

    if request.method == "POST":
        action = request.POST.get("action", "").strip()
        if action == "create":
            tag_value = request.POST.get("tag", "").strip().lstrip("#").lower()
            if tag_value:
                hashtag, created = Hashtag.objects.get_or_create(tag=tag_value)
                if created:
                    _log_moderation_action(request.user, ModerationTargetType.HASHTAG, hashtag.id, ModerationAction.UPDATE)
                    messages.success(request, "Đã tạo hashtag mới.")
                else:
                    messages.info(request, "Hashtag đã tồn tại.")
            else:
                messages.error(request, "Hashtag không hợp lệ.")
        return _redirect_back(request, "custom_admin:hashtag_list")

    hashtags = Hashtag.objects.annotate(post_count=Count("posts", distinct=True)).order_by("-post_count", "tag")
    if query:
        hashtags = hashtags.filter(tag__icontains=query)

    paginator = Paginator(hashtags, 30)
    page_obj = paginator.get_page(request.GET.get("page", 1))

    return render(request, "admin/hashtags/list.html", {
        "hashtags": page_obj,
        "query": query,
    })


@user_passes_test(is_admin, login_url='/accounts/login/')
def hashtag_detail(request, tag_id):
    hashtag = get_object_or_404(Hashtag, id=tag_id)

    if request.method == "POST":
        new_tag = request.POST.get("tag", "").strip().lstrip("#").lower()
        if not new_tag:
            messages.error(request, "Hashtag không hợp lệ.")
            return redirect("custom_admin:hashtag_detail", tag_id=hashtag.id)

        if Hashtag.objects.exclude(id=hashtag.id).filter(tag=new_tag).exists():
            messages.error(request, "Hashtag đã tồn tại.")
            return redirect("custom_admin:hashtag_detail", tag_id=hashtag.id)

        hashtag.tag = new_tag
        hashtag.save(update_fields=["tag"])
        _log_moderation_action(request.user, ModerationTargetType.HASHTAG, hashtag.id, ModerationAction.UPDATE)
        messages.success(request, "Đã cập nhật hashtag.")
        return redirect("custom_admin:hashtag_list")

    return render(request, "admin/hashtags/detail.html", {"hashtag": hashtag})


@user_passes_test(is_admin, login_url='/accounts/login/')
def hashtag_delete(request, tag_id):
    if request.method != "POST":
        return _redirect_back(request, "custom_admin:hashtag_list")

    hashtag = get_object_or_404(Hashtag, id=tag_id)
    hashtag.delete()
    _log_moderation_action(request.user, ModerationTargetType.HASHTAG, tag_id, ModerationAction.DELETE)
    messages.success(request, "Đã xóa hashtag.")
    return _redirect_back(request, "custom_admin:hashtag_list")

@user_passes_test(is_admin, login_url='/accounts/login/')
def report_detail(request, report_id):
    report = get_object_or_404(Report.objects.select_related("reporter", "handled_by"), id=report_id)
    
    target_content = None
    related_context = None

    # Lấy nội dung bị report để xem xét
    if report.target_type == ModerationTargetType.POST:
        target_content = Post.objects.filter(id=report.target_id).first()
        if target_content:
            # Context: Xem các comment gần nhất trên post này quan hệ 1 bình luận thuộc 1 post (quan hệ 1-nhiều)
            related_context = Comment.objects.filter(post_id=target_content.id).order_by("-created_at")[:5]
            
    elif report.target_type == ModerationTargetType.COMMENT:
        target_content = Comment.objects.select_related('post').filter(id=report.target_id).first()
        if target_content:
            # Context: Lấy bài viết chứa comment đó để hiểu bối cảnh
            related_context = target_content.post

    # Lấy các report khác cũng nhắm vào nội dung này để xem admin khác nói gì
    similar_reports = Report.objects.filter(
        target_type=report.target_type,
        target_id=report.target_id
    ).exclude(id=report.id).order_by("-created_at")

    return render(request, "admin/reports/detail.html", {
        "report": report,
        "target_content": target_content,
        "related_context": related_context,
        "similar_reports": similar_reports,
    })

@user_passes_test(is_admin, login_url='/accounts/login/')
def report_list(request):
    query = request.GET.get("q", "").strip()
    status = request.GET.get("status", "pending").strip()
    category_id = request.GET.get("category", "").strip() # Lấy ID thay vì chuỗi tên

    # 1. Luôn lấy danh sách lý do từ DB để hiển thị ở dropdown
    all_reasons = ReportReason.objects.all()

    # Thêm select_related để tối ưu
    reports = Report.objects.select_related("reporter", "handled_by", "reason")

    # 2. Lọc theo trạng thái
    if status == "pending":
        reports = reports.filter(status="pending")
    elif status == "handled":
        reports = reports.exclude(status="pending")

    # 3. LỌC THEO CATEGORY (ID từ Database)
    if category_id and category_id.isdigit():
        reports = reports.filter(reason_id=int(category_id))
    elif category_id == "custom": # Xử lý trường hợp "Vấn đề khác" (Lý do tùy chỉnh)
        reports = reports.filter(reason__isnull=True)

    # 4. Tìm kiếm văn bản
    if query:
        query_filter = (
            Q(custom_reason__icontains=query) | 
            Q(reporter__username__icontains=query) |
            Q(reason__name__icontains=query)
        )
        if query.isdigit():
            query_filter |= Q(id=int(query)) | Q(target_id=int(query))
        reports = reports.filter(query_filter)

    # 5. Auto-priority (Giữ nguyên)
    target_report_counts = Report.objects.filter(
        target_type=OuterRef('target_type'),
        target_id=OuterRef('target_id'),
        status="pending" 
    ).values('target_type', 'target_id').annotate(count=Count('id')).values('count')

    reports = reports.annotate(
        priority_score=Coalesce(Subquery(target_report_counts), 0)
    ).order_by("-priority_score", "-created_at")

    paginator = Paginator(reports, 20)
    page_obj = paginator.get_page(request.GET.get("page", 1))

    return render(request, "admin/reports/list.html", {
        "reports": page_obj,
        "query": query,
        "status": status,
        "category": category_id,
        "all_reasons": all_reasons, # Truyền danh sách từ DB vào Template
    })

@user_passes_test(is_admin, login_url='/accounts/login/')
def report_action(request, report_id):
    if request.method != "POST":
        return _redirect_back(request, "custom_admin:report_list")

    report = get_object_or_404(Report, id=report_id)
    action = request.POST.get("action", "").strip() 
    reason = request.POST.get("reason", "").strip()
    # Thêm cờ xác nhận thay đổi quyết định
    confirm_change = request.POST.get("confirm_change") == "yes"

    # KIỂM TRA: Nếu đã xử lý mà chưa bấm "Thay đổi"
    if report.status != "pending" and not confirm_change:
        messages.warning(request, "Báo cáo này đã được xử lý. Vui lòng xác nhận nếu bạn muốn thay đổi quyết định.")
        return redirect('custom_admin:report_detail', report_id=report.id)

    target_user = None
    target_obj = None

    # Lấy đối tượng mục tiêu (kể cả đã bị đánh dấu xóa is_deleted=True)
    if report.target_type == ModerationTargetType.POST:
        target_obj = Post.objects.filter(id=report.target_id).first()
        if target_obj: target_user = target_obj.author
    elif report.target_type == ModerationTargetType.COMMENT:
        target_obj = Comment.objects.filter(id=report.target_id).first()
        if target_obj: target_user = target_obj.user

    # FIX BAN USER: Nếu không tìm thấy target_obj (do đã xóa cứng), 
    # ta vẫn nên cho phép admin xử lý report nhưng báo lỗi nếu muốn Ban.
    if action == "BAN_USER" and not target_user:
        messages.error(request, "Không tìm thấy người dùng để khóa (có thể nội dung đã bị xóa hoàn toàn).")
        return redirect('custom_admin:report_detail', report_id=report.id)

    new_status = "pending"
    
    if action == "IGNORE":
        new_status = "rejected"
        # Nếu thay đổi từ Xóa sang Bỏ qua -> Khôi phục nội dung (Tùy chọn)
        if target_obj and target_obj.is_deleted:
            target_obj.is_deleted = False
            target_obj.status = ContentStatus.NORMAL
            target_obj.save()
        messages.success(request, "Đã cập nhật: Bỏ qua báo cáo.")

    elif action in ["DELETE_CONTENT", "BAN_USER"]:
        if target_obj:
            target_obj.status = ContentStatus.DELETED
            target_obj.is_deleted = True
            target_obj.save()
            _log_moderation_action(request.user, report.target_type, target_obj.id, ModerationAction.DELETE, reason)

        if action == "BAN_USER" and target_user:
            target_user.is_banned = True
            target_user.save()
            _log_moderation_action(request.user, ModerationTargetType.USER, target_user.id, "BAN", reason)
            messages.warning(request, f"Đã khóa tài khoản {target_user.username}.")
        
        new_status = "approved"
        messages.success(request, "Đã cập nhật: Xử lý vi phạm.")

    # Cập nhật thông tin xử lý
    report.status = new_status
    report.handled_by = request.user
    report.handled_at = timezone.now()
    report.save()

    # Đồng bộ các report trùng lặp
    Report.objects.filter(target_type=report.target_type, target_id=report.target_id).update(
        status=new_status,
        handled_by=request.user,
        handled_at=timezone.now()
    )

    return redirect('custom_admin:report_list')

# apps/admin/views.py

@user_passes_test(is_admin, login_url='/accounts/login/')
def mass_notification(request):
    if request.method == "POST":
        target_group = request.POST.get("target_group")
        notify_types = request.POST.getlist("notify_types")
        title = request.POST.get("title")
        content = request.POST.get("content")
        link = request.POST.get("link", "")

        # 1. Xác định danh sách User nhận tin
        if target_group == "staff":
            recipients = User.objects.filter(is_staff=True)
        else:
            recipients = User.objects.filter(is_active=True)

        recipient_count = recipients.count()

        try:
            with transaction.atomic():
                # --- KÊNH 1: THÔNG BÁO HỆ THỐNG (WEB) ---
                if 'web' in notify_types:
                    for user in recipients:
                        # FIX: Theo signature mới của bạn
                        create_notification(
                            actor=request.user,
                            recipient=user,
                            verb_code='SYSTEM_BROADCAST', # Mã định danh loại thông báo
                            verb_text=f"{title}: {content}", # Kết hợp tiêu đề và nội dung vào text
                            link=link,
                            target=None,         # Thông báo toàn hệ thống thường không có target cụ thể
                            reaction_type=None    # Không phải thông báo cảm xúc
                        )

                # --- KÊNH 2: EMAIL HÀNG LOẠT ---
                if 'email' in notify_types:
                    recipient_list = list(recipients.values_list('email', flat=True))
                    send_mail(
                        subject=f"[{settings.SITE_NAME}] {title}",
                        message=content,
                        from_email=settings.EMAIL_HOST_USER,
                        recipient_list=recipient_list,
                        fail_silently=False,
                    )

            messages.success(request, f"Đã gửi thông báo thành công tới {recipient_count} người dùng!")
        except Exception as e:
            messages.error(request, f"Lỗi hệ thống: {str(e)}")

        return redirect('custom_admin:mass_notification')

    return render(request, "admin/notifications/index.html")