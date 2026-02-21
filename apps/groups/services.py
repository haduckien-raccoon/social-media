from apps.groups.models import *
from apps.posts.services import *
from django.utils import timezone

def approve_group_post(group_post: GroupPost, approver: User):
    group_post.status = 'approved'
    group_post.approved_by = approver
    group_post.approved_at = timezone.now()
    group_post.save()

class GroupService:
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
    