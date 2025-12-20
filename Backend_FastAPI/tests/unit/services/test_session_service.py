# tests/unit/services/test_session_service.py
"""
Unit tests for session_service.

Tests the session management logic including:
- Session creation
- Session revocation
- Active session retrieval
- Session activity updates
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone, timedelta


class TestCreateSession:
    """Tests for session_service.create_session"""

    @pytest.mark.asyncio
    async def test_create_session_parses_user_agent(self):
        """Test that create_session correctly parses user agent string."""
        from app.services import session_service
        
        # Arrange
        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()
        
        user_id = 1
        refresh_jti = "test-jti-123"
        ip_address = "192.168.1.1"
        user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0"
        expires_at = datetime.now(timezone.utc) + timedelta(days=7)
        
        # Mock the geoip service
        with patch.object(session_service, 'get_geoip_service') as mock_geoip:
            mock_geoip.return_value.lookup.return_value = ("Vietnam", "Ho Chi Minh City")
            
            with patch.object(session_service, '_revoke_previous_sessions_on_device', new_callable=AsyncMock):
                # Act
                session = await session_service.create_session(
                    db=mock_db,
                    user_id=user_id,
                    refresh_jti=refresh_jti,
                    ip_address=ip_address,
                    user_agent_string=user_agent,
                    expires_at=expires_at,
                )
        
        # Assert
        mock_db.add.assert_called_once()
        mock_db.flush.assert_called_once()
        assert session.user_id == user_id
        assert session.refresh_jti == refresh_jti
        assert session.device_type == "desktop"

    @pytest.mark.asyncio
    async def test_create_session_handles_missing_user_agent(self):
        """Test that create_session handles None user agent gracefully."""
        from app.services import session_service
        
        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()
        
        user_id = 1
        refresh_jti = "test-jti-456"
        expires_at = datetime.now(timezone.utc) + timedelta(days=7)
        
        with patch.object(session_service, '_revoke_previous_sessions_on_device', new_callable=AsyncMock):
            session = await session_service.create_session(
                db=mock_db,
                user_id=user_id,
                refresh_jti=refresh_jti,
                ip_address=None,
                user_agent_string=None,
                expires_at=expires_at,
            )
        
        assert session.device_type == "unknown"
        assert session.browser == "Unknown"


class TestRevokeSession:
    """Tests for session_service.revoke_session"""

    @pytest.mark.asyncio
    async def test_revoke_session_returns_false_when_not_found(self):
        """Test revoke_session returns False when session doesn't exist."""
        from app.services import session_service
        
        mock_db = AsyncMock()
        mock_repo = MagicMock()
        mock_repo.get_for_update = AsyncMock(return_value=None)
        
        with patch('app.services.session_service.SessionRepository', return_value=mock_repo):
            # We need to mock begin_nested context manager
            mock_db.begin_nested = MagicMock(return_value=AsyncMock(__aenter__=AsyncMock(), __aexit__=AsyncMock()))
            
            result = await session_service.revoke_session(
                db=mock_db,
                session_id=999,
                user_id=1
            )
        
        assert result is False

    @pytest.mark.asyncio
    async def test_revoke_session_skips_already_revoked(self):
        """Test revoke_session returns False for already revoked session."""
        from app.services import session_service
        
        mock_db = AsyncMock()
        mock_session = MagicMock()
        mock_session.revoked_at = datetime.now(timezone.utc)  # Already revoked
        
        mock_repo = MagicMock()
        mock_repo.get_for_update = AsyncMock(return_value=mock_session)
        
        with patch('app.services.session_service.SessionRepository', return_value=mock_repo):
            mock_db.begin_nested = MagicMock(return_value=AsyncMock(__aenter__=AsyncMock(), __aexit__=AsyncMock()))
            
            result = await session_service.revoke_session(
                db=mock_db,
                session_id=1,
                user_id=1
            )
        
        assert result is False


class TestGetActiveSessions:
    """Tests for session_service.get_active_sessions"""

    @pytest.mark.asyncio
    async def test_get_active_sessions_returns_list(self):
        """Test get_active_sessions returns list of sessions."""
        from app.services import session_service
        
        mock_db = AsyncMock()
        mock_sessions = [MagicMock(), MagicMock()]
        mock_repo = MagicMock()
        mock_repo.get_active_by_user = AsyncMock(return_value=mock_sessions)
        
        with patch('app.services.session_service.SessionRepository', return_value=mock_repo):
            result = await session_service.get_active_sessions(
                db=mock_db,
                user_id=1
            )
        
        assert len(result) == 2


class TestRevokeAllOtherSessions:
    """Tests for session_service.revoke_all_other_sessions"""

    @pytest.mark.asyncio
    async def test_revoke_all_preserves_except_session(self):
        """Test that revoke_all_other_sessions preserves the excepted session."""
        from app.services import session_service
        
        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()
        
        session1 = MagicMock(id=1, refresh_jti="jti-1", expires_at=datetime.now(timezone.utc) + timedelta(days=1))
        session2 = MagicMock(id=2, refresh_jti="jti-2", expires_at=datetime.now(timezone.utc) + timedelta(days=1))
        session3 = MagicMock(id=3, refresh_jti="jti-3", expires_at=datetime.now(timezone.utc) + timedelta(days=1))
        
        mock_repo = MagicMock()
        mock_repo.get_active_by_user = AsyncMock(return_value=[session1, session2, session3])
        
        with patch('app.services.session_service.SessionRepository', return_value=mock_repo):
            with patch('app.services.session_service.safe_redis_set', new_callable=AsyncMock):
                with patch('app.services.session_service.safe_redis_delete', new_callable=AsyncMock):
                    with patch('app.services.session_service.dispatcher'):
                        result = await session_service.revoke_all_other_sessions(
                            db=mock_db,
                            user_id=1,
                            except_session_id=2  # Preserve session 2
                        )
        
        # Should revoke 2 sessions (1 and 3), not session 2
        assert result == 2


class TestRevokeSessionByJti:
    """Tests for session_service.revoke_session_by_jti"""

    @pytest.mark.asyncio
    async def test_revoke_by_jti_returns_false_when_not_found(self):
        """Test revoke_session_by_jti returns False when session not found."""
        from app.services import session_service
        
        mock_db = AsyncMock()
        mock_repo = MagicMock()
        mock_repo.get_by_refresh_jti_and_user = AsyncMock(return_value=None)
        
        with patch('app.services.session_service.SessionRepository', return_value=mock_repo):
            result = await session_service.revoke_session_by_jti(
                db=mock_db,
                refresh_jti="nonexistent-jti",
                user_id=1
            )
        
        assert result is False

    @pytest.mark.asyncio
    async def test_revoke_by_jti_succeeds(self):
        """Test revoke_session_by_jti successfully revokes session."""
        from app.services import session_service
        
        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()
        
        mock_session = MagicMock()
        mock_session.id = 1
        mock_session.revoked_at = None
        mock_session.refresh_jti = "test-jti"
        
        mock_repo = MagicMock()
        mock_repo.get_by_refresh_jti_and_user = AsyncMock(return_value=mock_session)
        
        with patch('app.services.session_service.SessionRepository', return_value=mock_repo):
            result = await session_service.revoke_session_by_jti(
                db=mock_db,
                refresh_jti="test-jti",
                user_id=1
            )
        
        assert result is True
        assert mock_session.revoked_at is not None
