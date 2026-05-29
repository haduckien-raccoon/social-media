from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

from django.conf import settings

from apps.accounts.models import User
from apps.friends.models import FriendRequest, Friend, Block
from apps.friends.neo4j_client import Neo4jClient

try:
    from apps.groups.models import GroupMember
except Exception:  # groups app may be unavailable in some deployments
    GroupMember = None


@dataclass
class Neo4jSuggestedUser:
    """Template-friendly object returned by Neo4j-only friend suggestion query."""

    id: int
    username: str = ""
    email: str = ""
    full_name: str = ""
    avatar: str = ""
    school: str = ""
    province: str = ""
    town: str = ""
    mutual_count: int = 0
    common_group_count: int = 0
    profile_view_count: int = 0
    same_school: int = 0
    same_province: int = 0
    score: float = 0.0
    relation_status: str = "none"

    def __str__(self):
        return self.username or self.full_name or str(self.id)


def _avatar_url(user: User) -> Optional[str]:
    profile = getattr(user, "profile", None)
    if not profile or not getattr(profile, "avatar", None):
        return None
    try:
        return profile.avatar.url
    except Exception:
        return None


def setup_neo4j_schema():
    """Run once before syncing. Safe to call multiple times."""

    queries = [
        """
        CREATE CONSTRAINT user_id_unique IF NOT EXISTS
        FOR (u:User)
        REQUIRE u.id IS UNIQUE
        """,
        """
        CREATE CONSTRAINT group_id_unique IF NOT EXISTS
        FOR (g:Group)
        REQUIRE g.id IS UNIQUE
        """,
        """
        CREATE INDEX user_school_index IF NOT EXISTS
        FOR (u:User)
        ON (u.school)
        """,
        """
        CREATE INDEX user_province_index IF NOT EXISTS
        FOR (u:User)
        ON (u.province)
        """,
        """
        CREATE INDEX user_active_banned_index IF NOT EXISTS
        FOR (u:User)
        ON (u.is_active, u.is_banned)
        """,
    ]

    for query in queries:
        Neo4jClient.execute(query)


def sync_user_to_neo4j(user: User):
    profile = getattr(user, "profile", None)

    query = """
    MERGE (u:User {id: $id})
    SET u.username = $username,
        u.email = $email,
        u.full_name = $full_name,
        u.avatar = $avatar,
        u.school = $school,
        u.province = $province,
        u.town = $town,
        u.is_active = $is_active,
        u.is_banned = $is_banned,
        u.updated_at = datetime()
    """

    Neo4jClient.execute(
        query,
        id=user.id,
        username=user.username or "",
        email=user.email or "",
        full_name=(profile.full_name if profile else None) or "",
        avatar=_avatar_url(user) or "",
        school=(profile.school if profile else None) or "",
        province=(profile.province if profile else None) or "",
        town=(profile.town if profile else None) or "",
        is_active=bool(user.is_active),
        is_banned=bool(user.is_banned),
    )


def sync_friend_request_to_neo4j(friend_request: FriendRequest):
    sync_user_to_neo4j(friend_request.from_user)
    sync_user_to_neo4j(friend_request.to_user)

    query = """
    MATCH (fromUser:User {id: $from_user_id})
    MATCH (toUser:User {id: $to_user_id})
    MERGE (fromUser)-[r:SENT_REQUEST]->(toUser)
    SET r.mysql_id = $request_id,
        r.status = $status,
        r.created_at = datetime($created_at),
        r.updated_at = datetime()
    """

    Neo4jClient.execute(
        query,
        request_id=friend_request.id,
        from_user_id=friend_request.from_user_id,
        to_user_id=friend_request.to_user_id,
        status=friend_request.status,
        created_at=friend_request.created_at.isoformat(),
    )


def delete_friend_request_from_neo4j(from_user_id: int, to_user_id: int):
    query = """
    MATCH (:User {id: $from_user_id})-[r:SENT_REQUEST]->(:User {id: $to_user_id})
    DELETE r
    """
    Neo4jClient.execute(query, from_user_id=from_user_id, to_user_id=to_user_id)


