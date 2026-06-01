from django.core.management.base import BaseCommand
from django.db import close_old_connections

from apps.accounts.models import User
from apps.posts.models import Post, Comment, Hashtag
from apps.moderation.models import ContentModerationLog, ModerationTargetType
from apps.accounts.neo4j_sync import sync_account_to_neo4j
from apps.posts.neo4j_feed import (
    sync_post_node,
    sync_post_hashtags,
    sync_tagged_users,
    refresh_comment_interaction_edge,
)
from apps.admin.neo4j_sync import (
    sync_moderation_log_to_neo4j,
    sync_comment_moderation_node_to_neo4j,
    sync_hashtag_node_to_neo4j,
)


def iter_batches(queryset, batch_size):
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


class Command(BaseCommand):
    help = "Backfill admin/moderation-related graph data to Neo4j."

    def add_arguments(self, parser):
        parser.add_argument(
            "--chunk-size",
            type=int,
            default=300,
            help="Batch size for MySQL reads.",
        )
        parser.add_argument(
            "--skip-posts",
            action="store_true",
            help="Skip re-syncing moderated posts.",
        )
        parser.add_argument(
            "--skip-comments",
            action="store_true",
            help="Skip re-syncing moderated comments.",
        )
        parser.add_argument(
            "--skip-hashtags",
            action="store_true",
            help="Skip re-syncing hashtags.",
        )
        parser.add_argument(
            "--skip-logs",
            action="store_true",
            help="Skip syncing moderation logs.",
        )

    def handle(self, *args, **options):
        chunk_size = int(options["chunk_size"] or 300)

        if not options["skip_posts"]:
            self.stdout.write("Syncing moderated/deleted/flagged posts...")

            post_qs = (
                Post.objects
                .select_related("author", "author__profile")
                .filter(is_deleted=True)
            )

            total = 0
            for batch in iter_batches(post_qs, chunk_size):
                for post in batch:
                    sync_post_node(post)
                    sync_post_hashtags(post)
                    sync_tagged_users(post)

                total += len(batch)
                self.stdout.write(f"  Synced posts: {total}")

        if not options["skip_comments"]:
            self.stdout.write("Syncing moderated/deleted comments...")

            comment_qs = (
                Comment.objects
                .select_related("user", "user__profile", "post", "post__author")
                .filter(is_deleted=True)
            )

            total = 0
            for batch in iter_batches(comment_qs, chunk_size):
                for comment in batch:
                    sync_comment_moderation_node_to_neo4j(comment)

                    alive_count = Comment.objects.filter(
                        user_id=comment.user_id,
                        post_id=comment.post_id,
                        is_deleted=False,
                    ).count()

                    refresh_comment_interaction_edge(
                        user_id=comment.user_id,
                        username=comment.user.username,
                        post_id=comment.post_id,
                        comment_count=alive_count,
                    )

                    sync_post_node(comment.post)

                total += len(batch)
                self.stdout.write(f"  Synced comments: {total}")

        if not options["skip_hashtags"]:
            self.stdout.write("Syncing hashtags...")

            hashtag_qs = Hashtag.objects.all()

            total = 0
            for batch in iter_batches(hashtag_qs, chunk_size):
                for hashtag in batch:
                    sync_hashtag_node_to_neo4j(hashtag)

                total += len(batch)
                self.stdout.write(f"  Synced hashtags: {total}")

        if not options["skip_logs"]:
            self.stdout.write("Syncing moderation logs...")

            log_qs = (
                ContentModerationLog.objects
                .select_related("actor", "actor__profile")
                .all()
            )

            total = 0
            for batch in iter_batches(log_qs, chunk_size):
                for log in batch:
                    if log.actor_id:
                        sync_account_to_neo4j(log.actor)

                    sync_moderation_log_to_neo4j(log)

                total += len(batch)
                self.stdout.write(f"  Synced moderation logs: {total}")

        self.stdout.write(
            self.style.SUCCESS("Neo4j admin/moderation graph sync completed.")
        )