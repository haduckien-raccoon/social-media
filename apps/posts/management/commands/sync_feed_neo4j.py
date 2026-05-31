"""
Initial full sync from MySQL to Neo4j for the news feed graph.

Run:
    python manage.py sync_feed_neo4j

This command does not change MySQL data.
"""

from django.core.management.base import BaseCommand

from apps.accounts.models import User
from apps.friends.models import Friend, Block
from apps.groups.models import Group, GroupMember, GroupPost
from apps.posts.models import Post, PostReaction, Comment, PostShare
from apps.posts.neo4j_feed import (
    setup_feed_constraints,
    bootstrap_feed_relationship_types,
    sync_user_node,
    sync_friend_edge,
    sync_block_edge,
    sync_group_node,
    sync_group_member_edge,
    sync_post_node,
    sync_group_post_relation,
    sync_post_reaction_edge,
    sync_comment_edge,
    sync_share_edge,
    sync_post_hashtags,
    sync_tagged_users,
)


class Command(BaseCommand):
    help = "Sync MySQL feed data to Neo4j"

    def handle(self, *args, **options):
        self.stdout.write("Setting up Neo4j constraints...")
        setup_feed_constraints()

        self.stdout.write("Bootstrapping relationship types...")
        bootstrap_feed_relationship_types()

        self.stdout.write("Syncing users...")
        for user in User.objects.select_related("profile").all().iterator():
            sync_user_node(user)

        self.stdout.write("Syncing friendships...")
        for friend in Friend.objects.all().iterator():
            sync_friend_edge(friend.user_id, friend.friend_id)

        self.stdout.write("Syncing blocks...")
        for block in Block.objects.all().iterator():
            sync_block_edge(block.blocker_id, block.blocked_id)

        self.stdout.write("Syncing groups...")
        for group in Group.objects.select_related("owner").all().iterator():
            sync_group_node(group)

        self.stdout.write("Syncing group members...")
        for member in GroupMember.objects.select_related("user", "group").filter(status="approved").iterator():
            sync_group_member_edge(member)

        self.stdout.write("Syncing posts...")
        for post in Post.objects.select_related("author", "author__profile").all().iterator():
            sync_post_node(post)
            sync_post_hashtags(post)
            sync_tagged_users(post)

        self.stdout.write("Syncing group posts...")
        for group_post in GroupPost.objects.select_related("group", "post").all().iterator():
            sync_group_post_relation(group_post)

        self.stdout.write("Syncing post reactions...")
        for reaction in PostReaction.objects.select_related("user", "post").all().iterator():
            sync_post_reaction_edge(reaction)

        self.stdout.write("Syncing comments...")
        for comment in Comment.objects.select_related("user", "post").filter(is_deleted=False).iterator():
            sync_comment_edge(comment)

        self.stdout.write("Syncing shares...")
        for share in PostShare.objects.select_related("user", "original_post", "new_post").all().iterator():
            sync_share_edge(share)

        self.stdout.write(self.style.SUCCESS("Feed graph sync completed."))
