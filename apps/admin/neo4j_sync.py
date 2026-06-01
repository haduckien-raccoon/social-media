# apps/admin/neo4j_sync.py
from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.posts.models import Post, Comment, Hashtag, ContentStatus
from apps.moderation.models import ContentModerationLog, ModerationTargetType
from apps.friends.neo4j_client import Neo4jClient

from apps.accounts.neo4j_sync import (
    sync_account_to_neo4j,
    sync_account_status_to_neo4j,
)

from apps.posts.neo4j_feed import (
    sync_post_node,
    sync_post_hashtags,
    sync_tagged_users,
    mark_post_deleted_in_neo4j,
    refresh_comment_interaction_edge,
)


# =====================================================
# 1. USER / ACCOUNT ADMIN SYNC
# =====================================================

def sync_admin_user_to_neo4j(user: User) -> None:
    """
    Dùng khi admin ban/unban hoặc đổi quyền user.
    """
    sync_account_to_neo4j(user)


def sync_admin_user_status_to_neo4j(user: User) -> None:
    """
    Dùng khi chỉ đổi trạng thái: banned, active, staff, superuser...
    """
    sync_account_status_to_neo4j(user)


def sync_admin_user_to_neo4j_on_commit(user: User) -> None:
    user_id = user.id

    def _sync():
        fresh_user = (
            User.objects
            .select_related("profile")
            .filter(id=user_id)
            .first()
        )
        if fresh_user:
            sync_admin_user_to_neo4j(fresh_user)

    transaction.on_commit(_sync)


# =====================================================
# 2. POST ADMIN SYNC
# =====================================================

def sync_admin_post_to_neo4j(post: Post) -> None:
    """
    Đồng bộ trạng thái post do admin thay đổi:
    hide/delete/restore/flag/unflag.
    """
    sync_post_node(post)
    sync_post_hashtags(post)
    sync_tagged_users(post)

    if post.is_deleted or post.status in [
        getattr(ContentStatus, "DELETED", "deleted"),
        getattr(ContentStatus, "BLOCKED", "blocked"),
    ]:
        mark_post_deleted_in_neo4j(post.id)


def sync_admin_post_to_neo4j_on_commit(post: Post) -> None:
    post_id = post.id

    def _sync():
        fresh_post = (
            Post.objects
            .select_related("author", "author__profile")
            .filter(id=post_id)
            .first()
        )
        if fresh_post:
            sync_admin_post_to_neo4j(fresh_post)

    transaction.on_commit(_sync)


# =====================================================
# 3. COMMENT ADMIN SYNC
# =====================================================

def sync_comment_moderation_node_to_neo4j(comment: Comment) -> None:
    """
    Tạo/cập nhật Comment node để phục vụ moderation graph sau này.
    Feed hiện tại chủ yếu dùng COMMENTED_ON edge và Post counter,
    nhưng node Comment hữu ích cho admin/moderation analytics.
    """
    query = """
    MERGE (c:Comment {id: $comment_id})
    SET c.post_id = $post_id,
        c.user_id = $user_id,
        c.content_preview = $content_preview,
        c.status = $status,
        c.is_deleted = $is_deleted,
        c.created_at = datetime($created_at),
        c.updated_at = datetime($updated_at),
        c.synced_at = datetime()

    WITH c
    MERGE (u:User {id: $user_id})
    SET u.username = $username

    MERGE (p:Post {id: $post_id})

    MERGE (u)-[:AUTHORED_COMMENT]->(c)
    MERGE (c)-[:ON_POST]->(p)
    """

    Neo4jClient.execute(
        query,
        comment_id=comment.id,
        post_id=comment.post_id,
        user_id=comment.user_id,
        username=comment.user.username if comment.user else "",
        content_preview=(comment.content or "")[:200],
        status=getattr(comment, "status", ""),
        is_deleted=bool(comment.is_deleted),
        created_at=comment.created_at.isoformat(),
        updated_at=comment.updated_at.isoformat(),
    )


def sync_admin_comment_to_neo4j(comment: Comment) -> None:
    """
    Khi admin hide/delete/restore comment:
    - cập nhật Comment node
    - cập nhật lại COMMENTED_ON edge theo số comment còn sống
    - cập nhật lại counter/ranking của Post
    """
    sync_comment_moderation_node_to_neo4j(comment)

    alive_comment_count = Comment.objects.filter(
        user_id=comment.user_id,
        post_id=comment.post_id,
        is_deleted=False,
    ).count()

    refresh_comment_interaction_edge(
        user_id=comment.user_id,
        username=comment.user.username,
        post_id=comment.post_id,
        comment_count=alive_comment_count,
    )

    sync_post_node(comment.post)


def sync_admin_comment_to_neo4j_on_commit(comment: Comment) -> None:
    comment_id = comment.id

    def _sync():
        fresh_comment = (
            Comment.objects
            .select_related("user", "post", "post__author")
            .filter(id=comment_id)
            .first()
        )
        if fresh_comment:
            sync_admin_comment_to_neo4j(fresh_comment)

    transaction.on_commit(_sync)


# =====================================================
# 4. HASHTAG ADMIN SYNC
# =====================================================

