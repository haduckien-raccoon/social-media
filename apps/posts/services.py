from django.db import transaction
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone
from django.db.models import Q, Count
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from apps.accounts.models import User
from apps.friends.models import Friend
from apps.posts.models import *
from apps.notifications.services import create_notification

# =====================================================
# 1. WEBSOCKET HELPER - REALTIME BROADCAST
# =====================================================
def send_ws_message(group_name, message_type, data):
    """
    Hàm tiện ích để gửi tin nhắn xuống WebSocket channel
    
    Args:
        group_name: Tên group (vd: "feed_global", "post_123")
        message_type: Loại event (vd: "feed_update", "post_event")
        data: Dictionary chứa dữ liệu cần gửi
    """
    channel_layer = get_channel_layer()
    if channel_layer:
        async_to_sync(channel_layer.group_send)(
            group_name,
            {
                "type": message_type,
                "data": data
            }
        )

# =====================================================
# 2. VALIDATION HELPERS
# =====================================================
def require_owner(user, obj):
    """Kiểm tra quyền sở hữu"""
    if obj.author != user:
        raise PermissionDenied("You do not have permission to perform this action.")

def ensure_comment_enable(post):
    """Kiểm tra bài viết có cho phép comment không"""
    if not post.is_comment_enabled:
        raise ValidationError("Comments are disabled for this post.")

# =====================================================
# 3. READ DATA HELPERS
# =====================================================
def get_friend_ids(user):
    """Lấy danh sách ID bạn bè của user"""
    friend_ids = Friend.objects.filter(
        Q(friend_id=user.id) | Q(user_id=user.id)
    ).values_list('friend_id', 'user_id')
    
    friend_ids_set = set()
    for u1, u2 in friend_ids:
        if u1 != user.id:
            friend_ids_set.add(u1)
        if u2 != user.id:
            friend_ids_set.add(u2)
    return list(friend_ids_set)

def get_public_feed():
    """Lấy bảng tin công khai"""
    return Post.objects.filter(
        privacy="public",
        is_deleted=False
    ).select_related('author').prefetch_related('images', 'reactions').order_by('-created_at')

def get_user_feed(user, friends_ids):
    """Lấy bảng tin cá nhân (public + friends + own)"""
    return Post.objects.filter(
        is_deleted=False
    ).filter(
        Q(privacy="public") |
        Q(privacy="friends", author__id__in=friends_ids) |
        Q(privacy="only_me", author=user)
    ).select_related('author').prefetch_related('images', 'reactions').order_by('-created_at')

def get_avatar_url(user):
    """Lấy URL avatar của user"""
    if hasattr(user, "profile") and user.profile.avatar:
        return user.profile.avatar.url
    return f"https://ui-avatars.com/api/?name={user.username}"


def _get_post_author_and_tagged_recipient_ids(post, actor_user):
    recipient_ids = {post.author_id}
    tagged_user_ids = set(
        PostTagUser.objects.filter(post=post).values_list("user_id", flat=True)
    )
    recipient_ids.update(tagged_user_ids)
    recipient_ids.discard(actor_user.id)
    return recipient_ids, tagged_user_ids


def _build_post_stats_payload(post, *, reaction_count=None, comment_count=None, share_count=None):
    if reaction_count is None:
        reaction_count = PostReaction.objects.filter(post=post).count()
    if comment_count is None:
        comment_count = Comment.objects.filter(post=post, is_deleted=False).count()
    if share_count is None:
        share_count = PostShare.objects.filter(original_post=post).count()

    return {
        "reaction_count": reaction_count,
        "comment_count": comment_count,
        "share_count": share_count,
    }

