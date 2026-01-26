# tests/unit/test_csrf_middleware.py
"""
Unit tests for CSRF Protection Middleware.

Tests the double-submit cookie pattern implementation:
- Token generation
- Cookie/header validation
- Exempt paths
- Error responses
"""

import pytest
import secrets
from unittest.mock import MagicMock, AsyncMock, patch
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from starlette.responses import JSONResponse

from app.middleware.csrf import (
    CSRFMiddleware,
    generate_csrf_token,
    is_path_exempt,
    set_csrf_cookie,
    CSRF_COOKIE_NAME,
    CSRF_HEADER_NAME,
    PROTECTED_METHODS,
    EXEMPT_PATHS,
)


class TestGenerateCSRFToken:
    """Test CSRF token generation."""

    def test_generates_token(self):
        """Should generate a non-empty token."""
        token = generate_csrf_token()
        assert token is not None
        assert len(token) > 0

    def test_generates_unique_tokens(self):
        """Should generate unique tokens on each call."""
        tokens = [generate_csrf_token() for _ in range(100)]
        assert len(set(tokens)) == 100  # All unique

    def test_token_is_url_safe(self):
        """Token should be URL-safe base64."""
        token = generate_csrf_token()
        # URL-safe base64 only contains alphanumeric, -, _
        import re
        assert re.match(r'^[A-Za-z0-9_-]+$', token)

    def test_token_has_sufficient_entropy(self):
        """Token should have at least 256 bits of entropy (32 bytes)."""
        token = generate_csrf_token()
        # URL-safe base64 encoding: 4 chars = 3 bytes
        # 32 bytes → ~43 characters
        assert len(token) >= 40


class TestIsPathExempt:
    """Test path exemption logic."""

    def test_login_is_exempt(self):
        """Login endpoint should be exempt."""
        assert is_path_exempt("/api/auth/login") is True

    def test_register_is_exempt(self):
        """Register endpoint should be exempt."""
        assert is_path_exempt("/api/auth/register") is True

    def test_refresh_is_exempt(self):
        """Refresh endpoint should be exempt."""
        assert is_path_exempt("/api/auth/refresh") is True

    def test_docs_is_exempt(self):
        """Documentation endpoints should be exempt."""
        assert is_path_exempt("/docs") is True
        assert is_path_exempt("/redoc") is True
        assert is_path_exempt("/openapi.json") is True

    def test_public_endpoints_exempt(self):
        """Public API endpoints should be exempt."""
        assert is_path_exempt("/api/public/contact") is True
        assert is_path_exempt("/api/public/programs") is True

    def test_webhooks_exempt(self):
        """Webhook endpoints should be exempt."""
        assert is_path_exempt("/api/webhooks/payment") is True

    def test_leads_not_exempt(self):
        """Business endpoints should NOT be exempt."""
        assert is_path_exempt("/api/leads") is False
        assert is_path_exempt("/api/leads/123") is False

    def test_admissions_not_exempt(self):
        """Admission endpoints should NOT be exempt."""
        assert is_path_exempt("/api/admissions") is False
        assert is_path_exempt("/api/admissions/123/status") is False


class TestSetCSRFCookie:
    """Test CSRF cookie setting."""

    def test_sets_cookie_with_generated_token(self):
        """Should set cookie with auto-generated token."""
        response = MagicMock()

        token = set_csrf_cookie(response)

        response.set_cookie.assert_called_once()
        call_kwargs = response.set_cookie.call_args[1]
        assert call_kwargs["key"] == CSRF_COOKIE_NAME
        assert call_kwargs["value"] == token
        assert call_kwargs["httponly"] is False  # Must be readable by JS
        assert call_kwargs["samesite"] == "strict"

    def test_sets_cookie_with_provided_token(self):
        """Should set cookie with provided token."""
        response = MagicMock()
        custom_token = "my_custom_token_123"

        token = set_csrf_cookie(response, token=custom_token)

        assert token == custom_token
        call_kwargs = response.set_cookie.call_args[1]
        assert call_kwargs["value"] == custom_token

    def test_cookie_not_httponly(self):
        """CSRF cookie must NOT be httpOnly (JS needs to read it)."""
        response = MagicMock()

        set_csrf_cookie(response)

        call_kwargs = response.set_cookie.call_args[1]
        assert call_kwargs["httponly"] is False


