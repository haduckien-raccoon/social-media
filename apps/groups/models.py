from os import name
from django.db import models
from apps.accounts.models import User
from apps.posts.models import  *
# Create your models here.
class GroupSortChoices(models.TextChoices):
    LATEST_ACTIVITY = "latest_activity", "Hoạt động mới nhất"
    NEWEST = "newest", "Bài viết mới"
    RELEVANT = "relevant", "Phù hợp nhất"

class Group(models.Model):
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    cover_image = models.ImageField(upload_to="group_covers/", null=True, blank=True) # Ảnh bìa nhóm
    is_activate = models.BooleanField(default=True)
    is_private = models.BooleanField(default=True)

    owner = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="owned_groups"
    )
    # --- SETTINGS (CÀI ĐẶT NHÓM) ---
    # Thành viên
    mod_can_approve_member = models.BooleanField(default=False, help_text="Cho phép Người kiểm duyệt phê duyệt thành viên")
    
    # Bài viết
    require_post_approval = models.BooleanField(default=False, help_text="Bật để yêu cầu phê duyệt bài viết mới")
    mod_can_approve_post = models.BooleanField(default=False, help_text="Cho phép Người kiểm duyệt phê duyệt bài viết")
    
    require_edit_approval = models.BooleanField(default=False, help_text="Bật để yêu cầu phê duyệt khi chỉnh sửa")
    mod_can_approve_edit = models.BooleanField(default=False, help_text="Cho phép Người kiểm duyệt phê duyệt chỉnh sửa")
    
    default_sort = models.CharField(
        max_length=20, 
        choices=GroupSortChoices.choices, 
        default=GroupSortChoices.LATEST_ACTIVITY,
        help_text="Tiêu chí sắp xếp bài viết mặc định"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name
    
class GroupRole(models.TextChoices):
    OWNER = "owner", "Owner"
    ADMIN = "admin", "Admin"
    MEMBER = "member", "Member"
    MODERATOR = "moderator", "Moderator"

class GroupMember(models.Model):
    STATUS_CHOICES = (
        ("pending", "Pending"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
        ("banned", "Banned")
    )

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    group = models.ForeignKey(Group, on_delete=models.CASCADE, related_name="members")
    role = models.CharField(
        max_length=20,
        choices=GroupRole.choices,
        default=GroupRole.MEMBER
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="pending"
    )
    joined_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta: 
        unique_together = ("user", "group")
        indexes = [
            models.Index(fields=["group", "status"]),
            models.Index(fields=["group", "role"]),
        ]
    def __str__(self):
        return f"{self.user.username} in {self.group.name} as {self.role}"
    
class GroupPost(models.Model):
    STATUS_CHOICES = (
        ("pending", "Pending"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
        ("deleted", "Deleted")
    )

    group = models.ForeignKey(Group, on_delete=models.CASCADE, related_name="group_posts")
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="group_context")
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="pending"
    )
    is_pinned = models.BooleanField(default=False)
    is_deleted = models.BooleanField(default=False)

    approved_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="approved_group_posts"
    )

    approved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta: 
        unique_together = ("group", "post")
        indexes = [
            models.Index(fields=["group", "status"]),
            models.Index(fields=["is_pinned"]),
        ]
    def __str__(self):
        return f"Post {self.post.id} in Group {self.group.name} - Status: {self.status}"
    
class GroupPermission(models.Model):
    code = models.CharField(max_length=100, unique=True)
    description = models.TextField()

    def __str__(self):
        return self.code

class GroupRolePermission(models.Model):
    role = models.CharField(
        max_length=20,
        choices=GroupRole.choices
    )

    permission = models.ForeignKey(
        GroupPermission,
        on_delete=models.CASCADE
    )

    class Meta:
        unique_together = ("role", "permission")

    def __str__(self):
        return f"{self.role} → {self.permission.code}"

class GroupRule(models.Model):
    group = models.ForeignKey(
        Group,
        on_delete=models.CASCADE,
        related_name="rules"
    )

    title = models.CharField(max_length=255)
    description = models.TextField()
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order"]

    def __str__(self):
        return f"{self.group} - {self.title}"

class GroupReport(models.Model):
    STATUS_CHOICES = (
        ("pending", "Pending"),
        ("reviewed", "Reviewed"),
        ("resolved", "Resolved"),
        ("rejected", "Rejected"),
    )

    group = models.ForeignKey(Group, on_delete=models.CASCADE)
    reporter = models.ForeignKey(User, on_delete=models.CASCADE)

    post = models.ForeignKey(
        Post,
        null=True,
        blank=True,
        on_delete=models.CASCADE
    )

    comment = models.ForeignKey(
        Comment,
        null=True,
        blank=True,
        on_delete=models.CASCADE
    )

    reason = models.TextField()
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="pending"
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                check=(
                    models.Q(post__isnull=False, comment__isnull=True) |
                    models.Q(post__isnull=True, comment__isnull=False)
                ),
                name="group_report_post_xor_comment"
            )
        ]

    def __str__(self):
        return f"Report by {self.reporter.username} in {self.group.name} - Status: {self.status}"
    
class GroupActivityLog(models.Model):
    group = models.ForeignKey(Group, on_delete=models.CASCADE)

    actor = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL
    )

    action = models.CharField(max_length=100)

    target_type = models.CharField(
        max_length=50,
        null=True,
        blank=True
    )

    target_id = models.PositiveIntegerField(
        null=True,
        blank=True
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["group", "created_at"]),
        ]

