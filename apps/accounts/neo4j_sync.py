# apps/accounts/neo4j_sync.py
from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, List, Optional

from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User, UserProfile
from apps.friends.neo4j_client import Neo4jClient

logger = logging.getLogger(__name__)


# =====================================================
# 1. SMALL HELPERS
# =====================================================

def _get_profile(user: User) -> Optional[UserProfile]:
    try:
        return user.profile
    except Exception:
        return None


def _avatar_url(profile: Optional[UserProfile]) -> str:
    if not profile or not getattr(profile, "avatar", None):
        return ""

    try:
        return profile.avatar.url
    except Exception:
        return ""


def _iso_datetime(value) -> Optional[str]:
    if not value:
        return None

    try:
        return value.isoformat()
    except Exception:
        return None


def _birth_year(profile: Optional[UserProfile]) -> Optional[int]:
    if not profile or not profile.birth_day:
        return None

    try:
        return int(profile.birth_day.year)
    except Exception:
        return None


def _safe_text(value: Any) -> str:
    return str(value or "").strip()


def _build_user_payload(user: User) -> Dict[str, Any]:
    """
    Build data đưa sang Neo4j.

    Lưu ý:
    - Không sync password/token.
    - Không sync phone_number/address đầy đủ để tránh đưa dữ liệu nhạy cảm
      không cần thiết vào graph.
    - Chỉ sync field phục vụ feed, friend suggestion, search, ranking, moderation.
    """
    profile = _get_profile(user)

    return {
        "id": int(user.id),
        "email": _safe_text(user.email),
        "username": _safe_text(user.username),

        # account status
        "is_active": bool(user.is_active),
        "is_deleted": bool(getattr(user, "is_deleted", False)),
        "is_banned": bool(user.is_banned),
        "is_verified": bool(user.is_verified),
        "is_staff": bool(user.is_staff),
        "is_superuser": bool(user.is_superuser),
        "is_owner": bool(user.is_owner),
        "violation_score": int(user.violation_score or 0),

        # profile fields useful for recommendation
        "full_name": _safe_text(profile.full_name if profile else ""),
        "avatar": _avatar_url(profile),
        "bio": _safe_text(profile.bio if profile else ""),
        "school": _safe_text(profile.school if profile else ""),
        "province": _safe_text(profile.province if profile else ""),
        "town": _safe_text(profile.town if profile else ""),
        "nationality": _safe_text(profile.nationality if profile else ""),

        # date fields
        "birth_year": _birth_year(profile),
        "date_joined": _iso_datetime(user.date_joined),
        "date_banned": _iso_datetime(user.date_banned),
        "date_unactivate": _iso_datetime(user.date_unactivate),
        "deleted_at": _iso_datetime(getattr(user, "deleted_at", None)),
        "profile_created_at": _iso_datetime(profile.created_at if profile else None),
        "profile_updated_at": _iso_datetime(profile.updated_at if profile else None),
    }


# =====================================================
# 2. SCHEMA / INDEX
# =====================================================

def setup_account_graph_schema() -> None:
    """
    Chạy 1 lần khi deploy hoặc trước khi bulk sync.

    Safe to run multiple times.
    """
    queries = [
        """
        CREATE CONSTRAINT user_id_unique IF NOT EXISTS
        FOR (u:User)
        REQUIRE u.id IS UNIQUE
        """,
        """
        CREATE INDEX user_username_index IF NOT EXISTS
        FOR (u:User)
        ON (u.username)
        """,
        """
        CREATE INDEX user_email_index IF NOT EXISTS
        FOR (u:User)
        ON (u.email)
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
        CREATE INDEX user_town_index IF NOT EXISTS
        FOR (u:User)
        ON (u.town)
        """,
        """
        CREATE INDEX user_status_index IF NOT EXISTS
        FOR (u:User)
        ON (u.is_active, u.is_banned, u.is_verified)
        """,
        """
        CREATE INDEX user_violation_score_index IF NOT EXISTS
        FOR (u:User)
        ON (u.violation_score)
        """,
        """
        CREATE INDEX user_deleted_index IF NOT EXISTS
        FOR (u:User)
        ON (u.is_deleted)
        """,
    ]

    for query in queries:
        Neo4jClient.execute(query)


