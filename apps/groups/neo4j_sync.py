# # apps/groups/neo4j_sync.py
# from __future__ import annotations

# from django.db import transaction

# from apps.accounts.models import User
# from apps.groups.models import Group, GroupMember, GroupPost
# from apps.friends.neo4j_client import Neo4jClient

# try:
#     from apps.accounts.neo4j_sync import sync_account_to_neo4j
# except Exception:
#     sync_account_to_neo4j = None


# # =====================================================
# # 1. SCHEMA
# # =====================================================

# def setup_group_graph_schema() -> None:
#     queries = [
#         """
#         CREATE CONSTRAINT group_id_unique IF NOT EXISTS
#         FOR (g:Group)
#         REQUIRE g.id IS UNIQUE
#         """,
#         """
#         CREATE CONSTRAINT user_id_unique IF NOT EXISTS
#         FOR (u:User)
#         REQUIRE u.id IS UNIQUE
#         """,
#         """
#         CREATE CONSTRAINT post_id_unique IF NOT EXISTS
#         FOR (p:Post)
#         REQUIRE p.id IS UNIQUE
#         """,
#         """
#         CREATE INDEX group_active_private_index IF NOT EXISTS
#         FOR (g:Group)
#         ON (g.is_activate, g.is_private)
#         """,
#         """
#         CREATE INDEX group_name_index IF NOT EXISTS
#         FOR (g:Group)
#         ON (g.name)
#         """,
#     ]

#     for query in queries:
#         Neo4jClient.execute(query)


# # =====================================================
# # 2. HELPERS
# # =====================================================

# def _cover_url(group: Group) -> str:
#     if not group.cover_image:
#         return ""
#     try:
#         return group.cover_image.url
#     except Exception:
#         return ""


# def _sync_user(user: User) -> None:
#     """
#     Dùng sync account chuẩn nếu bạn đã tạo apps.accounts.neo4j_sync.
#     Nếu chưa có, fallback tạo User node tối thiểu.
#     """
#     if sync_account_to_neo4j:
#         sync_account_to_neo4j(user)
#         return

#     Neo4jClient.execute(
#         """
#         MERGE (u:User {id: $id})
#         SET u.username = $username,
#             u.email = $email,
#             u.is_active = $is_active,
#             u.is_banned = $is_banned,
#             u.updated_at = datetime()
#         """,
#         id=user.id,
#         username=user.username or "",
#         email=user.email or "",
#         is_active=bool(user.is_active),
#         is_banned=bool(user.is_banned),
#     )


# # =====================================================
# # 3. GROUP NODE
# # =====================================================

# def sync_group_to_neo4j(group: Group) -> None:
#     """
#     Sync Group node và owner MEMBER_OF.

#     Owner phải là MEMBER_OF để feed Neo4j nhìn thấy bài trong group của owner.
#     """
#     _sync_user(group.owner)

#     query = """
#     MERGE (g:Group {id: $group_id})
#     SET g.name = $name,
#         g.description = $description,
#         g.cover_image = $cover_image,
#         g.is_private = $is_private,
#         g.is_activate = $is_activate,

#         g.owner_id = $owner_id,

#         g.admin_can_approve_member = $admin_can_approve_member,
#         g.require_post_approval = $require_post_approval,
#         g.admin_can_approve_post = $admin_can_approve_post,
#         g.require_edit_approval = $require_edit_approval,
#         g.admin_can_approve_edit = $admin_can_approve_edit,
#         g.default_sort = $default_sort,

#         g.created_at = datetime($created_at),
#         g.updated_at = datetime($updated_at),
#         g.synced_at = datetime()

#     WITH g
#     MATCH (owner:User {id: $owner_id})
#     MERGE (owner)-[r:MEMBER_OF]->(g)
#     SET r.role = "owner",
#         r.status = "approved",
#         r.updated_at = datetime()
#     """

#     Neo4jClient.execute(
#         query,
#         group_id=group.id,
#         name=group.name or "",
#         description=group.description or "",
#         cover_image=_cover_url(group),
#         is_private=bool(group.is_private),
#         is_activate=bool(group.is_activate),
#         owner_id=group.owner_id,
#         admin_can_approve_member=bool(group.admin_can_approve_member),
#         require_post_approval=bool(group.require_post_approval),
#         admin_can_approve_post=bool(group.admin_can_approve_post),
#         require_edit_approval=bool(group.require_edit_approval),
#         admin_can_approve_edit=bool(group.admin_can_approve_edit),
#         default_sort=group.default_sort,
#         created_at=group.created_at.isoformat(),
#         updated_at=group.updated_at.isoformat(),
#     )


