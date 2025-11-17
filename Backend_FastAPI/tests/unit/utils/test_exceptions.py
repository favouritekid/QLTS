# tests/utils/test_exceptions.py
"""
Unit tests for custom exception hierarchy.

Tests all custom exceptions defined in app.utils.exceptions to ensure:
- Correct HTTP status codes
- Proper error messages
- Error code consistency
- Context handling
- Exception hierarchy
"""

import pytest
from fastapi import status

from app.utils import exceptions as app_exceptions
from app.utils.exceptions import (
    BaseAppException,
    ResourceNotFoundError,
    UserNotFoundError,
    LeadNotFoundError,
    OrganizationNotFoundError,
    SessionNotFoundError,
    DuplicateResourceError,
    DataValidationError,
    FileValidationError,
    FileSizeError,
    FileTypeError,
    AuthenticationError,
    InvalidCredentials,
    InvalidToken,
    SessionRevokedError,
    PermissionDeniedError,
    ServiceError,
    CacheServiceError,
    SessionServiceError,
    SessionRevocationError,
    EmailServiceError,
    UserServiceError,
    WebSocketServiceError,
    EXCEPTION_HTTP_STATUS_MAP,
)

# Use alias to avoid conflict with pydantic ValidationError
ValidationError = app_exceptions.ValidationError


# ============================================================================
# BASE EXCEPTION TESTS
# ============================================================================


class TestBaseAppException:
    """Tests for BaseAppException class."""

    def test_default_values(self):
        """Test that BaseAppException has correct default values."""
        exc = BaseAppException()
        assert exc.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert exc.detail == "An internal server error occurred."
        assert exc.error_code == "INTERNAL_ERROR"
        assert exc.context == {}

    def test_custom_detail(self):
        """Test that custom detail message overrides default."""
        custom_message = "Custom error message"
        exc = BaseAppException(detail=custom_message)
        assert exc.detail == custom_message
        assert str(exc) == custom_message

    def test_with_context(self):
        """Test exception with context data."""
        context = {"user_id": 123, "action": "delete"}
        exc = BaseAppException(detail="Test error", context=context)
        assert exc.context == context
        assert "user_id" in str(exc)
        assert "delete" in str(exc)

    def test_string_representation(self):
        """Test __str__ method."""
        exc = BaseAppException(detail="Test")
        assert str(exc) == "Test"

        exc_with_context = BaseAppException(
            detail="Test", context={"key": "value"}
        )
        str_repr = str(exc_with_context)
        assert "Test" in str_repr
        assert "context" in str_repr


# ============================================================================
# RESOURCE EXCEPTION TESTS (404, 409)
# ============================================================================


class TestResourceNotFoundError:
    """Tests for ResourceNotFoundError and its subclasses."""

    def test_base_resource_not_found(self):
        """Test base ResourceNotFoundError."""
        exc = ResourceNotFoundError()
        assert exc.status_code == status.HTTP_404_NOT_FOUND
        assert exc.error_code == "RESOURCE_NOT_FOUND"

    def test_user_not_found(self):
        """Test UserNotFoundError."""
        exc = UserNotFoundError(detail="User 123 not found")
        assert exc.status_code == status.HTTP_404_NOT_FOUND
        assert exc.error_code == "USER_NOT_FOUND"
        assert "User 123" in exc.detail
        assert isinstance(exc, ResourceNotFoundError)

    def test_lead_not_found(self):
        """Test LeadNotFoundError."""
        exc = LeadNotFoundError()
        assert exc.status_code == status.HTTP_404_NOT_FOUND
        assert exc.error_code == "LEAD_NOT_FOUND"

    def test_organization_not_found(self):
        """Test OrganizationNotFoundError."""
        exc = OrganizationNotFoundError()
        assert exc.status_code == status.HTTP_404_NOT_FOUND
        assert exc.error_code == "ORGANIZATION_NOT_FOUND"

    def test_session_not_found(self):
        """Test SessionNotFoundError."""
        exc = SessionNotFoundError()
        assert exc.status_code == status.HTTP_404_NOT_FOUND
        assert exc.error_code == "SESSION_NOT_FOUND"


class TestDuplicateResourceError:
    """Tests for DuplicateResourceError."""

    def test_duplicate_resource(self):
        """Test DuplicateResourceError."""
        exc = DuplicateResourceError(detail="User already exists")
        assert exc.status_code == status.HTTP_409_CONFLICT
        assert exc.error_code == "DUPLICATE_RESOURCE"
        assert "already exists" in exc.detail


# ============================================================================
# VALIDATION EXCEPTION TESTS (400)
# ============================================================================


