# tests/integration/services/test_session_service_integration.py
"""
Integration tests for session_service.py

These tests use real database to verify:
- Session creation and storage
- Session revocation with proper transaction handling
- Redis interaction for session tracking
- Edge cases with real data
"""
import logging
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.services import session_service
from app.security import get_password_hash
from app.utils.exceptions import SessionRevocationError

log = logging.getLogger(__name__)


# =============================================================================
# SESSION FIXTURES
# =============================================================================

@pytest_asyncio.fixture
async def session_user(db: AsyncSession) -> models.User:
    """Create a user for session tests."""
    user = models.User(
        username="session_test_user",
        email="session_user@test.com",
        password_hash=get_password_hash("TestPass123!"),
        role="officer",
        status="active",
        full_name="Session Test User"
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user


@pytest_asyncio.fixture
async def active_session(db: AsyncSession, session_user: models.User) -> models.UserSession:
    """Create an active session for a user."""
    session = models.UserSession(
        user_id=session_user.id,
        refresh_jti="test-jti-active-123",
        ip_address="192.168.1.100",
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0",
        device_type="desktop",
        browser="Chrome 120.0.0.0",
        os="Windows 10",
        country="Vietnam",
        city="Ho Chi Minh City",
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        created_at=datetime.now(timezone.utc),
        last_activity_at=datetime.now(timezone.utc),
        is_suspicious=False,
    )
    db.add(session)
    await db.flush()
    await db.refresh(session)
    return session


@pytest_asyncio.fixture
async def multiple_sessions(db: AsyncSession, session_user: models.User) -> list:
    """Create multiple sessions for a user."""
    sessions = []
    for i in range(3):
        session = models.UserSession(
            user_id=session_user.id,
            refresh_jti=f"test-jti-multi-{i}",
            ip_address=f"192.168.1.{100 + i}",
            user_agent="Mozilla/5.0 (Windows NT 10.0) Chrome/120.0.0.0",
            device_type="desktop",
            browser="Chrome 120.0.0.0",
            os="Windows 10",
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
            created_at=datetime.now(timezone.utc),
            last_activity_at=datetime.now(timezone.utc),
            is_suspicious=False,
        )
        db.add(session)
        sessions.append(session)
    
    await db.flush()
    for s in sessions:
        await db.refresh(s)
    
    return sessions


# =============================================================================
# CREATE SESSION TESTS
# =============================================================================

@pytest.mark.asyncio
@pytest.mark.integration
class TestCreateSession:
    """Tests for session_service.create_session"""

    async def test_create_session_success(
        self,
        db: AsyncSession,
        session_user: models.User
    ):
        """Test creating a new session stores it in database."""
        # Arrange
        refresh_jti = "test-create-jti-123"
        expires_at = datetime.now(timezone.utc) + timedelta(days=7)
        
        # Mock Redis operations
        with patch.object(session_service, 'safe_redis_delete', new_callable=AsyncMock):
            with patch.object(session_service, 'safe_redis_set', new_callable=AsyncMock):
                # Act
                session = await session_service.create_session(
                    db=db,
                    user_id=session_user.id,
                    refresh_jti=refresh_jti,
                    ip_address="10.0.0.1",
                    user_agent_string="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0) Safari/605.1.15",
                    expires_at=expires_at,
                )
        
        # Assert
        assert session is not None
        assert session.id is not None  # ID assigned after flush
        assert session.user_id == session_user.id
        assert session.refresh_jti == refresh_jti
        assert session.device_type == "mobile"  # iPhone detected
        assert "Safari" in session.browser  # Contains check instead of exact match
        assert "iOS" in session.os

    async def test_create_session_parses_desktop_user_agent(
        self,
        db: AsyncSession,
        session_user: models.User
    ):
        """Test user agent parsing for desktop browser."""
        with patch.object(session_service, 'safe_redis_delete', new_callable=AsyncMock):
            with patch.object(session_service, 'safe_redis_set', new_callable=AsyncMock):
                session = await session_service.create_session(
                    db=db,
                    user_id=session_user.id,
                    refresh_jti="test-desktop-jti",
                    ip_address="10.0.0.2",
                    user_agent_string="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
                    expires_at=datetime.now(timezone.utc) + timedelta(days=7),
                )
        
        assert session.device_type == "desktop"
        assert "Chrome" in session.browser

    async def test_create_session_handles_missing_user_agent(
        self,
        db: AsyncSession,
        session_user: models.User
    ):
        """Test session creation with no user agent."""
        with patch.object(session_service, 'safe_redis_delete', new_callable=AsyncMock):
            with patch.object(session_service, 'safe_redis_set', new_callable=AsyncMock):
                session = await session_service.create_session(
                    db=db,
                    user_id=session_user.id,
                    refresh_jti="test-no-ua-jti",
                    ip_address=None,
                    user_agent_string=None,
                    expires_at=datetime.now(timezone.utc) + timedelta(days=7),
                )
        
        assert session.device_type == "unknown"
        assert session.browser == "Unknown"
        assert session.os == "Unknown"


# =============================================================================
# GET ACTIVE SESSIONS TESTS
# =============================================================================

@pytest.mark.asyncio
@pytest.mark.integration
class TestGetActiveSessions:
    """Tests for session_service.get_active_sessions"""

    async def test_get_active_sessions_returns_active_only(
        self,
        db: AsyncSession,
        session_user: models.User,
        multiple_sessions: list
    ):
        """Test that only active (non-revoked) sessions are returned."""
        # Arrange - revoke one session
        multiple_sessions[0].revoked_at = datetime.now(timezone.utc)
        db.add(multiple_sessions[0])
        await db.flush()
        
        # Act
        active = await session_service.get_active_sessions(
            db=db,
            user_id=session_user.id
        )
        
        # Assert - should return 2, not 3
        assert len(active) == 2
        assert all(s.revoked_at is None for s in active)

    async def test_get_active_sessions_empty_for_no_sessions(
        self,
        db: AsyncSession,
        session_user: models.User
    ):
        """Test returns empty list when user has no sessions."""
        # Note: session_user fixture doesn't create sessions
        # But we need to ensure the fixture doesn't auto-create sessions
        result = await session_service.get_active_sessions(
            db=db,
            user_id=999999  # Non-existent user
        )
        
        assert result == []


# =============================================================================
# REVOKE SESSION TESTS
# =============================================================================

@pytest.mark.asyncio
@pytest.mark.integration
class TestRevokeSession:
    """Tests for session_service.revoke_session"""

    async def test_revoke_session_success(
        self,
        db: AsyncSession,
        session_user: models.User,
        active_session: models.UserSession
    ):
        """Test revoking an active session."""
        # Mock Redis and dispatcher
        with patch.object(session_service, 'safe_redis_set', new_callable=AsyncMock):
            with patch.object(session_service, 'safe_redis_delete', new_callable=AsyncMock):
                with patch.object(session_service, 'dispatcher'):
                    result = await session_service.revoke_session(
                        db=db,
                        session_id=active_session.id,
                        user_id=session_user.id
                    )
        
        # Refresh to get updated state
        await db.refresh(active_session)
        
        assert result is True
        assert active_session.revoked_at is not None

    async def test_revoke_session_not_found(
        self,
        db: AsyncSession,
        session_user: models.User
    ):
        """Test revoking non-existent session returns False."""
        with patch.object(session_service, 'safe_redis_set', new_callable=AsyncMock):
            with patch.object(session_service, 'safe_redis_delete', new_callable=AsyncMock):
                result = await session_service.revoke_session(
                    db=db,
                    session_id=999999,
                    user_id=session_user.id
                )
        
        assert result is False

    async def test_revoke_session_wrong_user(
        self,
        db: AsyncSession,
        active_session: models.UserSession
    ):
        """Test revoking session with wrong user_id returns False."""
        with patch.object(session_service, 'safe_redis_set', new_callable=AsyncMock):
            with patch.object(session_service, 'safe_redis_delete', new_callable=AsyncMock):
                result = await session_service.revoke_session(
                    db=db,
                    session_id=active_session.id,
                    user_id=999999  # Wrong user
                )
        
        assert result is False
        
        # Session should NOT be revoked
        await db.refresh(active_session)
        assert active_session.revoked_at is None


# =============================================================================
# REVOKE ALL OTHER SESSIONS TESTS
# =============================================================================

@pytest.mark.asyncio
@pytest.mark.integration
class TestRevokeAllOtherSessions:
    """Tests for session_service.revoke_all_other_sessions"""

    async def test_revoke_all_except_one(
        self,
        db: AsyncSession,
        session_user: models.User,
        multiple_sessions: list
    ):
        """Test revoking all sessions except specified one."""
        preserve_session = multiple_sessions[1]
        
        with patch.object(session_service, 'safe_redis_set', new_callable=AsyncMock):
            with patch.object(session_service, 'safe_redis_delete', new_callable=AsyncMock):
                with patch.object(session_service, 'dispatcher'):
                    count = await session_service.revoke_all_other_sessions(
                        db=db,
                        user_id=session_user.id,
                        except_session_id=preserve_session.id
                    )
        
        # Should revoke 2 out of 3
        assert count == 2
        
        # Refresh all sessions
        for s in multiple_sessions:
            await db.refresh(s)
        
        # Preserved session should NOT be revoked
        assert preserve_session.revoked_at is None
        
        # Others should be revoked
        revoked = [s for s in multiple_sessions if s.id != preserve_session.id]
        assert all(s.revoked_at is not None for s in revoked)

    async def test_revoke_all_sessions(
        self,
        db: AsyncSession,
        session_user: models.User,
        multiple_sessions: list
    ):
        """Test revoking ALL sessions (no exception)."""
        with patch.object(session_service, 'safe_redis_set', new_callable=AsyncMock):
            with patch.object(session_service, 'safe_redis_delete', new_callable=AsyncMock):
                with patch.object(session_service, 'dispatcher'):
                    count = await session_service.revoke_all_other_sessions(
                        db=db,
                        user_id=session_user.id,
                        except_session_id=None  # Revoke ALL
                    )
        
        assert count == 3
        
        for s in multiple_sessions:
            await db.refresh(s)
            assert s.revoked_at is not None


# =============================================================================
# UPDATE SESSION ACTIVITY TESTS
# =============================================================================

@pytest.mark.asyncio
@pytest.mark.integration
class TestUpdateSessionActivity:
    """Tests for session_service.update_session_activity"""

    async def test_update_session_activity_success(
        self,
        db: AsyncSession,
        session_user: models.User,
        active_session: models.UserSession
    ):
        """Test updating session activity updates JTI and timestamp."""
        old_jti = active_session.refresh_jti
        new_jti = "new-rotated-jti-456"
        old_activity = active_session.last_activity_at
        
        # Act
        updated = await session_service.update_session_activity(
            db=db,
            old_refresh_jti=old_jti,
            new_refresh_jti=new_jti,
            user_id=session_user.id
        )
        
        # Assert
        assert updated is not None
        assert updated.refresh_jti == new_jti
        assert updated.last_activity_at > old_activity

    async def test_update_session_activity_wrong_user(
        self,
        db: AsyncSession,
        active_session: models.UserSession
    ):
        """Test update fails for wrong user."""
        result = await session_service.update_session_activity(
            db=db,
            old_refresh_jti=active_session.refresh_jti,
            new_refresh_jti="new-jti",
            user_id=999999  # Wrong user
        )
        
        assert result is None

    async def test_update_session_activity_not_found(
        self,
        db: AsyncSession,
        session_user: models.User
    ):
        """Test update returns None for non-existent JTI."""
        result = await session_service.update_session_activity(
            db=db,
            old_refresh_jti="non-existent-jti",
            new_refresh_jti="new-jti",
            user_id=session_user.id
        )
        
        assert result is None


# =============================================================================
# REVOKE SESSION BY JTI TESTS
# =============================================================================

@pytest.mark.asyncio
@pytest.mark.integration
class TestRevokeSessionByJti:
    """Tests for session_service.revoke_session_by_jti"""

    async def test_revoke_by_jti_success(
        self,
        db: AsyncSession,
        session_user: models.User,
        active_session: models.UserSession
    ):
        """Test revoking session by JTI."""
        result = await session_service.revoke_session_by_jti(
            db=db,
            refresh_jti=active_session.refresh_jti,
            user_id=session_user.id
        )
        
        assert result is True
        
        await db.refresh(active_session)
        assert active_session.revoked_at is not None

    async def test_revoke_by_jti_not_found(
        self,
        db: AsyncSession,
        session_user: models.User
    ):
        """Test returns False for non-existent JTI."""
        result = await session_service.revoke_session_by_jti(
            db=db,
            refresh_jti="non-existent-jti",
            user_id=session_user.id
        )
        
        assert result is False

    async def test_revoke_by_jti_already_revoked(
        self,
        db: AsyncSession,
        session_user: models.User,
        active_session: models.UserSession
    ):
        """Test returns False for already revoked session."""
        # Pre-revoke the session
        active_session.revoked_at = datetime.now(timezone.utc)
        db.add(active_session)
        await db.flush()
        
        result = await session_service.revoke_session_by_jti(
            db=db,
            refresh_jti=active_session.refresh_jti,
            user_id=session_user.id
        )
        
        assert result is False
