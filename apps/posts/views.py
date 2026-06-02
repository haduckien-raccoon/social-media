from celery import result
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse, HttpResponseForbidden
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.db.models import Count, Q, Case, When, IntegerField
from django.core.exceptions import ValidationError
from rest_framework import request
from apps.posts.models import *
from apps.posts.services import *
from apps.friends.models import Friend
from django.shortcuts import render
from django.db.models import Q, Count
from .models import Post, PostReaction
from apps.friends.models import *
from apps.groups.models import *
from django.shortcuts import render
from django.db.models import Q, Count
from django.core.paginator import Paginator
from django.template.loader import render_to_string
from django.http import JsonResponse
from .models import Post, PostReaction
from apps.accounts.services import create_user_profile
from apps.moderation.services import *
from apps.moderation.models import *
from apps.posts.neo4j_feed import (
    get_recommended_feed_post_ids,
    mark_feed_posts_seen,
)
from apps.groups.services import *
MAX_CLIENT_SEEN_IDS = 200

def _parse_seen_post_ids(raw_value):
    if not raw_value:
        return []

    result = []
    for value in str(raw_value).split(","):
        try:
            result.append(int(value))
        except (TypeError, ValueError):
            continue

    return result


def feed_view(request):
    """
    Recommended feed using Neo4j for post ranking.

    Neo4j:
        - selects/ranks post IDs by graph relationships
        - applies time decay, seen penalty, hashtag fatigue

    MySQL:
        - hydrates selected post IDs
        - keeps existing template, annotations, prefetches, and lazy loading
    """
    page_number = int(request.GET.get("page", 1) or 1)
    per_page = 5

    seen_post_ids = _parse_seen_post_ids(
        request.GET.get("seen_post_ids", "")
    )

    feed_result = get_recommended_feed_post_ids(
        user=request.user,
        page=page_number,
        per_page=per_page,
        seen_post_ids=seen_post_ids,
    )

    post_ids = feed_result["post_ids"]
    has_next = feed_result["has_next"]

    if not post_ids:
        post_list = []
    else:
        preserved_order = Case(
            *[
                When(id=post_id, then=position)
                for position, post_id in enumerate(post_ids)
            ],
            output_field=IntegerField(),
        )

        posts = (
            Post.objects
            .filter(id__in=post_ids, is_deleted=False)
            .select_related("author", "author__profile")
            .prefetch_related(
                "images",
                "files",
                "comments",
                "shared_post",
                "hashtags",
                "tagged_users__user",
                "group_context__group",
                "shared_post__original_post",
                "shared_post__original_post__author",
                "shared_post__original_post__author__profile",
                "shared_post__original_post__images",
                "shared_post__original_post__files",
            )
            .annotate(
                reaction_count=Count("reactions", distinct=True),
                comment_count=Count(
                    "comments",
                    filter=Q(comments__is_deleted=False),
                    distinct=True,
                ),
                share_count=Count("shares", distinct=True),
                neo4j_order=preserved_order,
            )
            .order_by("neo4j_order")
        )

        post_list = list(posts)

    if post_list:
        my_reactions = (
            PostReaction.objects
            .filter(user=request.user, post__in=post_list)
            .values_list("post_id", "reaction_type")
        )
        my_reaction_map = {pid: rtype for pid, rtype in my_reactions}
    else:
        my_reaction_map = {}

    for post in post_list:
        post.current_user_reaction = my_reaction_map.get(post.id)
        shares = list(post.shared_post.all())
        post.original_post_obj = shares[0].original_post if shares else None

        # FIX SHARE PRIVACY:
        # Gắn cờ cho template feed biết có được hiện nút share không.
        # Backend vẫn chặn thật ở share_post(), đây chỉ phục vụ UI.
        post.can_share = can_share_post(post)

    rendered_post_ids = [post.id for post in post_list]

    if rendered_post_ids:
        mark_feed_posts_seen(request.user.id, rendered_post_ids)

    if request.GET.get("ajax") == "1":
        # html = render_to_string(
        #     "posts/partials/post_list_chunk.html",
        #     {"posts": post_list, "request": request},
        # )
        html = render_to_string(
            "posts/partials/post_list_chunk.html",
            {"posts": post_list},
            request=request,
        )
        return JsonResponse({
            "html": html,
            "has_next": has_next,
            "post_ids": rendered_post_ids,
        })

    context = {
        "posts": post_list,
        "has_next": has_next,
        "profile": getattr(request.user, "profile", None),
        "post_ids": rendered_post_ids,
    }

    return render(request, "posts/feed.html", context)

