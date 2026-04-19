from django.shortcuts import render, get_object_or_404, redirect
from django.core.exceptions import PermissionDenied
from django.core.exceptions import ValidationError
from django.contrib import messages
from django import forms
from apps.groups.models import *
from apps.groups.services import *
from django.http import JsonResponse
from django.template.loader import render_to_string
from apps.accounts.services import create_user_profile

class GroupForm(forms.ModelForm):
    class Meta:
        model = Group
        fields = ["name", "description"]
    
def create_group(request):
    if request.method == "POST":
        form = GroupForm(request.POST)
        tagged = request.POST.getlist("tagged_users")
        if form.is_valid():
            group = GroupService.create_group(
                owner=request.user,
                name=form.cleaned_data["name"],
                description=form.cleaned_data["description"],
                is_private=True
            )
            messages.success(request, "Group created successfully!")
            return redirect("groups:group_detail", group_id=group.id)
    else:
        form = GroupForm()
        
    return render(request, "groups/group_form.html", {"form": form})


# def update_group(request, group_id):
#     group = get_object_or_404(Group, id=group_id)
#     if not GroupService.can_manage_group(request.user, group):
#         raise PermissionDenied("You do not have permission to edit this group.")
#     if request.method == "POST":
#         form = GroupForm(request.POST, instance=group)
#         if form.is_valid():
#             form.save()
#             messages.success(request, "Group updated successfully!")
#             return redirect("groups:group_detail", group_id=group.id)
#     else:
#         form = GroupForm(instance=group)

#     return render(request, "groups/group_form.html", {"form": form, "group": group})

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
    query = request.GET.get('q')
    groups = get_group_list(request.user, query=query)

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

def create_post_in_group(request, group_id):
    group = get_object_or_404(Group, id=group_id)

    if not GroupMemberService.is_member(request.user, group):
        raise PermissionDenied("You must be a member of the group to create posts.")
    
    if request.method == "POST":
        content = request.POST.get("content", "")
        images = request.FILES.getlist("images")
        files = request.FILES.getlist("files")
        tagged = request.POST.getlist("tagged_users")

        if content.strip() or images or files:
            try:
                GroupPostService.create_post_in_group(
                    group,
                    request.user,
                    content,
                    images=images,
                    files=files,
                    tagged_users=tagged,
                )
            except ValidationError as e:
                return JsonResponse({"error": str(e)}, status=400)
            messages.success(request, "Post created successfully!")
            return redirect("groups:group_detail", group_id=group.id)
        else:
            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return JsonResponse({"error": "Post must include content, images, or files."}, status=400)
            messages.error(request, "Post must include content, images, or files.")
    
    create_user_profile(request.user)
    friends = list_people_tag(request.user)
    for friend in friends:
        create_user_profile(friend)
    return render(request, "groups/create_post.html", {"group": group, "friends": friends})

def update_post_in_group(request, group_id, post_id):
    group = get_object_or_404(Group, id=group_id)
    post = get_object_or_404(GroupPost, id=post_id, group=group)

    if not GroupPostService.can_edit_post(request.user, post):
        raise PermissionDenied("You do not have permission to edit this post.")
    
    if request.method == "POST":
        content = request.POST.get("content")
        images = request.FILES.getlist("images")
        files = request.FILES.getlist("files")
        tagged = request.POST.getlist("tagged_users")

        if content:
            GroupPostService.update_post_in_group(post, content, images=images, files=files, tagged_users=tagged)
            messages.success(request, "Post updated successfully!")
            return redirect("groups:group_detail", group_id=group.id)
        else:
            messages.error(request, "Content cannot be empty.")
    
    return render(request, "groups/update_post.html", {"group": group, "post": post})

def group_detail(request, group_id):
    group = GroupService.get_group_by_id(group_id)
    user_role = GroupService.get_user_role(request.user, group)
    
    # Lấy số trang từ URL (mặc định là 1)
    page = int(request.GET.get('page', 1))
    posts = []
    has_next = False
    cover_image = group.cover_image.url if group.cover_image else None
    
    if not (group.is_private and user_role in ['none', 'pending']):
        posts, has_next = GroupService.get_group_feed(group, request.user, page=page, page_size=10)

    # Nếu JS gọi Fetch/AJAX (dùng tham số ajax=1) -> Trả về JSON chứa HTML
    if request.GET.get('ajax'):
        html = render_to_string('groups/partials/post_list.html', {
            'posts': posts,
            'user': request.user,
            'user_role': user_role,
        }, request=request)
        
        return JsonResponse({
            'html': html,
            'has_next': has_next
        })

    context = {
        'group': group,
        'user_role': user_role,
        'posts': posts,
        'has_next': has_next, # Truyền ra ngoài để JS biết còn dữ liệu không
        'cover_image': cover_image
    }

    print("Group Detail Context:", context)  # Debug: In ra context để kiểm tra dữ liệu truyền ra template
    return render(request, 'groups/group_detail.html', context)

