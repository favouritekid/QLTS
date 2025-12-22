# app/middleware/exception_handlers.py
"""
Exception handlers for converting custom exceptions to HTTP responses.

This module provides handlers that automatically convert our custom exceptions
(defined in app.utils.exceptions) to appropriate HTTP responses, eliminating
the need to manually catch and convert them in routers.

Usage:
    In main.py:
        from app.middleware import register_exception_handlers
        register_exception_handlers(app)

    In services:
        raise UserNotFoundError(f"User {user_id} not found")

    Result:
        Automatically returns HTTP 404 with proper JSON response
"""

import logging
from typing import Union

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.utils.exceptions import (
    BaseAppException,
    ResourceNotFoundError,
    UserNotFoundError,
    LeadNotFoundError,
    OrganizationNotFoundError,
    SessionNotFoundError,
    DuplicateResourceError,
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
    ServiceError,
    CacheServiceError,
    SessionServiceError,
    SessionRevocationError,
    EmailServiceError,
    UserServiceError,
    WebSocketServiceError,
)

logger = logging.getLogger(__name__)


# ============================================================================
# CUSTOM EXCEPTION HANDLERS
# ============================================================================


async def base_app_exception_handler(
    request: Request, exc: BaseAppException
) -> JSONResponse:
    """
    Generic handler for all BaseAppException subclasses.

    This handler converts any custom exception into a JSON response with:
    - status_code: from exception.status_code
    - detail: from exception.detail
    - error_code: machine-readable error code
    - context: additional debugging information (only in dev mode)

    Args:
        request: The incoming request
        exc: The custom exception

    Returns:
        JSONResponse with error details
    """
    # Log the exception with context
    logger.warning(
        f"{exc.__class__.__name__}: {exc.detail}",
        extra={
            "error_code": exc.error_code,
            "context": exc.context,
            "path": request.url.path,
            "method": request.method,
        },
    )

    # Build response payload
    response_data = {
        "detail": exc.detail,
        "error_code": exc.error_code,
    }

    # Include context in development mode (optional)
    # if settings.APP_ENV == "development" and exc.context:
    #     response_data["context"] = exc.context

    # Add headers if present (e.g., WWW-Authenticate for 401)
    headers = getattr(exc, "headers", None)

    return JSONResponse(
        status_code=exc.status_code,
        content=response_data,
        headers=headers,
    )


async def resource_not_found_handler(
    request: Request, exc: ResourceNotFoundError
) -> JSONResponse:
    """
    Handler for resource not found errors (404).

    Provides more specific logging for missing resources.
    """
    logger.info(
        f"Resource not found: {exc.detail}",
        extra={
            "error_code": exc.error_code,
            "context": exc.context,
            "path": request.url.path,
        },
    )

    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content={
            "detail": exc.detail,
            "error_code": exc.error_code,
        },
    )


async def validation_error_handler(
    request: Request, exc: ValidationError
) -> JSONResponse:
    """
    Handler for validation errors (400).

    Includes validation context when available.
    """
    logger.info(
        f"Validation error: {exc.detail}",
        extra={
            "error_code": exc.error_code,
            "context": exc.context,
            "path": request.url.path,
        },
    )

    response_data = {
        "detail": exc.detail,
        "error_code": exc.error_code,
    }

    # Include validation errors if present
    if exc.context and "errors" in exc.context:
        response_data["errors"] = exc.context["errors"]

    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content=response_data,
    )


async def authentication_error_handler(
    request: Request, exc: AuthenticationError
) -> JSONResponse:
    """
    Handler for authentication errors (401).

    Includes WWW-Authenticate header as required by HTTP spec.
    """
    logger.warning(
        f"Authentication error: {exc.detail}",
        extra={
            "error_code": exc.error_code,
            "path": request.url.path,
        },
    )

    return JSONResponse(
        status_code=status.HTTP_401_UNAUTHORIZED,
        content={
            "detail": exc.detail,
            "error_code": exc.error_code,
        },
        headers=exc.headers,
    )


async def service_error_handler(
    request: Request, exc: ServiceError
) -> JSONResponse:
    """
    Handler for service layer errors (500).

    Logs full error details for debugging while returning safe message to client.
    """
    logger.error(
        f"Service error: {exc.detail}",
        extra={
            "error_code": exc.error_code,
            "context": exc.context,
            "path": request.url.path,
            "method": request.method,
        },
        exc_info=True,  # Include stack trace
    )

    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "detail": exc.detail,
            "error_code": exc.error_code,
        },
    )


# ============================================================================
# PYDANTIC VALIDATION ERROR HANDLER
# ============================================================================