# =====================================================
# 4. POST WRITE LOGIC (REALTIME)
# =====================================================
@transaction.atomic
def create_post(
    *,
    user,
    content,
    privacy="public",
    images=None,
    files=None,
    tagged_users=None,
    hashtags=None,
    location_name=None,
):
    """
    Tạo bài viết mới và broadcast realtime
    """
    normalized_content = content.strip() if content else ""
    image_list = list(images or [])
    file_list = list(files or [])
    if not normalized_content and not image_list and not file_list:
        raise ValidationError("Post must include content, images, or files.")

    valid_privacies = {choice[0] for choice in PostPrivacy.choices}
    if privacy not in valid_privacies:
        raise ValidationError("Invalid privacy value.")

    # 1. Tạo Post (DB)
    post = Post.objects.create(
        author=user,
        content=normalized_content,
        privacy=privacy,
    )

    # 2. Xử lý Images
    if image_list:
        for order, image in enumerate(image_list):
            PostImage.objects.create(post=post, image=image, order=order)

    # 3. Xử lý Files
    if file_list:
        for file in file_list:
            PostFile.objects.create(post=post, file=file, filename=file.name)

    # 4. Tagged users
    tagged_user_ids = set()
    if tagged_users:
        for uid in tagged_users:
            try:
                uid_int = int(uid)
            except (TypeError, ValueError):
                continue
            is_friend = Friend.objects.filter(
                Q(user=user, friend_id=uid_int) | Q(user_id=uid_int, friend=user)
            ).exists()
            if is_friend:
                PostTagUser.objects.get_or_create(post=post, user_id=uid_int)
                tagged_user_ids.add(uid_int)

    # 5. Hashtags
    if hashtags:
        add_hashtags(post, hashtags)

    # 6. Location
    if location_name:
        add_location(post, location_name, 0.0, 0.0)

    # 7. 🚀 REALTIME BROADCAST - Thông báo có bài viết mới
    send_ws_message("feed_global", "feed_update", {
        "action": "new_post",
        "post_id": post.id,
        "author": user.username,
        "avatar": get_avatar_url(user),
        "content": post.content[:100] + "..." if len(post.content) > 100 else post.content,
        "created_at": "Vừa xong"
    })

    # 8. Notifications for tagged users
    for tagged_user_id in tagged_user_ids:
        if tagged_user_id == user.id:
            continue
        tagged_user = User.objects.filter(id=tagged_user_id).first()
        if not tagged_user:
            continue
        create_notification(
            actor=user,
            recipient=tagged_user,
            verb_code="mention_in_post",
            target=post,
            link=f"/posts/{post.id}/",
        )

    return post

@transaction.atomic
def update_post(
    post, 
    content=None, 
    privacy=None, 
    tagged_users=None, 
    images=None, 
    files=None, 
    location_name=None,
    delete_image_ids=None,
    delete_file_ids=None
):
    """Cập nhật bài viết"""
    original_tagged_user_ids = set(
        PostTagUser.objects.filter(post=post).values_list("user_id", flat=True)
    )
    
    # 1. Update Basic Info
    if content is not None:
        post.content = content.strip()
    if privacy is not None:
        valid_privacies = {choice[0] for choice in PostPrivacy.choices}
        if privacy not in valid_privacies:
            raise ValidationError("Invalid privacy value.")
        post.privacy = privacy
    
    # 2. Update Tags
    final_tagged_user_ids = set()
    if tagged_users is not None:
        valid_user_ids = set()
        for uid in tagged_users:
            try:
                uid_int = int(uid)
                valid_user_ids.add(uid_int)
            except (ValueError, TypeError):
                continue

        existing_user_ids = set(
            User.objects.filter(id__in=valid_user_ids).values_list("id", flat=True)
        )

        for uid in existing_user_ids:
            is_friend = Friend.objects.filter(
                Q(user=post.author, friend_id=uid) | Q(user_id=uid, friend=post.author)
            ).exists()
            if is_friend:
                final_tagged_user_ids.add(uid)

        PostTagUser.objects.filter(post=post).exclude(user_id__in=final_tagged_user_ids).delete()
        for uid in final_tagged_user_ids:
            PostTagUser.objects.get_or_create(post=post, user_id=uid)

    # 3. Update Images
    if delete_image_ids:
        PostImage.objects.filter(post=post, id__in=delete_image_ids).delete()

    if images:
        current_count = PostImage.objects.filter(post=post).count()
        for i, image in enumerate(images):
            PostImage.objects.create(post=post, image=image, order=current_count + i)

    # 4. Update Files
    if delete_file_ids:
        PostFile.objects.filter(post=post, id__in=delete_file_ids).delete()
    
    if files:
        for file in files:
            PostFile.objects.create(post=post, file=file, filename=file.name)

    # 5. Update Location
    if location_name is not None:
        if location_name == "":
            remove_location(post)
        else:
            add_location(post, location_name, 0.0, 0.0)

    post.updated_at = timezone.now()
    post.save()

    if tagged_users is not None:
        new_tagged_user_ids = final_tagged_user_ids - original_tagged_user_ids
        for tagged_user_id in new_tagged_user_ids:
            if tagged_user_id == post.author_id:
                continue
            tagged_user = User.objects.filter(id=tagged_user_id).first()
            if not tagged_user:
                continue
            create_notification(
                actor=post.author,
                recipient=tagged_user,
                verb_code="mention_in_post",
                target=post,
                link=f"/posts/{post.id}/",
            )
    
    send_ws_message(f"post_{post.id}", "post_event", {
        "event": "post_updated",
        "post_id": post.id,
        "content": post.content,
        "privacy": post.privacy
    })
    
    return post