def public_feed_view(request):
    """Bảng tin công khai"""
    posts = get_public_feed()
    posts = posts.annotate(
        reaction_count=Count('reactions', distinct=True),
        comment_count=Count('comments', filter=Q(comments__is_deleted=False), distinct=True),
        share_count=Count('shares', distinct=True),
    )
    for post in posts:
        reaction = PostReaction.objects.filter(post=post, user=request.user).first()
        setattr(post, 'current_user_reaction', reaction.reaction_type if reaction else None)
    return render(request, "posts/public_feed.html", {"posts": posts})


def hashtag_feed_view(request, tag):
    """Danh sách bài viết theo hashtag"""
    normalized_tag = (tag or "").strip().lstrip("#").lower()
    hashtag = get_object_or_404(Hashtag, tag=normalized_tag)

    friends_ids = get_friend_ids(request.user)

    personal_posts_q = Q(group_context__isnull=True) & (
        Q(privacy="public") |
        Q(privacy="friends", author__id__in=friends_ids) |
        Q(privacy="only_me", author=request.user)
    )

    group_posts_q = Q(
        group_context__isnull=False,
        group_context__is_deleted=False,
        group_context__status="approved"
    ) & (
        Q(group_context__group__members__user=request.user, group_context__group__members__status="approved") |
        Q(group_context__group__owner=request.user)
    )

    final_filter = (personal_posts_q | group_posts_q) & Q(hashtags=hashtag)

    posts = (
        Post.objects
        .filter(is_deleted=False)
        .filter(final_filter)
        .distinct()
        .select_related("author", "author__profile")
        .prefetch_related(
            "images", "files", "comments", "shared_post",
            "hashtags", "tagged_users__user", "group_context__group",
            "shared_post__original_post", "shared_post__original_post__author",
            "shared_post__original_post__author__profile", "shared_post__original_post__images"
        )
        .annotate(
            reaction_count=Count("reactions", distinct=True),
            comment_count=Count("comments", filter=Q(comments__is_deleted=False), distinct=True),
            share_count=Count("shares", distinct=True),
        )
        .order_by("-created_at")
    )

    paginator = Paginator(posts, 5)
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)

    post_list = list(page_obj.object_list)
    if post_list:
        my_reactions = (
            PostReaction.objects
            .filter(user=request.user, post__in=post_list)
            .values_list("post_id", "reaction_type")
        )
        my_reaction_map = {pid: rtype for pid, rtype in my_reactions}
    else:
        my_reaction_map = {}

    for post in post_list:
        post.current_user_reaction = my_reaction_map.get(post.id)
        shares = list(post.shared_post.all())
        post.original_post_obj = shares[0].original_post if shares else None

        # FIX SHARE PRIVACY:
        # Bài group/friends trong hashtag feed cũng không được hiện share.
        post.can_share = can_share_post(post)

    if request.GET.get("ajax") == "1":
        # html = render_to_string(
        #     "posts/partials/post_list_chunk.html",
        #     {"posts": post_list, "request": request}
        # )
        html = render_to_string(
            "posts/partials/post_list_chunk.html",
            {"posts": post_list},
            request=request,
        )
        return JsonResponse({
            "html": html,
            "has_next": page_obj.has_next()
        })

    return render(request, "posts/feed.html", {
        "hashtag": hashtag,
        "posts": post_list,
        "has_next": page_obj.has_next(),
        "profile": getattr(request.user, "profile", None),
    })

