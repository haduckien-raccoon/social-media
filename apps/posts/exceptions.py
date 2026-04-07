"""Domain-level exceptions for post/comment/reaction services."""


class PostsServiceError(Exception):
    """Base exception carrying status code and machine-readable error code."""

    status_code = 400
    error_code = "posts_error"

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class PostsNotFoundError(PostsServiceError):
    status_code = 404
    error_code = "not_found"


class PostsValidationError(PostsServiceError):
    status_code = 400
    error_code = "validation_error"


class PostsPermissionDeniedError(PostsServiceError):
    status_code = 403
    error_code = "permission_denied"
