"""API URL routes for posts/comment/reaction module."""

from django.urls import path

from .views import CommentDetailAPIView
from .views import CommentReactionAPIView
from .views import FeedListAPIView
from .views import PostCommentListCreateAPIView
from .views import PostDetailAPIView
from .views import PostListCreateAPIView
from .views import PostReactionAPIView

urlpatterns = [
    path("feed", FeedListAPIView.as_view(), name="api_feed_list"),
    path("posts", PostListCreateAPIView.as_view(), name="api_posts_list_create"),
    path("posts/<int:post_id>", PostDetailAPIView.as_view(), name="api_posts_detail"),
    path(
        "posts/<int:post_id>/comments",
        PostCommentListCreateAPIView.as_view(),
        name="api_posts_comments_list_create",
    ),
    path("comments/<int:comment_id>", CommentDetailAPIView.as_view(), name="api_comments_detail"),
    path(
        "posts/<int:post_id>/reaction",
        PostReactionAPIView.as_view(),
        name="api_posts_reaction",
    ),
    path(
        "comments/<int:comment_id>/reaction",
        CommentReactionAPIView.as_view(),
        name="api_comments_reaction",
    ),
]
