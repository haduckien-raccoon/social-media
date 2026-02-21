from django.shortcuts import render, get_object_or_404, redirect
from django.core.exceptions import PermissionDenied
from django.contrib import messages
from django import forms
from apps.groups.models import *
from apps.groups.services import GroupService, GroupMemberService

class GroupForm(forms.ModelForm):
    class Meta:
        model = Group
        fields = ["name", "description", "is_private"]
    
def create_group(request):
    if request.method == "POST":
        form = GroupForm(request.POST)
        if form.is_valid():
            group = GroupService.create_group(
                owner=request.user,
                name=form.cleaned_data["name"],
                description=form.cleaned_data["description"],
                is_private=form.cleaned_data["is_private"]
            )
            messages.success(request, "Group created successfully!")
            return redirect("groups:group_detail", group_id=group.id)
    else:
        form = GroupForm()
    return render(request, "groups/group_form.html", {"form": form})
def group_detail(request, group_id):
    group = get_object_or_404(Group, id=group_id)
    if not GroupService.can_view_group(request.user, group):
        raise PermissionDenied("You do not have permission to view this group.")
    return render(request, "groups/group_detail.html", {"group": group})

def update_group(request, group_id):
    group = get_object_or_404(Group, id=group_id)
    if not GroupService.can_manage_group(request.user, group):
        raise PermissionDenied("You do not have permission to edit this group.")
    if request.method == "POST":
        form = GroupForm(request.POST, instance=group)
        if form.is_valid():
            form.save()
            messages.success(request, "Group updated successfully!")
            return redirect("groups:group_detail", group_id=group.id)
    else:
        form = GroupForm(instance=group)

    return render(request, "groups/group_form.html", {"form": form, "group": group})

def delete_group(request, group_id):
    group = get_object_or_404(Group, id=group_id)
    if not GroupService.is_owner(request.user, group):
        raise PermissionDenied("You do not have permission to delete this group.")
    if request.method == "POST":
        group.delete()
        messages.success(request, "Group deleted successfully!")
        return redirect("groups:group_list")
    return render(request, "groups/group_confirm_delete.html", {"group": group})

def group_list(request):
    groups = Group.objects.all()

    return render(
        request,
        "groups/group_list.html",
        {"groups": groups}
    )

def join_group(request, group_id):
    group = get_object_or_404(Group, id=group_id)
    try:
        GroupMemberService.join_group(request.user, group)
        messages.success(request, "Your join request has been sent.")
    except PermissionDenied as e:
        messages.error(request, str(e))
    return redirect("groups:group_list")

def approve_member(request, group_id, user_id):
    group = get_object_or_404(Group, id=group_id)
    if not GroupService.can_manage_group(request.user, group):
        raise PermissionDenied("You do not have permission to manage this group.")
    membership = get_object_or_404(GroupMember, group=group, user_id=user_id)
    GroupMemberService.approve_member(request.user, membership)
    messages.success(request, f"{membership.user.username} has been approved as a member.")
    return redirect("groups:group_detail", group_id=group.id)

def reject_member(request, group_id, user_id):
    group = get_object_or_404(Group, id=group_id)
    if not GroupService.can_manage_group(request.user, group):
        raise PermissionDenied("You do not have permission to manage this group.")
    membership = get_object_or_404(GroupMember, group=group, user_id=user_id)
    GroupMemberService.reject_member(request.user, membership)
    messages.success(request, f"{membership.user.username} has been rejected as a member.")
    return redirect("groups:group_detail", group_id=group.id)

def leave_group(request, group_id):
    group = get_object_or_404(Group, id=group_id)
    membership = get_object_or_404(GroupMember, group=group, user=request.user)
    GroupMemberService.leave_group(request.user, group)
    messages.success(request, "You have left the group.")
    return redirect("groups:group_list")

def ban_member(request, group_id, user_id):
    group = get_object_or_404(Group, id=group_id)
    if not GroupService.can_manage_group(request.user, group):
        raise PermissionDenied("You do not have permission to manage this group.")
    membership = get_object_or_404(GroupMember, group=group, user_id=user_id)
    GroupMemberService.ban_member(request.user, membership)
    messages.success(request, f"{membership.user.username} has been banned from the group.")
    return redirect("groups:group_detail", group_id=group.id)