def post_detail_view(request, post_id):
    """Chi tiết bài viết - Đã tích hợp kiểm tra quyền Group & Bạn bè"""
    post = get_object_or_404(
        Post.objects.select_related("author").prefetch_related(
            "images", "files", "tagged_users__user", "hashtags", "reactions"
        ),
        id=post_id,
        is_deleted=False
    )

    # =========================================================
    # CHỐT CHẶN 1: KIỂM TRA QUYỀN GROUP (NẾU BÀI THUỘC GROUP)
    # =========================================================
    group_post = GroupPost.objects.filter(
        post=post, 
        is_deleted=False, 
        status="approved" 
    ).select_related('group').first()

    if group_post:
        group = group_post.group
        
        if not request.user.is_authenticated:
            return HttpResponseForbidden("Bạn cần đăng nhập để xem nội dung của nhóm.")

        is_owner = (group.owner == request.user)
        is_author = (post.author == request.user)
        is_approved_member = GroupMember.objects.filter(
            group=group,
            user=request.user,
            status="approved"
        ).exists()

        if not (is_owner or is_author or is_approved_member):
            return HttpResponseForbidden("Bài viết này thuộc một nhóm kín mà bạn chưa tham gia.")

    # =========================================================
    # CHỐT CHẶN 2: KIỂM TRA QUYỀN PRIVACY CÁ NHÂN (BẠN BÈ)
    # =========================================================
    if post.privacy == "only_me" and post.author != request.user:
        return HttpResponseForbidden("Bài viết riêng tư")
    
    if post.privacy == "friends":
        # Tối ưu: Nếu là tác giả thì không cần query db check bạn bè
        if post.author != request.user:
            is_friend = Friend.objects.filter(
                Q(user=post.author, friend=request.user) | 
                Q(user=request.user, friend=post.author)
            ).exists()
            if not is_friend:
                return HttpResponseForbidden("Chỉ bạn bè mới xem được bài viết này.")

    # =========================================================
    # PHẦN CÒN LẠI GIỮ NGUYÊN (XỬ LÝ COMMENT, REACTION, SHARE)
    # =========================================================
    raw_comments = (
        Comment.objects
        .filter(post=post, is_deleted=False)
        .select_related("user")
        .prefetch_related("images", "files")
        .annotate(likes_count=Count('reactions'))
        .order_by("created_at") 
    )

    from collections import defaultdict
    children_map = defaultdict(list)
    root_comments = []
    
    comment_reactions = CommentReaction.objects.filter(
        comment__post=post, user=request.user
    ).values_list('comment_id', 'reaction_type')
    my_reaction_map = {c_id: r_type for c_id, r_type in comment_reactions}

    for c in raw_comments:
        c.current_reaction = my_reaction_map.get(c.id)
        c.index_px = max(0, (c.level - 1) * 20) 

        if c.parent_id:
            children_map[c.parent_id].append(c)
        else:
            root_comments.append(c)

    sorted_comments = []
    def recursive_add(comment):
        sorted_comments.append(comment)
        children = children_map.get(comment.id, [])
        for child in children:
            recursive_add(child)

    for root in root_comments:
        recursive_add(root)
    
    post_reaction = PostReaction.objects.filter(post=post, user=request.user).first()
    post.current_user_reaction = post_reaction.reaction_type if post_reaction else None

    reaction_counts = PostReaction.objects.filter(post=post).values('reaction_type').annotate(count=Count('id'))
    reaction_breakdown = {item['reaction_type']: item['count'] for item in reaction_counts}

    count_comment = get_comment_count(post)
    report_reaseons = ReportReason.objects.all()

    original_post = None
    share_info = post.shared_post.select_related(
        "original_post",
        "original_post__author"
    ).prefetch_related(
        "original_post__images",
        "original_post__files",
        "original_post__tagged_users",
        "original_post__hashtags",
    ).first()
    if share_info:
        original_post = share_info.original_post

    context = {
        "post": post,
        "group_post": group_post,
        "original_post": original_post,
        "comments": sorted_comments,
        "reaction_breakdown": reaction_breakdown,
        "total_reactions": PostReaction.objects.filter(post=post).count(),
        "total_comments": len(sorted_comments),
        "total_shares": PostShare.objects.filter(original_post=post).count(),
        "count_comment": count_comment,
        "report_reasons": report_reaseons,

        # FIX SHARE PRIVACY:
        # Cho template post_detail biết có được hiện nút/modal share hay không.
        # Backend vẫn chặn cứng trong share_post().
        "can_share_current_post": can_share_post(post),
    }

    #in ra toàn bộ thông tin context để debug
    # print(f"[DEBUG] Post Detail Context: {context}")

    return render(request, "posts/post_detail.html", context)