# =====================================================
# 3. SINGLE USER SYNC
# =====================================================

def sync_account_to_neo4j(user: User) -> None:
    """
    Sync đầy đủ User + UserProfile sang Neo4j.

    Dùng cho:
    - register
    - verify email
    - update profile
    - change email
    - change username
    - activate/deactivate
    - ban/unban
    - violation score changed
    """
    payload = _build_user_payload(user)

    query = """
    MERGE (u:User {id: $id})
    SET
        u.email = $email,
        u.username = $username,

        u.is_active = $is_active,
        u.is_deleted = $is_deleted,
        u.is_banned = $is_banned,
        u.is_verified = $is_verified,
        u.is_staff = $is_staff,
        u.is_superuser = $is_superuser,
        u.is_owner = $is_owner,
        u.violation_score = $violation_score,

        u.full_name = $full_name,
        u.avatar = $avatar,
        u.bio = $bio,
        u.school = $school,
        u.province = $province,
        u.town = $town,
        u.nationality = $nationality,

        u.birth_year = $birth_year,

        u.date_joined = CASE
            WHEN $date_joined IS NULL THEN null
            ELSE datetime($date_joined)
        END,
        u.date_banned = CASE
            WHEN $date_banned IS NULL THEN null
            ELSE datetime($date_banned)
        END,
        u.date_unactivate = CASE
            WHEN $date_unactivate IS NULL THEN null
            ELSE datetime($date_unactivate)
        END,
        u.deleted_at = CASE
            WHEN $deleted_at IS NULL THEN null
            ELSE datetime($deleted_at)
        END,
        u.profile_created_at = CASE
            WHEN $profile_created_at IS NULL THEN null
            ELSE datetime($profile_created_at)
        END,
        u.profile_updated_at = CASE
            WHEN $profile_updated_at IS NULL THEN null
            ELSE datetime($profile_updated_at)
        END,

        u.updated_at = datetime()
    """

    Neo4jClient.execute(query, **payload)


def sync_account_status_to_neo4j(user: User) -> None:
    """
    Sync nhanh các field trạng thái tài khoản.

    Dùng khi:
    - active/deactive
    - ban/unban
    - verify email
    - tăng violation_score
    """
    query = """
    MERGE (u:User {id: $id})
    SET
        u.email = $email,
        u.username = $username,
        u.is_active = $is_active,
        u.is_deleted = $is_deleted,
        u.is_banned = $is_banned,
        u.is_verified = $is_verified,
        u.is_staff = $is_staff,
        u.is_superuser = $is_superuser,
        u.is_owner = $is_owner,
        u.violation_score = $violation_score,
        u.date_banned = CASE
            WHEN $date_banned IS NULL THEN null
            ELSE datetime($date_banned)
        END,
        u.date_unactivate = CASE
            WHEN $date_unactivate IS NULL THEN null
            ELSE datetime($date_unactivate)
        END,
        u.deleted_at = CASE
            WHEN $deleted_at IS NULL THEN null
            ELSE datetime($deleted_at)
        END,
        u.updated_at = datetime()
    """

    Neo4jClient.execute(
        query,
        id=int(user.id),
        email=user.email or "",
        username=user.username or "",
        is_active=bool(user.is_active),
        is_deleted=bool(getattr(user, "is_deleted", False)),
        is_banned=bool(user.is_banned),
        is_verified=bool(user.is_verified),
        is_staff=bool(user.is_staff),
        is_superuser=bool(user.is_superuser),
        is_owner=bool(user.is_owner),
        violation_score=int(user.violation_score or 0),
        date_banned=_iso_datetime(user.date_banned),
        date_unactivate=_iso_datetime(user.date_unactivate),
        deleted_at=_iso_datetime(getattr(user, "deleted_at", None)),
    )