def delete_post(user, post):
    """Xóa bài viết (soft delete)"""
    require_owner(user, post)
    post.soft_delete()
    
    # Realtime broadcast
    send_ws_message(f"post_{post.id}", "post_event", {
        "event": "post_deleted",
        "post_id": post.id
    })

@transaction.atomic
def share_post(user, post_to_share, caption="", privacy="public"):
    """
    Share bài viết
    - Share bài gốc → original_post = bài đó
    - Share bài share → original_post = bài gốc
    """

    # 1. Chuẩn hoá bài gốc (ROOT POST)
    if hasattr(post_to_share, "shared_post") and post_to_share.shared_post.exists():
        # post_to_share là bài share → lấy bài gốc
        original_post = post_to_share.shared_post.first().original_post
    else:
        # post_to_share là bài gốc
        original_post = post_to_share

    # 2. Tạo post mới (post share)
    new_post = Post.objects.create(
        author=user,
        content=caption,
        privacy=privacy,
    )

    # 3. Ghi PostShare
    PostShare.objects.create(
        user=user,
        original_post=original_post,
        new_post=new_post,
        caption=caption,
        privacy=privacy,
    )

    create_notification(
        actor=user,
        recipient=original_post.author,
        verb_code="share_post",
        target=original_post,
        link=f"/posts/{original_post.id}/",
    )

    post_stats = _build_post_stats_payload(original_post)
    send_ws_message(f"post_{original_post.id}", "post_event", {
        "event": "share_updated",
        "post_id": original_post.id,
        **post_stats,
    })
    send_ws_message("feed_global", "feed_update", {
        "action": "post_stats",
        "post_id": original_post.id,
        **post_stats,
    })

    return new_post


# =====================================================
# 5. COMMENT WRITE LOGIC (REALTIME)
# =====================================================
def create_comment(user, post, content, parent=None, images=None, files=None):
    """
    Tạo bình luận mới và broadcast realtime
    """
    ensure_comment_enable(post)

    if parent:
        if parent.post != post:
            raise ValidationError("Parent comment must belong to the same post.")
        if parent.level >= 7:
            raise ValidationError("Max comment depth is 7.")

    # 1. Lưu DB
    comment = Comment.objects.create(
        user=user,
        post=post,
        parent=parent,
        content=content
    )

    # 2. Xử lý images
    img_urls = []
    if images:
        for i, img in enumerate(images):
            obj = CommentImage.objects.create(comment=comment, image=img, order=i)
            img_urls.append(obj.image.url)

    # 3. Xử lý files
    file_urls = []
    if files:
        for f in files:
            obj = CommentFile.objects.create(comment=comment, file=f, filename=f.name)
            file_urls.append({"url": obj.file.url, "name": obj.filename})

    post_stats = _build_post_stats_payload(post)

    # 4. 🚀 REALTIME BROADCAST
    send_ws_message(f"post_{post.id}", "post_event", {
        "event": "comment_new",
        "post_id": post.id,
        "comment_id": comment.id,
        "content": comment.content,
        "user": user.username,
        "user_id": user.id,
        "avatar": get_avatar_url(user),
        "created_at": "Vừa xong",
        "parent_id": parent.id if parent else None,
        "level": comment.level,
        "images": img_urls,
        "files": file_urls,
        "comment_count": post_stats["comment_count"],
    })
    send_ws_message("feed_global", "feed_update", {
        "action": "post_stats",
        "post_id": post.id,
        **post_stats,
    })

    recipient_ids, tagged_user_ids = _get_post_author_and_tagged_recipient_ids(post, user)
    if recipient_ids:
        recipients_by_id = User.objects.in_bulk(recipient_ids)
        for recipient_id in recipient_ids:
            recipient_user = recipients_by_id.get(recipient_id)
            if not recipient_user:
                continue

            custom_verb_text = ""
            if recipient_id in tagged_user_ids and recipient_id != post.author_id:
                custom_verb_text = (
                    f"{user.username} commented on a post that mentioned you: "
                    f"'{comment.content[:80]}'"
                )

            create_notification(
                actor=user,
                recipient=recipient_user,
                verb_code="comment_post",
                target=post,
                link=f"/posts/{post.id}/",
                verb_text=custom_verb_text,
            )

    if parent and parent.user_id != user.id:
        create_notification(
            actor=user,
            recipient=parent.user,
            verb_code="reply_comment",
            target=parent,
            link=f"/posts/{post.id}/",
        )

    return comment