def sync_friend_to_neo4j(user_id: int, friend_id: int):
    query = """
    MATCH (a:User {id: $user_id})
    MATCH (b:User {id: $friend_id})
    MERGE (a)-[r:FRIEND_WITH]-(b)
    ON CREATE SET r.created_at = datetime()
    SET r.updated_at = datetime()
    """
    Neo4jClient.execute(query, user_id=user_id, friend_id=friend_id)


def delete_friend_from_neo4j(user_id: int, friend_id: int):
    query = """
    MATCH (:User {id: $user_id})-[r:FRIEND_WITH]-(:User {id: $friend_id})
    DELETE r
    """
    Neo4jClient.execute(query, user_id=user_id, friend_id=friend_id)


def sync_block_to_neo4j(block: Block):
    sync_user_to_neo4j(block.blocker)
    sync_user_to_neo4j(block.blocked)

    query = """
    MATCH (blocker:User {id: $blocker_id})
    MATCH (blocked:User {id: $blocked_id})
    MERGE (blocker)-[r:BLOCKED]->(blocked)
    SET r.created_at = datetime($created_at),
        r.updated_at = datetime()
    """
    Neo4jClient.execute(
        query,
        blocker_id=block.blocker_id,
        blocked_id=block.blocked_id,
        created_at=block.created_at.isoformat(),
    )


def delete_block_from_neo4j(blocker_id: int, blocked_id: int):
    query = """
    MATCH (:User {id: $blocker_id})-[r:BLOCKED]->(:User {id: $blocked_id})
    DELETE r
    """
    Neo4jClient.execute(query, blocker_id=blocker_id, blocked_id=blocked_id)


def sync_group_member_to_neo4j(group_member):
    if group_member.status != "approved":
        return

    sync_user_to_neo4j(group_member.user)

    query = """
    MERGE (g:Group {id: $group_id})
    SET g.name = $group_name,
        g.is_private = $is_private,
        g.updated_at = datetime()
    WITH g
    MATCH (u:User {id: $user_id})
    MERGE (u)-[r:MEMBER_OF]->(g)
    SET r.role = $role,
        r.status = $status,
        r.joined_at = datetime($joined_at),
        r.updated_at = datetime()
    """

    Neo4jClient.execute(
        query,
        group_id=group_member.group_id,
        group_name=group_member.group.name,
        is_private=bool(group_member.group.is_private),
        user_id=group_member.user_id,
        role=group_member.role,
        status=group_member.status,
        joined_at=group_member.joined_at.isoformat(),
    )


def sync_profile_view_to_neo4j(search_history):
    if not getattr(search_history, "target_user_id", None):
        return

    sync_user_to_neo4j(search_history.user)
    sync_user_to_neo4j(search_history.target_user)

    query = """
    MATCH (u:User {id: $user_id})
    MATCH (target:User {id: $target_user_id})
    ON CREATE SET r.count = 1,
                  r.first_seen_at = datetime($created_at)
    ON MATCH SET r.count = coalesce(r.count, 0) + 1
    SET r.last_seen_at = datetime($updated_at)
    """

    Neo4jClient.execute(
        query,
        user_id=search_history.user_id,
        target_user_id=search_history.target_user_id,
        created_at=search_history.created_at.isoformat(),
        updated_at=search_history.updated_at.isoformat(),
    )


# def get_friend_suggestions_from_neo4j(user: User, limit: int = 10) -> list[Neo4jSuggestedUser]:
#     """
#     Neo4j-only recommendation query.

#     MySQL is NOT used for candidate search, mutual friends, pending request filtering,
#     block filtering, or scoring. The returned objects contain display data from Neo4j.
#     """

#     # Ensure current user node exists even if initial sync was not run yet.
#     sync_user_to_neo4j(user)

#     query = """
#     MATCH (me:User {id: $user_id})