# def mark_group_deleted_in_neo4j(group_id: int) -> None:
#     """
#     Không DETACH DELETE để tránh mất lịch sử.
#     Chỉ mark inactive để feed/recommendation không lấy nữa.
#     """
#     query = """
#     MATCH (g:Group {id: $group_id})
#     SET g.is_activate = false,
#         g.is_deleted = true,
#         g.synced_at = datetime()
#     """
#     Neo4jClient.execute(query, group_id=int(group_id))


# # =====================================================
# # 4. GROUP MEMBER EDGE
# # =====================================================

# def sync_group_member_to_neo4j(member: GroupMember) -> None:
#     """
#     Quy ước graph:
#     - approved: tạo MEMBER_OF thật, feed được phép dùng.
#     - pending/rejected: không tạo MEMBER_OF, chỉ lưu REQUESTED_JOIN_GROUP để admin/debug.
#     - banned: không tạo MEMBER_OF, chỉ lưu BANNED_FROM_GROUP.
#     """
#     _sync_user(member.user)
#     sync_group_to_neo4j(member.group)

#     if getattr(member.user, "is_deleted", False):
#         delete_group_member_from_neo4j(member.user_id, member.group_id)
#         mark_group_join_request_in_neo4j(
#             user_id=member.user_id,
#             group_id=member.group_id,
#             status="deleted_user",
#             role=member.role,
#             joined_at=member.joined_at,
#             updated_at=member.updated_at,
#         )
#         return

#     if member.status == "approved":
#         query = """
#         MATCH (u:User {id: $user_id})
#         MATCH (g:Group {id: $group_id})

#         OPTIONAL MATCH (u)-[req:REQUESTED_JOIN_GROUP]->(g)
#         DELETE req

#         WITH u, g
#         OPTIONAL MATCH (u)-[ban:BANNED_FROM_GROUP]->(g)
#         DELETE ban

#         WITH u, g
#         MERGE (u)-[r:MEMBER_OF]->(g)
#         SET r.role = $role,
#             r.status = "approved",
#             r.is_deleted = false,
#             r.joined_at = datetime($joined_at),
#             r.updated_at = datetime($updated_at),
#             r.synced_at = datetime()
#         """
#         Neo4jClient.execute(
#             query,
#             user_id=member.user_id,
#             group_id=member.group_id,
#             role=member.role,
#             joined_at=member.joined_at.isoformat(),
#             updated_at=member.updated_at.isoformat(),
#         )
#         return

#     # Không cho pending/rejected/banned tồn tại MEMBER_OF
#     delete_group_member_from_neo4j(member.user_id, member.group_id)

#     if member.status in ["pending", "rejected"]:
#         mark_group_join_request_in_neo4j(
#             user_id=member.user_id,
#             group_id=member.group_id,
#             status=member.status,
#             role=member.role,
#             joined_at=member.joined_at,
#             updated_at=member.updated_at,
#         )
#         return

#     if member.status == "banned":
#         mark_group_banned_member_in_neo4j(
#             user_id=member.user_id,
#             group_id=member.group_id,
#             role=member.role,
#             joined_at=member.joined_at,
#             updated_at=member.updated_at,
#         )
#         return
    
# def mark_group_join_request_in_neo4j(
#     user_id: int,
#     group_id: int,
#     status: str,
#     role: str = "member",
#     joined_at=None,
#     updated_at=None,
# ) -> None:
#     query = """
#     MATCH (u:User {id: $user_id})
#     MATCH (g:Group {id: $group_id})
#     MERGE (u)-[r:REQUESTED_JOIN_GROUP]->(g)
#     SET r.status = $status,
#         r.role = $role,
#         r.joined_at = CASE
#             WHEN $joined_at IS NULL THEN null
#             ELSE datetime($joined_at)
#         END,
#         r.updated_at = CASE
#             WHEN $updated_at IS NULL THEN datetime()
#             ELSE datetime($updated_at)
#         END,
#         r.synced_at = datetime()
#     """