# =====================================================
# POST CRUD
# =====================================================
def create_post_view(request):
    """Tạo bài viết mới"""
    if request.method == "POST":
        content = request.POST.get("content", "")
        privacy = request.POST.get("privacy", "public")

        images = request.FILES.getlist("images")
        #in ra log để debug
        print(f"[DEBUG] Uploaded images: {images}")
        files = request.FILES.getlist("files")
        tagged = request.POST.getlist("tagged_users")
        location = request.POST.get("location", "")

        result = moderate_text(content)

        if result["blocked"]:

            # tăng violation score
            request.user.violation_score += 1
            request.user.save()

            # save moderation log
            save_moderation_log(
                actor=request.user,
                target_type=ModerationTargetType.POST,
                target_id=0,
                result=result,
                reason="Toxic post content detected"
            )

            return JsonResponse({
                "success": False,
                "error": (
                    "Nội dung chứa từ vi phạm "
                    "tiêu chuẩn cộng đồng."
                ),
                "violations": result["violations"]
            }, status=400)


        try:
            post = create_post(
                user=request.user,
                content=content,
                privacy=privacy,
                images=images,
                files=files,
                tagged_users=tagged,
                location_name=location
            )
        except ValidationError as e:
            return JsonResponse({"error": str(e)}, status=400)

        return redirect("posts:post_detail", post_id=post.id)
    
    # GET request - Show form
    profile, _ = create_user_profile(request.user)
    friends = list_people_tag(request.user)
    for friend in friends:
        create_user_profile(friend)
    return render(request, "posts/create_post.html", {"friends": friends, "profile": profile})

def edit_post_view(request, post_id):
    """Chỉnh sửa bài viết"""
    post = get_object_or_404(Post, id=post_id, is_deleted=False)

    if post.author != request.user:
        return HttpResponseForbidden()

    if request.method == "POST":
        content = request.POST.get("content")
        privacy = request.POST.get("privacy")
        tag_users = request.POST.getlist("tagged_users")
        print(f"[DEBUG] Tagged Users: {tag_users}")
        location = request.POST.get("location", "")
        
        # 1. Lấy file MỚI upload lên
        images = request.FILES.getlist("images")
        files = request.FILES.getlist("files")
        
        # 2. Lấy danh sách ID CŨ cần xóa (quan trọng)
        delete_image_ids = request.POST.getlist("delete_image_ids")
        delete_file_ids = request.POST.getlist("delete_file_ids")

        print(f"[DEBUG] New Images: {images}")
        print(f"[DEBUG] Delete Img IDs: {delete_image_ids}")

        result = moderate_text(content)

        if result["blocked"]:

            request.user.violation_score += 1
            request.user.save()

            save_moderation_log(
                actor=request.user,
                target_type=ModerationTargetType.POST,
                target_id=post.id,
                result=result,
                reason="Toxic post edit detected"
            )

            return JsonResponse({
                "success": False,
                "error": (
                    "Nội dung chỉnh sửa chứa "
                    "từ vi phạm."
                ),
                "violations": result["violations"]
            }, status=400)

        try:
            update_post(
                post,
                content=content,
                privacy=privacy,
                tagged_users=tag_users,
                images=images,
                files=files,
                location_name=location,
                delete_image_ids=delete_image_ids, # Truyền vào service
                delete_file_ids=delete_file_ids    # Truyền vào service
            )
        except ValidationError as e:
            return JsonResponse({"error": str(e)}, status=400)
        return redirect("posts:post_detail", post_id=post.id)
    
    profile, _ = create_user_profile(request.user)
    friends = list_people_tag(request.user)
    for friend in friends:
        create_user_profile(friend)
    #tạo 1 dictionary {id: user} để dễ lookup trong template
    tagged_user_map = {
        tag.user.id: tag.user
        for tag in post.tagged_users.all()
    }
    return render(request, "posts/edit_post.html", {"post": post, "friends": friends, "profile": profile, "tagged_user_map": tagged_user_map})

@require_POST
def delete_post_view(request, post_id):
    """Xóa bài viết"""
    post = get_object_or_404(Post, id=post_id)
    delete_post(request.user, post)
    return redirect("posts:feed")