def update_comment(user, comment, content):
    """Cập nhật nội dung bình luận"""
    if comment.user != user:
        raise PermissionDenied()
    
    comment.content = content
    comment.save(update_fields=["content", "updated_at"])

    # 🚀 Realtime Update
    send_ws_message(f"post_{comment.post.id}", "post_event", {
        "event": "comment_updated",
        "comment_id": comment.id,
        "content": content
    })

def delete_comment(user, comment):
    """Xóa bình luận và toàn bộ bình luận con (cascade soft delete)"""
    # 1. Kiểm tra quyền (Chủ comment hoặc Chủ bài viết mới được xóa)
    if comment.user != user and comment.post.author != user:
        raise PermissionDenied("Bạn không có quyền xóa bình luận này.")
    
    post_id = comment.post.id
    
    # Danh sách lưu các ID sẽ bị xóa (để gửi socket cho FE cập nhật UI)
    deleted_ids = []

    # 2. Hàm đệ quy để tìm và xóa con cháu
    def recursive_soft_delete(cmt):
        # Tìm các comment con trực tiếp
        child_comments = Comment.objects.filter(parent=cmt)
        
        # Đệ quy xuống các cấp sâu hơn trước
        for child in child_comments:
            recursive_soft_delete(child)
            
        # Sau khi xử lý con, xóa chính nó
        # (Kiểm tra nếu chưa xóa thì mới xóa để tránh lặp)
        if not cmt.is_deleted:
            cmt.soft_delete()
            deleted_ids.append(cmt.id)

    # 3. Thực thi xóa
    with transaction.atomic():
        recursive_soft_delete(comment)

    post_stats = _build_post_stats_payload(comment.post)

    # 4. 🚀 Realtime Delete
    # Gửi danh sách toàn bộ ID bị xóa để Frontend ẩn đi
    send_ws_message(f"post_{post_id}", "post_event", {
        "event": "comment_deleted",
        "comment_id": comment.id,         # ID chính bị click xóa
        "deleted_ids": deleted_ids,       # Danh sách tất cả ID bị ảnh hưởng (bao gồm con)
        "comment_count": post_stats["comment_count"],
    })
    send_ws_message("feed_global", "feed_update", {
        "action": "post_stats",
        "post_id": post_id,
        **post_stats,
    })

