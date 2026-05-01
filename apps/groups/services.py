from django.shortcuts import get_object_or_404

from apps.groups.models import *
from apps.posts.services import *
from apps.posts.models import *
from apps.accounts.models import User
from apps.notifications.services import create_notification
from django.core.paginator import Paginator, EmptyPage
from django.db.models import Case, Case, Count, Q, IntegerField, IntegerField, Max, Value, When, When
from django.utils import timezone
from django.db.models import Prefetch


def approve_group_post(group_post: GroupPost, approver: User):
    group_post.status = 'approved'
    group_post.approved_by = approver
    group_post.approved_at = timezone.now()
    group_post.save()

class GroupService:
    @staticmethod
    def get_group_by_id(group_id):
        return get_object_or_404(Group, id=group_id, is_activate=True)
    @staticmethod
    def get_user_role(user, group):
        if group.owner == user:
            return GroupRole.OWNER
        try:
            member = GroupMember.objects.get(group=group, user=user)
            if member.status == "approved":
                return member.role
            elif member.status == "pending":
                return "pending"
            else:
                return "none"
        except GroupMember.DoesNotExist:
            return "none"
    @staticmethod
    def get_group_feed(group, user, page=1, page_size=10):
        """
        Lấy danh sách bài viết trong nhóm dựa trên cài đặt default_sort của nhóm.
        Lấy danh sách bài viết trong nhóm theo từng trang.
        Trả về (posts_list, has_next_page)
        """
        group_posts_qs = GroupPost.objects.filter(
            group=group,
            is_deleted=False,
            post__is_deleted=False,
            status="approved"
        ).select_related(
            'post', 'post__author'
        ).prefetch_related(
            'post__images'
        ).annotate(
            reaction_count=Count('post__reactions', distinct=True),
            comment_count=Count(
                'post__comments',
                filter=Q(post__comments__is_deleted=False),
                distinct=True
            ),
            latest_comment_time=Max('post__comments__created_at')
        )
        # .order_by('-is_pinned', '-post__created_at')

        # Xử lý Sắp xếp dựa trên Cài đặt nhóm
        if group.default_sort == GroupSortChoices.NEWEST:
            # Bài viết mới: Mới đăng lên đầu tiên
            group_posts_qs = group_posts_qs.order_by('-is_pinned', '-post__created_at')
            
        elif group.default_sort == GroupSortChoices.LATEST_ACTIVITY:
            # Hoạt động mới nhất: Có bình luận mới thì đẩy lên đầu, nếu không có bình luận thì lấy ngày tạo bài viết
            # (PostgreSQL/MySQL có thể dùng Coalesce để gộp, ở đây Django sắp xếp linh hoạt)
            group_posts_qs = group_posts_qs.order_by('-is_pinned', '-latest_comment_time', '-post__created_at')
            
        else: # RELEVANT (Phù hợp nhất)
            # Nếu hệ thống bạn chưa có models Friend rõ ràng, tạm thời lùi về LATEST_ACTIVITY
            # Nếu có bảng Friend, bạn có thể annotate thêm: is_friend = Case(When(post__author__in=user_friends, then=1), default=0)
            group_posts_qs = group_posts_qs.order_by('-is_pinned', '-latest_comment_time', '-post__created_at')

        # Phân trang QuerySet
        paginator = Paginator(group_posts_qs, page_size)
        try:
            group_posts_page = paginator.page(page)
        except EmptyPage:
            return [], False # Nếu request trang không tồn tại, trả về rỗng

        # Ép kiểu page object về list để query và xử lý
        group_posts_list = list(group_posts_page.object_list)

        # Lấy Reaction của User (Chỉ lấy cho số bài viết trên trang hiện tại -> Tối ưu cực mạnh)
        user_reactions_dict = {}
        if user.is_authenticated and group_posts_list:
            post_ids = [gp.post_id for gp in group_posts_list]
            reactions = PostReaction.objects.filter(user=user, post_id__in=post_ids)
            user_reactions_dict = {r.post_id: r.reaction_type for r in reactions}

        # Đổ dữ liệu
        posts = []
        for gp in group_posts_list:
            post = gp.post
            post.is_pinned = gp.is_pinned
            post.reaction_count = gp.reaction_count
            post.comment_count = gp.comment_count
            post.current_user_reaction = user_reactions_dict.get(post.id)
            
            posts.append(post)

        return posts, group_posts_page.has_next()
    
    @staticmethod
    def create_group(owner, name, description="",is_private=True):
        group = Group.objects.create(
            owner=owner,
            name=name,
            description=description,
            is_private=is_private
        )
        GroupMember.objects.create(
            user=owner,
            group=group,
            role=GroupRole.OWNER,
            status="approved"
        )
        return group
    
    @staticmethod
    def can_view_group(user, group):
        if not group.is_private:
            return True
        return GroupMember.objects.filter(group=group, user=user, status="approved").exists()
    
    @staticmethod
    def can_manage_group(user, group):
        # return GroupMember.objects.filter(
        #     group=group,
        #     user=user,
        #     role__in=[GroupRole.OWNER, GroupRole.ADMIN],
        #     status="approved"
        # ).exists()
        role = GroupService.get_user_role(user, group)
        return role in [GroupRole.OWNER, GroupRole.ADMIN]
    
    @staticmethod
    def is_owner(user, group):
        return GroupMember.objects.filter(
            group=group,
            user=user,
            role=GroupRole.OWNER,
            status="approved"
        ).exists()
    
    @staticmethod
    def is_member(user, group):
        return GroupMember.objects.filter(
            group=group,
            user=user,
            status="approved"
        ).exists()
    
    @staticmethod
    def change_member_role(request_user, group, target_user_id, new_role):
        """Owner thay đổi chức vụ cho Member/Admin"""
        if not GroupService.is_owner(request_user, group):
            return False, "Chỉ chủ sở hữu mới có quyền thay đổi chức vụ."
        
        try:
            membership = GroupMember.objects.get(group=group, user_id=target_user_id)
            if membership.user == request_user:
                return False, "Bạn không thể tự thay đổi chức vụ của chính mình."
            
            membership.role = new_role
            membership.save()
            return True, f"Đã cập nhật vai trò của {membership.user.username} thành {new_role}."
        except GroupMember.DoesNotExist:
            return False, "Không tìm thấy thành viên."
        
    @staticmethod
    def get_manage_dashboard_data(group):
        """
        Lấy toàn bộ dữ liệu cần thiết cho trang Quản lý nhóm.
        """
        # 1. Lấy danh sách yêu cầu chờ duyệt (Pending)
        pending_requests = GroupMember.objects.filter(
            group=group, 
            status='pending'
        ).select_related('user', 'user__profile').order_by('-joined_at')
        
        # 2. Lấy danh sách thành viên chính thức, ưu tiên sắp xếp: Owner > Admin > Moderator > Member
        members = GroupMember.objects.filter(
            group=group, 
            status='approved'
        ).select_related('user', 'user__profile').annotate(
            role_order=Case(
                When(role=GroupRole.OWNER, then=Value(1)),
                When(role=GroupRole.ADMIN, then=Value(2)),
                When(role=GroupRole.MEMBER, then=Value(3)),
                default=Value(4),
                output_field=IntegerField(),
            )
        ).order_by('role_order', '-joined_at')

        # 3. Bị báo cáo (Bao gồm cả bài viết và bình luận)
        reported_items = GroupReport.objects.filter(
            group=group,
            status='pending'
        ).select_related(
            'post', 'post__author', 'comment', 'comment__user'
        ).order_by('-created_at')

        # 4. Bài viết chờ duyệt (Pending posts)
        pending_posts = GroupPost.objects.filter(
            group=group,
            status='pending'
        ).select_related('post', 'post__author').order_by('created_at')

        #5 Lấy ảnh bìa
        cover_image = group.cover_image.url if group.cover_image else None

        # 5. Lấy danh sách thành viên bị chặn
        blocked_members = GroupMember.objects.filter(
            group=group, 
            status='banned'
        ).select_related('user', 'user__profile').order_by('-updated_at')

        data = {
            'pending_requests': pending_requests,
            'pending_count': pending_requests.count(),
            'members': members,
            'members_count': members.count(),
            'blocked_members': blocked_members, # Mới
            'blocked_count': blocked_members.count(), # Mới
            'reported_items': reported_items,
            'reports_count': reported_items.count(),
            'pending_posts': pending_posts,
            'pending_posts_count': pending_posts.count(),
            'cover_image': cover_image,
        }

        return data
    @staticmethod
    def handle_join_request(group, user_id, action):
        """
        Xử lý yêu cầu tham gia nhóm (approve/reject).
        """
        try:
            member_request = GroupMember.objects.get(
                group=group, 
                user_id=user_id, 
                status='pending'
            )
            
            if action == 'approve':
                member_request.status = 'approved'
                member_request.save()
            elif action == 'reject':
                member_request.status = 'rejected'
                # Hoặc bạn có thể dùng member_request.delete() nếu không muốn lưu lịch sử reject
                member_request.save()
                
            return True, "Xử lý thành công."
        except GroupMember.DoesNotExist:
            return False, "Không tìm thấy yêu cầu này."
        
    @staticmethod
    def report_content(group, reporter, reason, post_id=None, comment_id=None):
        """Hàm tạo báo cáo mới cho Post hoặc Comment"""
        if not post_id and not comment_id:
            return False, "Phải báo cáo một bài viết hoặc bình luận cụ thể."
        
        """Hàm tạo báo cáo với kiểm tra bảo vệ Owner"""
        target_user = None
        if post_id:
            from apps.posts.models import Post
            post = get_object_or_404(Post, id=post_id)
            target_user = post.author
        elif comment_id:
            from apps.posts.models import Comment
            comment = get_object_or_404(Comment, id=comment_id)
            target_user = comment.user

        # QUY TẮC 1: Không thể báo cáo Owner
        if target_user == group.owner:
            return False, "Bạn không thể báo cáo Chủ sở hữu nhóm."
        
        # Đảm bảo tuân thủ CheckConstraint (chỉ post hoặc comment)
        report = GroupReport.objects.create(
            group=group,
            reporter=reporter,
            post_id=post_id,
            comment_id=comment_id,
            reason=reason,
            status='pending'
        )
        return True, "Cảm ơn bạn! Báo cáo đã được gửi tới quản trị viên."
    
    @staticmethod
    def resolve_report(request_user, group, report_id, action_type):
        """
        Xử lý báo cáo với các hành động:
        - 'dismiss': Bỏ qua báo cáo
        - 'delete_content': Xóa nội dung bị báo cáo
        - 'delete_and_remove': Xóa nội dung + Xóa thành viên khỏi nhóm
        - 'delete_and_ban': Xóa nội dung + Chặn thành viên vĩnh viễn
        """
        if not GroupService.can_manage_group(request_user, group):
            return False, "Bạn không có quyền xử lý báo cáo."

        report = get_object_or_404(GroupReport, id=report_id, group=group)
        # Lấy vai trò của người bị báo cáo
        target_user = report.post.author if report.post else report.comment.user
        target_role = GroupService.get_user_role(target_user, group)
        request_role = GroupService.get_user_role(request_user, group)
        
        if target_role == GroupRole.ADMIN and request_role != GroupRole.OWNER:
            return False, "Chỉ Chủ sở hữu mới có quyền xử lý báo cáo nhắm vào Quản trị viên."
        # Xác định đối tượng bị báo cáo (Post hoặc Comment)
        if report.post:
            target_author = report.post.author
        elif report.comment:
            target_author = report.comment.user

        # 1. Thực hiện hành động xóa nội dung nếu yêu cầu
        if action_type in ['delete_content', 'delete_and_remove', 'delete_and_ban']:
            if report.post:
                # Gọi service xóa bài viết (đã có trong code của bạn)
                report.post.is_deleted = True 
                report.post.save()
            elif report.comment:
                report.comment.is_deleted = True
                report.comment.save()

        # 2. Thực hiện hành động với thành viên
        if action_type == 'delete_and_remove' and target_author:
            GroupMemberService.remove_member(request_user, group, target_author.id)
        
        elif action_type == 'delete_and_ban' and target_author:
            membership = GroupMember.objects.filter(group=group, user=target_author).first()
            if membership:
                GroupMemberService.ban_member(request_user, membership)

        # 3. Cập nhật trạng thái báo cáo
        report.status = 'resolved' if action_type != 'dismiss' else 'rejected'
        report.save()
        
        return True, "Đã xử lý báo cáo thành công."
    