class TestValidationErrors:
    """Tests for validation error classes."""

    def test_base_validation_error(self):
        """Test base ValidationError."""
        exc = ValidationError()
        assert exc.status_code == status.HTTP_400_BAD_REQUEST
        assert exc.error_code == "VALIDATION_ERROR"

    def test_data_validation_error(self):
        """Test DataValidationError."""
        exc = DataValidationError(detail="Invalid email format")
        assert exc.status_code == status.HTTP_400_BAD_REQUEST
        assert exc.error_code == "DATA_VALIDATION_ERROR"
        assert isinstance(exc, ValidationError)

    def test_file_validation_error(self):
        """Test FileValidationError base class."""
        exc = FileValidationError()
        assert exc.status_code == status.HTTP_400_BAD_REQUEST
        assert exc.error_code == "FILE_VALIDATION_ERROR"

    def test_file_size_error(self):
        """Test FileSizeError."""
        exc = FileSizeError(
            detail="File size 10MB exceeds limit of 5MB",
            context={"size": 10485760, "limit": 5242880}
        )
        assert exc.status_code == status.HTTP_400_BAD_REQUEST
        assert exc.error_code == "FILE_SIZE_ERROR"
        assert isinstance(exc, FileValidationError)
        assert exc.context["size"] == 10485760

    def test_file_type_error(self):
        """Test FileTypeError."""
        exc = FileTypeError(
            detail="File type 'exe' not allowed",
            context={"file_type": "exe", "allowed": ["jpg", "png"]}
        )
        assert exc.status_code == status.HTTP_400_BAD_REQUEST
        assert exc.error_code == "FILE_TYPE_ERROR"
        assert isinstance(exc, FileValidationError)


# ============================================================================
# AUTHENTICATION & AUTHORIZATION TESTS (401, 403)
# ============================================================================


class TestAuthenticationErrors:
    """Tests for authentication error classes."""

    def test_base_authentication_error(self):
        """Test base AuthenticationError."""
        exc = AuthenticationError()
        assert exc.status_code == status.HTTP_401_UNAUTHORIZED
        assert exc.error_code == "AUTHENTICATION_ERROR"
        assert exc.headers == {"WWW-Authenticate": "Bearer"}

    def test_invalid_credentials(self):
        """Test InvalidCredentials."""
        exc = InvalidCredentials()
        assert exc.status_code == status.HTTP_401_UNAUTHORIZED
        assert exc.error_code == "INVALID_CREDENTIALS"
        assert isinstance(exc, AuthenticationError)

    def test_invalid_token(self):
        """Test InvalidToken."""
        exc = InvalidToken(detail="JWT token expired")
        assert exc.status_code == status.HTTP_401_UNAUTHORIZED
        assert exc.error_code == "INVALID_TOKEN"
        assert "expired" in exc.detail.lower()

    def test_session_revoked_error(self):
        """Test SessionRevokedError."""
        exc = SessionRevokedError()
        assert exc.status_code == status.HTTP_401_UNAUTHORIZED
        assert exc.error_code == "SESSION_REVOKED"
        assert isinstance(exc, AuthenticationError)


class TestPermissionDeniedError:
    """Tests for PermissionDeniedError."""

    def test_permission_denied(self):
        """Test PermissionDeniedError."""
        exc = PermissionDeniedError(
            detail="Admin role required",
            context={"required_role": "admin", "user_role": "user"}
        )
        assert exc.status_code == status.HTTP_403_FORBIDDEN
        assert exc.error_code == "PERMISSION_DENIED"
        assert exc.context["required_role"] == "admin"


# ============================================================================
# SERVICE ERROR TESTS (500)
# ============================================================================


class TestServiceErrors:
    """Tests for service layer error classes."""

    def test_base_service_error(self):
        """Test base ServiceError."""
        exc = ServiceError()
        assert exc.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert exc.error_code == "SERVICE_ERROR"

    def test_cache_service_error(self):
        """Test CacheServiceError."""
        exc = CacheServiceError(
            detail="Redis connection failed",
            context={"operation": "set", "key": "user:123"}
        )
        assert exc.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert exc.error_code == "CACHE_ERROR"
        assert isinstance(exc, ServiceError)
        assert exc.context["operation"] == "set"

    def test_session_service_error(self):
        """Test SessionServiceError."""
        exc = SessionServiceError()
        assert exc.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert exc.error_code == "SESSION_SERVICE_ERROR"
        assert isinstance(exc, ServiceError)

    def test_session_revocation_error(self):
        """Test SessionRevocationError."""
        exc = SessionRevocationError(
            detail="Failed to revoke session 456"
        )
        assert exc.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert exc.error_code == "SESSION_REVOCATION_ERROR"
        assert isinstance(exc, SessionServiceError)

    def test_email_service_error(self):
        """Test EmailServiceError."""
        exc = EmailServiceError(
            detail="SMTP server unreachable",
            context={"server": "smtp.example.com", "port": 587}
        )
        assert exc.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert exc.error_code == "EMAIL_ERROR"
        assert isinstance(exc, ServiceError)

    def test_user_service_error(self):
        """Test UserServiceError."""
        exc = UserServiceError()
        assert exc.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert exc.error_code == "USER_SERVICE_ERROR"
        assert isinstance(exc, ServiceError)

    def test_websocket_service_error(self):
        """Test WebSocketServiceError."""
        exc = WebSocketServiceError()
        assert exc.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert exc.error_code == "WEBSOCKET_ERROR"
        assert isinstance(exc, ServiceError)


