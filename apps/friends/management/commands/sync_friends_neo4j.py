from django.core.management.base import BaseCommand
from django.db import close_old_connections

from apps.accounts.models import User
from apps.accounts.neo4j_sync import (
    setup_account_graph_schema,
    sync_account_to_neo4j,
)
from apps.friends.models import FriendRequest, Friend, Block
from apps.friends.neo4j_client import Neo4jClient
from apps.friends.neo4j_recommendations import setup_neo4j_schema

try:
    from apps.groups.models import GroupMember
except Exception:
    GroupMember = None


def _iso(value):
    if not value:
        return None
    try:
        return value.isoformat()
    except Exception:
        return None


def iter_object_batches(queryset, batch_size):
    """
    Không dùng queryset.iterator() vì MySQL cursor sẽ bị giữ mở lâu
    trong lúc đang write sang Neo4j.
    """
    last_id = 0

    while True:
        close_old_connections()

        batch = list(
            queryset
            .filter(id__gt=last_id)
            .order_by("id")[:batch_size]
        )

        if not batch:
            break

        yield batch

        last_id = batch[-1].id
        close_old_connections()


def iter_value_batches(queryset, value_fields, batch_size):
    """
    Đọc dữ liệu theo id-window pagination.
    Mỗi batch là một query ngắn, tránh rớt MySQL connection.
    """
    last_id = 0

    while True:
        close_old_connections()

        rows = list(
            queryset
            .filter(id__gt=last_id)
            .order_by("id")
            .values_list("id", *value_fields)[:batch_size]
        )

        if not rows:
            break

        yield rows

        last_id = rows[-1][0]
        close_old_connections()


def bulk_sync_friend_requests(rows):
    payload = []

    for row in rows:
        request_id, from_user_id, to_user_id, status, created_at = row
        payload.append({
            "request_id": request_id,
            "from_user_id": from_user_id,
            "to_user_id": to_user_id,
            "status": status,
            "created_at": _iso(created_at),
        })

    if not payload:
        return 0

    query = """
    UNWIND $rows AS row

    MERGE (fromUser:User {id: row.from_user_id})
    MERGE (toUser:User {id: row.to_user_id})

    MERGE (fromUser)-[r:SENT_REQUEST]->(toUser)
    SET r.mysql_id = row.request_id,
        r.status = row.status,
        r.created_at = CASE
            WHEN row.created_at IS NULL THEN null
            ELSE datetime(row.created_at)
        END,
        r.updated_at = datetime()
    """

    Neo4jClient.execute(query, rows=payload)
    return len(payload)


def bulk_sync_friend_pairs(rows):
    payload = []
    seen_pairs = set()

    for row in rows:
        _, user_id, friend_id = row

        if not user_id or not friend_id:
            continue

        if user_id == friend_id:
            continue

        # MySQL có thể lưu 2 chiều, Neo4j dùng FRIEND_WITH dạng undirected.
        a, b = sorted([int(user_id), int(friend_id)])
        pair = (a, b)

        if pair in seen_pairs:
            continue

        seen_pairs.add(pair)

        payload.append({
            "user_id": a,
            "friend_id": b,
        })

    if not payload:
        return 0

    query = """
    UNWIND $rows AS row

    MERGE (a:User {id: row.user_id})
    MERGE (b:User {id: row.friend_id})

    MERGE (a)-[r:FRIEND_WITH]-(b)
    ON CREATE SET r.created_at = datetime()
    SET r.updated_at = datetime()
    """

    Neo4jClient.execute(query, rows=payload)
    return len(payload)


def bulk_sync_blocks(rows):
    payload = []

    for row in rows:
        block_id, blocker_id, blocked_id, created_at = row

        if not blocker_id or not blocked_id:
            continue

        payload.append({
            "block_id": block_id,
            "blocker_id": blocker_id,
            "blocked_id": blocked_id,
            "created_at": _iso(created_at),
        })

    if not payload:
        return 0

    query = """
    UNWIND $rows AS row

    MERGE (blocker:User {id: row.blocker_id})
    MERGE (blocked:User {id: row.blocked_id})

    MERGE (blocker)-[r:BLOCKED]->(blocked)
    SET r.mysql_id = row.block_id,
        r.created_at = CASE
            WHEN row.created_at IS NULL THEN null
            ELSE datetime(row.created_at)
        END,
        r.updated_at = datetime()
    """

    Neo4jClient.execute(query, rows=payload)
    return len(payload)


