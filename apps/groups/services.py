from django.shortcuts import get_object_or_404

from apps.groups.models import *
from apps.posts.services import *
from apps.posts.models import *
from apps.accounts.models import User
from django.core.paginator import Paginator, EmptyPage
from django.db.models import Case, Case, Count, Q, IntegerField, IntegerField, Value, When, When
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
            comment_count=Count('post__comments', filter=Q(post__comments__is_deleted=False), distinct=True)
        ).order_by('-is_pinned', '-post__created_at')

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
    def create_group(owner, name, description="", is_private=True):
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
        return GroupMember.objects.filter(
            group=group,
            user=user,
            role__in=[GroupRole.OWNER, GroupRole.ADMIN],
            status="approved"
        ).exists()
    
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
    def get_manage_dashboard_data(group):
        """
        Lấy toàn bộ dữ liệu cần thiết cho trang Quản lý nhóm.
        """
        # 1. Lấy danh sách yêu cầu chờ duyệt (Pending)
        pending_requests = GroupMember.objects.filter(
            group=group, 
            status='pending'
        ).select_related('user', 'user__profile').order_by('-joined_at')
        
        pending_count = pending_requests.count()

        # 2. Lấy danh sách thành viên chính thức, ưu tiên sắp xếp: Owner > Admin > Moderator > Member
        members = GroupMember.objects.filter(
            group=group, 
            status='approved'
        ).select_related('user', 'user__profile').annotate(
            role_order=Case(
                When(role=GroupRole.OWNER, then=Value(1)),
                When(role=GroupRole.ADMIN, then=Value(2)),
                When(role=GroupRole.MODERATOR, then=Value(3)),
                When(role=GroupRole.MEMBER, then=Value(4)),
                default=Value(5),
                output_field=IntegerField(),
            )
        ).order_by('role_order', '-joined_at')

        # 3. Lấy danh sách bài viết bị báo cáo (Pending Reports)
        reported_posts = GroupReport.objects.filter(
            group=group,
            status='pending',
            post__isnull=False # Chỉ lấy report cho bài viết
        ).select_related(
            'post', 'post__author', 'post__author__profile'
        ).order_by('-created_at')

        return {
            'pending_requests': pending_requests,
            'pending_count': pending_count,
            'members': members,
            'reported_posts': reported_posts
        }

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
                return membership
            
        return GroupMember.objects.create(
            user=user,
            group=group,
            role="member",
            status="pending"
        )
    
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
    def create_post_in_group(group, user, content="", images=None, files=None):
        if not GroupMemberService.is_member(user, group):
            raise PermissionDenied("You must be a member of the group to create posts.")
        
        post = Post.objects.create(
            author=user,
            content = content,
            privacy=PostPrivacy.PUBLIC,
            status=ContentStatus.NORMAL
        )

        if images:
            for idx, img in enumerate(images):
                PostImage.objects.create(post=post, image=img, order=idx)
            
        if files:
            for file in files:
                PostFile.objects.create(post=post, file=file, filename=file.name)
        
        GroupPost.objects.create(
            group=group,
            post=post,
            status="pending"
        )

        return post
    
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