# ============================================================================
# EXCEPTION MAPPING TABLE TESTS
# ============================================================================


class TestExceptionMapping:
    """Tests for EXCEPTION_HTTP_STATUS_MAP."""

    def test_mapping_exists(self):
        """Test that mapping table exists and is not empty."""
        assert EXCEPTION_HTTP_STATUS_MAP is not None
        assert len(EXCEPTION_HTTP_STATUS_MAP) > 0

    def test_mapping_correctness(self):
        """Test that mapping contains correct status codes."""
        # Sample checks
        assert EXCEPTION_HTTP_STATUS_MAP[UserNotFoundError] == 404
        assert EXCEPTION_HTTP_STATUS_MAP[AuthenticationError] == 401
        assert EXCEPTION_HTTP_STATUS_MAP[PermissionDeniedError] == 403
        assert EXCEPTION_HTTP_STATUS_MAP[ValidationError] == 400
        assert EXCEPTION_HTTP_STATUS_MAP[DuplicateResourceError] == 409
        assert EXCEPTION_HTTP_STATUS_MAP[ServiceError] == 500

    def test_all_exceptions_mapped(self):
        """Test that all exception classes are in the mapping."""
        expected_exceptions = [
            ValidationError,
            DataValidationError,
            FileValidationError,
            FileSizeError,
            FileTypeError,
            AuthenticationError,
            InvalidCredentials,
            InvalidToken,
            SessionRevokedError,
            PermissionDeniedError,
            ResourceNotFoundError,
            UserNotFoundError,
            LeadNotFoundError,
            OrganizationNotFoundError,
            SessionNotFoundError,
            DuplicateResourceError,
            BaseAppException,
            ServiceError,
            CacheServiceError,
            SessionServiceError,
            SessionRevocationError,
            EmailServiceError,
            UserServiceError,
            WebSocketServiceError,
        ]

        for exc_class in expected_exceptions:
            assert exc_class in EXCEPTION_HTTP_STATUS_MAP, \
                f"{exc_class.__name__} not found in mapping"


# ============================================================================
# EXCEPTION HIERARCHY TESTS
# ============================================================================


class TestExceptionHierarchy:
    """Tests for exception inheritance hierarchy."""

    def test_user_not_found_hierarchy(self):
        """Test UserNotFoundError inheritance chain."""
        exc = UserNotFoundError()
        assert isinstance(exc, UserNotFoundError)
        assert isinstance(exc, ResourceNotFoundError)
        assert isinstance(exc, BaseAppException)
        assert isinstance(exc, Exception)

    def test_file_size_error_hierarchy(self):
        """Test FileSizeError inheritance chain."""
        exc = FileSizeError()
        assert isinstance(exc, FileSizeError)
        assert isinstance(exc, FileValidationError)
        assert isinstance(exc, ValidationError)
        assert isinstance(exc, BaseAppException)

    def test_session_revocation_error_hierarchy(self):
        """Test SessionRevocationError inheritance chain."""
        exc = SessionRevocationError()
        assert isinstance(exc, SessionRevocationError)
        assert isinstance(exc, SessionServiceError)
        assert isinstance(exc, ServiceError)
        assert isinstance(exc, BaseAppException)

    def test_invalid_credentials_hierarchy(self):
        """Test InvalidCredentials inheritance chain."""
        exc = InvalidCredentials()
        assert isinstance(exc, InvalidCredentials)
        assert isinstance(exc, AuthenticationError)
        assert isinstance(exc, BaseAppException)


# ============================================================================
# INTEGRATION TESTS
# ============================================================================


class TestExceptionIntegration:
    """Integration tests for exception usage scenarios."""

    def test_raise_and_catch_user_not_found(self):
        """Test raising and catching UserNotFoundError."""
        with pytest.raises(UserNotFoundError) as exc_info:
            raise UserNotFoundError(
                detail="User 999 not found",
                context={"user_id": 999}
            )

        assert exc_info.value.status_code == 404
        assert "999" in str(exc_info.value)
        assert exc_info.value.context["user_id"] == 999

    def test_catch_specific_vs_base(self):
        """Test that specific exceptions can be caught by base class."""
        try:
            raise CacheServiceError("Redis down")
        except ServiceError as e:
            assert isinstance(e, CacheServiceError)
            assert e.error_code == "CACHE_ERROR"

    def test_exception_chaining(self):
        """Test exception chaining with context."""
        try:
            try:
                raise ConnectionError("Database unreachable")
            except ConnectionError as e:
                raise UserServiceError(
                    detail="Failed to fetch user",
                    context={"original_error": str(e)}
                )
        except UserServiceError as exc:
            assert "Failed to fetch user" in exc.detail
            assert "Database unreachable" in exc.context["original_error"]