class GroupMemberService:
    @staticmethod
    def join_group(user, group):

        membership = GroupMember.objects.filter(
            user=user,
            group=group
        ).first()
        
        if membership:
            if membership.status == "banned":
                raise PermissionDenied("You are banned from this group.")

            if membership.status == "approved":
                raise PermissionDenied("You are already a member.")

            if membership.status == "pending":
                raise PermissionDenied("Your request is already pending.")

            if membership.status == "rejected":
                membership.status = "pending"
                membership.save()
                create_notification(
                    actor=user,
                    recipient=group.owner,
                    verb_code="group_join_request",
                    target=group,
                    link=f"/groups/{group.id}/manage/",
                )
                return membership
             
        membership = GroupMember.objects.create(
            user=user,
            group=group,
            role="member",
            status="pending"
        )
        create_notification(
            actor=user,
            recipient=group.owner,
            verb_code="group_join_request",
            target=group,
            link=f"/groups/{group.id}/manage/",
        )
        return membership
    
    @staticmethod
    def reject_member(request_user, membership):
        #Admin and owner can reject members
        admin = GroupMember.objects.filter(
            group=membership.group,
            user=request_user,
            role__in=[GroupRole.OWNER, GroupRole.ADMIN],
            status="approved"
        ).first()
        if not admin:
            raise PermissionDenied("Only group owner or admin can reject members.")
        membership.status = "rejected"
        membership.save()

    @staticmethod
    def approve_member(request_user, membership):
        #Admin and owner can approve members
        admin = GroupMember.objects.filter(
            group=membership.group,
            user=request_user,
            role__in=[GroupRole.OWNER, GroupRole.ADMIN],
            status="approved"
        ).first()
        if not admin:
            raise PermissionDenied("Only group owner or admin can approve members.")
        membership.status = "approved"
        membership.save()
        create_notification(
            actor=request_user,
            recipient=membership.user,
            verb_code="group_request_accept",
            target=membership.group,
            link=f"/groups/{membership.group_id}/",
        )

    @staticmethod
    def ban_member(request_user, membership):
        #Admin and owner can ban members
        admin = GroupMember.objects.filter(
            group=membership.group,
            user=request_user,
            role__in=[GroupRole.OWNER, GroupRole.ADMIN],
            status="approved"
        ).first()
        if not admin:
            raise PermissionDenied("Only group owner or admin can ban members.")
        membership.status = "banned"
        membership.save()
    
    @staticmethod
    def remove_member(request_user, group, target_user_id):
        """Xóa thành viên khỏi nhóm (có thể xin vào lại)"""
        if not GroupService.can_manage_group(request_user, group):
            return False, "Bạn không có quyền."
        try:
            membership = GroupMember.objects.get(group=group, user_id=target_user_id)
            if membership.role == GroupRole.OWNER:
                return False, "Không thể xóa chủ sở hữu."
            membership.delete() # Xóa hẳn record để họ có thể join lại
            return True, "Đã xóa thành viên khỏi nhóm."
        except GroupMember.DoesNotExist:
            return False, "Thành viên không tồn tại."

    @staticmethod
    def unban_member(request_user, group, target_user_id):
        """Gỡ chặn (xóa record banned để họ có thể tìm thấy và xin vào lại)"""
        if not GroupService.can_manage_group(request_user, group):
            return False, "Bạn không có quyền."
        try:
            membership = GroupMember.objects.get(group=group, user_id=target_user_id, status='banned')
            membership.delete() # Xóa record banned để trạng thái trở thành 'none'
            return True, "Đã gỡ chặn thành viên."
        except GroupMember.DoesNotExist:
            return False, "Thành viên không nằm trong danh sách chặn."

    @staticmethod
    def leave_group(user, group):
        membership = GroupMember.objects.filter(user=user, group=group).first()
        if not membership:
            raise PermissionDenied("You are not a member of this group.")
        if membership.role == GroupRole.OWNER:
            raise PermissionDenied("Group owner cannot leave the group. Please transfer ownership or delete the group.")
        membership.delete()

    @staticmethod
    def get_group_members(group):
        return GroupMember.objects.filter(group=group, status="approved").select_related("user")
    
    @staticmethod
    def get_pending_members(group):
        return GroupMember.objects.filter(group=group, status="pending").select_related("user")
    
    @staticmethod
    def get_group_admins(group):
        return GroupMember.objects.filter(group=group, role__in=[GroupRole.OWNER, GroupRole.ADMIN], status="approved").select_related("user")
    
    @staticmethod
    def is_member(user, group):
        return GroupMember.objects.filter(group=group, user=user, status="approved").exists()
    
    @staticmethod
    def is_admin(user, group):
        return GroupMember.objects.filter(group=group, user=user, role__in=[GroupRole.OWNER, GroupRole.ADMIN], status="approved").exists()
    
    @staticmethod
    def is_owner(user, group):
        return GroupMember.objects.filter(group=group, user=user, role=GroupRole.OWNER, status="approved").exists()
    
    @staticmethod
    def is_group_admin_or_owner(user, group):
        return GroupMember.objects.filter(group=group, user=user, role__in=[GroupRole.OWNER, GroupRole.ADMIN], status="approved").exists()
    
