# app/middleware/csrf.py
"""
CSRF Protection Middleware.

Implements Double-Submit Cookie pattern for CSRF protection:
1. On login, server generates a random CSRF token
2. Token is stored in a non-httpOnly cookie (readable by JS)
3. Client must send token in X-CSRF-Token header for state-changing requests
4. Server validates header token matches cookie token

This protects against CSRF because:
- Attacker cannot read the CSRF cookie due to Same-Origin Policy
- Attacker cannot set custom headers in cross-origin requests
- Even with SameSite=Lax, the header requirement blocks CSRF

Usage:
    from app.middleware.csrf import CSRFMiddleware, generate_csrf_token

    # In main.py
    app.add_middleware(CSRFMiddleware)

    # In auth.py (login endpoint)
    csrf_token = generate_csrf_token()
    response.set_cookie("csrf_token", csrf_token, httponly=False, ...)
"""

import secrets
from typing import Callable, List, Optional, Set

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp
import structlog

from ..config import settings

log = structlog.get_logger(__name__)

# Constants
CSRF_COOKIE_NAME = "csrf_token"
CSRF_HEADER_NAME = "X-CSRF-Token"
CSRF_TOKEN_LENGTH = 32  # 256 bits of entropy

# HTTP methods that require CSRF protection (state-changing)
PROTECTED_METHODS: Set[str] = {"POST", "PUT", "DELETE", "PATCH"}

# Endpoints that are exempt from CSRF protection
# (e.g., login itself, public APIs, webhooks)
EXEMPT_PATHS: List[str] = [
    "/api/auth/login",
    "/api/auth/register",
    "/api/auth/forgot-password",
    "/api/auth/reset-password",
    "/api/auth/refresh",
    "/api/public/",
    "/api/webhooks/",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/health",
    "/metrics",
]


def generate_csrf_token() -> str:
    """
    Generate a cryptographically secure CSRF token.

    Returns:
        32-character URL-safe base64 token (256 bits of entropy)
    """
    return secrets.token_urlsafe(CSRF_TOKEN_LENGTH)


def is_path_exempt(path: str) -> bool:
    """Check if a path is exempt from CSRF protection."""
    for exempt in EXEMPT_PATHS:
        if path.startswith(exempt):
            return True
    return False


class CSRFMiddleware(BaseHTTPMiddleware):
    """
    CSRF Protection Middleware using Double-Submit Cookie pattern.

    Configuration:
        - Enabled by default in production
        - Can be disabled via CSRF_PROTECTION_ENABLED setting
        - Exempt paths can be configured via EXEMPT_PATHS

    Behavior:
        - GET, HEAD, OPTIONS requests are not protected (safe methods)
        - POST, PUT, DELETE, PATCH require X-CSRF-Token header
        - Token must match the csrf_token cookie value
        - Returns 403 Forbidden if validation fails
    """

    def __init__(
        self,
        app: ASGIApp,
        enabled: Optional[bool] = None,
        exempt_paths: Optional[List[str]] = None,
    ):
        super().__init__(app)
        # Allow override via constructor or use settings
        self.enabled = enabled if enabled is not None else getattr(
            settings, 'CSRF_PROTECTION_ENABLED', True
        )
        self.exempt_paths = exempt_paths or EXEMPT_PATHS

    async def dispatch(
        self, request: Request, call_next: Callable
    ) -> Response:
        # Skip if disabled
        if not self.enabled:
            return await call_next(request)

        # Skip for safe methods
        if request.method not in PROTECTED_METHODS:
            return await call_next(request)

        # Skip for exempt paths
        if is_path_exempt(request.url.path):
            return await call_next(request)

        # Skip in test environment (unless explicitly enabled)
        if settings.APP_ENV == "test" and not getattr(
            settings, 'CSRF_PROTECTION_IN_TEST', False
        ):
            return await call_next(request)

        # Validate CSRF token
        csrf_cookie = request.cookies.get(CSRF_COOKIE_NAME)
        csrf_header = request.headers.get(CSRF_HEADER_NAME)

        # Both must be present
        if not csrf_cookie:
            log.warning(
                "CSRF validation failed: missing cookie",
                path=request.url.path,
                method=request.method,
                client_ip=request.client.host if request.client else None,
            )
            return JSONResponse(
                status_code=403,
                content={
                    "detail": "CSRF token missing. Please refresh the page and try again.",
                    "error_code": "CSRF_TOKEN_MISSING",
                },
            )

        if not csrf_header:
            log.warning(
                "CSRF validation failed: missing header",
                path=request.url.path,
                method=request.method,
                client_ip=request.client.host if request.client else None,
            )
            return JSONResponse(
                status_code=403,
                content={
                    "detail": "CSRF token header missing. Include X-CSRF-Token in request headers.",
                    "error_code": "CSRF_HEADER_MISSING",
                },
            )

        # Constant-time comparison to prevent timing attacks
        if not secrets.compare_digest(csrf_cookie, csrf_header):
            log.warning(
                "CSRF validation failed: token mismatch",
                path=request.url.path,
                method=request.method,
                client_ip=request.client.host if request.client else None,
            )
            return JSONResponse(
                status_code=403,
                content={
                    "detail": "CSRF token invalid. Please refresh the page and try again.",
                    "error_code": "CSRF_TOKEN_INVALID",
                },
            )

        # Token validated, proceed with request
        return await call_next(request)


