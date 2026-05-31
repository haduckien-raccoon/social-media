"""
Neo4j news-feed recommendation layer.

Design:
- MySQL/Django ORM remains the source of truth.
- Neo4j only stores a read-optimized graph and returns ranked post IDs.
- Django ORM hydrates those post IDs to render the existing templates.

Smart feed version:
- Uses continuous time decay instead of fixed recency buckets.
- Adds SEEN impression tracking so posts shown many times decay for that user.
- Penalizes author fatigue and hashtag fatigue across the last 24 hours.
- Keeps hashtag discovery strict to avoid spammy repeated hashtags.
- Adds recent friend-interaction bump so older posts can reappear only when there is a new reason.
- Diversifies each page by author, hashtag and feed lane after Neo4j ranking.

Important:
- Call mark_feed_posts_seen(user.id, post_ids) after the posts are actually rendered to the user.
- For infinite scroll, pass seen_post_ids from the frontend to get_recommended_feed_post_ids(...).
"""

from __future__ import annotations

import logging
from collections import Counter
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from django.conf import settings
from neo4j import GraphDatabase

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# Feed tuning constants
# -----------------------------------------------------------------------------

DEFAULT_FEED_PER_PAGE = 5
FEED_CANDIDATE_MULTIPLIER = 8
MAX_HASHTAGS_PER_POST_IN_GRAPH = 5
MAX_SAME_AUTHOR_PER_PAGE = 2
MAX_SAME_HASHTAG_PER_PAGE = 2

# Keep direct social signals higher than discovery.
SOURCE_SCORE_OWN = 10
SOURCE_SCORE_FRIEND_PRIVATE = 80
SOURCE_SCORE_FRIEND_PUBLIC = 65

# Group posts are direct social content: the user explicitly joined the group.
# Keep this higher than normal friend-public posts, but below direct tagged posts.
SOURCE_SCORE_GROUP = 95

SOURCE_SCORE_TAGGED = 130
SOURCE_SCORE_FRIEND_INTERACTED = 48
SOURCE_SCORE_MUTUAL_DISCOVERY = 34
SOURCE_SCORE_PUBLIC_FALLBACK = 8

# Extra group-specific ranking signals.
# These are applied only after permission checks, so they cannot leak private groups.
GROUP_POST_WINDOW_DAYS = 45
GROUP_DIRECT_BONUS = 30.0
GROUP_PINNED_BONUS = 24.0
GROUP_SHARED_GROUP_BONUS = 10.0
GROUP_COMMON_AUTHOR_BONUS = 8.0
GROUP_MEMBER_REACTION_WEIGHT = 5.0
GROUP_MEMBER_COMMENT_WEIGHT = 8.0
GROUP_MEMBER_SHARE_WEIGHT = 11.0
GROUP_MEMBER_REACTION_CAP = 6
GROUP_MEMBER_COMMENT_CAP = 4
GROUP_MEMBER_SHARE_CAP = 3

# Half-life values control how fast a source becomes old.
# Higher = survives longer. Lower = disappears faster.
HALF_LIFE_TAGGED_HOURS = 168.0
HALF_LIFE_FRIEND_POST_HOURS = 72.0

# Group posts should survive longer than generic public discovery because the
# user has an explicit group-membership relationship with the content.
HALF_LIFE_GROUP_HOURS = 96.0

HALF_LIFE_SOCIAL_DISCOVERY_HOURS = 36.0
HALF_LIFE_HASHTAG_DISCOVERY_HOURS = 18.0
HALF_LIFE_PUBLIC_FALLBACK_HOURS = 12.0
HALF_LIFE_OWN_HOURS = 8.0

# Small random jitter prevents the exact same equal-score order forever.
# Keep this low; relevance and time should still dominate.
EXPLORATION_JITTER = 1.5
MAX_CLIENT_SEEN_IDS = 200

class Neo4jFeedClient:
    _driver = None

    @classmethod
    def driver(cls):
        if cls._driver is None:
            cls._driver = GraphDatabase.driver(
                settings.NEO4J_URI,
                auth=(settings.NEO4J_USERNAME, settings.NEO4J_PASSWORD),
            )
        return cls._driver

    @classmethod
    def execute(cls, query: str, **params):
        records, summary, keys = cls.driver().execute_query(
            query,
            **params,
            database_=getattr(settings, "NEO4J_DATABASE", "neo4j"),
        )
        return records

    @classmethod
    def close(cls):
        if cls._driver is not None:
            cls._driver.close()
            cls._driver = None


# -----------------------------------------------------------------------------
# Setup / bootstrap
# -----------------------------------------------------------------------------


