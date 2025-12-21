# app/utils/exceptions.py
"""
Custom exception hierarchy for the application.

This module defines all custom exceptions used throughout the application,
replacing direct usage of FastAPI's HTTPException in service and utility layers.

Exception Hierarchy:
    BaseAppException
    ├── ResourceNotFoundError
    │   ├── UserNotFoundError
    │   ├── LeadNotFoundError
    │   ├── OrganizationNotFoundError
    │   └── SessionNotFoundError
    ├── DuplicateResourceError
    ├── ConflictError
    ├── ValidationError
    │   ├── FileValidationError
    │   │   ├── FileSizeError
    │   │   └── FileTypeError
    │   └── DataValidationError
    ├── PermissionDeniedError
    ├── AuthenticationError
    │   ├── InvalidCredentials
    │   ├── InvalidToken
    │   └── SessionRevokedError
    └── ServiceError
        ├── CacheServiceError
        ├── SessionServiceError
        ├── EmailServiceError
        ├── UserServiceError
        └── WebSocketServiceError

Usage:
    In services, raise custom exceptions:
        raise UserNotFoundError(f"User {user_id} not found")

    In routers, catch and convert to HTTPException:
        try:
            user = await user_service.get_user(db, user_id)
        except UserNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e))

    Or use exception handlers in main.py to auto-convert.
"""

from typing import Any, Dict, Optional
from fastapi import status


# ============================================================================
# BASE EXCEPTIONS
# ============================================================================


class BaseAppException(Exception):
    """
    Base class for all custom exceptions in the application.

    Attributes:
        status_code: HTTP status code for this exception (default 500)
        detail: Human-readable error message
        error_code: Machine-readable error code for API consumers
        context: Additional context data for debugging
    """

    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    detail: str = "An internal server error occurred."
    error_code: str = "INTERNAL_ERROR"

    def __init__(
        self,
        detail: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ):
        """
        Initialize exception with custom detail message and context.

        Args:
            detail: Custom error message (overrides class default)
            context: Additional context data (e.g., {"user_id": 123})
        """
        if detail is not None:
            self.detail = detail
        self.context = context or {}
        super().__init__(self.detail)

    def __str__(self) -> str:
        """String representation of the exception."""
        if self.context:
            return f"{self.detail} (context: {self.context})"
        return self.detail


# ============================================================================
# RESOURCE EXCEPTIONS (404, 409)
# ============================================================================


class ResourceNotFoundError(BaseAppException):
    """Base class for resource not found errors (HTTP 404)."""

    status_code = status.HTTP_404_NOT_FOUND
    detail = "The requested resource was not found."
    error_code = "RESOURCE_NOT_FOUND"


class UserNotFoundError(ResourceNotFoundError):
    """User not found in database."""

    detail = "User not found."
    error_code = "USER_NOT_FOUND"


class LeadNotFoundError(ResourceNotFoundError):
    """Lead not found in database."""

    detail = "Lead not found."
    error_code = "LEAD_NOT_FOUND"


class OrganizationNotFoundError(ResourceNotFoundError):
    """Organization unit not found in database."""

    detail = "Organization unit not found."
    error_code = "ORGANIZATION_NOT_FOUND"


class SessionNotFoundError(ResourceNotFoundError):
    """User session not found in database."""

    detail = "Session not found."
    error_code = "SESSION_NOT_FOUND"


class DuplicateResourceError(BaseAppException):
    """Resource already exists (HTTP 409)."""

    status_code = status.HTTP_409_CONFLICT
    detail = "This resource already exists."
    error_code = "DUPLICATE_RESOURCE"


class ConflictError(BaseAppException):
    """
    State conflict error (HTTP 409).

    Used for:
    - Optimistic locking failures (version mismatch)
    - Concurrent operation conflicts (race conditions)
    - Business logic state conflicts

    Different from DuplicateResourceError which is for unique constraint violations.
    """

    status_code = status.HTTP_409_CONFLICT
    detail = "Request conflicts with current state."
    error_code = "CONFLICT"


# ============================================================================
# VALIDATION EXCEPTIONS (400)
# ============================================================================


class ValidationError(BaseAppException):
    """Base class for validation errors (HTTP 400)."""

    status_code = status.HTTP_400_BAD_REQUEST
    detail = "Validation error."
    error_code = "VALIDATION_ERROR"


class DataValidationError(ValidationError):
    """Data validation failed."""

    detail = "Data validation failed."
    error_code = "DATA_VALIDATION_ERROR"


class FileValidationError(ValidationError):
    """File validation error base class."""

    detail = "File validation failed."
    error_code = "FILE_VALIDATION_ERROR"


