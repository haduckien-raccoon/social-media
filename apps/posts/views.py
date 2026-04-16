from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse, HttpResponseForbidden
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.db.models import Count, Q
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

def feed_view(request):
    """
    Bảng tin cá nhân (Lazy Loading)
    Đã fix logic chuẩn xác: 
    - Không chung nhóm -> Không thấy bài nhóm.
    - Không kết bạn -> Không thấy bài friends (nhưng vẫn thấy bài nhóm nếu chung nhóm).
    """
    # 1. Lấy danh sách ID bạn bè
    friends_ids = get_friend_ids(request.user)

    # ==========================================
    # LUỒNG 1: BÀI VIẾT CÁ NHÂN (Ngoài tường nhà)
    # ==========================================
    # Điều kiện: KHÔNG thuộc nhóm NÀO + Thỏa mãn quyền riêng tư
    personal_posts_q = Q(group_context__isnull=True) & (
        Q(privacy="public") | 
        Q(privacy="friends", author__id__in=friends_ids) | 
        Q(privacy="only_me", author=request.user)
    )

    # ==========================================
    # LUỒNG 2: BÀI VIẾT NHÓM
    # ==========================================
    # Điều kiện: THUỘC nhóm + Đã duyệt + User đang xem là thành viên hợp lệ HOẶC chủ nhóm
    # (Bỏ qua check bạn bè ở đây, vì đã chung nhóm là thấy bài)
    group_posts_q = Q(
        group_context__isnull=False,
        group_context__is_deleted=False,
        group_context__status="approved"
    ) & (
        Q(group_context__group__members__user=request.user, group_context__group__members__status="approved") |
        Q(group_context__group__owner=request.user)
    )

    # Gộp 2 luồng lại: Lấy bài cá nhân hợp lệ HOẶC bài nhóm hợp lệ
    final_feed_filter = personal_posts_q | group_posts_q

    # ==========================================
    # KẾT HỢP QUERY TỔNG (1 QUERY DUY NHẤT)
    # ==========================================
    posts = (
        Post.objects
        .filter(is_deleted=False)
        .filter(final_feed_filter)
        .distinct()  # Bắt buộc có distinct() vì ta có JOIN với bảng GroupMember (Many-to-Many)
        .select_related("author", "author__profile")
        .prefetch_related(
            "images", "files", "comments", "shared_post", 
            "shared_post__original_post", "shared_post__original_post__author",
            "shared_post__original_post__author__profile", "shared_post__original_post__images"
        )
        .annotate(
            reaction_count=Count("reactions", distinct=True),
            comment_count=Count("comments", filter=Q(comments__is_deleted=False), distinct=True)
        )
        .order_by("-created_at")
    )

    # ==========================================
    # CẮT NHỎ DỮ LIỆU (PAGINATION)
    # ==========================================
    paginator = Paginator(posts, 5) # Trả về 5 bài mỗi lần cuộn
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    post_list = list(page_obj.object_list)

    # ==========================================
    # XỬ LÝ REACTION CHO NGƯỜI DÙNG HIỆN TẠI
    # ==========================================
    if post_list:
        my_reactions = (
            PostReaction.objects
            .filter(user=request.user, post__in=post_list)
            .values_list("post_id", "reaction_type")
        )
        my_reaction_map = {pid: rtype for pid, rtype in my_reactions}
    else:
        my_reaction_map = {}

    # Gán dữ liệu bổ sung
    for post in post_list:
        post.current_user_reaction = my_reaction_map.get(post.id)
        shares = list(post.shared_post.all())
        post.original_post_obj = shares[0].original_post if shares else None

    # ==========================================
    # TRẢ VỀ DỮ LIỆU (AJAX CHO LAZY LOAD HOẶC LOAD LẦN ĐẦU)
    # ==========================================
    if request.GET.get('ajax') == '1':
        html = render_to_string(
            "posts/partials/post_list_chunk.html", 
            {"posts": post_list, "request": request}
        )
        return JsonResponse({
            "html": html,
            "has_next": page_obj.has_next() 
        })

    context = {
        "posts": post_list,
        "has_next": page_obj.has_next(), 
        "profile": getattr(request.user, "profile", None),
    }

    return render(request, "posts/feed.html", context)


def public_feed_view(request):
    """Bảng tin công khai"""
    posts = get_public_feed()
    posts = posts.annotate(
        reaction_count=Count('reactions', distinct=True),
        comment_count=Count('comments', filter=Q(comments__is_deleted=False), distinct=True)
    )
    for post in posts:
        reaction = PostReaction.objects.filter(post=post, user=request.user).first()
        setattr(post, 'current_user_reaction', reaction.reaction_type if reaction else None)
    return render(request, "posts/public_feed.html", {"posts": posts})

def post_detail_view(request, post_id):
    """Chi tiết bài viết - Đã tích hợp kiểm tra quyền Group & Bạn bè"""
    post = get_object_or_404(
        Post.objects.select_related("author").prefetch_related(
            "images", "files", "tagged_users", "hashtags", "reactions"
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
        "group_post": group_post, # Truyền ra context để HTML biết bài này ở group nào (nếu cần hiển thị tên nhóm)
        "original_post": original_post,
        "comments": sorted_comments, 
        "reaction_breakdown": reaction_breakdown,
        "total_reactions": PostReaction.objects.filter(post=post).count(),
        "total_comments": len(sorted_comments),
        "count_comment": count_comment,
        "report_reasons": report_reaseons,
    }

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

        post = create_post(
            user=request.user,
            content=content,
            privacy=privacy,
            images=images,
            files=files,
            tagged_users=tagged,
            location_name=location
        )

        return redirect("posts:post_detail", post_id=post.id)
    
    # GET request - Show form
    friends = list_people_tag(request.user)
    profile = request.user.profile
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
        return redirect("posts:post_detail", post_id=post.id)
    
    friends = list_people_tag(request.user)
    profile = request.user.profile
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
    """Chia sẻ bài viết"""
    original_post = get_object_or_404(Post, id=post_id)
    caption = request.POST.get("caption", "")
    privacy = request.POST.get("privacy", "public")

    new_post = share_post(request.user, original_post, caption, privacy)
    return redirect("posts:post_detail", post_id=new_post.id)

@require_POST
def report_view(request):
    """Báo cáo bài viết hoặc bình luận"""
    target_type = request.POST.get("target_type")
    target_id = request.POST.get("target_id")
    reason_id = request.POST.get("reason")
    custom_reason = request.POST.get("custom_reason", "")
    reporter = request.user

    #in ra log để debug
    print(f"[DEBUG] Report - Type: {target_type}, ID: {target_id}, Reason: {reason_id}, Custom: {custom_reason}, Reporter: {reporter}")

    report_target(
        user=reporter,
        target_type=target_type,
        target_id=target_id,
        reason_id=reason_id,
        custom_reason=custom_reason
    )
    return JsonResponse({"success": True})

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
