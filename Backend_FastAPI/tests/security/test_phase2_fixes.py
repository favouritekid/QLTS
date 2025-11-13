"""
Unit tests for Phase 2 Security Fixes (MEDIUM Priority)

Tests:
1. Socket Rate Limit Bypass Fix (CVSS 5.3)
2. User Enumeration Fix (CVSS 5.3)

Run with:
    pytest tests/security/test_phase2_fixes.py -v
"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi import HTTPException
from app.socket_manager import check_rate_limit


# ============================================================================
# TEST #1: SOCKET RATE LIMIT BYPASS FIX (CVSS 5.3)
# ============================================================================

class TestSocketRateLimitBypassFix:
    """
    Test that Socket.IO rate limiting fails closed when Redis is unavailable.
    
    VULNERABILITY: Socket Rate Limit Bypass (CVSS 5.3 MEDIUM)
    - Old behavior: return True when Redis fails (fail-open)
    - Attack: Crash Redis → unlimited Socket.IO connections → DoS
    - Fix: return False when Redis fails (fail-closed)
    """
    
    @pytest.mark.asyncio
    async def test_rate_limit_denies_when_redis_client_unavailable(self):
        """Test that rate limit DENIES connection when Redis client is None."""
        # Simulate Redis client unavailable
        with patch('app.socket_manager.redis_client', None):
            with patch('app.socket_manager.RATE_LIMIT_SCRIPT_SHA', 'dummy_sha'):
                result = await check_rate_limit("192.168.1.1")
                
                # ✅ SECURITY FIX: Should return False (deny connection)
                assert result is False, "Should deny connection when Redis client is unavailable"
    
    @pytest.mark.asyncio
    async def test_rate_limit_denies_when_lua_script_not_loaded(self):
        """Test that rate limit DENIES connection when LUA script is not loaded."""
        # Simulate LUA script not loaded
        mock_redis = MagicMock()
        with patch('app.socket_manager.redis_client', mock_redis):
            with patch('app.socket_manager.RATE_LIMIT_SCRIPT_SHA', None):
                result = await check_rate_limit("192.168.1.1")
                
                # ✅ SECURITY FIX: Should return False (deny connection)
                assert result is False, "Should deny connection when LUA script is not loaded"
    
    @pytest.mark.asyncio
    async def test_rate_limit_denies_when_redis_evalsha_fails(self):
        """Test that rate limit DENIES connection when Redis evalsha fails."""
        # Simulate Redis evalsha failure
        mock_redis = AsyncMock()
        mock_redis.evalsha.side_effect = Exception("Redis connection error")
        mock_redis.script_load.side_effect = Exception("Cannot load script")
        
        with patch('app.socket_manager.redis_client', mock_redis):
            with patch('app.socket_manager.RATE_LIMIT_SCRIPT_SHA', 'dummy_sha'):
                result = await check_rate_limit("192.168.1.1")
                
                # ✅ SECURITY FIX: Should return False (deny connection)
                assert result is False, "Should deny connection when Redis evalsha fails"
    
    @pytest.mark.asyncio
    async def test_rate_limit_allows_when_redis_works(self):
        """Test that rate limit ALLOWS connection when Redis works and limit not exceeded."""
        # Simulate successful Redis operation (under limit)
        mock_redis = AsyncMock()
        mock_redis.evalsha.return_value = 1  # 1 = allowed (under limit)
        
        with patch('app.socket_manager.redis_client', mock_redis):
            with patch('app.socket_manager.RATE_LIMIT_SCRIPT_SHA', 'dummy_sha'):
                result = await check_rate_limit("192.168.1.1")
                
                # Should return True (allow connection)
                assert result is True, "Should allow connection when under rate limit"
    
    @pytest.mark.asyncio
    async def test_rate_limit_denies_when_limit_exceeded(self):
        """Test that rate limit DENIES connection when limit is exceeded."""
        # Simulate rate limit exceeded
        mock_redis = AsyncMock()
        mock_redis.evalsha.return_value = 0  # 0 = denied (over limit)
        
        with patch('app.socket_manager.redis_client', mock_redis):
            with patch('app.socket_manager.RATE_LIMIT_SCRIPT_SHA', 'dummy_sha'):
                result = await check_rate_limit("192.168.1.1")
                
                # Should return False (deny connection)
                assert result is False, "Should deny connection when rate limit exceeded"


# ============================================================================
# TEST #2: USER ENUMERATION FIX (CVSS 5.3)
# ============================================================================

class TestUserEnumerationFix:
    """
    Test that registration endpoint returns generic error messages.
    
    VULNERABILITY: User Enumeration (CVSS 5.3 MEDIUM)
    - Old behavior: "Username 'john' already registered" → Attacker knows username exists
    - Attack: Enumerate all usernames/emails in database
    - Fix: Generic message "Username or email already registered"
    """
    
    @pytest.mark.asyncio
    async def test_registration_returns_generic_error_for_duplicate_username(self, client, test_db):
        """Test that duplicate username returns generic error message."""
        from app.services import user_service
        from app.schemas.user import UserCreate
        
        # Create a user first
        user_data = UserCreate(
            username="testuser",
            email="test@example.com",
            password="SecurePass123!",
            full_name="Test User"
        )
        await user_service.create_user(test_db, user_data)
        
        # Try to register with same username but different email
        response = client.post(
            "/api/auth/register",
            json={
                "username": "testuser",  # Same username
                "email": "different@example.com",  # Different email
                "password": "SecurePass123!",
                "full_name": "Another User"
            }
        )
        
        # ✅ SECURITY FIX: Should return generic error message
        assert response.status_code == 409
        assert response.json()["detail"] == "Username or email already registered"
        # ❌ OLD BEHAVIOR: Would return "Username 'testuser' already registered"
    
    @pytest.mark.asyncio
    async def test_registration_returns_generic_error_for_duplicate_email(self, client, test_db):
        """Test that duplicate email returns generic error message."""
        from app.services import user_service
        from app.schemas.user import UserCreate
        
        # Create a user first
        user_data = UserCreate(
            username="testuser",
            email="test@example.com",
            password="SecurePass123!",
            full_name="Test User"
        )
        await user_service.create_user(test_db, user_data)
        
        # Try to register with different username but same email
        response = client.post(
            "/api/auth/register",
            json={
                "username": "differentuser",  # Different username
                "email": "test@example.com",  # Same email
                "password": "SecurePass123!",
                "full_name": "Another User"
            }
        )
        
        # ✅ SECURITY FIX: Should return generic error message
        assert response.status_code == 409
        assert response.json()["detail"] == "Username or email already registered"
        # ❌ OLD BEHAVIOR: Would return "Email 'test@example.com' already registered"