def sync_hashtag_node_to_neo4j(hashtag: Hashtag) -> None:
    query = """
    MERGE (h:Hashtag {tag: $tag})
    SET h.mysql_id = $hashtag_id,
        h.updated_at = datetime()
    """

    Neo4jClient.execute(
        query,
        hashtag_id=hashtag.id,
        tag=hashtag.tag,
    )


def mark_hashtag_deleted_in_neo4j(tag: str, hashtag_id: int = None) -> None:
    """
    Không delete node ngay để tránh mất lịch sử.
    Chỉ đánh dấu deleted.
    """
    query = """
    MATCH (h:Hashtag {tag: $tag})
    SET h.is_deleted = true,
        h.mysql_id = $hashtag_id,
        h.updated_at = datetime()
    """

    Neo4jClient.execute(
        query,
        tag=tag,
        hashtag_id=hashtag_id,
    )


def sync_hashtag_posts_to_neo4j(hashtag: Hashtag) -> None:
    """
    Khi admin đổi tag, các Post-HAS_HASHTAG edge cần sync lại.
    """
    posts = (
        Post.objects
        .filter(post_hashtags__hashtag=hashtag)
        .select_related("author")
        .distinct()
    )

    for post in posts.iterator(chunk_size=300):
        sync_post_hashtags(post)


def sync_admin_hashtag_to_neo4j_on_commit(hashtag: Hashtag) -> None:
    hashtag_id = hashtag.id

    def _sync():
        fresh = Hashtag.objects.filter(id=hashtag_id).first()
        if fresh:
            sync_hashtag_node_to_neo4j(fresh)
            sync_hashtag_posts_to_neo4j(fresh)

    transaction.on_commit(_sync)


def mark_admin_hashtag_deleted_on_commit(tag: str, hashtag_id: int = None) -> None:
    transaction.on_commit(
        lambda: mark_hashtag_deleted_in_neo4j(tag=tag, hashtag_id=hashtag_id)
    )


# =====================================================
# 5. MODERATION LOG SYNC
# =====================================================

def sync_moderation_log_to_neo4j(log: ContentModerationLog) -> None:
    """
    Sync moderation log để sau này tính:
    - user nào bị xử lý nhiều
    - post/comment nào nhiều moderation event
    - admin nào xử lý nhiều
    """
    query = """
    MERGE (m:ModerationLog {id: $log_id})
    SET m.target_type = $target_type,
        m.target_id = $target_id,
        m.action = $action,
        m.status = $status,
        m.source = $source,
        m.risk_score = $risk_score,
        m.reason = $reason,
        m.admin_note = $admin_note,
        m.is_automatic = $is_automatic,
        m.is_resolved = $is_resolved,
        m.created_at = datetime($created_at),
        m.updated_at = datetime($updated_at),
        m.resolved_at = CASE
            WHEN $resolved_at IS NULL THEN null
            ELSE datetime($resolved_at)
        END,
        m.synced_at = datetime()

    WITH m
    OPTIONAL MATCH (actor:User {id: $actor_id})
    FOREACH (_ IN CASE WHEN actor IS NULL THEN [] ELSE [1] END |
        MERGE (actor)-[:PERFORMED_MODERATION]->(m)
    )
    """

    Neo4jClient.execute(
        query,
        log_id=log.id,
        actor_id=log.actor_id,
        target_type=log.target_type,
        target_id=log.target_id,
        action=log.action,
        status=log.status,
        source=log.source,
        risk_score=float(log.risk_score or 0),
        reason=log.reason or "",
        admin_note=log.admin_note or "",
        is_automatic=bool(log.is_automatic),
        is_resolved=bool(log.is_resolved),
        created_at=log.created_at.isoformat(),
        updated_at=log.updated_at.isoformat(),
        resolved_at=log.resolved_at.isoformat() if log.resolved_at else None,
    )

    # Link target nếu target là post/comment/user/hashtag
    if log.target_type == ModerationTargetType.POST:
        Neo4jClient.execute(
            """
            MATCH (m:ModerationLog {id: $log_id})
            MERGE (p:Post {id: $target_id})
            MERGE (m)-[:TARGETS]->(p)
            """,
            log_id=log.id,
            target_id=log.target_id,
        )

    elif log.target_type == ModerationTargetType.COMMENT:
        Neo4jClient.execute(
            """
            MATCH (m:ModerationLog {id: $log_id})
            MERGE (c:Comment {id: $target_id})
            MERGE (m)-[:TARGETS]->(c)
            """,
            log_id=log.id,
            target_id=log.target_id,
        )

    elif log.target_type == "user":
        Neo4jClient.execute(
            """
            MATCH (m:ModerationLog {id: $log_id})
            MERGE (u:User {id: $target_id})
            MERGE (m)-[:TARGETS]->(u)
            """,
            log_id=log.id,
            target_id=log.target_id,
        )


def sync_moderation_log_to_neo4j_on_commit(log: ContentModerationLog) -> None:
    log_id = log.id

    def _sync():
        fresh = (
            ContentModerationLog.objects
            .select_related("actor")
            .filter(id=log_id)
            .first()
        )
        if fresh:
            sync_moderation_log_to_neo4j(fresh)

    transaction.on_commit(_sync)