class FileSizeError(FileValidationError):
    """File size exceeds limit."""

    detail = "File size exceeds maximum allowed size."
    error_code = "FILE_SIZE_ERROR"


class FileTypeError(FileValidationError):
    """File type not allowed."""

    detail = "File type not allowed."
    error_code = "FILE_TYPE_ERROR"


# ============================================================================
# AUTHENTICATION & AUTHORIZATION EXCEPTIONS (401, 403)
# ============================================================================


class AuthenticationError(BaseAppException):
    """Base class for authentication errors (HTTP 401)."""

    status_code = status.HTTP_401_UNAUTHORIZED
    detail = "Authentication required."
    error_code = "AUTHENTICATION_ERROR"
    headers = {"WWW-Authenticate": "Bearer"}


class InvalidCredentials(AuthenticationError):
    """Invalid username or password."""

    detail = "Incorrect username or password."
    error_code = "INVALID_CREDENTIALS"


class InvalidToken(AuthenticationError):
    """JWT token is invalid or expired."""

    detail = "Could not validate credentials (invalid or expired token)."
    error_code = "INVALID_TOKEN"


class SessionRevokedError(AuthenticationError):
    """User session has been revoked."""

    detail = "Your session has been revoked. Please login again."
    error_code = "SESSION_REVOKED"


class SessionExpiredError(AuthenticationError):
    """User session has expired."""

    detail = "Your session has expired. Please login again."
    error_code = "SESSION_EXPIRED"


class PermissionDeniedError(BaseAppException):
    """User does not have permission (HTTP 403)."""

    status_code = status.HTTP_403_FORBIDDEN
    detail = "You do not have permission to perform this action."
    error_code = "PERMISSION_DENIED"


# Alias for convenience (Level-specific IDOR checks)
ForbiddenError = PermissionDeniedError


# ============================================================================
# SERVICE LAYER EXCEPTIONS (500)
# ============================================================================


class ServiceError(BaseAppException):
    """
    Base class for service layer errors.

    These exceptions indicate that something went wrong in the service layer,
    independent of HTTP protocol. They should be caught by routers and
    converted to appropriate HTTP responses.
    """

    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    detail = "A service error occurred."
    error_code = "SERVICE_ERROR"


class CacheServiceError(ServiceError):
    """Error occurred in cache operations (Redis)."""

    detail = "Cache operation failed."
    error_code = "CACHE_ERROR"


class SessionServiceError(ServiceError):
    """Error occurred in session management."""

    detail = "Session management error."
    error_code = "SESSION_SERVICE_ERROR"


class SessionRevocationError(SessionServiceError):
    """Failed to revoke user session."""

    detail = "Failed to revoke session."
    error_code = "SESSION_REVOCATION_ERROR"


class EmailServiceError(ServiceError):
    """Error occurred in email sending."""

    detail = "Email service error."
    error_code = "EMAIL_ERROR"


class UserServiceError(ServiceError):
    """Error occurred in user service operations."""

    detail = "User service error."
    error_code = "USER_SERVICE_ERROR"


class WebSocketServiceError(ServiceError):
    """Error occurred in WebSocket operations."""

    detail = "WebSocket service error."
    error_code = "WEBSOCKET_ERROR"


# ============================================================================
# LEGACY SUPPORT (Deprecated)
# ============================================================================


class BadRequest(ValidationError):
    """
    DEPRECATED: Use ValidationError or specific subclasses instead.
    Kept for backward compatibility.
    """

    detail = "Bad request."
    error_code = "BAD_REQUEST"


# ============================================================================
# EXCEPTION MAPPING TABLE (for documentation)
# ============================================================================

EXCEPTION_HTTP_STATUS_MAP = {
    # 400 Bad Request
    ValidationError: 400,
    DataValidationError: 400,
    FileValidationError: 400,
    FileSizeError: 400,
    FileTypeError: 400,
    BadRequest: 400,
    # 401 Unauthorized
    AuthenticationError: 401,
    InvalidCredentials: 401,
    InvalidToken: 401,
    SessionRevokedError: 401,
    # 403 Forbidden
    PermissionDeniedError: 403,
    # 404 Not Found
    ResourceNotFoundError: 404,
    UserNotFoundError: 404,
    LeadNotFoundError: 404,
    OrganizationNotFoundError: 404,
    SessionNotFoundError: 404,
    # 409 Conflict
    DuplicateResourceError: 409,
    ConflictError: 409,
    # 500 Internal Server Error
    BaseAppException: 500,
    ServiceError: 500,
    CacheServiceError: 500,
    SessionServiceError: 500,
    SessionRevocationError: 500,
    EmailServiceError: 500,
    UserServiceError: 500,
    WebSocketServiceError: 500,
}