def bulk_sync_group_members(rows):
    payload = []

    for row in rows:
        (
            member_id,
            user_id,
            group_id,
            role,
            status,
            joined_at,
            updated_at,
            group_name,
            group_is_private,
            group_is_activate,
        ) = row

        if not user_id or not group_id:
            continue

        payload.append({
            "member_id": member_id,
            "user_id": user_id,
            "group_id": group_id,
            "role": role,
            "status": status,
            "joined_at": _iso(joined_at),
            "updated_at": _iso(updated_at),
            "group_name": group_name or "",
            "group_is_private": bool(group_is_private),
            "group_is_activate": bool(group_is_activate),
        })

    if not payload:
        return 0

    query = """
    UNWIND $rows AS row

    MERGE (u:User {id: row.user_id})

    MERGE (g:Group {id: row.group_id})
    SET g.name = row.group_name,
        g.is_private = row.group_is_private,
        g.is_activate = row.group_is_activate,
        g.updated_at = datetime()

    MERGE (u)-[r:MEMBER_OF]->(g)
    SET r.mysql_id = row.member_id,
        r.role = row.role,
        r.status = row.status,
        r.joined_at = CASE
            WHEN row.joined_at IS NULL THEN null
            ELSE datetime(row.joined_at)
        END,
        r.updated_at = CASE
            WHEN row.updated_at IS NULL THEN datetime()
            ELSE datetime(row.updated_at)
        END
    """

    Neo4jClient.execute(query, rows=payload)
    return len(payload)


class Command(BaseCommand):
    help = "Sync friends graph data from MySQL to Neo4j for friend recommendations"

    def add_arguments(self, parser):
        parser.add_argument(
            "--skip-users",
            action="store_true",
            help="Skip syncing account/user nodes. Use this if sync_accounts_neo4j was already run.",
        )
        parser.add_argument(
            "--skip-groups",
            action="store_true",
            help="Skip syncing approved group members.",
        )
        parser.add_argument(
            "--chunk-size",
            "--batch-size",
            dest="chunk_size",
            type=int,
            default=500,
            help="Batch size for MySQL reads and Neo4j writes.",
        )

    def handle(self, *args, **options):
        chunk_size = int(options["chunk_size"] or 500)

        self.stdout.write("Setting up Neo4j account schema...")
        setup_account_graph_schema()

        self.stdout.write("Setting up Neo4j friends schema...")
        setup_neo4j_schema()

        if not options["skip_users"]:
            self.stdout.write("Syncing account/user nodes...")

            total_users = 0

            user_qs = User.objects.select_related("profile").all()

            for batch in iter_object_batches(user_qs, chunk_size):
                for user in batch:
                    sync_account_to_neo4j(user)

                total_users += len(batch)
                self.stdout.write(f"  Synced users: {total_users}")

            self.stdout.write(self.style.SUCCESS(f"Synced {total_users} account/user nodes."))
        else:
            self.stdout.write("Skipping account/user node sync...")

        self.stdout.write("Syncing friend requests...")

        total_requests = 0
        request_qs = FriendRequest.objects.all()

        for rows in iter_value_batches(
            request_qs,
            ["from_user_id", "to_user_id", "status", "created_at"],
            chunk_size,
        ):
            total_requests += bulk_sync_friend_requests(rows)
            self.stdout.write(f"  Synced friend requests: {total_requests}")

        self.stdout.write("Syncing friends...")

        total_friends = 0
        friend_qs = Friend.objects.all()

        for rows in iter_value_batches(
            friend_qs,
            ["user_id", "friend_id"],
            chunk_size,
        ):
            total_friends += bulk_sync_friend_pairs(rows)
            self.stdout.write(f"  Synced friend pairs: {total_friends}")

        self.stdout.write("Syncing blocks...")

        total_blocks = 0
        block_qs = Block.objects.all()

        for rows in iter_value_batches(
            block_qs,
            ["blocker_id", "blocked_id", "created_at"],
            chunk_size,
        ):
            total_blocks += bulk_sync_blocks(rows)
            self.stdout.write(f"  Synced blocks: {total_blocks}")

        if not options["skip_groups"] and GroupMember is not None:
            self.stdout.write("Syncing approved group members...")

            total_members = 0

            member_qs = (
                GroupMember.objects
                .filter(status="approved")
                .select_related("group")
            )

            for rows in iter_value_batches(
                member_qs,
                [
                    "user_id",
                    "group_id",
                    "role",
                    "status",
                    "joined_at",
                    "updated_at",
                    "group__name",
                    "group__is_private",
                    "group__is_activate",
                ],
                chunk_size,
            ):
                total_members += bulk_sync_group_members(rows)
                self.stdout.write(f"  Synced approved group members: {total_members}")
        else:
            self.stdout.write("Skipping group member sync...")

        close_old_connections()

        self.stdout.write(self.style.SUCCESS("Neo4j friends graph sync completed."))