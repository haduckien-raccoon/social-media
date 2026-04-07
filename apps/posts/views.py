"""REST API transport layer for posts/comment/reaction domain."""

from __future__ import annotations

import logging

from apps.core.logging_utils import set_log_context
from rest_framework import status
from rest_framework.parsers import FormParser
from rest_framework.parsers import JSONParser
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .exceptions import PostsServiceError
from .serializers import CommentSerializer
from .serializers import CreateCommentSerializer
from .serializers import CreatePostSerializer
from .serializers import PostSerializer
from .serializers import ReactionSerializer
from .serializers import UpdateCommentSerializer
from .services import create_comment
from .services import create_post
from .services import get_post
from .services import list_following_feed_query
from .services import list_post_comments
from .services import list_posts_query
from .services import set_comment_reaction
from .services import set_post_reaction
from .services import soft_delete_comment
from .services import update_comment
from .utils import resolve_request_id


DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100
logger = logging.getLogger(__name__)


def _pagination_params(request):
    limit = request.query_params.get("limit", DEFAULT_PAGE_SIZE)
    offset = request.query_params.get("offset", 0)

    try:
        limit = min(MAX_PAGE_SIZE, max(1, int(limit)))
        offset = max(0, int(offset))
    except (TypeError, ValueError):
        limit = DEFAULT_PAGE_SIZE
        offset = 0

    return limit, offset


def _service_error_response(exc: PostsServiceError):
    return Response(
        {
            "detail": exc.message,
            "code": exc.error_code,
        },
        status=exc.status_code,
    )


