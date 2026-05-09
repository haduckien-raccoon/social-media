from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import user_passes_test
from django.contrib import messages
from django.db.models import Q, Count
from django.core.paginator import Paginator
from django.urls import reverse
from apps.accounts.models import User
from apps.posts.models import (
    Post,
    Comment,
    PostImage,
    PostFile,
    CommentImage,
    CommentFile,
    Hashtag,
    ContentStatus,
)
from apps.moderation.models import ContentModerationLog, ModerationTargetType, ModerationAction
import string
import random

def is_admin(user):
    return user.is_authenticated and user.is_staff

def generate_random_password(length=12):
    characters = string.ascii_letters + string.digits + string.punctuation
    return ''.join(random.choice(characters) for _ in range(length))

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