#     CALL {
#         WITH me
#         MATCH (me)-[:FRIEND_WITH]-(mutual:User)-[:FRIEND_WITH]-(candidate:User)
#         RETURN candidate

#         UNION

#         WITH me
#         MATCH (me)-[:MEMBER_OF]->(:Group)<-[:MEMBER_OF]-(candidate:User)
#         RETURN candidate

#         UNION

#         WITH me
#         MATCH (me)-[:VIEWED_PROFILE]->(candidate:User)
#         RETURN candidate

#         UNION

#         WITH me
#         MATCH (candidate:User)
#         WHERE me.school <> "" AND candidate.school = me.school
#         RETURN candidate

#         UNION

#         WITH me
#         MATCH (candidate:User)
#         WHERE me.province <> "" AND candidate.province = me.province
#         RETURN candidate
#     }

#     WITH DISTINCT me, candidate
#     WHERE candidate.id <> me.id
#       AND coalesce(candidate.is_active, false) = true
#       AND coalesce(candidate.is_banned, false) = false
#       AND NOT (me)-[:FRIEND_WITH]-(candidate)
#       AND NOT (me)-[:SENT_REQUEST {status: "pending"}]->(candidate)
#       AND NOT (candidate)-[:SENT_REQUEST {status: "pending"}]->(me)
#       AND NOT (me)-[:BLOCKED]->(candidate)
#       AND NOT (candidate)-[:BLOCKED]->(me)

#     OPTIONAL MATCH (me)-[:FRIEND_WITH]-(mutual:User)-[:FRIEND_WITH]-(candidate)
#     WITH me, candidate, count(DISTINCT mutual) AS mutual_count

#     OPTIONAL MATCH (me)-[view:VIEWED_PROFILE]->(candidate)
#     WITH me, candidate, mutual_count, coalesce(view.count, 0) AS profile_view_count

#     OPTIONAL MATCH (me)-[:MEMBER_OF]->(g:Group)<-[:MEMBER_OF]-(candidate)
#     WITH me, candidate, mutual_count, profile_view_count, count(DISTINCT g) AS common_group_count

#     WITH candidate,
#          mutual_count,
#          profile_view_count,
#          common_group_count,
#          CASE WHEN me.school <> "" AND me.school = candidate.school THEN 1 ELSE 0 END AS same_school,
#          CASE WHEN me.province <> "" AND me.province = candidate.province THEN 1 ELSE 0 END AS same_province

#     WITH candidate,
#          mutual_count,
#          profile_view_count,
#          common_group_count,
#          same_school,
#          same_province,
#          mutual_count * 10
#            + common_group_count * 3
#            + profile_view_count * 2
#            + same_school * 4
#            + same_province * 2 AS score

#     RETURN candidate.id AS id,
#            candidate.username AS username,
#            candidate.email AS email,
#            candidate.full_name AS full_name,
#            candidate.avatar AS avatar,
#            candidate.school AS school,
#            candidate.province AS province,
#            candidate.town AS town,
#            mutual_count,
#            common_group_count,
#            profile_view_count,
#            same_school,
#            same_province,
#            score
#     ORDER BY score DESC, mutual_count DESC, common_group_count DESC
#     LIMIT $limit
#     """

#     records = Neo4jClient.execute(query, user_id=user.id, limit=int(limit or 10))