#     Neo4jClient.execute(
#         query,
#         user_id=int(user_id),
#         group_id=int(group_id),
#         status=status,
#         role=role or "member",
#         joined_at=joined_at.isoformat() if joined_at else None,
#         updated_at=updated_at.isoformat() if updated_at else None,
#     )


# def mark_group_banned_member_in_neo4j(
#     user_id: int,
#     group_id: int,
#     role: str = "member",
#     joined_at=None,
#     updated_at=None,
# ) -> None:
#     query = """
#     MATCH (u:User {id: $user_id})
#     MATCH (g:Group {id: $group_id})
#     MERGE (u)-[r:BANNED_FROM_GROUP]->(g)
#     SET r.role = $role,
#         r.status = "banned",
#         r.joined_at = CASE
#             WHEN $joined_at IS NULL THEN null
#             ELSE datetime($joined_at)
#         END,
#         r.updated_at = CASE
#             WHEN $updated_at IS NULL THEN datetime()
#             ELSE datetime($updated_at)
#         END,
#         r.synced_at = datetime()
#     """

#     Neo4jClient.execute(
#         query,
#         user_id=int(user_id),
#         group_id=int(group_id),
#         role=role or "member",
#         joined_at=joined_at.isoformat() if joined_at else None,
#         updated_at=updated_at.isoformat() if updated_at else None,
#     )


# def delete_group_member_from_neo4j(user_id: int, group_id: int) -> None:
#     """
#     Dùng khi leave/remove/unban bằng cách xóa record GroupMember.
#     """
#     query = """
#     MATCH (:User {id: $user_id})-[r:MEMBER_OF]->(:Group {id: $group_id})
#     DELETE r
#     """
#     Neo4jClient.execute(
#         query,
#         user_id=int(user_id),
#         group_id=int(group_id),
#     )


# # =====================================================
# # 5. GROUP POST RELATION
# # =====================================================

# def sync_group_post_to_neo4j(group_post: GroupPost) -> None:
#     """
#     Sync quan hệ:
#     (:Post)-[:IN_GROUP]->(:Group)

#     Feed Neo4j đang dựa vào quan hệ này để lấy bài trong group user đã tham gia.
#     """
#     sync_group_to_neo4j(group_post.group)

#     query = """
#     MERGE (p:Post {id: $post_id})
#     SET p.author_id = $author_id,
#         p.privacy = $privacy,
#         p.status = $post_status,
#         p.is_deleted = $post_is_deleted,
#         p.created_at = datetime($post_created_at),
#         p.updated_at = datetime($post_updated_at)

#     WITH p
#     MATCH (g:Group {id: $group_id})
#     MERGE (p)-[r:IN_GROUP]->(g)
#     SET r.status = $status,
#         r.is_deleted = $is_deleted,
#         r.is_pinned = $is_pinned,
#         r.approved_by_id = $approved_by_id,
#         r.approved_at = CASE
#             WHEN $approved_at IS NULL THEN null
#             ELSE datetime($approved_at)
#         END,
#         r.created_at = datetime($created_at),
#         r.updated_at = datetime($updated_at),
#         r.synced_at = datetime()
#     """

#     Neo4jClient.execute(
#         query,
#         post_id=group_post.post_id,
#         author_id=group_post.post.author_id,
#         privacy=group_post.post.privacy,
#         post_status=group_post.post.status,
#         post_is_deleted=bool(group_post.post.is_deleted),
#         post_created_at=group_post.post.created_at.isoformat(),
#         post_updated_at=group_post.post.updated_at.isoformat(),

#         group_id=group_post.group_id,
#         status=group_post.status,
#         is_deleted=bool(group_post.is_deleted),
#         is_pinned=bool(group_post.is_pinned),
#         approved_by_id=group_post.approved_by_id,
#         approved_at=group_post.approved_at.isoformat() if group_post.approved_at else None,
#         created_at=group_post.created_at.isoformat(),
#         updated_at=group_post.updated_at.isoformat(),
#     )


# def mark_group_post_deleted_in_neo4j(group_post_id: int = None, post_id: int = None, group_id: int = None) -> None:
#     """
#     Soft delete quan hệ IN_GROUP.
#     Có thể truyền post_id + group_id là đủ.
#     """
#     if post_id and group_id:
#         query = """
#         MATCH (:Post {id: $post_id})-[r:IN_GROUP]->(:Group {id: $group_id})
#         SET r.is_deleted = true,
#             r.status = "deleted",
#             r.synced_at = datetime()
#         """
#         Neo4jClient.execute(
#             query,
#             post_id=int(post_id),
#             group_id=int(group_id),
#         )
#         return

