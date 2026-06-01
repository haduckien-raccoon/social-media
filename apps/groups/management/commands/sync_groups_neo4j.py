# apps/groups/management/commands/sync_groups_neo4j.py
from django.core.management.base import BaseCommand

from apps.groups.models import Group, GroupMember, GroupPost
from apps.groups.neo4j_sync import (
    setup_group_graph_schema,
    sync_group_to_neo4j,
    sync_group_member_to_neo4j,
    sync_group_post_to_neo4j,
)
from apps.posts.neo4j_feed import (
    setup_feed_constraints,
    sync_post_node,
    sync_post_hashtags,
    sync_tagged_users,
)


class Command(BaseCommand):
    help = "Sync groups, group members, and group posts from MySQL to Neo4j."

    def add_arguments(self, parser):
        parser.add_argument(
            "--chunk-size",
            type=int,
            default=1000,
            help="Django ORM iterator chunk size.",
        )
        parser.add_argument(
            "--skip-posts",
            action="store_true",
            help="Skip syncing Post nodes/hashtags/tagged users for group posts.",
        )

    def handle(self, *args, **options):
        chunk_size = options["chunk_size"]

        self.stdout.write("Setting up Neo4j group/feed schema...")
        setup_group_graph_schema()
        setup_feed_constraints()

        self.stdout.write("Syncing groups...")
        for group in (
            Group.objects
            .select_related("owner", "owner__profile")
            .all()
            .iterator(chunk_size=chunk_size)
        ):
            sync_group_to_neo4j(group)

        self.stdout.write("Syncing group members...")
        for member in (
            GroupMember.objects
            .select_related("user", "user__profile", "group", "group__owner", "group__owner__profile")
            .all()
            .iterator(chunk_size=chunk_size)
        ):
            sync_group_member_to_neo4j(member)

        self.stdout.write("Syncing group posts...")
        for group_post in (
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
            .all()
            .iterator(chunk_size=chunk_size)
        ):
            if not options["skip_posts"]:
                sync_post_node(group_post.post)
                sync_post_hashtags(group_post.post)
                sync_tagged_users(group_post.post)

            sync_group_post_to_neo4j(group_post)

        self.stdout.write(
            self.style.SUCCESS("Neo4j groups graph sync completed.")
        )