#     return [
#         Neo4jSuggestedUser(
#             id=record["id"],
#             username=record.get("username") or "",
#             email=record.get("email") or "",
#             full_name=record.get("full_name") or "",
#             avatar=record.get("avatar") or "",
#             school=record.get("school") or "",
#             province=record.get("province") or "",
#             town=record.get("town") or "",
#             mutual_count=int(record.get("mutual_count") or 0),
#             common_group_count=int(record.get("common_group_count") or 0),
#             profile_view_count=int(record.get("profile_view_count") or 0),
#             same_school=int(record.get("same_school") or 0),
#             same_province=int(record.get("same_province") or 0),
#             score=float(record.get("score") or 0),
#             relation_status="none",
#         )
#         for record in records
#     ]
def get_friend_suggestions_from_neo4j(user, limit=10) -> list[Neo4jSuggestedUser]:
    query = """
    MATCH (me:User {id: $user_id})

    CALL (me) {
        // Nguồn 1: bạn của bạn
        MATCH (me)-[:FRIEND_WITH]-(mutual:User)-[:FRIEND_WITH]-(candidate:User)
        RETURN candidate, 5 AS source_bonus

        UNION

        // Nguồn 2: cùng group
        MATCH (me)-[:MEMBER_OF]->(:Group)<-[:MEMBER_OF]-(candidate:User)
        RETURN candidate, 3 AS source_bonus

        UNION

        // Nguồn 4: cùng trường
        MATCH (candidate:User)
        WHERE coalesce(me.school, "") <> ""
          AND candidate.school = me.school
        RETURN candidate, 1 AS source_bonus

        UNION

        // Nguồn 5: cùng tỉnh/thành
        MATCH (candidate:User)
        WHERE coalesce(me.province, "") <> ""
          AND candidate.province = me.province
        RETURN candidate, 1 AS source_bonus

        UNION

        // Nguồn 6: fallback cho admin/user mới
        // Lấy tất cả user hợp lệ sơ bộ, sau đó lọc kỹ ở ngoài.
        MATCH (candidate:User)
        RETURN candidate, 0 AS source_bonus
    }

    WITH me, candidate, max(source_bonus) AS source_bonus

    WHERE candidate.id <> me.id
      AND coalesce(candidate.is_active, false) = true
      AND coalesce(candidate.is_banned, false) = false

      // Không gợi ý người đã là bạn
      AND NOT (me)-[:FRIEND_WITH]-(candidate)

      // Không gợi ý người đang có request pending 2 chiều
      AND NOT (me)-[:SENT_REQUEST {status: "pending"}]->(candidate)
      AND NOT (candidate)-[:SENT_REQUEST {status: "pending"}]->(me)

      // Không gợi ý người bị block 2 chiều
      AND NOT (me)-[:BLOCKED]->(candidate)
      AND NOT (candidate)-[:BLOCKED]->(me)

    OPTIONAL MATCH (me)-[:FRIEND_WITH]-(mutual:User)-[:FRIEND_WITH]-(candidate)
    WITH me, candidate, source_bonus, count(DISTINCT mutual) AS mutual_count


    OPTIONAL MATCH (me)-[:MEMBER_OF]->(g:Group)<-[:MEMBER_OF]-(candidate)
    WITH me, candidate, source_bonus, mutual_count, count(DISTINCT g) AS common_group_count

    WITH candidate,
         source_bonus,
         mutual_count,
         common_group_count,
         CASE
            WHEN coalesce(me.school, "") <> ""
             AND me.school = candidate.school
            THEN 1 ELSE 0
         END AS same_school,
         CASE
            WHEN coalesce(me.province, "") <> ""
             AND me.province = candidate.province
            THEN 1 ELSE 0
         END AS same_province

    WITH candidate,
         source_bonus,
         mutual_count,
         common_group_count,
         same_school,
         same_province,
         mutual_count * 10
           + common_group_count * 3
           + same_school * 4
           + same_province * 2
           + source_bonus AS score

    RETURN candidate.id AS id,
           candidate.username AS username,
           candidate.email AS email,
           candidate.full_name AS full_name,
           candidate.avatar AS avatar,
           candidate.school AS school,
           candidate.province AS province,
           candidate.town AS town,
           mutual_count,
           common_group_count,
           same_school,
           same_province,
           source_bonus,
           score
    ORDER BY score DESC,
             mutual_count DESC,
             common_group_count DESC,
             same_school DESC,
             same_province DESC,
             candidate.id ASC
    LIMIT $limit
    """

    records = Neo4jClient.execute(
        query,
        user_id=user.id,
        limit=limit,
    )

    return [record.data() for record in records]