# =====================================================
# 6. REACTION LOGIC (REALTIME)
# =====================================================
def toggle_post_reaction(user, post, reaction_type):
    """
    Toggle reaction cho bài viết (Like, Love, Haha, Sad, Angry)
    Trả về: status (added/removed/changed), current_type, total_count
    """
    valid_reactions = {choice[0] for choice in ReactionType.choices}
    if reaction_type not in valid_reactions:
        raise ValidationError("Invalid reaction type.")

    with transaction.atomic():
        reaction = PostReaction.objects.filter(user=user, post=post).select_for_update().first()
        status = "added"
        current_type = reaction_type

        if reaction:
            if reaction.reaction_type == reaction_type:
                # Remove reaction
                reaction.delete()
                status = "removed"
                current_type = None
            else:
                # Change reaction type
                reaction.reaction_type = reaction_type
                reaction.save()
                status = "changed"
        else:
            # Add new reaction
            PostReaction.objects.create(user=user, post=post, reaction_type=reaction_type)

        # Đếm tổng reactions
        total_count = PostReaction.objects.filter(post=post).count()
        
        # Đếm từng loại reaction
        reaction_counts = PostReaction.objects.filter(post=post).values('reaction_type').annotate(count=Count('id'))
        reaction_breakdown = {item['reaction_type']: item['count'] for item in reaction_counts}

    post_stats = _build_post_stats_payload(post, reaction_count=total_count)

    # 🚀 REALTIME BROADCAST
    send_ws_message(f"post_{post.id}", "post_event", {
        "event": "reaction",
        "post_id": post.id,
        "status": status,
        "user": user.username,
        "user_id": user.id,
        "reaction_type": current_type,
        "total_count": total_count,
        "breakdown": reaction_breakdown,
        "comment_count": post_stats["comment_count"],
        "share_count": post_stats["share_count"],
    })
    send_ws_message("feed_global", "feed_update", {
        "action": "post_stats",
        "post_id": post.id,
        **post_stats,
    })

    if current_type:
        recipient_ids, tagged_user_ids = _get_post_author_and_tagged_recipient_ids(post, user)
        if recipient_ids:
            recipients_by_id = User.objects.in_bulk(recipient_ids)
            for recipient_id in recipient_ids:
                recipient_user = recipients_by_id.get(recipient_id)
                if not recipient_user:
                    continue

                custom_verb_text = ""
                if recipient_id in tagged_user_ids and recipient_id != post.author_id:
                    custom_verb_text = (
                        f"{user.username} reacted to a post that mentioned you "
                        f"({current_type})."
                    )

                create_notification(
                    actor=user,
                    recipient=recipient_user,
                    verb_code="react_post",
                    target=post,
                    reaction_type=current_type,
                    link=f"/posts/{post.id}/",
                    verb_text=custom_verb_text,
                )
    
    return {"status": status, "total_count": total_count}

def toggle_comment_reaction(user, comment, reaction_type):
    """
    Toggle reaction cho bình luận
    """
    valid_reactions = {choice[0] for choice in ReactionType.choices}
    if reaction_type not in valid_reactions:
        raise ValidationError("Invalid reaction type.")

    with transaction.atomic():
        reaction = CommentReaction.objects.filter(user=user, comment=comment).select_for_update().first()
        status = "added"
        current_type = reaction_type

        if reaction:
            if reaction.reaction_type == reaction_type:
                reaction.delete()
                status = "removed"
                current_type = None
            else:
                reaction.reaction_type = reaction_type
                reaction.save()
                status = "changed"
        else:
            CommentReaction.objects.create(user=user, comment=comment, reaction_type=reaction_type)

        count = CommentReaction.objects.filter(comment=comment).count()

    # 🚀 REALTIME BROADCAST
    send_ws_message(f"post_{comment.post.id}", "post_event", {
        "event": "comment_reaction",
        "comment_id": comment.id,
        "status": status,
        "user": user.username,
        "user_id": user.id,
        "reaction_type": current_type,
        "count": count
    })

    if current_type:
        create_notification(
            actor=user,
            recipient=comment.user,
            verb_code="react_comment",
            target=comment,
            reaction_type=current_type,
            link=f"/posts/{comment.post.id}/",
        )
    
    return {"status": status, "count": count}

# =====================================================
# 7. UTILS
# =====================================================
def toggle_comments(post, user, enable: bool):
    """Bật/tắt bình luận cho bài viết"""
    if post.author != user:
        raise PermissionDenied()
    post.is_comment_enabled = enable
    post.save(update_fields=["is_comment_enabled"])
    return post

def toggle_hide_counts(post, user, hide_comment=None, hide_reaction=None):
    """Ẩn/hiện số lượng bình luận và reaction"""
    if post.author != user:
        raise PermissionDenied()
    if hide_comment is not None:
        post.hide_comment_count = hide_comment
    if hide_reaction is not None:
        post.hide_reaction_count = hide_reaction
    post.save()
    return post

