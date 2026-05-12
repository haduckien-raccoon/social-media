from django.db import models
from apps.accounts.models import User


class ModerationTargetType(models.TextChoices):
	POST = "post", "Post"
	COMMENT = "comment", "Comment"
	POST_IMAGE = "post_image", "Post Image"
	COMMENT_IMAGE = "comment_image", "Comment Image"
	POST_FILE = "post_file", "Post File"
	COMMENT_FILE = "comment_file", "Comment File"
	HASHTAG = "hashtag", "Hashtag"


class ModerationAction(models.TextChoices):
	FLAG = "flag", "Flag"
	UNFLAG = "unflag", "Unflag"
	HIDE = "hide", "Hide"
	RESTORE = "restore", "Restore"
	DELETE = "delete", "Delete"
	UPDATE = "update", "Update"
	RESOLVE = "resolve", "Resolve"
	REJECT = "reject", "Reject"
	REJECTED = "rejected", "Rejected"
	APPROVED = "approved", "Approved"
	IGNORE = "ignore", "Ignore"
	RESOLVED = "resolved", "Resolved"


class ContentModerationLog(models.Model):
	actor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
	target_type = models.CharField(max_length=20, choices=ModerationTargetType.choices)
	target_id = models.PositiveIntegerField()
	action = models.CharField(max_length=20, choices=ModerationAction.choices)
	reason = models.TextField(blank=True)
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		indexes = [
			models.Index(fields=["target_type", "target_id"]),
			models.Index(fields=["created_at"]),
		]
		ordering = ["-created_at"]

	def __str__(self):
		return f"{self.target_type}:{self.target_id} {self.action}"