class GroupPostService:
    @staticmethod
    def create_post_in_group(group, user, content="", images=None, files=None, tagged_users=None):
        if not GroupMemberService.is_member(user, group):
            raise PermissionDenied("You must be a member of the group to create posts.")

        normalized_content = content.strip() if content else ""
        image_list = list(images or [])
        file_list = list(files or [])
        if not normalized_content and not image_list and not file_list:
            raise ValidationError("Post must include content, images, or files.")
        
        post = Post.objects.create(
            author=user,
            content=normalized_content,
            privacy=PostPrivacy.PUBLIC,
            status=ContentStatus.NORMAL
        )

        if image_list:
            for idx, img in enumerate(image_list):
                PostImage.objects.create(post=post, image=img, order=idx)
            
        if file_list:
            for file in file_list:
                PostFile.objects.create(post=post, file=file, filename=file.name)

        tagged_user_ids = set()
        if tagged_users:
            friend_ids = set(get_friend_ids(user))
            for user_id in tagged_users:
                try:
                    uid_int = int(user_id)
                except (TypeError, ValueError):
                    continue
                if uid_int not in friend_ids:
                    continue
                try:
                    tagged_user = User.objects.get(id=uid_int)
                except User.DoesNotExist:
                    continue
                PostTagUser.objects.get_or_create(post=post, user=tagged_user)
                tagged_user_ids.add(uid_int)

        #check quyền user đăng nếu là admin | owner thì duyệt luôn, còn member thường thì để pending
        status = "approved" if GroupMemberService.is_group_admin_or_owner(user, group) else "pending"
        
        GroupPost.objects.create(
            group=group,
            post=post,
            status=status,
            is_pinned=False,
            is_deleted=False
        )

        create_notification(
            actor=user,
            recipient=group.owner,
            verb_code="post_in_group",
            target=post,
            link=f"/groups/{group.id}/",
        )

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
    
    @staticmethod
    def update_post_in_group(group_post, user, content=None, images=None, files=None, tagged_users=None):
        if group_post.post.author != user:
            raise PermissionDenied("You can only edit your own posts.")
        
        if content is not None:
            group_post.post.content = content

        if tagged_users is not None:
            # Xóa tag cũ
            group_post.post.tagged_users.clear()
            # Thêm tag mới
            for user_id in tagged_users:
                try:
                    tagged_user = User.objects.get(id=user_id)
                    group_post.post.tagged_users.add(tagged_user)
                except User.DoesNotExist:
                    continue
        
        if images is not None:
            # Xóa ảnh cũ
            group_post.post.images.all().delete()
            # Thêm ảnh mới
            for idx, img in enumerate(images):
                PostImage.objects.create(post=group_post.post, image=img, order=idx)
        
        if files is not None:
            # Xóa file cũ
            group_post.post.files.all().delete()
            # Thêm file mới
            for file in files:
                PostFile.objects.create(post=group_post.post, file=file, filename=file.name)
        
        group_post.post.save()
        return group_post.post
    
    @staticmethod
    def get_group_posts(group, user):
        if not GroupService.can_view_group(user, group):
            raise PermissionDenied("You do not have permission to view this group's posts.")
        
        posts = group.group_posts.filter(status="approved", is_deleted=False).select_related("post", "post__author").order_by("-is_pinned", "-created_at")
        return posts
    
    @staticmethod
    def pin_post(group_post, user):
        if not GroupMemberService.is_admin(user, group_post.group):
            raise PermissionDenied("Only group admins can pin posts.")
        group_post.is_pinned = True
        group_post.save()
    
    @staticmethod
    def unpin_post(group_post, user):
        if not GroupMemberService.is_admin(user, group_post.group):
            raise PermissionDenied("Only group admins can unpin posts.")
        group_post.is_pinned = False
        group_post.save()
    
    @staticmethod
    def delete_post(group_post, user):
        if not GroupMemberService.is_admin(user, group_post.group):
            raise PermissionDenied("Only group admins can delete posts.")
        group_post.is_deleted = True
        group_post.status = "deleted"
        group_post.save()

    @staticmethod
    def approve_group_post(group_post, approver):
        if not GroupMemberService.is_admin(approver, group_post.group):
            raise PermissionDenied("Only group admins can approve posts.")
        group_post.status = "approved"
        group_post.save()

    @staticmethod
    def reject_group_post(group_post, approver):
        if not GroupMemberService.is_admin(approver, group_post.group):
            raise PermissionDenied("Only group admins can reject posts.")
        group_post.status = "rejected"
        group_post.save()

    @staticmethod
    def can_edit_post(user, group_post):
        if group_post.post.author == user:
            return True
        return False

def is_member(user, group):
    return GroupMember.objects.filter(group=group, user=user, status="approved").exists()
    
def is_admin(user, group):
    return GroupMember.objects.filter(group=group, user=user, role__in=[GroupRole.OWNER, GroupRole.ADMIN], status="approved").exists()
    
def is_owner(user, group):
    return GroupMember.objects.filter(group=group, user=user, role=GroupRole.OWNER, status="approved").exists()
    
def is_group_admin_or_owner(user, group):
    return GroupMember.objects.filter(group=group, user=user, role__in=[GroupRole.OWNER, GroupRole.ADMIN], status="approved").exists()

def get_group_list(user, query=None):
    # 1. Nếu có tìm kiếm -> Lọc và trả về kết quả ngay lập tức
    if query:
        return Group.objects.filter(name__icontains=query)

    # 2. Nếu không tìm kiếm -> Tìm group của user
    user_groups = Group.objects.filter(
        Q(owner=user) | Q(members__user=user, members__status="approved")
    ).distinct()
    
    # Nếu user có group -> Trả về danh sách group của user
    if user_groups.exists():
        return user_groups
        
    # 3. Fallback: Nếu không rơi vào 2 trường hợp trên -> Trả về 20 group đầu tiên
    return Group.objects.all()[:20]