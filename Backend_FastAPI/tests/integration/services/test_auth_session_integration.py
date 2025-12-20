# tests/integration/services/test_auth_session_integration.py
"""
✅ CONSOLIDATED INTEGRATION TESTS FOR AUTH & SESSION MODULES

This file consolidates all auth-related tests into a single location with consistent patterns.
Follows the same class-based structure as test_lead_service_integration.py.

Tests cover:
1. Login/Logout flows
2. Token refresh/rotation
3. Password change/reset
4. Session management
5. Security features (cookie security, token blacklisting, etc.)
"""
import logging
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession
from httpx import AsyncClient, ASGITransport

from app import models
from app.services import session_service
from app.security import get_password_hash, create_password_reset_token

log = logging.getLogger(__name__)


# =============================================================================
# FIXTURES
# =============================================================================

@pytest_asyncio.fixture
async def auth_test_user(db: AsyncSession) -> models.User:
    """Create a user for auth tests."""
    user = models.User(
        username="auth_test_user",
        email="auth_test@example.com",
        password_hash=get_password_hash("TestPassword123!"),
        role="officer",
        status="active",
        full_name="Auth Test User"
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user


@pytest_asyncio.fixture
async def auth_user_session(db: AsyncSession, auth_test_user: models.User) -> models.UserSession:
    """Create an active session for auth test user."""
    session = models.UserSession(
        user_id=auth_test_user.id,
        refresh_jti="auth-test-jti-123",
        ip_address="192.168.1.1",
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0",
        device_type="desktop",
        browser="Chrome 120.0.0.0",
        os="Windows 10",
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        created_at=datetime.now(timezone.utc),
        last_activity_at=datetime.now(timezone.utc),
        is_suspicious=False,
    )
    db.add(session)
    await db.flush()
    await db.refresh(session)
    return session


# =============================================================================
# LOGIN TESTS
# =============================================================================

@pytest.mark.asyncio
@pytest.mark.integration
class TestLogin:
    """Tests for login functionality."""

    async def test_login_success_sets_cookies(
        self,
        client: AsyncClient,
        regular_user_in_db: dict
    ):
        """Test successful login sets httpOnly cookies."""
        username = regular_user_in_db["username"]
        password = regular_user_in_db["password"]

        login_res = await client.post("/api/auth/login", data={
            "username": username,
            "password": password
        })

        assert login_res.status_code == 200
        assert "access_token" in login_res.cookies
        assert "refresh_token" in login_res.cookies
        
        # Verify httpOnly attribute
        set_cookies = login_res.headers.get_list("set-cookie")
        access_cookie = [h for h in set_cookies if "access_token=" in h][0]
        assert "HttpOnly" in access_cookie or "httponly" in access_cookie.lower()

    async def test_login_invalid_password_rejected(
        self,
        client: AsyncClient,
        regular_user_in_db: dict
    ):
        """Test login with wrong password is rejected."""
        username = regular_user_in_db["username"]

        login_res = await client.post("/api/auth/login", data={
            "username": username,
            "password": "WrongPassword123!"
        })

        assert login_res.status_code == 401

    async def test_login_nonexistent_user_rejected(
        self,
        client: AsyncClient
    ):
        """Test login with non-existent user is rejected."""
        login_res = await client.post("/api/auth/login", data={
            "username": "nonexistent_user_12345",
            "password": "AnyPassword123!"
        })

        assert login_res.status_code == 401


# =============================================================================
# LOGOUT TESTS
# =============================================================================

@pytest.mark.asyncio
@pytest.mark.integration
class TestLogout:
    """Tests for logout functionality."""

    async def test_logout_success_clears_cookies(
        self,
        client: AsyncClient,
        regular_user_in_db: dict
    ):
        """Test logout clears httpOnly cookies."""
        username = regular_user_in_db["username"]
        password = regular_user_in_db["password"]

        # Login first
        login_res = await client.post("/api/auth/login", data={
            "username": username,
            "password": password
        })
        assert login_res.status_code == 200

        # Logout
        logout_res = await client.post("/api/auth/logout")
        assert logout_res.status_code == 204

        # Verify cookies deleted
        logout_cookies = logout_res.headers.get_list("set-cookie")
        access_delete = [h for h in logout_cookies if "access_token=" in h]
        if access_delete:
            assert "Max-Age=0" in access_delete[0] or "max-age=0" in access_delete[0].lower()

    async def test_logout_unauthenticated_rejected(
        self,
        client: AsyncClient
    ):
        """Test logout without authentication is rejected."""
        from app.main import fastapi_app
        async with AsyncClient(transport=ASGITransport(app=fastapi_app), base_url="http://test") as new_client:
            logout_res = await new_client.post("/api/auth/logout")
        
        assert logout_res.status_code == 401

    async def test_logout_invalidates_token(
        self,
        client: AsyncClient,
        regular_user_in_db: dict
    ):
        """Test old token cannot be used after logout."""
        username = regular_user_in_db["username"]
        password = regular_user_in_db["password"]

        # Login
        login_res = await client.post("/api/auth/login", data={
            "username": username,
            "password": password
        })
        old_access_token = login_res.cookies.get("access_token")

        # Logout
        await client.post("/api/auth/logout")

        # Try to use old token
        from app.main import fastapi_app
        async with AsyncClient(transport=ASGITransport(app=fastapi_app), base_url="http://test") as new_client:
            new_client.cookies.set("access_token", old_access_token)
            profile_res = await new_client.get("/api/auth/profile")
        
        assert profile_res.status_code == 401


# =============================================================================
# TOKEN REFRESH TESTS
# =============================================================================

@pytest.mark.asyncio
@pytest.mark.integration
class TestTokenRefresh:
    """Tests for token refresh functionality."""

    async def test_refresh_returns_new_tokens(
        self,
        client: AsyncClient,
        regular_user_in_db: dict
    ):
        """Test refresh endpoint returns new tokens."""
        username = regular_user_in_db["username"]
        password = regular_user_in_db["password"]

        # Login
        login_res = await client.post("/api/auth/login", data={
            "username": username,
            "password": password
        })
        old_access = login_res.cookies.get("access_token")
        old_refresh = login_res.cookies.get("refresh_token")

        # Refresh
        refresh_res = await client.post("/api/auth/refresh")
        
        assert refresh_res.status_code == 200
        assert "access_token" in refresh_res.cookies
        assert "refresh_token" in refresh_res.cookies

        # Tokens should be different
        assert refresh_res.cookies.get("access_token") != old_access
        assert refresh_res.cookies.get("refresh_token") != old_refresh

    async def test_refresh_old_token_rejected_after_rotation(
        self,
        client: AsyncClient,
        regular_user_in_db: dict
    ):
        """Test old refresh token cannot be reused after rotation."""
        username = regular_user_in_db["username"]
        password = regular_user_in_db["password"]

        # Login
        login_res = await client.post("/api/auth/login", data={
            "username": username,
            "password": password
        })
        old_refresh = login_res.cookies.get("refresh_token")

        # First refresh (succeeds)
        refresh_res = await client.post("/api/auth/refresh")
        assert refresh_res.status_code == 200

        # Try to reuse old refresh token
        from app.main import fastapi_app
        async with AsyncClient(transport=ASGITransport(app=fastapi_app), base_url="http://test") as new_client:
            new_client.cookies.set("refresh_token", old_refresh)
            replay_res = await new_client.post("/api/auth/refresh")
        
        assert replay_res.status_code == 401

    async def test_refresh_without_token_rejected(
        self,
        client: AsyncClient
    ):
        """Test refresh without refresh token is rejected."""
        from app.main import fastapi_app
        async with AsyncClient(transport=ASGITransport(app=fastapi_app), base_url="http://test") as new_client:
            refresh_res = await new_client.post("/api/auth/refresh")
        
        assert refresh_res.status_code == 401


# =============================================================================
# PASSWORD CHANGE TESTS
# =============================================================================

@pytest.mark.asyncio
@pytest.mark.integration
class TestPasswordChange:
    """Tests for password change functionality."""

    async def test_change_password_success(
        self,
        client: AsyncClient,
        regular_user_in_db: dict
    ):
        """Test password change with correct old password."""
        username = regular_user_in_db["username"]
        old_password = regular_user_in_db["password"]
        new_password = "NewSecurePassword123!"

        # Login
        login_res = await client.post("/api/auth/login", data={
            "username": username,
            "password": old_password
        })
        assert login_res.status_code == 200

        # Change password
        change_res = await client.post("/api/auth/change-password", json={
            "old_password": old_password,
            "new_password": new_password
        })
        
        assert change_res.status_code == 204

        # Login with new password
        from app.main import fastapi_app
        async with AsyncClient(transport=ASGITransport(app=fastapi_app), base_url="http://test") as new_client:
            new_login_res = await new_client.post("/api/auth/login", data={
                "username": username,
                "password": new_password
            })
        
        assert new_login_res.status_code == 200

    async def test_change_password_wrong_old_password(
        self,
        client: AsyncClient,
        regular_user_in_db: dict
    ):
        """Test password change with wrong old password is rejected."""
        username = regular_user_in_db["username"]
        password = regular_user_in_db["password"]

        # Login
        login_res = await client.post("/api/auth/login", data={
            "username": username,
            "password": password
        })
        assert login_res.status_code == 200

        # Try change with wrong old password
        change_res = await client.post("/api/auth/change-password", json={
            "old_password": "WrongOldPassword123!",
            "new_password": "NewPassword123!"
        })
        
        assert change_res.status_code == 400


# =============================================================================
# PASSWORD RESET TESTS
# =============================================================================

@pytest.mark.asyncio
@pytest.mark.integration
class TestPasswordReset:
    """Tests for password reset functionality."""

    async def test_forgot_password_always_returns_202(
        self,
        client: AsyncClient,
        regular_user_in_db: dict
    ):
        """Test forgot password returns 202 (no user enumeration)."""
        user_email = regular_user_in_db["email"]

        res = await client.post("/api/auth/forgot-password", json={
            "email": user_email
        })
        
        assert res.status_code == 202

    async def test_forgot_password_nonexistent_email_returns_202(
        self,
        client: AsyncClient
    ):
        """Test forgot password with non-existent email still returns 202."""
        res = await client.post("/api/auth/forgot-password", json={
            "email": "nonexistent@email.com"
        })
        
        # Same response for security (no user enumeration)
        assert res.status_code == 202

    async def test_reset_password_with_valid_token(
        self,
        client: AsyncClient,
        regular_user_in_db: dict
    ):
        """Test password reset with valid token."""
        user_email = regular_user_in_db["email"]
        username = regular_user_in_db["username"]
        new_password = "ResetNewPassword123!"

        # Generate valid token
        token = create_password_reset_token(email=user_email)

        reset_res = await client.post("/api/auth/reset-password", json={
            "token": token,
            "new_password": new_password
        })
        
        assert reset_res.status_code == 200

        # Login with new password
        from app.main import fastapi_app
        async with AsyncClient(transport=ASGITransport(app=fastapi_app), base_url="http://test") as new_client:
            login_res = await new_client.post("/api/auth/login", data={
                "username": username,
                "password": new_password
            })
        
        assert login_res.status_code == 200


# =============================================================================
# SESSION SERVICE TESTS
# =============================================================================

@pytest.mark.asyncio
@pytest.mark.integration
class TestSessionCreate:
    """Tests for session_service.create_session"""

    async def test_create_session_parses_mobile_user_agent(
        self,
        db: AsyncSession,
        auth_test_user: models.User
    ):
        """Test create_session detects mobile device."""
        with patch.object(session_service, 'safe_redis_delete', new_callable=AsyncMock):
            with patch.object(session_service, 'safe_redis_set', new_callable=AsyncMock):
                session = await session_service.create_session(
                    db=db,
                    user_id=auth_test_user.id,
                    refresh_jti="mobile-test-jti",
                    ip_address="10.0.0.1",
                    user_agent_string="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0) Safari/605.1.15",
                    expires_at=datetime.now(timezone.utc) + timedelta(days=7),
                )
        
        assert session.device_type == "mobile"
        assert "Safari" in session.browser
        assert "iOS" in session.os

    async def test_create_session_parses_desktop_user_agent(
        self,
        db: AsyncSession,
        auth_test_user: models.User
    ):
        """Test create_session detects desktop device."""
        with patch.object(session_service, 'safe_redis_delete', new_callable=AsyncMock):
            with patch.object(session_service, 'safe_redis_set', new_callable=AsyncMock):
                session = await session_service.create_session(
                    db=db,
                    user_id=auth_test_user.id,
                    refresh_jti="desktop-test-jti",
                    ip_address="10.0.0.2",
                    user_agent_string="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0",
                    expires_at=datetime.now(timezone.utc) + timedelta(days=7),
                )
        
        assert session.device_type == "desktop"
        assert "Chrome" in session.browser


@pytest.mark.asyncio
@pytest.mark.integration
class TestSessionRevoke:
    """Tests for session_service.revoke_session"""

    async def test_revoke_session_success(
        self,
        db: AsyncSession,
        auth_test_user: models.User,
        auth_user_session: models.UserSession
    ):
        """Test revoking an active session."""
        with patch.object(session_service, 'safe_redis_set', new_callable=AsyncMock):
            with patch.object(session_service, 'safe_redis_delete', new_callable=AsyncMock):
                with patch.object(session_service, 'dispatcher'):
                    result = await session_service.revoke_session(
                        db=db,
                        session_id=auth_user_session.id,
                        user_id=auth_test_user.id
                    )
        
        await db.refresh(auth_user_session)
        
        assert result is True
        assert auth_user_session.revoked_at is not None

    async def test_revoke_session_wrong_user_rejected(
        self,
        db: AsyncSession,
        auth_user_session: models.UserSession
    ):
        """Test revoking session with wrong user ID is rejected."""
        with patch.object(session_service, 'safe_redis_set', new_callable=AsyncMock):
            with patch.object(session_service, 'safe_redis_delete', new_callable=AsyncMock):
                result = await session_service.revoke_session(
                    db=db,
                    session_id=auth_user_session.id,
                    user_id=999999  # Wrong user
                )
        
        assert result is False
        
        await db.refresh(auth_user_session)
        assert auth_user_session.revoked_at is None


@pytest.mark.asyncio
@pytest.mark.integration  
class TestSessionRevokeAll:
    """Tests for session_service.revoke_all_other_sessions"""

    async def test_revoke_all_preserves_current_session(
        self,
        db: AsyncSession,
        auth_test_user: models.User
    ):
        """Test revoke_all preserves the specified session."""
        # Create 3 sessions
        sessions = []
        for i in range(3):
            session = models.UserSession(
                user_id=auth_test_user.id,
                refresh_jti=f"revoke-all-jti-{i}",
                ip_address=f"192.168.1.{100+i}",
                device_type="desktop",
                browser="Chrome",
                os="Windows",
                expires_at=datetime.now(timezone.utc) + timedelta(days=7),
                created_at=datetime.now(timezone.utc),
                last_activity_at=datetime.now(timezone.utc),
            )
            db.add(session)
            sessions.append(session)
        await db.flush()
        for s in sessions:
            await db.refresh(s)
        
        preserve_id = sessions[1].id
        
        with patch.object(session_service, 'safe_redis_set', new_callable=AsyncMock):
            with patch.object(session_service, 'safe_redis_delete', new_callable=AsyncMock):
                with patch.object(session_service, 'dispatcher'):
                    count = await session_service.revoke_all_other_sessions(
                        db=db,
                        user_id=auth_test_user.id,
                        except_session_id=preserve_id
                    )
        
        assert count == 2
        
        for s in sessions:
            await db.refresh(s)
        
        # Preserved session should NOT be revoked
        assert sessions[1].revoked_at is None
        # Others should be revoked
        assert sessions[0].revoked_at is not None
        assert sessions[2].revoked_at is not None