#     if group_post_id:
#         return

#     raise ValueError("post_id + group_id is required.")


# # =====================================================
# # 6. ON_COMMIT WRAPPERS
# # =====================================================

# def sync_group_to_neo4j_on_commit(group: Group) -> None:
#     group_id = group.id

#     def _sync():
#         fresh = (
#             Group.objects
#             .select_related("owner", "owner__profile")
#             .filter(id=group_id)
#             .first()
#         )
#         if fresh:
#             sync_group_to_neo4j(fresh)

#     transaction.on_commit(_sync)


# def sync_group_member_to_neo4j_on_commit(member: GroupMember) -> None:
#     member_id = member.id

#     def _sync():
#         fresh = (
#             GroupMember.objects
#             .select_related("user", "user__profile", "group", "group__owner", "group__owner__profile")
#             .filter(id=member_id)
#             .first()
#         )
#         if fresh:
#             sync_group_member_to_neo4j(fresh)

#     transaction.on_commit(_sync)


# def delete_group_member_from_neo4j_on_commit(user_id: int, group_id: int) -> None:
#     transaction.on_commit(
#         lambda: delete_group_member_from_neo4j(user_id=user_id, group_id=group_id)
#     )


# def sync_group_post_to_neo4j_on_commit(group_post: GroupPost) -> None:
#     group_post_id = group_post.id

#     def _sync():
#         fresh = (
#             GroupPost.objects
#             .select_related(
#                 "group",
#                 "group__owner",
#                 "group__owner__profile",
#                 "post",
#                 "post__author",
#                 "post__author__profile",
#                 "approved_by",
#             )
#             .filter(id=group_post_id)
#             .first()
#         )
#         if fresh:
#             sync_group_post_to_neo4j(fresh)

#     transaction.on_commit(_sync)


# def mark_group_post_deleted_in_neo4j_on_commit(post_id: int, group_id: int) -> None:
#     transaction.on_commit(
#         lambda: mark_group_post_deleted_in_neo4j(post_id=post_id, group_id=group_id)
#     )


# def mark_group_deleted_in_neo4j_on_commit(group_id: int) -> None:
#     transaction.on_commit(
#         lambda: mark_group_deleted_in_neo4j(group_id)
#     )
# apps/groups/neo4j_sync.py
from __future__ import annotations

from django.db import transaction

from apps.accounts.models import User
from apps.groups.models import Group, GroupMember, GroupPost
from apps.friends.neo4j_client import Neo4jClient

try:
    from apps.accounts.neo4j_sync import sync_account_to_neo4j
except Exception:
    sync_account_to_neo4j = None


# =====================================================
# 1. SCHEMA
# =====================================================

def setup_group_graph_schema() -> None:
    queries = [
        """
        CREATE CONSTRAINT group_id_unique IF NOT EXISTS
        FOR (g:Group)
        REQUIRE g.id IS UNIQUE
        """,
        """
        CREATE CONSTRAINT user_id_unique IF NOT EXISTS
        FOR (u:User)
        REQUIRE u.id IS UNIQUE
        """,
        """
        CREATE CONSTRAINT post_id_unique IF NOT EXISTS
        FOR (p:Post)
        REQUIRE p.id IS UNIQUE
        """,
        """
        CREATE INDEX group_active_private_index IF NOT EXISTS
        FOR (g:Group)
        ON (g.is_activate, g.is_private)
        """,
        """
        CREATE INDEX group_name_index IF NOT EXISTS
        FOR (g:Group)
        ON (g.name)
        """,
    ]

    for query in queries:
        Neo4jClient.execute(query)


# =====================================================
# 2. HELPERS
# =====================================================

def _cover_url(group: Group) -> str:
    if not group.cover_image:
        return ""
    try:
        return group.cover_image.url
    except Exception:
        return ""