def report_target(user, target_type, target_id, reason_id=None, custom_reason=""):
    """Báo cáo bài viết hoặc bình luận"""
    reason = None
    if reason_id:
        reason = ReportReason.objects.filter(id=reason_id).first()
    report = Report.objects.create(
        reporter=user,
        target_type=target_type,
        target_id=target_id,
        reason=reason,
        custom_reason=custom_reason
    )
    return report

def tag_user(post, user):
    """Tag người dùng vào bài viết"""
    tag, created = PostTagUser.objects.get_or_create(post=post, user=user)
    return tag

def un_tag_user(post, user):
    """Bỏ tag người dùng"""
    tag = PostTagUser.objects.filter(post=post, user=user)
    tag.delete()

def add_hashtags(post, hashtags):
    """Thêm hashtags cho bài viết"""
    for raw_tag in hashtags:
        tag = raw_tag.strip().lower().lstrip("#")
        if not tag:
            continue
        hashtag, _ = Hashtag.objects.get_or_create(tag=tag)
        PostHashtag.objects.get_or_create(post=post, hashtag=hashtag)

def remove_hashtags(post, hashtags):
    """Xóa hashtags khỏi bài viết"""
    for tag in hashtags:
        hashtag = Hashtag.objects.filter(tag=tag).first()
        if hashtag:
            PostHashtag.objects.filter(post=post, hashtag=hashtag).delete()

def add_location(post, name, lat, lng):
    """Thêm vị trí cho bài viết"""
    if hasattr(post, 'location'):
        post.location.delete()
    location = Location.objects.create(post=post, name=name, latitude=lat, longitude=lng)
    return location

def remove_location(post):
    """Xóa vị trí khỏi bài viết"""
    if hasattr(post, 'location'):
        post.location.delete()

def list_people_tag(user):
    """Liệt kê bạn bè để tag vào bài viết"""
    friend_ids = get_friend_ids(user)
    if not friend_ids:
        return []
    return list(User.objects.filter(id__in=friend_ids))

#lấy  các user đã tag trong post
def get_tagged_users(post):
    """Lấy danh sách người dùng đã được tag trong bài viết"""
    tagged_users = PostTagUser.objects.filter(post=post).select_related('user')
    return [tag.user for tag in tagged_users]

def get_comment_count(post):
    """Lấy số lượng bình luận của bài viết"""
    return Comment.objects.filter(post=post, is_deleted=False).count()

def get_my_posts(user):
    """Lấy tất cả bài viết của user"""
    posts =  Post.objects.filter(author=user, is_deleted=False).order_by('-created_at')
    #Lọc các bài post không nằm trong group (vì group = private))
    posts = posts.exclude(group_context__isnull=False)
    #nếu là post là bài share thì lấy ảnh của bài gốc
    for post in posts:
        if hasattr(post, "shared_post") and post.shared_post.exists():
            original_post = post.shared_post.first().original_post
            post.image = original_post.images.first().image if original_post.images.exists() else None
        else:
            post.image = post.images.first().image if post.images.exists() else None
    return posts

def get_user_posts(viewer, profile_user, friends_ids):
    """Lấy bài viết của một user khác dựa trên quyền riêng tư"""
    posts = Post.objects.filter(
        author=profile_user,
        is_deleted=False
    ).filter(
        Q(privacy="public") |
        Q(privacy="friends", author__id__in=friends_ids) |
        Q(privacy="only_me", author=viewer)
    ).select_related('author').prefetch_related('images', 'reactions').order_by('-created_at')
    #Lọc các bài post không nằm trong group (vì group = private))
    posts = posts.exclude(group_context__isnull=False)
    #nếu là post là bài share thì lấy ảnh của bài gốc
    for post in posts:
        if hasattr(post, "shared_post") and post.shared_post.exists():
            original_post = post.shared_post.first().original_post
            post.image = original_post.images.first().image if original_post.images.exists() else None
        else:
            post.image = post.images.first().image if post.images.exists() else None
    return posts



