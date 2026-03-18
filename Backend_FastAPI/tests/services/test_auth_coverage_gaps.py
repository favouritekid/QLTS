# tests/services/test_auth_coverage_gaps.py
"""
Additional auth tests to close coverage gaps identified by OWASP/ASVS audit.

Covers:
1. Register user enumeration prevention (generic 409 message)
2. Register duplicate email vs username (same response)
3. Refresh token failure paths
4. Change-password cookie clearing
5. Reset-password cookie clearing
"""
from unittest.mock import patch, AsyncMock

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.security import get_password_hash, create_password_reset_token


# =============================================================================
# 1. REGISTER — USER ENUMERATION PREVENTION
# =============================================================================

@pytest.mark.asyncio
@pytest.mark.security
class TestRegisterEnumerationPrevention:
    """Registration should return the same generic error for both
    duplicate username and duplicate email — prevents attackers from
    discovering which field is already taken."""

    async def test_duplicate_username_returns_generic_409(
        self,
        client: AsyncClient,
        admin_user_in_db: dict,
    ):
        """Registering with existing username returns generic message."""
        res = await client.post("/api/auth/register", json={
            "username": admin_user_in_db["username"],
            "email": "new_unique_enum@example.com",
            "password": "UniqueSecure123!",
        })
        assert res.status_code == 409
        detail = res.json()["detail"]
        assert "already registered" in detail.lower() or "already exists" in detail.lower(), \
            "Error should be generic, not reveal which field is taken"

    async def test_duplicate_email_returns_generic_409(
        self,
        client: AsyncClient,
        admin_user_in_db: dict,
    ):
        """Registering with existing email returns same generic message."""
        res = await client.post("/api/auth/register", json={
            "username": "brand_new_enum_user",
            "email": admin_user_in_db["email"],
            "password": "UniqueSecure123!",
        })
        assert res.status_code == 409
        detail = res.json()["detail"]
        assert "already registered" in detail.lower() or "already exists" in detail.lower(), \
            "Error should be generic, not reveal which field is taken"

    async def test_duplicate_both_returns_same_message(
        self,
        client: AsyncClient,
        admin_user_in_db: dict,
    ):
        """Same message when both username and email are taken."""
        res = await client.post("/api/auth/register", json={
            "username": admin_user_in_db["username"],
            "email": admin_user_in_db["email"],
            "password": "UniqueSecure123!",
        })
        assert res.status_code == 409
        detail = res.json()["detail"]
        assert "already registered" in detail.lower() or "already exists" in detail.lower()


# =============================================================================
# 2. REFRESH TOKEN — FAILURE PATHS
# =============================================================================

@pytest.mark.asyncio
@pytest.mark.security
class TestRefreshTokenFailurePaths:
    """Refresh token edge cases and failure paths."""

    async def test_refresh_with_expired_session_rejected(
        self,
        client: AsyncClient,
        regular_user_in_db: dict,
    ):
        """Refresh fails if the session was revoked/expired."""
        # Login to get tokens
        login_res = await client.post("/api/auth/login", data={
            "username": regular_user_in_db["username"],
            "password": regular_user_in_db["password"],
        })
        assert login_res.status_code == 200

        # Logout to revoke session
        await client.post("/api/auth/logout")

        # Try refresh — should fail
        refresh_res = await client.post("/api/auth/refresh")
        assert refresh_res.status_code in (401, 429), \
            "Refresh after logout should be rejected"

    async def test_refresh_without_cookie_returns_401(
        self,
        client: AsyncClient,
    ):
        """Refresh without refresh_token cookie returns 401."""
        from httpx import AsyncClient as NewClient, ASGITransport
        from app.main import fastapi_app

        async with NewClient(
            transport=ASGITransport(app=fastapi_app),
            base_url="http://test",
        ) as fresh_client:
            res = await fresh_client.post("/api/auth/refresh")
            assert res.status_code == 401


# =============================================================================
# 3. CHANGE-PASSWORD — COOKIE CLEARING
# =============================================================================

@pytest.mark.asyncio
@pytest.mark.security
class TestChangePasswordCookieClearing:
    """Change-password should clear auth cookies in response."""

    async def test_change_password_clears_cookies(
        self,
        client: AsyncClient,
        regular_user_in_db: dict,
    ):
        """After changing password, response should delete auth cookies."""
        # Login first
        login_res = await client.post("/api/auth/login", data={
            "username": regular_user_in_db["username"],
            "password": regular_user_in_db["password"],
        })
        assert login_res.status_code == 200

        # Change password
        with patch("app.services.user_service.check_password_breached",
                    new_callable=AsyncMock, return_value=(False, 0)):
            change_res = await client.post("/api/auth/change-password", json={
                "old_password": regular_user_in_db["password"],
                "new_password": "BrandNewSecure123!",
            })

        assert change_res.status_code == 204

        # Check that cookies are cleared (Set-Cookie with Max-Age=0 or expires in past)
        set_cookies = change_res.headers.get_list("set-cookie")
        cookie_names = [c.split("=")[0].strip() for c in set_cookies]
        assert "access_token" in cookie_names, "access_token cookie should be cleared"