# =====================================================
# COMMENT CRUD (AJAX/REALTIME)
# =====================================================
@require_POST
def create_comment_view(request, post_id):
    """Tạo bình luận mới - Trả về JSON cho AJAX"""
    post = get_object_or_404(Post, id=post_id, is_deleted=False)
    
    content = request.POST.get("content", "").strip()
    if not content:
        return JsonResponse({"error": "Content is required"}, status=400)
    
    parent_id = request.POST.get("parent_id")
    parent = Comment.objects.filter(id=parent_id).first() if parent_id else None

    images = request.FILES.getlist("images")
    files = request.FILES.getlist("files")

    result = moderate_text(content)

    if result["blocked"]:

        request.user.violation_score += 1
        request.user.save()

        save_moderation_log(
            actor=request.user,
            target_type=ModerationTargetType.POST,
            target_id=post.id,
            result=result,
            reason="Toxic post edit detected"
        )

        return JsonResponse({
            "success": False,
            "error": (
                "Nội dung chỉnh sửa chứa "
                "từ vi phạm."
            ),
            "violations": result["violations"]
        }, status=400)

    try:
        comment = create_comment(
            user=request.user,
            post=post,
            content=content,
            parent=parent,
            images=images,
            files=files
        )
        
        return JsonResponse({
            "status": "ok",
            "comment_id": comment.id,
            "message": "Comment created successfully"
        })
    except ValidationError as e:
        return JsonResponse({"error": str(e)}, status=400)

@require_POST
def edit_comment_view(request, comment_id):
    """Chỉnh sửa bình luận"""
    comment = get_object_or_404(Comment, id=comment_id, is_deleted=False)
    content = request.POST.get("content", "").strip()
    
    if not content:
        return JsonResponse({"error": "Content is required"}, status=400)
    
    result = moderate_text(content)

    if result["blocked"]:

        request.user.violation_score += 1
        request.user.save()

        save_moderation_log(
            actor=request.user,
            target_type=ModerationTargetType.POST,
            target_id=post.id,
            result=result,
            reason="Toxic post edit detected"
        )

        return JsonResponse({
            "success": False,
            "error": (
                "Nội dung chỉnh sửa chứa "
                "từ vi phạm."
            ),
            "violations": result["violations"]
        }, status=400)
    
    try:
        update_comment(request.user, comment, content)
        return JsonResponse({"status": "ok"})
    except PermissionDenied as e:
        return JsonResponse({"error": str(e)}, status=403)

@require_POST
def delete_comment_view(request, comment_id):
    """Xóa bình luận"""
    comment = get_object_or_404(Comment, id=comment_id)
    
    try:
        delete_comment(request.user, comment)
        return JsonResponse({"status": "ok"})
    except PermissionDenied as e:
        return JsonResponse({"error": str(e)}, status=403)

# =====================================================
# REACTION VIEWS (AJAX/REALTIME)
# =====================================================
@require_POST
def toggle_post_reaction_view(request, post_id):
    """Toggle reaction cho bài viết"""
    post = get_object_or_404(Post, id=post_id)
    reaction_type = request.POST.get("reaction", "like")
    
    result = toggle_post_reaction(request.user, post, reaction_type)
    return JsonResponse(result)

@require_POST
def toggle_comment_reaction_view(request, comment_id):
    """Toggle reaction cho bình luận"""
    comment = get_object_or_404(Comment, id=comment_id)
    reaction_type = request.POST.get("reaction", "like")
    
    result = toggle_comment_reaction(request.user, comment, reaction_type)
    return JsonResponse(result)

# =====================================================
# OTHER ACTIONS
# =====================================================
@require_POST
def share_post_view(request, post_id):
    """
    Chia sẻ bài viết.

    FIX SHARE PRIVACY:
    - Không cho share bài thuộc group.
    - Không cho share bài friends.
    - Không cho share bài only_me.
    - Nếu user cố POST thủ công bằng devtools/Postman vẫn bị chặn.
    """
    post_to_share = get_object_or_404(Post, id=post_id, is_deleted=False)
    caption = request.POST.get("caption", "")
    privacy = request.POST.get("privacy", "public")

    try:
        new_post = share_post(
            request.user,
            post_to_share,
            caption=caption,
            privacy=privacy,
        )
    except ValidationError as e:
        if hasattr(e, "messages") and e.messages:
            error_message = e.messages[0]
        else:
            error_message = str(e)

        # Nếu sau này share bằng fetch/ajax thì trả JSON.
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JsonResponse({
                "success": False,
                "error": error_message,
            }, status=403)

        # Nếu là form POST thường thì trả 403.
        return HttpResponseForbidden(error_message)

    return redirect("posts:post_detail", post_id=new_post.id)

