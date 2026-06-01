from django.db import models
from apps.accounts.models import User


# ==========================================
# TARGET TYPES
# ==========================================

class ModerationTargetType(models.TextChoices):
	USER = "user", "User"
	
	POST = "post", "Post"
	COMMENT = "comment", "Comment"

	POST_IMAGE = "post_image", "Post Image"
	COMMENT_IMAGE = "comment_image", "Comment Image"

	POST_FILE = "post_file", "Post File"
	COMMENT_FILE = "comment_file", "Comment File"

	HASHTAG = "hashtag", "Hashtag"


# ==========================================
# MODERATION ACTIONS
# ==========================================

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


# ==========================================
# MODERATION SOURCES
# ==========================================

class ModerationSource(models.TextChoices):
	REGEX = "regex", "Regex"
	ML = "ml", "Machine Learning"
	USER_REPORT = "user_report", "User Report"
	ADMIN = "admin", "Admin"


# ==========================================
# MODERATION STATUS
# ==========================================

class ModerationStatus(models.TextChoices):
	PENDING = "pending", "Pending"
	REVIEWING = "reviewing", "Reviewing"

	FLAGGED = "flagged", "Flagged"

	APPROVED = "approved", "Approved"
	REJECTED = "rejected", "Rejected"

	REMOVED = "removed", "Removed"


# ==========================================
# MAIN MODERATION LOG
# ==========================================

class ContentModerationLog(models.Model):

	# ======================================
	# WHO
	# ======================================

	actor = models.ForeignKey(
		User,
		on_delete=models.SET_NULL,
		null=True,
		blank=True,
		related_name="moderation_actions"
	)

	# ======================================
	# TARGET
	# ======================================

	target_type = models.CharField(
		max_length=30,
		choices=ModerationTargetType.choices
	)

	target_id = models.PositiveBigIntegerField(
		default=0
	)

	# ======================================
	# MODERATION
	# ======================================

	action = models.CharField(
		max_length=30,
		choices=ModerationAction.choices
	)

	status = models.CharField(
		max_length=20,
		choices=ModerationStatus.choices,
		default=ModerationStatus.PENDING
	)

	source = models.CharField(
		max_length=20,
		choices=ModerationSource.choices,
		default=ModerationSource.REGEX
	)

	# ======================================
	# DETECTION DATA
	# ======================================

	risk_score = models.FloatField(
		default=0.0
	)

	matched_keywords = models.JSONField(
		default=list,
		blank=True
	)

	# ======================================
	# MESSAGE
	# ======================================

	reason = models.TextField(
		blank=True
	)

	admin_note = models.TextField(
		blank=True
	)

	# ======================================
	# FLAGS
	# ======================================

	is_automatic = models.BooleanField(
		default=True
	)

	is_resolved = models.BooleanField(
		default=False
	)

	# ======================================
	# TIMESTAMPS
	# ======================================

	created_at = models.DateTimeField(
		auto_now_add=True
	)

	updated_at = models.DateTimeField(
		auto_now=True
	)

	resolved_at = models.DateTimeField(
		null=True,
		blank=True
	)

	# ======================================
	# META
	# ======================================

	class Meta:

		db_table = "content_moderation_logs"

		ordering = ["-created_at"]

		indexes = [

			# target lookup
			models.Index(
				fields=["target_type", "target_id"]
			),

			# source lookup
			models.Index(
				fields=["source"]
			),

			# status lookup
			models.Index(
				fields=["status"]
			),

			# risk score
			models.Index(
				fields=["risk_score"]
			),

			# created_at
			models.Index(
				fields=["created_at"]
			),

			# actor lookup
			models.Index(
				fields=["actor"]
			),
		]

	# ======================================
	# STRING
	# ======================================

	def __str__(self):

		return (
			f"[{self.source}] "
			f"{self.target_type}:{self.target_id} "
			f"{self.action}"
		)