class TestCSRFMiddleware:
    """Test CSRF middleware behavior."""

    @pytest.fixture
    def app(self):
        """Create test FastAPI app with CSRF middleware."""
        app = FastAPI()

        # Create middleware instance that forces validation even in test
        class TestCSRFMiddleware(CSRFMiddleware):
            """CSRF middleware that always validates (ignores APP_ENV check)."""
            async def dispatch(self, request, call_next):
                # Skip if disabled via constructor
                if not self.enabled:
                    return await call_next(request)

                # Skip for safe methods
                if request.method not in PROTECTED_METHODS:
                    return await call_next(request)

                # Skip for exempt paths
                if is_path_exempt(request.url.path):
                    return await call_next(request)

                # Always validate (don't skip for test environment)
                csrf_cookie = request.cookies.get(CSRF_COOKIE_NAME)
                csrf_header = request.headers.get(CSRF_HEADER_NAME)

                if not csrf_cookie:
                    return JSONResponse(
                        status_code=403,
                        content={"detail": "CSRF token missing", "error_code": "CSRF_TOKEN_MISSING"},
                    )

                if not csrf_header:
                    return JSONResponse(
                        status_code=403,
                        content={"detail": "CSRF header missing", "error_code": "CSRF_HEADER_MISSING"},
                    )

                if not secrets.compare_digest(csrf_cookie, csrf_header):
                    return JSONResponse(
                        status_code=403,
                        content={"detail": "CSRF token invalid", "error_code": "CSRF_TOKEN_INVALID"},
                    )

                return await call_next(request)

        app.add_middleware(TestCSRFMiddleware, enabled=True)

        @app.get("/api/test")
        async def get_test():
            return {"status": "ok"}

        @app.post("/api/test")
        async def post_test():
            return {"status": "created"}

        @app.put("/api/test")
        async def put_test():
            return {"status": "updated"}

        @app.delete("/api/test")
        async def delete_test():
            return {"status": "deleted"}

        @app.patch("/api/test")
        async def patch_test():
            return {"status": "patched"}

        @app.post("/api/auth/login")
        async def login():
            return {"status": "logged_in"}

        return app

    @pytest.fixture
    def client(self, app):
        """Create test client."""
        return TestClient(app)

    def test_get_request_allowed_without_token(self, client):
        """GET requests should not require CSRF token."""
        response = client.get("/api/test")
        assert response.status_code == 200

    def test_post_to_exempt_path_allowed(self, client):
        """POST to exempt paths should not require CSRF token."""
        response = client.post("/api/auth/login")
        assert response.status_code == 200

    def test_post_without_cookie_rejected(self, client):
        """POST without CSRF cookie should be rejected."""
        response = client.post("/api/test")
        assert response.status_code == 403
        assert "CSRF_TOKEN_MISSING" in response.json()["error_code"]

    def test_post_without_header_rejected(self, client):
        """POST with cookie but without header should be rejected."""
        token = generate_csrf_token()
        client.cookies.set(CSRF_COOKIE_NAME, token)

        response = client.post("/api/test")
        assert response.status_code == 403
        assert "CSRF_HEADER_MISSING" in response.json()["error_code"]

    def test_post_with_mismatched_token_rejected(self, client):
        """POST with mismatched cookie/header should be rejected."""
        cookie_token = generate_csrf_token()
        header_token = generate_csrf_token()  # Different token

        client.cookies.set(CSRF_COOKIE_NAME, cookie_token)
        response = client.post(
            "/api/test",
            headers={CSRF_HEADER_NAME: header_token}
        )

        assert response.status_code == 403
        assert "CSRF_TOKEN_INVALID" in response.json()["error_code"]

    def test_post_with_valid_token_allowed(self, client):
        """POST with matching cookie/header should be allowed."""
        token = generate_csrf_token()

        client.cookies.set(CSRF_COOKIE_NAME, token)
        response = client.post(
            "/api/test",
            headers={CSRF_HEADER_NAME: token}
        )

        assert response.status_code == 200

    def test_put_requires_csrf(self, client):
        """PUT requests should require CSRF token."""
        response = client.put("/api/test")
        assert response.status_code == 403

    def test_delete_requires_csrf(self, client):
        """DELETE requests should require CSRF token."""
        response = client.delete("/api/test")
        assert response.status_code == 403

    def test_patch_requires_csrf(self, client):
        """PATCH requests should require CSRF token."""
        response = client.patch("/api/test")
        assert response.status_code == 403


class TestCSRFMiddlewareDisabled:
    """Test CSRF middleware when disabled."""

    @pytest.fixture
    def app(self):
        """Create test FastAPI app with CSRF middleware disabled."""
        app = FastAPI()
        app.add_middleware(CSRFMiddleware, enabled=False)

        @app.post("/api/test")
        async def post_test():
            return {"status": "created"}

        return app

    @pytest.fixture
    def client(self, app):
        return TestClient(app)

    def test_post_allowed_without_token_when_disabled(self, client):
        """POST should be allowed without token when middleware is disabled."""
        response = client.post("/api/test")
        assert response.status_code == 200


class TestProtectedMethods:
    """Test that correct HTTP methods are protected."""

    def test_protected_methods_are_state_changing(self):
        """Only state-changing methods should be protected."""
        assert "POST" in PROTECTED_METHODS
        assert "PUT" in PROTECTED_METHODS
        assert "DELETE" in PROTECTED_METHODS
        assert "PATCH" in PROTECTED_METHODS

    def test_safe_methods_not_protected(self):
        """Safe methods should not be protected."""
        assert "GET" not in PROTECTED_METHODS
        assert "HEAD" not in PROTECTED_METHODS
        assert "OPTIONS" not in PROTECTED_METHODS


class TestExemptPaths:
    """Test exempt paths configuration."""

    def test_auth_paths_exempt(self):
        """Authentication paths should be exempt."""
        auth_paths = [p for p in EXEMPT_PATHS if "/auth/" in p]
        assert len(auth_paths) >= 4  # login, register, forgot-password, reset-password

    def test_public_paths_exempt(self):
        """Public API paths should be exempt."""
        assert "/api/public/" in EXEMPT_PATHS

    def test_webhook_paths_exempt(self):
        """Webhook paths should be exempt."""
        assert "/api/webhooks/" in EXEMPT_PATHS

    def test_docs_paths_exempt(self):
        """Documentation paths should be exempt."""
        assert "/docs" in EXEMPT_PATHS
        assert "/redoc" in EXEMPT_PATHS
        assert "/openapi.json" in EXEMPT_PATHS