def setup_feed_constraints() -> None:
    """Run once before syncing. Safe to run repeatedly."""
    queries = [
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
        CREATE CONSTRAINT group_id_unique IF NOT EXISTS
        FOR (g:Group)
        REQUIRE g.id IS UNIQUE
        """,
        """
        CREATE CONSTRAINT hashtag_tag_unique IF NOT EXISTS
        FOR (h:Hashtag)
        REQUIRE h.tag IS UNIQUE
        """,
    ]
    for query in queries:
        Neo4jFeedClient.execute(query)


def bootstrap_feed_relationship_types() -> None:
    """
    Prevent Neo4j warnings when a relationship type has no real data yet.
    Bootstrap nodes do not use User/Post/Group labels, so they will never
    be returned by feed queries.
    """
    query = """
    MERGE (a:_GraphBootstrap {name: "feed_a"})
    MERGE (b:_GraphBootstrap {name: "feed_b"})

    MERGE (a)-[:AUTHORED]->(b)
    MERGE (a)-[:FRIEND_WITH]->(b)
    MERGE (a)-[:MEMBER_OF]->(b)
    MERGE (a)-[:BLOCKED]->(b)
    MERGE (a)-[:REACTED_TO]->(b)
    MERGE (a)-[:COMMENTED_ON {count: 0}]->(b)
    MERGE (a)-[:SHARED]->(b)
    MERGE (a)-[:TAGGED_IN]->(b)
    MERGE (a)-[:SEEN {count: 0}]->(b)
    MERGE (b)-[:IN_GROUP {status: "bootstrap", is_deleted: false, is_pinned: false}]->(a)
    MERGE (b)-[:HAS_HASHTAG]->(a)
    MERGE (b)-[:SHARE_OF]->(a)
    """
    Neo4jFeedClient.execute(query)


# -----------------------------------------------------------------------------
# Small helpers
# -----------------------------------------------------------------------------


def normalize_hashtag(tag: Any) -> str:
    """Normalize one hashtag before storing/querying it in the graph."""
    value = str(tag or "").strip().lower()
    if value.startswith("#"):
        value = value[1:]
    return value


def unique_limited_hashtags(
    tags: Iterable[Any],
    limit: int = MAX_HASHTAGS_PER_POST_IN_GRAPH,
) -> List[str]:
    """
    Keep hashtags unique, normalized and limited.

    This protects the graph read-model from posts such as:
    #backend #backend #backend #demo #demo ...
    """
    result: List[str] = []
    seen = set()

    for raw_tag in tags:
        tag = normalize_hashtag(raw_tag)

        # Skip empty or noisy one-character tags.
        if len(tag) < 2:
            continue

        if tag in seen:
            continue

        seen.add(tag)
        result.append(tag)

        if len(result) >= limit:
            break

    return result


def _safe_id_list(values: Optional[Iterable[Any]]) -> List[int]:
    """Convert a possibly mixed ID iterable into int list for Cypher params."""
    if not values:
        return []

    safe_values: List[int] = []
    for value in values:
        try:
            safe_values.append(int(value))
        except (TypeError, ValueError):
            continue
    return safe_values


def _primary_lane(sources: Sequence[str]) -> str:
    """
    Map one row's sources into a broad feed lane.

    This is used only for page-level diversity. Neo4j ranking still decides
    the initial relevance order.
    """
    source_set = set(sources or [])

    if "tagged" in source_set or "friend_post" in source_set or "friend_public" in source_set or "group" in source_set:
        return "direct_social"
    if "friend_interacted" in source_set or "mutual_discovery" in source_set:
        return "social_discovery"
    if "hashtag_discovery" in source_set:
        return "interest_discovery"
    if "own" in source_set:
        return "own"
    return "explore"


def _lane_limits(per_page: int) -> Dict[str, int]:
    """Soft caps by lane so one source type does not fill the whole page."""
    return {
        "direct_social": max(2, per_page),
        "social_discovery": max(1, per_page // 2),
        "interest_discovery": max(1, per_page // 3),
        "own": 1,
        "explore": max(1, per_page // 4),
    }


def diversify_feed_rows(
    rows: Sequence[Dict[str, Any]],
    *,
    per_page: int,
    max_same_author: int = MAX_SAME_AUTHOR_PER_PAGE,
    max_same_hashtag: int = MAX_SAME_HASHTAG_PER_PAGE,
) -> List[Dict[str, Any]]:
    """
    Re-rank only by diversity after Neo4j ranking.

    The graph query still decides relevance. This helper prevents one author,
    one hashtag, or one discovery lane from occupying the whole visible page.
    If rules are too strict and the page would be short, skipped rows are filled
    back in score order.
    """
    selected: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []

    author_counter: Counter = Counter()
    hashtag_counter: Counter = Counter()
    lane_counter: Counter = Counter()
    lane_limits = _lane_limits(per_page)

    for row in rows:
        author_id = row.get("author_id")
        sources = row.get("sources") or []
        lane = row.get("lane") or _primary_lane(sources)
        hashtags = [normalize_hashtag(tag) for tag in (row.get("hashtags") or [])]
        hashtags = [tag for tag in hashtags if tag]

        too_many_same_author = bool(author_id) and author_counter[author_id] >= max_same_author
        too_many_same_hashtag = any(hashtag_counter[tag] >= max_same_hashtag for tag in hashtags)
        too_many_same_lane = lane_counter[lane] >= lane_limits.get(lane, per_page)

        if too_many_same_author or too_many_same_hashtag or too_many_same_lane:
            skipped.append(row)
            continue

        selected.append(row)

        if author_id:
            author_counter[author_id] += 1

        for tag in set(hashtags):
            hashtag_counter[tag] += 1

        lane_counter[lane] += 1

        if len(selected) >= per_page:
            return selected[:per_page]

    # Avoid empty/short pages when data is sparse.
    for row in skipped:
        selected.append(row)
        if len(selected) >= per_page:
            break

    return selected[:per_page]


# -----------------------------------------------------------------------------
# Sync users / relationships
# -----------------------------------------------------------------------------


def sync_user_node(user) -> None:
    """
    Sync User + UserProfile properties.
    Also used by feed_view for new accounts so they can see public fallback.
    """
    profile = getattr(user, "profile", None)
    avatar = ""
    try:
        avatar = profile.avatar.url if profile and profile.avatar else ""
    except Exception:
        avatar = ""

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
    Neo4jFeedClient.execute(
        query,
        id=user.id,
        username=user.username,
        email=user.email,
        full_name=profile.full_name if profile else "",
        avatar=avatar,
        school=profile.school if profile else "",
        province=profile.province if profile else "",
        town=profile.town if profile else "",
        is_active=user.is_active,
        is_banned=user.is_banned,
    )


def sync_friend_edge(user_id: int, friend_id: int) -> None:
    """MySQL Friend is directional, but social friendship is queried as undirected."""
    query = """
    MERGE (a:User {id: $user_id})
    MERGE (b:User {id: $friend_id})
    MERGE (a)-[:FRIEND_WITH]-(b)
    """
    Neo4jFeedClient.execute(query, user_id=user_id, friend_id=friend_id)


def sync_block_edge(blocker_id: int, blocked_id: int) -> None:
    query = """
    MERGE (blocker:User {id: $blocker_id})
    MERGE (blocked:User {id: $blocked_id})
    MERGE (blocker)-[:BLOCKED]->(blocked)
    """
    Neo4jFeedClient.execute(query, blocker_id=blocker_id, blocked_id=blocked_id)


def sync_group_node(group) -> None:
    """
    Sync group and also make owner a MEMBER_OF the group for feed visibility.
    Your current MySQL feed lets group owner see group posts, so Neo4j must too.
    """
    query = """
    MERGE (g:Group {id: $group_id})
    SET g.name = $name,
        g.is_private = $is_private,
        g.is_activate = $is_activate,
        g.updated_at = datetime()

    MERGE (owner:User {id: $owner_id})
    SET owner.username = $owner_username

    MERGE (owner)-[r:MEMBER_OF]->(g)
    SET r.role = "owner",
        r.status = "approved",
        r.updated_at = datetime()
    """
    Neo4jFeedClient.execute(
        query,
        group_id=group.id,
        name=group.name,
        is_private=group.is_private,
        is_activate=group.is_activate,
        owner_id=group.owner_id,
        owner_username=group.owner.username,
    )


def sync_group_member_edge(member) -> None:
    if member.status != "approved":
        return

    query = """
    MERGE (u:User {id: $user_id})
    SET u.username = $username

    MERGE (g:Group {id: $group_id})
    SET g.name = $group_name,
        g.is_private = $is_private,
        g.is_activate = $is_activate

    MERGE (u)-[r:MEMBER_OF]->(g)
    SET r.role = $role,
        r.status = $status,
        r.joined_at = datetime($joined_at),
        r.updated_at = datetime()
    """
    Neo4jFeedClient.execute(
        query,
        user_id=member.user_id,
        username=member.user.username,
        group_id=member.group_id,
        group_name=member.group.name,
        is_private=member.group.is_private,
        is_activate=member.group.is_activate,
        role=member.role,
        status=member.status,
        joined_at=member.joined_at.isoformat(),
    )


def sync_post_node(post) -> None:
    """Sync one Post node and AUTHORED relation. Counts are denormalized for fast ranking."""
    reaction_count = post.reactions.count()
    comment_count = post.comments.filter(is_deleted=False).count()
    share_count = post.shares.count()

    query = """
    MERGE (author:User {id: $author_id})
    SET author.username = $author_username,
        author.email = $author_email

    MERGE (p:Post {id: $post_id})
    SET p.author_id = $author_id,
        p.content_preview = $content_preview,
        p.privacy = $privacy,
        p.status = $status,
        p.is_deleted = $is_deleted,
        p.is_comment_enabled = $is_comment_enabled,
        p.risk_score = $risk_score,
        p.created_at = datetime($created_at),
        p.updated_at = datetime($updated_at),
        p.reaction_count = $reaction_count,
        p.comment_count = $comment_count,
        p.share_count = $share_count

    MERGE (author)-[:AUTHORED]->(p)
    """
    Neo4jFeedClient.execute(
        query,
        post_id=post.id,
        author_id=post.author_id,
        author_username=post.author.username,
        author_email=post.author.email,
        content_preview=(post.content or "")[:200],
        privacy=post.privacy,
        status=post.status,
        is_deleted=post.is_deleted,
        is_comment_enabled=post.is_comment_enabled,
        risk_score=float(post.risk_score or 0),
        created_at=post.created_at.isoformat(),
        updated_at=post.updated_at.isoformat(),
        reaction_count=reaction_count,
        comment_count=comment_count,
        share_count=share_count,
    )


def sync_group_post_relation(group_post) -> None:
    query = """
    MERGE (g:Group {id: $group_id})
    SET g.name = $group_name,
        g.is_private = $is_private,
        g.is_activate = $is_activate

    MERGE (p:Post {id: $post_id})

    MERGE (p)-[r:IN_GROUP]->(g)
    SET r.status = $status,
        r.is_deleted = $is_deleted,
        r.is_pinned = $is_pinned,
        r.updated_at = datetime()
    """
    Neo4jFeedClient.execute(
        query,
        group_id=group_post.group_id,
        group_name=group_post.group.name,
        is_private=group_post.group.is_private,
        is_activate=group_post.group.is_activate,
        post_id=group_post.post_id,
        status=group_post.status,
        is_deleted=group_post.is_deleted,
        is_pinned=group_post.is_pinned,
    )


def sync_post_reaction_edge(reaction) -> None:
    query = """
    MERGE (u:User {id: $user_id})
    SET u.username = $username

    MERGE (p:Post {id: $post_id})

    MERGE (u)-[r:REACTED_TO]->(p)
    SET r.reaction_type = $reaction_type,
        r.created_at = datetime($created_at),
        r.updated_at = datetime()
    """
    Neo4jFeedClient.execute(
        query,
        user_id=reaction.user_id,
        username=reaction.user.username,
        post_id=reaction.post_id,
        reaction_type=reaction.reaction_type,
        created_at=reaction.created_at.isoformat(),
    )


def sync_comment_edge(comment) -> None:
    if comment.is_deleted:
        return

    created_at = getattr(comment, "created_at", None)
    created_at_value = created_at.isoformat() if created_at else None

    query = """
    MERGE (u:User {id: $user_id})
    SET u.username = $username

    MERGE (p:Post {id: $post_id})

    MERGE (u)-[r:COMMENTED_ON]->(p)
    ON CREATE SET
        r.count = 1,
        r.created_at = CASE
            WHEN $created_at IS NULL THEN datetime()
            ELSE datetime($created_at)
        END
    ON MATCH SET
        r.count = coalesce(r.count, 0) + 1
    SET r.updated_at = datetime()
    """
    Neo4jFeedClient.execute(
        query,
        user_id=comment.user_id,
        username=comment.user.username,
        post_id=comment.post_id,
        created_at=created_at_value,
    )


def sync_share_edge(share) -> None:
    query = """
    MERGE (u:User {id: $user_id})
    SET u.username = $username

    MERGE (original:Post {id: $original_post_id})
    MERGE (newPost:Post {id: $new_post_id})

    MERGE (u)-[r:SHARED]->(original)
    SET r.created_at = datetime($created_at),
        r.updated_at = datetime()

    MERGE (newPost)-[:SHARE_OF]->(original)
    """
    Neo4jFeedClient.execute(
        query,
        user_id=share.user_id,
        username=share.user.username,
        original_post_id=share.original_post_id,
        new_post_id=share.new_post_id,
        created_at=share.created_at.isoformat(),
    )


def sync_post_hashtags(post) -> None:
    """
    Sync hashtags for one post.

    Anti-spam behavior:
    - Deletes old HAS_HASHTAG edges first.
    - Normalizes tags to lowercase and strips leading '#'.
    - Keeps only unique tags.
    - Stores at most MAX_HASHTAGS_PER_POST_IN_GRAPH tags per post.
    """
    Neo4jFeedClient.execute(
        """
        MATCH (:Post {id: $post_id})-[r:HAS_HASHTAG]->(:Hashtag)
        DELETE r
        """,
        post_id=post.id,
    )

    raw_tags = [ph.hashtag.tag for ph in post.post_hashtags.select_related("hashtag").all()]
    hashtags = unique_limited_hashtags(raw_tags)

    for tag in hashtags:
        Neo4jFeedClient.execute(
            """
            MERGE (p:Post {id: $post_id})
            MERGE (h:Hashtag {tag: $tag})
            MERGE (p)-[:HAS_HASHTAG]->(h)
            """,
            post_id=post.id,
            tag=tag,
        )


def sync_tagged_users(post) -> None:
    Neo4jFeedClient.execute(
        """
        MATCH (:User)-[r:TAGGED_IN]->(:Post {id: $post_id})
        DELETE r
        """,
        post_id=post.id,
    )

    for tag in post.tagged_users.select_related("user").all():
        Neo4jFeedClient.execute(
            """
            MERGE (u:User {id: $user_id})
            SET u.username = $username
            MERGE (p:Post {id: $post_id})
            MERGE (u)-[:TAGGED_IN]->(p)
            """,
            user_id=tag.user_id,
            username=tag.user.username,
            post_id=post.id,
        )


# -----------------------------------------------------------------------------
# Impression / seen tracking
# -----------------------------------------------------------------------------


def mark_feed_posts_seen(user_id: int, post_ids: Iterable[Any]) -> None:
    """
    Mark posts as actually shown to a user.

    Call this after the feed posts are rendered, not merely when candidates are
    generated. This is what makes the feed stop showing the same high-score post
    again and again.
    """
    safe_post_ids = _safe_id_list(post_ids)
    if not safe_post_ids:
        return

    query = """
    MATCH (u:User {id: $user_id})
    UNWIND $post_ids AS post_id
    MATCH (p:Post {id: post_id})
    MERGE (u)-[s:SEEN]->(p)
    ON CREATE SET
        s.count = 1,
        s.first_seen_at = datetime(),
        s.last_seen_at = datetime()
    ON MATCH SET
        s.count = coalesce(s.count, 0) + 1,
        s.last_seen_at = datetime()
    """
    Neo4jFeedClient.execute(query, user_id=int(user_id), post_ids=safe_post_ids)


def reset_seen_post_for_user(user_id: int, post_id: int) -> None:
    """Optional helper for debugging: remove one SEEN edge."""
    query = """
    MATCH (:User {id: $user_id})-[s:SEEN]->(:Post {id: $post_id})
    DELETE s
    """
    Neo4jFeedClient.execute(query, user_id=int(user_id), post_id=int(post_id))


# -----------------------------------------------------------------------------
# Smart feed query
# -----------------------------------------------------------------------------


def get_recommended_feed_post_ids(
    user,
    page: int = 1,
    per_page: int = DEFAULT_FEED_PER_PAGE,
    *,
    seen_post_ids: Optional[Iterable[Any]] = None,
) -> Dict[str, Any]:
    """
    Return ranked post IDs for the user's feed.

    Important:
    - This is a READ path, so do not sync/write the full User node here.
    - User/Post/Interaction graph data must be synced from write paths:
      create_post, reaction, comment, share, friend/group actions, or the
      sync_feed_neo4j management command.
    - Neo4j returns ranked post IDs only; Django ORM hydrates the posts.
    """
    page = max(int(page or 1), 1)
    per_page = max(int(per_page or DEFAULT_FEED_PER_PAGE), 1)

    candidate_limit = per_page * FEED_CANDIDATE_MULTIPLIER + 1
    excluded_post_ids = _safe_id_list(seen_post_ids)[-MAX_CLIENT_SEEN_IDS:]

    # When the client sends seen_post_ids, do not also SKIP because the list is
    # dynamic. SKIP + dynamic exclusion can accidentally skip good candidates.
    skip = 0 if excluded_post_ids else (page - 1) * per_page

    query = """
    MATCH (me:User {id: $user_id})

    CALL (me) {
        // 1) Own non-group posts. Kept low score so user's own posts do not
        // dominate their feed.
        MATCH (me)-[:AUTHORED]->(post:Post)
        WHERE NOT (post)-[:IN_GROUP]->(:Group)
        RETURN post, $score_own AS source_score, "own" AS source

        UNION

        // 2) Friend-only posts from friends.
        MATCH (me)-[:FRIEND_WITH]-(author:User)-[:AUTHORED]->(post:Post)
        WHERE post.privacy = "friends"
          AND NOT (post)-[:IN_GROUP]->(:Group)
          AND post.created_at >= datetime() - duration({days: 30})
        RETURN post, $score_friend_private AS source_score, "friend_post" AS source

        UNION

        // 3) Public posts from friends.
        MATCH (me)-[:FRIEND_WITH]-(author:User)-[:AUTHORED]->(post:Post)
        WHERE post.privacy = "public"
          AND NOT (post)-[:IN_GROUP]->(:Group)
          AND post.created_at >= datetime() - duration({days: 30})
        RETURN post, $score_friend_public AS source_score, "friend_public" AS source

        UNION

        // 4) Approved posts in groups that the user belongs to.
        // This is a direct social source, not generic public discovery.
        MATCH (me)-[my_group_rel:MEMBER_OF]->(g:Group)<-[gp:IN_GROUP]-(post:Post)
        WHERE coalesce(my_group_rel.status, "approved") = "approved"
          AND gp.status = "approved"
          AND coalesce(gp.is_deleted, false) = false
          AND coalesce(g.is_activate, true) = true
          AND post.created_at >= datetime() - duration({days: $group_post_window_days})
        RETURN post, $score_group AS source_score, "group" AS source

        UNION

        // 5) Posts where the user is tagged. Keep longer than normal discovery.
        MATCH (me)-[:TAGGED_IN]->(post:Post)
        WHERE post.created_at >= datetime() - duration({days: 90})
        RETURN post, $score_tagged AS source_score, "tagged" AS source

        UNION

        // 6) Public posts that friends interacted with.
        MATCH (me)-[:FRIEND_WITH]-(friend:User)-[:REACTED_TO|COMMENTED_ON|SHARED]->(post:Post)
        WHERE post.privacy = "public"
          AND post.created_at >= datetime() - duration({days: 30})
        RETURN post, $score_friend_interacted AS source_score, "friend_interacted" AS source

        UNION

        // 7) Public posts from mutual-friend discovery.
        MATCH (me)-[:FRIEND_WITH]-(mutual:User)-[:FRIEND_WITH]-(author:User)-[:AUTHORED]->(post:Post)
        WHERE post.privacy = "public"
          AND author.id <> me.id
          AND NOT (me)-[:FRIEND_WITH]-(author)
          AND NOT (post)-[:IN_GROUP]->(:Group)
          AND post.created_at >= datetime() - duration({days: 30})
        RETURN post, $score_mutual_discovery AS source_score, "mutual_discovery" AS source

        UNION

        // 8) Strict hashtag discovery based on repeated interactions.
        MATCH (me)-[i:REACTED_TO|COMMENTED_ON|SHARED]->(:Post)-[:HAS_HASHTAG]->(h:Hashtag)
        WITH me, h,
             sum(
                CASE type(i)
                    WHEN "SHARED" THEN 3
                    WHEN "COMMENTED_ON" THEN 2
                    ELSE 1
                END
             ) AS hashtag_affinity
        WHERE hashtag_affinity >= 2

        MATCH (post:Post)-[:HAS_HASHTAG]->(h)
        WHERE post.privacy = "public"
          AND post.created_at >= datetime() - duration({days: 14})
        RETURN post,
               CASE
                  WHEN hashtag_affinity >= 6 THEN 25
                  WHEN hashtag_affinity >= 3 THEN 18
                  ELSE 12
               END AS source_score,
               "hashtag_discovery" AS source

        UNION

        // 9) Public fallback must be limited early. Without this, Neo4j may scan
        // nearly all public posts before ranking only 5 posts.
        MATCH (author:User)-[:AUTHORED]->(post:Post)
        WHERE post.privacy = "public"
          AND coalesce(post.is_deleted, false) = false
          AND coalesce(post.status, "normal") IN ["normal", "approved"]
          AND NOT (post)-[:IN_GROUP]->(:Group)
          AND post.created_at >= datetime() - duration({days: 14})
        WITH post
        ORDER BY post.created_at DESC
        LIMIT $public_fallback_limit
        RETURN post, $score_public_fallback AS source_score, "public_fallback" AS source
    }

    WITH me, post, max(source_score) AS source_score, collect(DISTINCT source) AS sources
    MATCH (author:User)-[:AUTHORED]->(post)

    WHERE coalesce(post.is_deleted, false) = false
      AND coalesce(post.status, "normal") IN ["normal", "approved"]
      AND coalesce(author.is_active, true) = true
      AND coalesce(author.is_banned, false) = false
      AND NOT post.id IN $excluded_post_ids
      AND NOT (me)-[:BLOCKED]->(author)
      AND NOT (author)-[:BLOCKED]->(me)
      AND (
        post.privacy = "public"
        OR author.id = me.id
        OR (post.privacy = "friends" AND (me)-[:FRIEND_WITH]-(author))
        OR EXISTS {
          MATCH (me)-[:MEMBER_OF]->(:Group)<-[gp:IN_GROUP]-(post)
          WHERE gp.status = "approved"
            AND coalesce(gp.is_deleted, false) = false
        }
      )

    // Group context for ranking.
    // A group post should not be treated like generic public fallback:
    // - shared_group_count: post is in a group the user joined
    // - common_group_with_author_count: author and user share groups
    // - is_group_pinned: admin/owner pinned the post in that group
    OPTIONAL MATCH (post)-[post_group_rel:IN_GROUP]->(post_group:Group)<-[my_post_group_rel:MEMBER_OF]-(me)
    WHERE coalesce(my_post_group_rel.status, "approved") = "approved"
      AND post_group_rel.status = "approved"
      AND coalesce(post_group_rel.is_deleted, false) = false
      AND coalesce(post_group.is_activate, true) = true
    WITH me, post, author, source_score, sources,
         count(DISTINCT post_group) AS shared_group_count,
         max(CASE WHEN coalesce(post_group_rel.is_pinned, false) THEN 1 ELSE 0 END) AS is_group_pinned

    OPTIONAL MATCH (author)-[author_group_rel:MEMBER_OF]->(author_group:Group)<-[my_author_group_rel:MEMBER_OF]-(me)
    WHERE author.id <> me.id
      AND coalesce(author_group_rel.status, "approved") = "approved"
      AND coalesce(my_author_group_rel.status, "approved") = "approved"
      AND coalesce(author_group.is_activate, true) = true
    WITH me, post, author, source_score, sources,
         shared_group_count, is_group_pinned,
         count(DISTINCT author_group) AS common_group_with_author_count

    // Group-member interactions are different from friend interactions.
    // A post that active members in the same joined group react/comment/share
    // should be pushed up in the user's group feed lane.
    OPTIONAL MATCH (post)-[engaged_group_rel:IN_GROUP]->(engagement_group:Group)<-[group_member_rel:MEMBER_OF]-(group_member:User)-[gr:REACTED_TO|COMMENTED_ON|SHARED]->(post)
    WHERE engaged_group_rel.status = "approved"
      AND coalesce(engaged_group_rel.is_deleted, false) = false
      AND coalesce(group_member_rel.status, "approved") = "approved"
      AND coalesce(engagement_group.is_activate, true) = true
      AND EXISTS {
          MATCH (me)-[my_engagement_group_rel:MEMBER_OF]->(engagement_group)
          WHERE coalesce(my_engagement_group_rel.status, "approved") = "approved"
      }
      AND group_member.id <> me.id
      AND NOT (me)-[:BLOCKED]->(group_member)
      AND NOT (group_member)-[:BLOCKED]->(me)
    WITH me, post, author, source_score, sources,
         shared_group_count, is_group_pinned, common_group_with_author_count,
         count(DISTINCT CASE WHEN type(gr) = "REACTED_TO" THEN group_member END) AS group_member_reaction_count,
         count(DISTINCT CASE WHEN type(gr) = "COMMENTED_ON" THEN group_member END) AS group_member_comment_count,
         count(DISTINCT CASE WHEN type(gr) = "SHARED" THEN group_member END) AS group_member_share_count

    // Friend interactions: one graph expansion instead of 3 OPTIONAL MATCHes.
    OPTIONAL MATCH (me)-[:FRIEND_WITH]-(friend:User)-[fr:REACTED_TO|COMMENTED_ON|SHARED]->(post)
    WITH me, post, author, source_score, sources,
         shared_group_count, is_group_pinned, common_group_with_author_count,
         group_member_reaction_count, group_member_comment_count, group_member_share_count,
         count(DISTINCT CASE WHEN type(fr) = "REACTED_TO" THEN friend END) AS friend_reaction_count,
         count(DISTINCT CASE WHEN type(fr) = "COMMENTED_ON" THEN friend END) AS friend_comment_count,
         count(DISTINCT CASE WHEN type(fr) = "SHARED" THEN friend END) AS friend_share_count

    OPTIONAL MATCH (me)-[:FRIEND_WITH]-(mutual:User)-[:FRIEND_WITH]-(author)
    WHERE NOT (me)-[:FRIEND_WITH]-(author)
      AND author.id <> me.id
    WITH me, post, author, source_score, sources,
         shared_group_count, is_group_pinned, common_group_with_author_count,
         group_member_reaction_count, group_member_comment_count, group_member_share_count,
         friend_reaction_count, friend_comment_count, friend_share_count,
         count(DISTINCT mutual) AS mutual_friend_count

    // My interactions: one graph expansion instead of 3 OPTIONAL MATCHes.
    OPTIONAL MATCH (me)-[mine:REACTED_TO|COMMENTED_ON|SHARED]->(post)
    WITH me, post, author, source_score, sources,
         shared_group_count, is_group_pinned, common_group_with_author_count,
         group_member_reaction_count, group_member_comment_count, group_member_share_count,
         friend_reaction_count, friend_comment_count, friend_share_count,
         mutual_friend_count,
         count(CASE WHEN type(mine) = "REACTED_TO" THEN mine END) AS my_reaction_count,
         count(CASE WHEN type(mine) = "COMMENTED_ON" THEN mine END) AS my_comment_count,
         count(CASE WHEN type(mine) = "SHARED" THEN mine END) AS my_share_count

    OPTIONAL MATCH (me)-[seen:SEEN]->(post)
    WITH me, post, author, source_score, sources,
         shared_group_count, is_group_pinned, common_group_with_author_count,
         group_member_reaction_count, group_member_comment_count, group_member_share_count,
         friend_reaction_count, friend_comment_count, friend_share_count,
         mutual_friend_count, my_reaction_count, my_comment_count, my_share_count,
         coalesce(seen.count, 0) AS seen_count,
         CASE
            WHEN seen.last_seen_at IS NULL THEN 999999.0
            ELSE toFloat(datetime().epochSeconds - seen.last_seen_at.epochSeconds) / 3600.0
         END AS hours_since_seen,
         coalesce(post.reaction_count, 0) AS reaction_count,
         coalesce(post.comment_count, 0) AS comment_count,
         coalesce(post.share_count, 0) AS share_count,
         coalesce(post.risk_score, 0.0) AS risk_score,
         CASE
            WHEN post.created_at IS NULL THEN 0.0
            ELSE toFloat(datetime().epochSeconds - post.created_at.epochSeconds) / 3600.0
         END AS age_hours

    WITH me, post, author, source_score, sources,
         shared_group_count, is_group_pinned, common_group_with_author_count,
         group_member_reaction_count, group_member_comment_count, group_member_share_count,
         friend_reaction_count, friend_comment_count, friend_share_count,
         mutual_friend_count, my_reaction_count, my_comment_count, my_share_count,
         seen_count, hours_since_seen, reaction_count, comment_count, share_count,
         risk_score, age_hours,
         CASE
            WHEN "tagged" IN sources THEN $half_life_tagged
            WHEN "friend_post" IN sources OR "friend_public" IN sources THEN $half_life_friend_post
            WHEN "group" IN sources THEN $half_life_group
            WHEN "friend_interacted" IN sources OR "mutual_discovery" IN sources THEN $half_life_social_discovery
            WHEN "hashtag_discovery" IN sources THEN $half_life_hashtag_discovery
            WHEN "public_fallback" IN sources THEN $half_life_public_fallback
            WHEN "own" IN sources THEN $half_life_own
            ELSE $half_life_public_fallback
         END AS half_life_hours

    WITH me, post, author, source_score, sources,
         shared_group_count, is_group_pinned, common_group_with_author_count,
         group_member_reaction_count, group_member_comment_count, group_member_share_count,
         friend_reaction_count, friend_comment_count, friend_share_count,
         mutual_friend_count, my_reaction_count, my_comment_count, my_share_count,
         seen_count, hours_since_seen, reaction_count, comment_count, share_count,
         risk_score, age_hours, half_life_hours,
         1.0 / (1.0 + age_hours / half_life_hours) AS time_decay,
         CASE
            WHEN age_hours <= 1 THEN 12.0
            WHEN age_hours <= 6 THEN 6.0
            WHEN age_hours <= 24 THEN 2.0
            ELSE 0.0
         END AS freshness_boost

    // Keep this block. It creates post_hashtags used by RETURN and Python diversity.
    OPTIONAL MATCH (post)-[:HAS_HASHTAG]->(ph:Hashtag)
    WITH post, author, sources, source_score,
         shared_group_count, is_group_pinned, common_group_with_author_count,
         group_member_reaction_count, group_member_comment_count, group_member_share_count,
         friend_reaction_count, friend_comment_count, friend_share_count,
         mutual_friend_count, my_reaction_count, my_comment_count, my_share_count,
         seen_count, hours_since_seen, reaction_count, comment_count, share_count,
         risk_score, age_hours, half_life_hours, time_decay, freshness_boost,
         collect(DISTINCT ph.tag) AS post_hashtags,
         count(DISTINCT ph) AS hashtag_count

    WITH post, author, sources, post_hashtags,
         source_score,
         shared_group_count,
         is_group_pinned,
         common_group_with_author_count,
         group_member_reaction_count,
         group_member_comment_count,
         group_member_share_count,
         age_hours,
         half_life_hours,
         time_decay,
         freshness_boost,
         seen_count,
         hours_since_seen,
         0 AS same_author_seen_24h,
         0 AS same_hashtag_seen_24h,
         0 AS author_same_hashtag_24h_count,
         hashtag_count,
         risk_score,
         (
            source_score

            // Direct group membership signals.
            + CASE WHEN "group" IN sources THEN $score_group_direct_bonus ELSE 0.0 END
            + CASE WHEN is_group_pinned > 0 THEN $score_group_pinned_bonus ELSE 0.0 END
            + shared_group_count * $score_group_shared_group_bonus
            + common_group_with_author_count * $score_group_common_author_bonus

            // Same-group social proof. Cap the counts so very large groups do
            // not dominate the whole feed only because of size.
            + CASE
                WHEN group_member_reaction_count > $group_member_reaction_cap
                THEN $group_member_reaction_cap
                ELSE group_member_reaction_count
              END * $score_group_member_reaction
            + CASE
                WHEN group_member_comment_count > $group_member_comment_cap
                THEN $group_member_comment_cap
                ELSE group_member_comment_count
              END * $score_group_member_comment
            + CASE
                WHEN group_member_share_count > $group_member_share_cap
                THEN $group_member_share_cap
                ELSE group_member_share_count
              END * $score_group_member_share

            + friend_reaction_count * 10.0
            + friend_comment_count * 15.0
            + friend_share_count * 18.0
            + mutual_friend_count * 8.0
            + my_reaction_count * 10.0
            + my_comment_count * 18.0
            + my_share_count * 22.0
            + reaction_count * 0.8
            + comment_count * 1.4
            + share_count * 2.2
         ) AS base_relevance,
         0.0 AS recent_bump_score,
         CASE
            WHEN (my_reaction_count + my_comment_count + my_share_count) > 0 THEN seen_count * 4.0
            WHEN seen_count >= 5 THEN 999.0
            WHEN seen_count >= 3 THEN 160.0
            WHEN seen_count = 2 THEN 80.0
            WHEN seen_count = 1 AND hours_since_seen <= 1 THEN 60.0
            WHEN seen_count = 1 THEN 35.0
            ELSE 0.0
         END AS seen_penalty,
         0.0 AS author_fatigue_penalty,
         0.0 AS hashtag_fatigue_penalty,
         (
            risk_score * 25.0
            + CASE
                WHEN hashtag_count > 5 THEN (hashtag_count - 5) * 8.0
                ELSE 0.0
              END
            + CASE
                WHEN "hashtag_discovery" IN sources
                 AND friend_reaction_count = 0
                 AND friend_comment_count = 0
                 AND friend_share_count = 0
                THEN 20.0
                ELSE 0.0
              END
         ) AS spam_penalty

    WITH post, author, sources, post_hashtags,
         shared_group_count, is_group_pinned, common_group_with_author_count,
         group_member_reaction_count, group_member_comment_count, group_member_share_count,
         age_hours, half_life_hours, time_decay, seen_count,
         base_relevance, freshness_boost, recent_bump_score,
         seen_penalty, author_fatigue_penalty, hashtag_fatigue_penalty, spam_penalty,
         (
            base_relevance * time_decay
            + freshness_boost
            + recent_bump_score
            - seen_penalty
            - author_fatigue_penalty
            - hashtag_fatigue_penalty
            - spam_penalty
            + rand() * $exploration_jitter
         ) AS score

    RETURN post.id AS post_id,
           author.id AS author_id,
           score,
           sources,
           post_hashtags AS hashtags,
           CASE
              WHEN "tagged" IN sources OR "friend_post" IN sources OR "friend_public" IN sources OR "group" IN sources THEN "direct_social"
              WHEN "friend_interacted" IN sources OR "mutual_discovery" IN sources THEN "social_discovery"
              WHEN "hashtag_discovery" IN sources THEN "interest_discovery"
              WHEN "own" IN sources THEN "own"
              ELSE "explore"
           END AS lane,
           {
              age_hours: age_hours,
              half_life_hours: half_life_hours,
              time_decay: time_decay,
              seen_count: seen_count,
              shared_group_count: shared_group_count,
              is_group_pinned: is_group_pinned,
              common_group_with_author_count: common_group_with_author_count,
              group_member_reaction_count: group_member_reaction_count,
              group_member_comment_count: group_member_comment_count,
              group_member_share_count: group_member_share_count,
              base_relevance: base_relevance,
              freshness_boost: freshness_boost,
              recent_bump_score: recent_bump_score,
              seen_penalty: seen_penalty,
              author_fatigue_penalty: author_fatigue_penalty,
              hashtag_fatigue_penalty: hashtag_fatigue_penalty,
              spam_penalty: spam_penalty
           } AS debug
    ORDER BY score DESC, post.created_at DESC
    SKIP $skip
    LIMIT $limit
    """

    records = Neo4jFeedClient.execute(
        query,
        user_id=user.id,
        skip=skip,
        limit=candidate_limit,
        excluded_post_ids=excluded_post_ids,
        public_fallback_limit=per_page * 4,
        group_post_window_days=GROUP_POST_WINDOW_DAYS,
        score_own=SOURCE_SCORE_OWN,
        score_friend_private=SOURCE_SCORE_FRIEND_PRIVATE,
        score_friend_public=SOURCE_SCORE_FRIEND_PUBLIC,
        score_group=SOURCE_SCORE_GROUP,
        score_group_direct_bonus=GROUP_DIRECT_BONUS,
        score_group_pinned_bonus=GROUP_PINNED_BONUS,
        score_group_shared_group_bonus=GROUP_SHARED_GROUP_BONUS,
        score_group_common_author_bonus=GROUP_COMMON_AUTHOR_BONUS,
        score_group_member_reaction=GROUP_MEMBER_REACTION_WEIGHT,
        score_group_member_comment=GROUP_MEMBER_COMMENT_WEIGHT,
        score_group_member_share=GROUP_MEMBER_SHARE_WEIGHT,
        group_member_reaction_cap=GROUP_MEMBER_REACTION_CAP,
        group_member_comment_cap=GROUP_MEMBER_COMMENT_CAP,
        group_member_share_cap=GROUP_MEMBER_SHARE_CAP,
        score_tagged=SOURCE_SCORE_TAGGED,
        score_friend_interacted=SOURCE_SCORE_FRIEND_INTERACTED,
        score_mutual_discovery=SOURCE_SCORE_MUTUAL_DISCOVERY,
        score_public_fallback=SOURCE_SCORE_PUBLIC_FALLBACK,
        half_life_tagged=HALF_LIFE_TAGGED_HOURS,
        half_life_friend_post=HALF_LIFE_FRIEND_POST_HOURS,
        half_life_group=HALF_LIFE_GROUP_HOURS,
        half_life_social_discovery=HALF_LIFE_SOCIAL_DISCOVERY_HOURS,
        half_life_hashtag_discovery=HALF_LIFE_HASHTAG_DISCOVERY_HOURS,
        half_life_public_fallback=HALF_LIFE_PUBLIC_FALLBACK_HOURS,
        half_life_own=HALF_LIFE_OWN_HOURS,
        exploration_jitter=EXPLORATION_JITTER,
    )

    raw_rows = [record.data() for record in records]
    diversified_rows = diversify_feed_rows(raw_rows, per_page=per_page)

    has_next = len(raw_rows) > per_page

    return {
        "post_ids": [row["post_id"] for row in diversified_rows],
        "score_map": {row["post_id"]: row["score"] for row in diversified_rows},
        "sources_map": {row["post_id"]: row.get("sources", []) for row in diversified_rows},
        "hashtags_map": {row["post_id"]: row.get("hashtags", []) for row in diversified_rows},
        "lane_map": {row["post_id"]: row.get("lane") for row in diversified_rows},
        "debug_map": {row["post_id"]: row.get("debug", {}) for row in diversified_rows},
        "has_next": has_next,
    }


# -----------------------------------------------------------------------------
# Soft-delete / interaction refresh helpers
# -----------------------------------------------------------------------------


def mark_post_deleted_in_neo4j(post_id: int) -> None:
    """
    Soft delete post trong graph.
    MySQL vẫn là source of truth, Neo4j chỉ cập nhật read model.
    """
    query = """
    MATCH (p:Post {id: $post_id})
    SET p.is_deleted = true,
        p.status = "deleted",
        p.updated_at = datetime()
    """
    Neo4jFeedClient.execute(query, post_id=post_id)


def delete_post_reaction_edge(user_id: int, post_id: int) -> None:
    """Xóa cạnh reaction khi user unlike/remove reaction."""
    query = """
    MATCH (:User {id: $user_id})-[r:REACTED_TO]->(:Post {id: $post_id})
    DELETE r
    """
    Neo4jFeedClient.execute(
        query,
        user_id=user_id,
        post_id=post_id,
    )


def refresh_comment_interaction_edge(
    *,
    user_id: int,
    username: str,
    post_id: int,
    comment_count: int,
) -> None:
    """
    Đồng bộ lại cạnh COMMENTED_ON theo số comment hiện còn sống của user trên post.
    Dùng khi tạo/xóa comment.
    """
    if comment_count <= 0:
        query = """
        MATCH (:User {id: $user_id})-[r:COMMENTED_ON]->(:Post {id: $post_id})
        DELETE r
        """
        Neo4jFeedClient.execute(
            query,
            user_id=user_id,
            post_id=post_id,
        )
        return

    query = """
    MERGE (u:User {id: $user_id})
    SET u.username = $username

    MERGE (p:Post {id: $post_id})

    MERGE (u)-[r:COMMENTED_ON]->(p)
    ON CREATE SET r.created_at = datetime()
    SET r.count = $comment_count,
        r.updated_at = datetime()
    """

    Neo4jFeedClient.execute(
        query,
        user_id=user_id,
        username=username,
        post_id=post_id,
        comment_count=comment_count,
    )