async def pydantic_validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """
    Handler for Pydantic validation errors from request body/query params.

    Formats Pydantic errors into a consistent structure.
    """
    # Safely serialize errors - convert any non-JSON-serializable objects to strings
    def serialize_error(error: dict) -> dict:
        serialized = {}
        for key, value in error.items():
            if key == "ctx" and isinstance(value, dict):
                # Context might contain non-serializable objects like ValueError
                serialized[key] = {
                    k: str(v) if not isinstance(v, (str, int, float, bool, list, dict, type(None))) else v
                    for k, v in value.items()
                }
            elif isinstance(value, Exception):
                serialized[key] = str(value)
            else:
                serialized[key] = value
        return serialized

    safe_errors = [serialize_error(e) for e in exc.errors()]

    logger.info(
        f"Request validation error: {len(safe_errors)} errors",
        extra={
            "path": request.url.path,
            "errors": safe_errors,
        },
    )

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={
            "detail": "Request validation failed",
            "error_code": "VALIDATION_ERROR",
            "errors": safe_errors,
        },
    )


# ============================================================================
# STARLETTE HTTP EXCEPTION HANDLER (Fallback)
# ============================================================================


async def http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    """
    Handler for Starlette HTTPException (backward compatibility).

    This handles any HTTPException raised directly (e.g., from dependencies).
    """
    logger.warning(
        f"HTTP {exc.status_code}: {exc.detail}",
        extra={
            "status_code": exc.status_code,
            "path": request.url.path,
        },
    )

    return JSONResponse(
        status_code=exc.status_code,
        content={
            "detail": exc.detail,
            "error_code": f"HTTP_{exc.status_code}",
        },
        headers=getattr(exc, "headers", None),
    )


# ============================================================================
# GENERIC EXCEPTION HANDLER (Catch-all)
# ============================================================================


async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    Catch-all handler for unexpected exceptions.

    Logs the full error and returns a generic 500 response to avoid
    leaking implementation details.
    """
    logger.error(
        f"Unhandled exception: {type(exc).__name__}: {str(exc)}",
        extra={
            "path": request.url.path,
            "method": request.method,
        },
        exc_info=True,
    )

    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "detail": "An unexpected error occurred. Please try again later.",
            "error_code": "INTERNAL_ERROR",
        },
    )


# ============================================================================
# REGISTRATION FUNCTION
# ============================================================================


def register_exception_handlers(app: FastAPI) -> None:
    """
    Register all exception handlers with the FastAPI application.

    Handlers are registered in order of specificity (most specific first).
    This ensures that subclass exceptions are caught before parent classes.

    Args:
        app: The FastAPI application instance

    Example:
        from fastapi import FastAPI
        from app.middleware import register_exception_handlers

        app = FastAPI()
        register_exception_handlers(app)
    """
    # Register custom exception handlers (most specific first)

    # Service errors (500)
    app.add_exception_handler(CacheServiceError, service_error_handler)
    app.add_exception_handler(SessionServiceError, service_error_handler)
    app.add_exception_handler(SessionRevocationError, service_error_handler)
    app.add_exception_handler(EmailServiceError, service_error_handler)
    app.add_exception_handler(UserServiceError, service_error_handler)
    app.add_exception_handler(WebSocketServiceError, service_error_handler)
    app.add_exception_handler(ServiceError, service_error_handler)

    # Authentication errors (401)
    app.add_exception_handler(InvalidCredentials, authentication_error_handler)
    app.add_exception_handler(InvalidToken, authentication_error_handler)
    app.add_exception_handler(SessionRevokedError, authentication_error_handler)
    app.add_exception_handler(AuthenticationError, authentication_error_handler)

    # Authorization errors (403)
    app.add_exception_handler(PermissionDeniedError, base_app_exception_handler)

    # Resource not found errors (404)
    app.add_exception_handler(UserNotFoundError, resource_not_found_handler)
    app.add_exception_handler(LeadNotFoundError, resource_not_found_handler)
    app.add_exception_handler(OrganizationNotFoundError, resource_not_found_handler)
    app.add_exception_handler(SessionNotFoundError, resource_not_found_handler)
    app.add_exception_handler(ResourceNotFoundError, resource_not_found_handler)

    # Validation errors (400)
    app.add_exception_handler(FileSizeError, validation_error_handler)
    app.add_exception_handler(FileTypeError, validation_error_handler)
    app.add_exception_handler(FileValidationError, validation_error_handler)
    app.add_exception_handler(DataValidationError, validation_error_handler)
    app.add_exception_handler(ValidationError, validation_error_handler)

    # Duplicate resource (409)
    app.add_exception_handler(DuplicateResourceError, base_app_exception_handler)

    # Base exception handler (catch-all for custom exceptions)
    app.add_exception_handler(BaseAppException, base_app_exception_handler)

    # Pydantic validation errors (422)
    app.add_exception_handler(
        RequestValidationError, pydantic_validation_error_handler
    )

    # Starlette HTTPException (backward compatibility)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)

    # Generic exception handler (last resort)
    app.add_exception_handler(Exception, generic_exception_handler)

    logger.info("✅ Exception handlers registered successfully")