def _sync_user(user: User) -> None:
    """
    Dùng sync account chuẩn nếu bạn đã tạo apps.accounts.neo4j_sync.
    Nếu chưa có, fallback tạo User node tối thiểu.
    """
    if sync_account_to_neo4j:
        sync_account_to_neo4j(user)
        return

    Neo4jClient.execute(
        """
        MERGE (u:User {id: $id})
        SET u.username = $username,
            u.email = $email,
            u.is_active = $is_active,
            u.is_banned = $is_banned,
            u.updated_at = datetime()
        """,
        id=user.id,
        username=user.username or "",
        email=user.email or "",
        is_active=bool(user.is_active),
        is_banned=bool(user.is_banned),
    )


# =====================================================
# 3. GROUP NODE
# =====================================================

def sync_group_to_neo4j(group: Group) -> None:
    """
    Sync Group node và owner MEMBER_OF.

    Owner phải là MEMBER_OF để feed Neo4j nhìn thấy bài trong group của owner.
    """
    _sync_user(group.owner)

    query = """
    MERGE (g:Group {id: $group_id})
    SET g.name = $name,
        g.description = $description,
        g.cover_image = $cover_image,
        g.is_private = $is_private,
        g.is_activate = $is_activate,

        g.owner_id = $owner_id,

        g.admin_can_approve_member = $admin_can_approve_member,
        g.require_post_approval = $require_post_approval,
        g.admin_can_approve_post = $admin_can_approve_post,
        g.require_edit_approval = $require_edit_approval,
        g.admin_can_approve_edit = $admin_can_approve_edit,
        g.default_sort = $default_sort,

        g.created_at = datetime($created_at),
        g.updated_at = datetime($updated_at),
        g.synced_at = datetime()

    WITH g
    MATCH (owner:User {id: $owner_id})
    MERGE (owner)-[r:MEMBER_OF]->(g)
    SET r.role = "owner",
        r.status = "approved",
        r.updated_at = datetime()
    """

    Neo4jClient.execute(
        query,
        group_id=group.id,
        name=group.name or "",
        description=group.description or "",
        cover_image=_cover_url(group),
        is_private=bool(group.is_private),
        is_activate=bool(group.is_activate),
        owner_id=group.owner_id,
        admin_can_approve_member=bool(group.admin_can_approve_member),
        require_post_approval=bool(group.require_post_approval),
        admin_can_approve_post=bool(group.admin_can_approve_post),
        require_edit_approval=bool(group.require_edit_approval),
        admin_can_approve_edit=bool(group.admin_can_approve_edit),
        default_sort=group.default_sort,
        created_at=group.created_at.isoformat(),
        updated_at=group.updated_at.isoformat(),
    )


def mark_group_deleted_in_neo4j(group_id: int) -> None:
    """
    Không DETACH DELETE để tránh mất lịch sử.
    Chỉ mark inactive để feed/recommendation không lấy nữa.
    """
    query = """
    MATCH (g:Group {id: $group_id})
    SET g.is_activate = false,
        g.is_deleted = true,
        g.synced_at = datetime()
    """
    Neo4jClient.execute(query, group_id=int(group_id))


# =====================================================
# 4. GROUP MEMBER EDGE
# =====================================================

def sync_group_member_to_neo4j(member: GroupMember) -> None:
    """
    Quy ước graph:
    - approved: tạo MEMBER_OF thật, feed được phép dùng.
    - pending/rejected: không tạo MEMBER_OF, chỉ lưu REQUESTED_JOIN_GROUP để admin/debug.
    - banned: không tạo MEMBER_OF, chỉ lưu BANNED_FROM_GROUP.
    """
    _sync_user(member.user)
    sync_group_to_neo4j(member.group)

    if getattr(member.user, "is_deleted", False):
        delete_group_member_from_neo4j(member.user_id, member.group_id)
        mark_group_join_request_in_neo4j(
            user_id=member.user_id,
            group_id=member.group_id,
            status="deleted_user",
            role=member.role,
            joined_at=member.joined_at,
            updated_at=member.updated_at,
        )
        return

    if member.status == "approved":
        query = """
        MATCH (u:User {id: $user_id})
        MATCH (g:Group {id: $group_id})

        OPTIONAL MATCH (u)-[req:REQUESTED_JOIN_GROUP]->(g)
        DELETE req

        WITH u, g
        OPTIONAL MATCH (u)-[ban:BANNED_FROM_GROUP]->(g)
        DELETE ban

        WITH u, g
        MERGE (u)-[r:MEMBER_OF]->(g)
        SET r.role = $role,
            r.status = "approved",
            r.is_deleted = false,
            r.joined_at = datetime($joined_at),
            r.updated_at = datetime($updated_at),
            r.synced_at = datetime()
        """
        Neo4jClient.execute(
            query,
            user_id=member.user_id,
            group_id=member.group_id,
            role=member.role,
            joined_at=member.joined_at.isoformat(),
            updated_at=member.updated_at.isoformat(),
        )
        return

    # Không cho pending/rejected/banned tồn tại MEMBER_OF
    delete_group_member_from_neo4j(member.user_id, member.group_id)

    if member.status in ["pending", "rejected"]:
        mark_group_join_request_in_neo4j(
            user_id=member.user_id,
            group_id=member.group_id,
            status=member.status,
            role=member.role,
            joined_at=member.joined_at,
            updated_at=member.updated_at,
        )
        return

    if member.status == "banned":
        mark_group_banned_member_in_neo4j(
            user_id=member.user_id,
            group_id=member.group_id,
            role=member.role,
            joined_at=member.joined_at,
            updated_at=member.updated_at,
        )
        return
    