class PostListCreateAPIView(APIView):
    """GET posts list and POST new post."""

    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get(self, request):
        set_log_context(
            request_id=resolve_request_id(request),
            user_id=getattr(request.user, "id", None),
            action=request.method,
        )
        limit, offset = _pagination_params(request)
        queryset = list_posts_query()
        total = queryset.count()
        rows = queryset[offset : offset + limit]

        return Response(
            {
                "count": total,
                "limit": limit,
                "offset": offset,
                "results": PostSerializer(rows, many=True, context={"request": request}).data,
            }
        )

    def post(self, request):
        serializer = CreatePostSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        request_id = resolve_request_id(request)
        set_log_context(request_id=request_id, user_id=getattr(request.user, "id", None), action=request.method)

        try:
            post = create_post(
                author=request.user,
                content=serializer.validated_data.get("content", ""),
                attachments=request.FILES.getlist("attachments"),
                request_id=request_id,
            )
        except PostsServiceError as exc:
            logger.warning(
                "create_post failed",
                extra={"request_id": request_id, "error_code": exc.error_code},
            )
            return _service_error_response(exc)

        return Response(
            PostSerializer(post, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )


class FeedListAPIView(APIView):
    """GET following feed (accepted friends + self)."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        request_id = resolve_request_id(request)
        set_log_context(
            request_id=request_id,
            user_id=getattr(request.user, "id", None),
            action=request.method,
        )

        limit, offset = _pagination_params(request)
        queryset = list_following_feed_query(viewer=request.user)
        total = queryset.count()
        rows = queryset[offset : offset + limit]

        return Response(
            {
                "count": total,
                "limit": limit,
                "offset": offset,
                "results": PostSerializer(rows, many=True, context={"request": request}).data,
            }
        )


class PostDetailAPIView(APIView):
    """GET one post by id."""

    permission_classes = [IsAuthenticated]

    def get(self, request, post_id: int):
        set_log_context(
            request_id=resolve_request_id(request),
            user_id=getattr(request.user, "id", None),
            action=request.method,
            post_id=post_id,
        )
        try:
            post = get_post(post_id)
        except PostsServiceError as exc:
            logger.warning(
                "get_post failed",
                extra={"request_id": resolve_request_id(request), "error_code": exc.error_code},
            )
            return _service_error_response(exc)

        return Response(PostSerializer(post, context={"request": request}).data)


class PostCommentListCreateAPIView(APIView):
    """GET comments for post and POST new comment/reply."""

    permission_classes = [IsAuthenticated]

    def get(self, request, post_id: int):
        set_log_context(
            request_id=resolve_request_id(request),
            user_id=getattr(request.user, "id", None),
            action=request.method,
            post_id=post_id,
        )
        limit, offset = _pagination_params(request)

        try:
            queryset = list_post_comments(post_id)
        except PostsServiceError as exc:
            logger.warning(
                "list_post_comments failed",
                extra={"request_id": resolve_request_id(request), "error_code": exc.error_code},
            )
            return _service_error_response(exc)

        total = queryset.count()
        rows = queryset[offset : offset + limit]
        return Response(
            {
                "count": total,
                "limit": limit,
                "offset": offset,
                "results": CommentSerializer(rows, many=True).data,
            }
        )

    def post(self, request, post_id: int):
        serializer = CreateCommentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        request_id = resolve_request_id(request)
        set_log_context(
            request_id=request_id,
            user_id=getattr(request.user, "id", None),
            action=request.method,
            post_id=post_id,
        )
        try:
            comment = create_comment(
                actor=request.user,
                post_id=post_id,
                content=serializer.validated_data["content"],
                parent_id=serializer.validated_data.get("parent_id"),
                request_id=request_id,
            )
        except PostsServiceError as exc:
            logger.warning(
                "create_comment failed",
                extra={"request_id": request_id, "error_code": exc.error_code},
            )
            return _service_error_response(exc)

        return Response(CommentSerializer(comment).data, status=status.HTTP_201_CREATED)


class CommentDetailAPIView(APIView):
    """PATCH to edit comment and DELETE to soft-delete comment."""

    permission_classes = [IsAuthenticated]

    def patch(self, request, comment_id: int):
        serializer = UpdateCommentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        request_id = resolve_request_id(request)
        set_log_context(
            request_id=request_id,
            user_id=getattr(request.user, "id", None),
            action=request.method,
        )

        try:
            comment = update_comment(
                actor=request.user,
                comment_id=comment_id,
                content=serializer.validated_data["content"],
                request_id=request_id,
            )
        except PostsServiceError as exc:
            logger.warning(
                "update_comment failed",
                extra={"request_id": request_id, "error_code": exc.error_code},
            )
            return _service_error_response(exc)

        return Response(CommentSerializer(comment).data)

    def delete(self, request, comment_id: int):
        request_id = resolve_request_id(request)
        set_log_context(
            request_id=request_id,
            user_id=getattr(request.user, "id", None),
            action=request.method,
        )

        try:
            comment = soft_delete_comment(
                actor=request.user,
                comment_id=comment_id,
                request_id=request_id,
            )
        except PostsServiceError as exc:
            logger.warning(
                "soft_delete_comment failed",
                extra={"request_id": request_id, "error_code": exc.error_code},
            )
            return _service_error_response(exc)

        return Response(CommentSerializer(comment).data)


class PostReactionAPIView(APIView):
    """PUT reaction on post with toggle behavior."""

    permission_classes = [IsAuthenticated]

    def put(self, request, post_id: int):
        serializer = ReactionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        request_id = resolve_request_id(request)
        set_log_context(
            request_id=request_id,
            user_id=getattr(request.user, "id", None),
            action=request.method,
            post_id=post_id,
        )

        try:
            payload = set_post_reaction(
                actor=request.user,
                post_id=post_id,
                reaction_type=serializer.validated_data["reaction_type"],
                request_id=request_id,
            )
        except PostsServiceError as exc:
            logger.warning(
                "set_post_reaction failed",
                extra={"request_id": request_id, "error_code": exc.error_code},
            )
            return _service_error_response(exc)

        return Response(payload)


class CommentReactionAPIView(APIView):
    """PUT reaction on comment with toggle behavior."""

    permission_classes = [IsAuthenticated]

    def put(self, request, comment_id: int):
        serializer = ReactionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        request_id = resolve_request_id(request)
        set_log_context(
            request_id=request_id,
            user_id=getattr(request.user, "id", None),
            action=request.method,
        )

        try:
            payload = set_comment_reaction(
                actor=request.user,
                comment_id=comment_id,
                reaction_type=serializer.validated_data["reaction_type"],
                request_id=request_id,
            )
        except PostsServiceError as exc:
            logger.warning(
                "set_comment_reaction failed",
                extra={"request_id": request_id, "error_code": exc.error_code},
            )
            return _service_error_response(exc)

        return Response(payload)