class CSRFOriginMiddleware(BaseHTTPMiddleware):
    """
    Additional CSRF protection via Origin/Referer header validation.

    This is a secondary layer of defense that validates the Origin or Referer
    header matches the allowed origins. This catches CSRF attempts even if
    the attacker somehow obtains a valid CSRF token.

    Note: This should be used in addition to CSRFMiddleware, not instead of it.
    """

    def __init__(
        self,
        app: ASGIApp,
        allowed_origins: Optional[List[str]] = None,
        enabled: Optional[bool] = None,
    ):
        super().__init__(app)
        self.enabled = enabled if enabled is not None else getattr(
            settings, 'CSRF_ORIGIN_CHECK_ENABLED', False
        )
        self.allowed_origins = allowed_origins or self._parse_cors_origins()

    def _parse_cors_origins(self) -> List[str]:
        """Parse CORS origins from settings."""
        cors_origins = getattr(settings, 'CORS_ORIGINS', '')
        if not cors_origins:
            return []
        return [o.strip() for o in cors_origins.split(',') if o.strip()]

    async def dispatch(
        self, request: Request, call_next: Callable
    ) -> Response:
        if not self.enabled:
            return await call_next(request)

        if request.method not in PROTECTED_METHODS:
            return await call_next(request)

        if is_path_exempt(request.url.path):
            return await call_next(request)

        # Check Origin header first
        origin = request.headers.get("origin")
        if origin:
            if origin not in self.allowed_origins:
                log.warning(
                    "CSRF origin check failed",
                    origin=origin,
                    allowed=self.allowed_origins,
                    path=request.url.path,
                )
                return JSONResponse(
                    status_code=403,
                    content={
                        "detail": "Origin not allowed",
                        "error_code": "CSRF_ORIGIN_INVALID",
                    },
                )
            return await call_next(request)

        # Fall back to Referer header
        referer = request.headers.get("referer")
        if referer:
            if not any(referer.startswith(o) for o in self.allowed_origins):
                log.warning(
                    "CSRF referer check failed",
                    referer=referer,
                    allowed=self.allowed_origins,
                    path=request.url.path,
                )
                return JSONResponse(
                    status_code=403,
                    content={
                        "detail": "Referer not allowed",
                        "error_code": "CSRF_REFERER_INVALID",
                    },
                )
            return await call_next(request)

        # No Origin or Referer - suspicious but allow (some browsers strip)
        log.debug(
            "CSRF check: no Origin or Referer header",
            path=request.url.path,
            method=request.method,
        )
        return await call_next(request)


def set_csrf_cookie(response: Response, token: Optional[str] = None) -> str:
    """
    Set CSRF token cookie on a response.

    Args:
        response: FastAPI Response object
        token: Optional pre-generated token. If None, generates new token.

    Returns:
        The CSRF token that was set
    """
    csrf_token = token or generate_csrf_token()

    response.set_cookie(
        key=CSRF_COOKIE_NAME,
        value=csrf_token,
        httponly=False,  # Must be readable by JavaScript
        secure=settings.APP_ENV == "production",
        samesite="strict",  # Strict for CSRF token cookie
        max_age=3600 * 24,  # 24 hours
        path="/",
    )

    return csrf_token