def mark_group_join_request_in_neo4j(
    user_id: int,
    group_id: int,
    status: str,
    role: str = "member",
    joined_at=None,
    updated_at=None,
) -> None:
    query = """
    MATCH (u:User {id: $user_id})
    MATCH (g:Group {id: $group_id})
    MERGE (u)-[r:REQUESTED_JOIN_GROUP]->(g)
    SET r.status = $status,
        r.role = $role,
        r.joined_at = CASE
            WHEN $joined_at IS NULL THEN null
            ELSE datetime($joined_at)
        END,
        r.updated_at = CASE
            WHEN $updated_at IS NULL THEN datetime()
            ELSE datetime($updated_at)
        END,
        r.synced_at = datetime()
    """

    Neo4jClient.execute(
        query,
        user_id=int(user_id),
        group_id=int(group_id),
        status=status,
        role=role or "member",
        joined_at=joined_at.isoformat() if joined_at else None,
        updated_at=updated_at.isoformat() if updated_at else None,
    )


def mark_group_banned_member_in_neo4j(
    user_id: int,
    group_id: int,
    role: str = "member",
    joined_at=None,
    updated_at=None,
) -> None:
    query = """
    MATCH (u:User {id: $user_id})
    MATCH (g:Group {id: $group_id})
    MERGE (u)-[r:BANNED_FROM_GROUP]->(g)
    SET r.role = $role,
        r.status = "banned",
        r.joined_at = CASE
            WHEN $joined_at IS NULL THEN null
            ELSE datetime($joined_at)
        END,
        r.updated_at = CASE
            WHEN $updated_at IS NULL THEN datetime()
            ELSE datetime($updated_at)
        END,
        r.synced_at = datetime()
    """

    Neo4jClient.execute(
        query,
        user_id=int(user_id),
        group_id=int(group_id),
        role=role or "member",
        joined_at=joined_at.isoformat() if joined_at else None,
        updated_at=updated_at.isoformat() if updated_at else None,
    )


def delete_group_member_from_neo4j(user_id: int, group_id: int) -> None:
    """
    Dùng khi leave/remove/unban/cancel pending request bằng cách xóa record GroupMember.

    Xóa toàn bộ relationship trạng thái giữa user và group để tránh graph còn giữ:
    - MEMBER_OF khi đã rời nhóm
    - REQUESTED_JOIN_GROUP khi đã hủy yêu cầu
    - BANNED_FROM_GROUP khi đã được gỡ chặn
    """
    query = """
    MATCH (:User {id: $user_id})-[r:MEMBER_OF|REQUESTED_JOIN_GROUP|BANNED_FROM_GROUP]->(:Group {id: $group_id})
    DELETE r
    """
    Neo4jClient.execute(
        query,
        user_id=int(user_id),
        group_id=int(group_id),
    )


# =====================================================
# 5. GROUP POST RELATION
# =====================================================