@require_POST
def report_view(request):
    """Báo cáo bài viết hoặc bình luận"""
    target_type = request.POST.get("target_type")
    target_id = request.POST.get("target_id")
    reason_id = request.POST.get("reason")
    custom_reason = (request.POST.get("custom_reason", "") or "").strip()
    reporter = request.user

    if not reporter.is_authenticated:
        return JsonResponse({
            "success": False,
            "error": "Bạn cần đăng nhập để báo cáo nội dung."
        }, status=401)

    if reason_id == "custom":
        reason_id = None

    if target_type not in [ReportTargetType.POST, ReportTargetType.COMMENT]:
        return JsonResponse({
            "success": False,
            "error": "Invalid target type"
        }, status=400)

    try:
        target_id_int = int(target_id)
    except (TypeError, ValueError):
        return JsonResponse({
            "success": False,
            "error": "Invalid target ID"
        }, status=400)

    target_post = None
    target_comment = None

    if target_type == ReportTargetType.POST:
        target_post = Post.objects.filter(
            id=target_id_int,
            is_deleted=False
        ).first()

        if not target_post:
            return JsonResponse({
                "success": False,
                "error": "Post not found"
            }, status=404)

    else:
        # FIX QUAN TRỌNG: select_related("post") riêng, filter() riêng
        target_comment = (
            Comment.objects
            .select_related("post")
            .filter(
                id=target_id_int,
                is_deleted=False,
                post__is_deleted=False,
            )
            .first()
        )

        if not target_comment:
            return JsonResponse({
                "success": False,
                "error": "Comment not found"
            }, status=404)

        target_post = target_comment.post

    group_post = (
        GroupPost.objects
        .select_related("group")
        .filter(
            post=target_post,
            is_deleted=False,
            status="approved"
        )
        .first()
    )

    # Case 1: Nội dung thuộc group -> gửi cho admin/owner nhóm xử lý
    if group_post:
        reason_text = custom_reason

        if reason_id:
            reason_obj = ReportReason.objects.filter(id=reason_id).first()
            if not reason_obj:
                return JsonResponse({
                    "success": False,
                    "error": "Report reason not found"
                }, status=404)

            reason_text = reason_obj.name
            if custom_reason:
                reason_text = f"{reason_obj.name}: {custom_reason}"

        if not reason_text:
            return JsonResponse({
                "success": False,
                "error": "Reason is required"
            }, status=400)

        if target_type == ReportTargetType.POST:
            success, message = GroupService.report_content(
                group=group_post.group,
                reporter=reporter,
                reason=reason_text,
                post_id=target_post.id,
            )
        else:
            success, message = GroupService.report_content(
                group=group_post.group,
                reporter=reporter,
                reason=reason_text,
                comment_id=target_comment.id,
            )

        if not success:
            return JsonResponse({
                "success": False,
                "scope": "group",
                "error": message
            }, status=400)

        return JsonResponse({
            "success": True,
            "scope": "group",
            "message": "Đã gửi báo cáo tới quản trị viên nhóm."
        })

    # Case 2: Nội dung không thuộc group -> gửi report hệ thống
    try:
        report_target(
            user=reporter,
            target_type=target_type,
            target_id=target_id_int,
            reason_id=reason_id,
            custom_reason=custom_reason,
        )
    except ValidationError as e:
        return JsonResponse({
            "success": False,
            "scope": "platform",
            "error": str(e)
        }, status=400)
    except Exception as e:
        return JsonResponse({
            "success": False,
            "scope": "platform",
            "error": f"Không thể gửi báo cáo lúc này: {str(e)}"
        }, status=500)

    return JsonResponse({
        "success": True,
        "scope": "platform",
        "message": "Đã gửi báo cáo tới đội ngũ kiểm duyệt."
    })

@require_POST
def toggle_commenting_view(request, post_id):
    """Bật/tắt bình luận cho bài viết"""
    post = get_object_or_404(Post, id=post_id)
    enable = request.POST.get("enable") == "true"
    
    try:
        toggle_comments(post, request.user, enable)
        return JsonResponse({"success": True})
    except PermissionDenied as e:
        return JsonResponse({"error": str(e)}, status=403)

@require_POST
def toggle_hide_counts_view(request, post_id):
    """Ẩn/hiện số lượng reactions và comments"""
    post = get_object_or_404(Post, id=post_id)
    hide_comment = request.POST.get("hide_comment")
    hide_reaction = request.POST.get("hide_reaction")

    try:
        toggle_hide_counts(
            post,
            request.user,
            hide_comment=hide_comment == "true" if hide_comment else None,
            hide_reaction=hide_reaction == "true" if hide_reaction else None,
        )
        return JsonResponse({"success": True})
    except PermissionDenied as e:
        return JsonResponse({"error": str(e)}, status=403)