def manage_group(request, group_id):
    # 1. Lấy Group và kiểm tra quyền
    group = GroupService.get_group_by_id(group_id)
    user_role = GroupService.get_user_role(request.user, group)

    # Nếu không phải Owner hoặc Admin, đá văng ra ngoài với lỗi 403
    if user_role not in [GroupRole.OWNER, GroupRole.ADMIN]:
        raise PermissionDenied("Bạn không có quyền quản lý nhóm này.")

    # 2. Xử lý POST request (Phê duyệt / Từ chối thành viên)
    if request.method == "POST":
        action = request.POST.get("action")
        user_id = request.POST.get("user_id")

        # Logic thăng chức/giáng chức (Chỉ Owner làm được)
        if action in ['promote_admin', 'demote_member']:
            new_role = GroupRole.ADMIN if action == 'promote_admin' else GroupRole.MEMBER
            success, msg = GroupService.change_member_role(request.user, group, user_id, new_role)
            if success: messages.success(request, msg)
            else: messages.error(request, msg)

        if action in ['approve', 'reject'] and user_id:
            success, msg = GroupService.handle_join_request(group, user_id, action)
            if success:
                messages.success(request, msg)
            else:
                messages.error(request, msg)
        if action == 'remove_member':
            success, msg = GroupMemberService.remove_member(request.user, group, user_id)
            messages.success(request, msg) if success else messages.error(request, msg)
        
        elif action == 'ban': # Chặn thành viên
            # Tận dụng hàm ban_member có sẵn hoặc viết lại logic ở service
            membership = get_object_or_404(GroupMember, group=group, user_id=user_id)
            try:
                GroupMemberService.ban_member(request.user, membership)
                messages.success(request, "Đã chặn thành viên thành công.")
            except PermissionDenied as e:
                messages.error(request, str(e))

        elif action == 'unban': # Gỡ chặn
            success, msg = GroupMemberService.unban_member(request.user, group, user_id)
            messages.success(request, msg) if success else messages.error(request, msg)
        
        # Xử lý xong thì redirect lại chính trang quản lý để reset form
        return redirect('groups:manage_group', group_id=group.id)

    # 3. Xử lý GET request (Hiển thị dữ liệu Dashboard)
    dashboard_data = GroupService.get_manage_dashboard_data(group)

    context = {
        'group': group,
        'user_role': user_role,
        'pending_requests': dashboard_data['pending_requests'],
        'pending_count': dashboard_data['pending_count'],
        'members': dashboard_data['members'],
        'members_count': dashboard_data['members_count'],
        'blocked_members': dashboard_data['blocked_members'], # Mới
        'blocked_count': dashboard_data['blocked_count'],
        'reported_items': dashboard_data['reported_items'],
        'reports_count': dashboard_data['reports_count'],
        'pending_posts': dashboard_data['pending_posts'],
        'pending_posts_count': dashboard_data['pending_posts_count'],
        'cover_image': dashboard_data['cover_image']
    }

    print("Dashboard Data:", dashboard_data)  # Debug: In ra dữ liệu dashboard để kiểm tra
    
    return render(request, 'groups/manage_group.html', context)

def update_group(request, group_id):
    """View để hứng dữ liệu từ Form Cài đặt nhóm"""
    group = GroupService.get_group_by_id(group_id)
    user_role = GroupService.get_user_role(request.user, group)

    if user_role not in [GroupRole.OWNER, GroupRole.ADMIN]:
        raise PermissionDenied("Bạn không có quyền chỉnh sửa nhóm này.")

    if request.method == "POST":
        # a. Thông tin cơ bản
        group.name = request.POST.get("name", group.name)
        group.description = request.POST.get("description", group.description)
        
        if 'cover_image' in request.FILES:
            group.cover_image = request.FILES['cover_image']

        # b. Cài đặt Thành viên
        group.admin_can_approve_member = request.POST.get("admin_can_approve_member") == "on"

        # c. Cài đặt Bài viết
        group.require_post_approval = request.POST.get("require_post_approval") == "on"
        group.admin_can_approve_post = request.POST.get("admin_can_approve_post") == "on"
        
        group.require_edit_approval = request.POST.get("require_edit_approval") == "on"
        group.admin_can_approve_edit = request.POST.get("admin_can_approve_edit") == "on"

        group.default_sort = request.POST.get("default_sort", "latest_activity")

        group.save()
        messages.success(request, "Cập nhật thông tin nhóm thành công!")
        
    return redirect('groups:manage_group', group_id=group.id)

def approve_post_in_group(request, group_id, post_id):
    group = get_object_or_404(Group, id=group_id)
    post = get_object_or_404(GroupPost, id=post_id, group=group)

    if not GroupService.can_manage_group(request.user, group):
        raise PermissionDenied("You do not have permission to manage this group.")
    
    GroupPostService.approve_group_post(post, request.user)
    messages.success(request, "Post approved successfully!")
    return redirect("groups:manage_group", group_id=group.id)

def reject_post_in_group(request, group_id, post_id):
    group = get_object_or_404(Group, id=group_id)
    post = get_object_or_404(GroupPost, id=post_id, group=group)

    if not GroupService.can_manage_group(request.user, group):
        raise PermissionDenied("You do not have permission to manage this group.")
    
    GroupPostService.reject_group_post(post, request.user)
    messages.success(request, "Post rejected successfully!")
    return redirect("groups:manage_group", group_id=group.id)