def sync_group_post_to_neo4j(group_post: GroupPost) -> None:
    """
    Sync quan hệ:
    (:Post)-[:IN_GROUP]->(:Group)

    Feed Neo4j đang dựa vào quan hệ này để lấy bài trong group user đã tham gia.
    """
    sync_group_to_neo4j(group_post.group)

    query = """
    MERGE (p:Post {id: $post_id})
    SET p.author_id = $author_id,
        p.privacy = $privacy,
        p.status = $post_status,
        p.is_deleted = $post_is_deleted,
        p.created_at = datetime($post_created_at),
        p.updated_at = datetime($post_updated_at)

    WITH p
    MATCH (g:Group {id: $group_id})
    MERGE (p)-[r:IN_GROUP]->(g)
    SET r.status = $status,
        r.is_deleted = $is_deleted,
        r.is_pinned = $is_pinned,
        r.approved_by_id = $approved_by_id,
        r.approved_at = CASE
            WHEN $approved_at IS NULL THEN null
            ELSE datetime($approved_at)
        END,
        r.created_at = datetime($created_at),
        r.updated_at = datetime($updated_at),
        r.synced_at = datetime()
    """

    Neo4jClient.execute(
        query,
        post_id=group_post.post_id,
        author_id=group_post.post.author_id,
        privacy=group_post.post.privacy,
        post_status=group_post.post.status,
        post_is_deleted=bool(group_post.post.is_deleted),
        post_created_at=group_post.post.created_at.isoformat(),
        post_updated_at=group_post.post.updated_at.isoformat(),

        group_id=group_post.group_id,
        status=group_post.status,
        is_deleted=bool(group_post.is_deleted),
        is_pinned=bool(group_post.is_pinned),
        approved_by_id=group_post.approved_by_id,
        approved_at=group_post.approved_at.isoformat() if group_post.approved_at else None,
        created_at=group_post.created_at.isoformat(),
        updated_at=group_post.updated_at.isoformat(),
    )


def mark_group_post_deleted_in_neo4j(group_post_id: int = None, post_id: int = None, group_id: int = None) -> None:
    """
    Soft delete quan hệ IN_GROUP.
    Có thể truyền post_id + group_id là đủ.
    """
    if post_id and group_id:
        query = """
        MATCH (:Post {id: $post_id})-[r:IN_GROUP]->(:Group {id: $group_id})
        SET r.is_deleted = true,
            r.status = "deleted",
            r.synced_at = datetime()
        """
        Neo4jClient.execute(
            query,
            post_id=int(post_id),
            group_id=int(group_id),
        )
        return

    if group_post_id:
        return

    raise ValueError("post_id + group_id is required.")


# =====================================================
# 6. ON_COMMIT WRAPPERS
# =====================================================

def sync_group_to_neo4j_on_commit(group: Group) -> None:
    group_id = group.id

    def _sync():
        fresh = (
            Group.objects
            .select_related("owner", "owner__profile")
            .filter(id=group_id)
            .first()
        )
        if fresh:
            sync_group_to_neo4j(fresh)

    transaction.on_commit(_sync)


def sync_group_member_to_neo4j_on_commit(member: GroupMember) -> None:
    member_id = member.id

    def _sync():
        fresh = (
            GroupMember.objects
            .select_related("user", "user__profile", "group", "group__owner", "group__owner__profile")
            .filter(id=member_id)
            .first()
        )
        if fresh:
            sync_group_member_to_neo4j(fresh)

    transaction.on_commit(_sync)


def delete_group_member_from_neo4j_on_commit(user_id: int, group_id: int) -> None:
    transaction.on_commit(
        lambda: delete_group_member_from_neo4j(user_id=user_id, group_id=group_id)
    )


def sync_group_post_to_neo4j_on_commit(group_post: GroupPost) -> None:
    group_post_id = group_post.id

    def _sync():
        fresh = (
            GroupPost.objects
            .select_related(
                "group",
                "group__owner",
                "group__owner__profile",
                "post",
                "post__author",
                "post__author__profile",
                "approved_by",
            )
            .filter(id=group_post_id)
            .first()
        )
        if fresh:
            sync_group_post_to_neo4j(fresh)

    transaction.on_commit(_sync)


def mark_group_post_deleted_in_neo4j_on_commit(post_id: int, group_id: int) -> None:
    transaction.on_commit(
        lambda: mark_group_post_deleted_in_neo4j(post_id=post_id, group_id=group_id)
    )


def mark_group_deleted_in_neo4j_on_commit(group_id: int) -> None:
    transaction.on_commit(
        lambda: mark_group_deleted_in_neo4j(group_id)
    )