def sync_account_profile_to_neo4j(profile: UserProfile) -> None:
    """
    Sync profile bằng object profile.
    Thực chất vẫn sync full account để node User luôn đầy đủ.
    """
    sync_account_to_neo4j(profile.user)


def mark_account_inactive_in_neo4j(user_id: int) -> None:
    """
    Dùng khi hard delete hoặc muốn ẩn user khỏi mọi query gợi ý/feed.
    Không DETACH DELETE để giữ lịch sử graph.
    """
    query = """
    MATCH (u:User {id: $user_id})
    SET u.is_active = false,
        u.is_deleted = true,
        u.deleted_at = datetime(),
        u.date_unactivate = datetime(),
        u.updated_at = datetime()
    """
    Neo4jClient.execute(query, user_id=int(user_id))


# =====================================================
# 4. SAFE ON_COMMIT HELPERS
# =====================================================

def sync_account_to_neo4j_on_commit(user: User) -> None:
    user_id = user.id

    def _sync():
        fresh_user = User.objects.select_related("profile").filter(id=user_id).first()
        if fresh_user:
            sync_account_to_neo4j(fresh_user)

    transaction.on_commit(_sync)


def sync_account_status_to_neo4j_on_commit(user: User) -> None:
    user_id = user.id

    def _sync():
        fresh_user = User.objects.filter(id=user_id).first()
        if fresh_user:
            sync_account_status_to_neo4j(fresh_user)

    transaction.on_commit(_sync)


# =====================================================
# 5. BULK SYNC / BACKFILL
# =====================================================

def _bulk_upsert_user_nodes(payloads: List[Dict[str, Any]]) -> int:
    if not payloads:
        return 0

    query = """
    UNWIND $users AS row
    MERGE (u:User {id: row.id})
    SET
        u.email = row.email,
        u.username = row.username,

        u.is_active = row.is_active,
        u.is_deleted = row.is_deleted,
        u.is_banned = row.is_banned,
        u.is_verified = row.is_verified,
        u.is_staff = row.is_staff,
        u.is_superuser = row.is_superuser,
        u.is_owner = row.is_owner,
        u.violation_score = row.violation_score,

        u.full_name = row.full_name,
        u.avatar = row.avatar,
        u.bio = row.bio,
        u.school = row.school,
        u.province = row.province,
        u.town = row.town,
        u.nationality = row.nationality,
        u.birth_year = row.birth_year,

        u.date_joined = CASE
            WHEN row.date_joined IS NULL THEN null
            ELSE datetime(row.date_joined)
        END,
        u.date_banned = CASE
            WHEN row.date_banned IS NULL THEN null
            ELSE datetime(row.date_banned)
        END,
        u.date_unactivate = CASE
            WHEN row.date_unactivate IS NULL THEN null
            ELSE datetime(row.date_unactivate)
        END,
        u.deleted_at = CASE
            WHEN row.deleted_at IS NULL THEN null
            ELSE datetime(row.deleted_at)
        END,
        u.profile_created_at = CASE
            WHEN row.profile_created_at IS NULL THEN null
            ELSE datetime(row.profile_created_at)
        END,
        u.profile_updated_at = CASE
            WHEN row.profile_updated_at IS NULL THEN null
            ELSE datetime(row.profile_updated_at)
        END,

        u.updated_at = datetime()
    """

    Neo4jClient.execute(query, users=payloads)
    return len(payloads)


def bulk_sync_accounts_to_neo4j(batch_size: int = 500) -> int:
    """
    Backfill toàn bộ User + UserProfile từ MySQL sang Neo4j.

    Chạy bằng management command hoặc Django shell.
    """
    setup_account_graph_schema()

    total = 0
    payloads: List[Dict[str, Any]] = []

    queryset = (
        User.objects
        .select_related("profile")
        .order_by("id")
    )

    for user in queryset.iterator(chunk_size=batch_size):
        payloads.append(_build_user_payload(user))

        if len(payloads) >= batch_size:
            total += _bulk_upsert_user_nodes(payloads)
            payloads = []

    if payloads:
        total += _bulk_upsert_user_nodes(payloads)

    return total