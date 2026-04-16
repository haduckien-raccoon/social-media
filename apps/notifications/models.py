from django.db import models
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from apps.accounts.models import User

class Notification(models.Model):
    # 1. ĐỊNH NGHĨA CÁC HÀNH ĐỘNG (VERBS)
    VERB_CHOICES = [
        # Tương tác Bài viết
        ("react_post", "React Post"),
        ("comment_post", "Comment Post"),
        ("share_post", "Share Post"),
        ("mention_in_post", "Mention in Post"),
        
        # Tương tác Bình luận
        ("react_comment", "React Comment"),
        ("reply_comment", "Reply Comment"),
        ("mention_in_comment", "Mention in Comment"),
        
        # Kết nối & Bạn bè
        ("friend_request", "Friend Request"),
        ("friend_accept", "Friend Accept"),
        ("follow_user", "Follow User"),
        
        # Tương tác Nhóm (Groups)
        ("group_invite", "Group Invite"),
        ("group_join_request", "Group Join Request"),
        ("group_request_accept", "Group Request Accept"),
        ("post_in_group", "Post in Group"),
        
        # Hệ thống
        ("system_alert", "System Alert"),
    ]

    # 2. ĐỊNH NGHĨA CÁC LOẠI CẢM XÚC (REACTIONS)
    REACTION_CHOICES = [
        ("like", "Like"),
        ("love", "Love"),
        ("haha", "Haha"),
        ("wow", "Wow"),
        ("sad", "Sad"),
        ("angry", "Angry"),
    ]

    # 3. THÔNG TIN NGƯỜI GỬI & NGƯỜI NHẬN
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="notifications")
    actor = models.ForeignKey(User, on_delete=models.CASCADE, related_name="actions")

    # 4. CHI TIẾT HÀNH ĐỘNG
    verb_code = models.CharField(max_length=50, choices=VERB_CHOICES)
    verb_text = models.CharField(max_length=255, blank=True)
    reaction_type = models.CharField(max_length=20, choices=REACTION_CHOICES, null=True, blank=True)

    # 5. ĐỐI TƯỢNG ĐƯỢC TƯƠNG TÁC (Generic Relation)
    # Áp dụng cho mọi Model: Post, Comment, Group, UserProfile...
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE, null=True, blank=True)
    object_id = models.PositiveIntegerField(null=True, blank=True)
    target_object = GenericForeignKey("content_type", "object_id")
    target_repr = models.CharField(max_length=255, blank=True) # Trích xuất ngắn gọn nội dung để hiển thị nhanh

    # 6. TRẠNG THÁI & THỜI GIAN
    link = models.URLField(blank=True, null=True) # Đường dẫn điều hướng khi click vào thông báo
    is_seen = models.BooleanField(default=False)  # Cờ đánh dấu đã hiển thị trên popup/chuông
    is_read = models.BooleanField(default=False)  # Cờ đánh dấu người dùng đã click vào xem
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True) # Quan trọng để đẩy thông báo lên đầu khi update reaction

    class Meta:
        # Sắp xếp theo thời gian cập nhật mới nhất
        ordering = ["-updated_at"] 
        
        # Đánh index để tăng tốc độ truy vấn DB
        indexes = [
            # Tối ưu cho truy vấn: đếm số lượng thông báo chưa đọc của 1 user
            models.Index(fields=['user', 'is_read']), 
            # Tối ưu cho truy vấn lấy target_object qua GenericForeignKey
            models.Index(fields=['content_type', 'object_id']), 
        ]

    def __str__(self):
        reaction = f" ({self.reaction_type})" if self.reaction_type else ""
        return f"{self.actor.username} -> {self.user.username}: {self.verb_code}{reaction}"