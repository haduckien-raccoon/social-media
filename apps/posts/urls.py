from django.urls import path
from apps.posts.views import *

app_name = "posts"

urlpatterns = [
    # Feed
    path("", feed_view, name="feed"),
    path("public/", public_feed_view, name="public_feed"),
    path("hashtag/<str:tag>/", hashtag_feed_view, name="hashtag_feed"),

    # Post CRUD
    path("create/", create_post_view, name="create"),
    path("<int:post_id>/", post_detail_view, name="post_detail"),
    path("<int:post_id>/edit/", edit_post_view, name="edit_post"),
    path("<int:post_id>/delete/", delete_post_view, name="delete_post"),

    # Comment CRUD
    path("<int:post_id>/comment/", create_comment_view, name="create_comment"),
    path("comment/<int:comment_id>/edit/", edit_comment_view, name="edit_comment"),
    path("comment/<int:comment_id>/delete/", delete_comment_view, name="delete_comment"),

    # Reactions
    path("<int:post_id>/reaction/", toggle_post_reaction_view, name="post_reaction"),
    path("comment/<int:comment_id>/reaction/", toggle_comment_reaction_view, name="comment_reaction"),

    # Share
    path("<int:post_id>/share/", share_post_view, name="share_post"),

    # Report
    path("report/", report_view, name="report_post"),
    
    # Settings
    path("<int:post_id>/toggle-commenting/", toggle_commenting_view, name="toggle_commenting"),
    path("<int:post_id>/toggle-counts/", toggle_hide_counts_view, name="toggle_counts"),
]