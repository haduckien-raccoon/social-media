from django.core.management.base import BaseCommand

from apps.accounts.models import User
from apps.friends.models import FriendRequest, Friend, Block
from apps.friends.neo4j_recommendations import (
    setup_neo4j_schema,
    sync_user_to_neo4j,
    sync_friend_request_to_neo4j,
    sync_friend_to_neo4j,
    sync_block_to_neo4j,
    sync_group_member_to_neo4j,
)

try:
    from apps.groups.models import GroupMember
except Exception:
    GroupMember = None


class Command(BaseCommand):
    help = "Sync friends graph data from MySQL to Neo4j for friend recommendations"

    def add_arguments(self, parser):
        parser.add_argument(
            "--skip-groups",
            action="store_true",
            help="Skip syncing approved group members",
        )

    def handle(self, *args, **options):
        self.stdout.write("Setting up Neo4j schema...")
        setup_neo4j_schema()

        self.stdout.write("Syncing users...")
        for user in User.objects.select_related("profile").all().iterator(chunk_size=1000):
            sync_user_to_neo4j(user)

        self.stdout.write("Syncing friend requests...")
        for req in FriendRequest.objects.select_related("from_user", "to_user").all().iterator(chunk_size=1000):
            sync_friend_request_to_neo4j(req)

        self.stdout.write("Syncing friends...")
        seen_pairs = set()
        for friend in Friend.objects.all().iterator(chunk_size=1000):
            pair = tuple(sorted([friend.user_id, friend.friend_id]))
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            sync_friend_to_neo4j(friend.user_id, friend.friend_id)

        self.stdout.write("Syncing blocks...")
        for block in Block.objects.select_related("blocker", "blocked").all().iterator(chunk_size=1000):
            sync_block_to_neo4j(block)

        if not options["skip_groups"] and GroupMember is not None:
            self.stdout.write("Syncing approved group members...")
            for member in (
                GroupMember.objects
                .select_related("user", "group")
                .filter(status="approved")
                .iterator(chunk_size=1000)
            ):
                sync_group_member_to_neo4j(member)

        self.stdout.write(self.style.SUCCESS("Neo4j friends graph sync completed."))
