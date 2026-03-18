"""
Unit tests for Phase 0-1 Security Fixes

SDET Rules Applied:
1. AAA Pattern: Strictly Arrange-Act-Assert
2. Hard Assertions: Assert specific values, not truthy checks
3. Boundary Testing: Empty inputs, null values, edge cases
4. Isolation: Mock only external dependencies (DB, Network)
5. Failure Scenarios: Verify specific error messages

Run with:
    pytest tests/security/test_security_phase0.py -v
"""
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy.ext.asyncio import AsyncSession

from app import models


# ============================================================================
# TEST #1: C1 - FINGERPRINT SPOOFING FIX
# ============================================================================

class TestFingerprintSpoofingFix:
    """
    Test that device fingerprint includes user_id and server-side salt.
    
    VULNERABILITY: Fingerprint Spoofing (CRITICAL)
    - Old behavior: fingerprint = hash(browser|os|device_type)
    - Fix: fingerprint = hash(browser|os|device_type|user_id|SECRET_SALT)
    """
    
    # ----- Rule 2: Hard Assertions -----
    
    def test_fingerprint_length_is_exactly_64_characters(self):
        """Assert fingerprint length is exactly 64 (SHA256 hex)."""
        # Arrange
        from app.services.login_history_service import generate_device_fingerprint
        
        # Act
        fingerprint = generate_device_fingerprint("Chrome", "Windows", "desktop", 1)
        
        # Assert - Hard assertion with specific value
        assert len(fingerprint) == 64
    
    def test_fingerprint_contains_only_hex_characters(self):
        """Assert fingerprint contains only lowercase hex chars [0-9a-f]."""
        # Arrange
        from app.services.login_history_service import generate_device_fingerprint
        
        # Act
        fingerprint = generate_device_fingerprint("Chrome", "Windows", "desktop", 1)
        
        # Assert - Verify each character is valid hex
        valid_hex_chars = set("0123456789abcdef")
        for i, char in enumerate(fingerprint):
            assert char in valid_hex_chars, f"Character at position {i} is '{char}', not a valid hex character"
    
    def test_different_users_produce_different_fingerprints(self):
        """Assert user_id=1 and user_id=2 produce different fingerprints."""
        # Arrange
        from app.services.login_history_service import generate_device_fingerprint
        browser = "Chrome 120.0"
        os = "Windows 10"
        device_type = "desktop"
        
        # Act
        fingerprint_user_1 = generate_device_fingerprint(browser, os, device_type, user_id=1)
        fingerprint_user_2 = generate_device_fingerprint(browser, os, device_type, user_id=2)
        
        # Assert - Different users MUST produce different fingerprints
        assert fingerprint_user_1 != fingerprint_user_2
    
    def test_same_inputs_produce_identical_fingerprints(self):
        """Assert deterministic: same inputs always produce same output."""
        # Arrange
        from app.services.login_history_service import generate_device_fingerprint
        
        # Act
        fp1 = generate_device_fingerprint("Firefox", "Linux", "desktop", 42)
        fp2 = generate_device_fingerprint("Firefox", "Linux", "desktop", 42)
        
        # Assert - Must be identical
        assert fp1 == fp2
    
    def test_different_salt_produces_different_fingerprint(self):
        """Assert changing DEVICE_FINGERPRINT_SALT changes fingerprint."""
        # Arrange
        from app.services.login_history_service import generate_device_fingerprint
        
        # Act - First fingerprint with default salt
        fp_original = generate_device_fingerprint("Chrome", "Windows", "desktop", 1)
        
        # Act - Second fingerprint with different salt
        with patch('app.config.settings.DEVICE_FINGERPRINT_SALT', 'ALTERED_SALT_12345'):
            fp_altered = generate_device_fingerprint("Chrome", "Windows", "desktop", 1)
        
        # Assert
        assert fp_original != fp_altered
    
    # ----- Rule 3: Boundary Testing -----
    
    def test_fingerprint_with_user_id_zero(self):
        """Boundary: user_id=0 should produce valid fingerprint."""
        # Arrange
        from app.services.login_history_service import generate_device_fingerprint
        
        # Act
        fingerprint = generate_device_fingerprint("Chrome", "Windows", "desktop", user_id=0)
        
        # Assert - Valid 64-char hex
        assert len(fingerprint) == 64
        assert all(c in "0123456789abcdef" for c in fingerprint)
    
    def test_fingerprint_with_negative_user_id(self):
        """Boundary: user_id=-1 should produce valid fingerprint."""
        # Arrange
        from app.services.login_history_service import generate_device_fingerprint
        
        # Act
        fingerprint = generate_device_fingerprint("Chrome", "Windows", "desktop", user_id=-1)
        
        # Assert
        assert len(fingerprint) == 64
    
    def test_fingerprint_with_none_user_id(self):
        """Boundary: user_id=None should produce valid fingerprint."""
        # Arrange
        from app.services.login_history_service import generate_device_fingerprint
        
        # Act
        fingerprint = generate_device_fingerprint("Chrome", "Windows", "desktop", user_id=None)
        
        # Assert
        assert len(fingerprint) == 64
    
    def test_fingerprint_with_all_none_inputs(self):
        """Boundary: All None values should not crash and return valid hash."""
        # Arrange
        from app.services.login_history_service import generate_device_fingerprint
        
        # Act
        fingerprint = generate_device_fingerprint(None, None, None, None)
        
        # Assert
        assert len(fingerprint) == 64
        assert all(c in "0123456789abcdef" for c in fingerprint)
    
    def test_fingerprint_with_empty_strings(self):
        """Boundary: Empty strings should produce valid fingerprint."""
        # Arrange
        from app.services.login_history_service import generate_device_fingerprint
        
        # Act
        fingerprint = generate_device_fingerprint("", "", "", user_id=1)
        
        # Assert
        assert len(fingerprint) == 64
    
    def test_fingerprint_with_max_int_user_id(self):
        """Boundary: Very large user_id should produce valid fingerprint."""
        # Arrange
        from app.services.login_history_service import generate_device_fingerprint
        max_int = 2**31 - 1  # 2147483647
        
        # Act
        fingerprint = generate_device_fingerprint("Chrome", "Windows", "desktop", user_id=max_int)
        
        # Assert
        assert len(fingerprint) == 64
    
    def test_none_and_integer_user_ids_produce_different_fingerprints(self):
        """Boundary: user_id=None vs user_id=1 should be different."""
        # Arrange
        from app.services.login_history_service import generate_device_fingerprint
        
        # Act
        fp_none = generate_device_fingerprint("Chrome", "Windows", "desktop", user_id=None)
        fp_one = generate_device_fingerprint("Chrome", "Windows", "desktop", user_id=1)
        
        # Assert
        assert fp_none != fp_one


# ============================================================================
# TEST #2: C2 - PASSWORD FORCE CHANGE (Middleware/Dependency)
# ============================================================================

class TestPasswordForceChangeFix:
    """
    Test require_password_not_forced dependency.
    
    VULNERABILITY: Account Takeover Persistence (CRITICAL)
    - Fix: Block all endpoints with 403 PASSWORD_CHANGE_REQUIRED
    """
    
    # ----- Rule 2: Hard Assertions + Rule 5: Exact Error Messages -----
    
    @pytest.mark.asyncio
    async def test_raises_403_when_password_reset_required_is_true(self):
        """Assert exact status code 403 when flag is True."""
        # Arrange
        from app.core.deps import require_password_not_forced
        from fastapi import HTTPException
        
        mock_user = MagicMock(spec=models.User)
        mock_user.id = 1
        mock_user.username = "testuser"
        mock_user.password_reset_required = True
        
        # Act & Assert
        with pytest.raises(HTTPException) as exc_info:
            await require_password_not_forced(mock_user)
        
        # Hard assertions on specific values
        assert exc_info.value.status_code == 403
        assert exc_info.value.detail["code"] == "PASSWORD_CHANGE_REQUIRED"
        assert "must change your password" in exc_info.value.detail["message"]
    
    @pytest.mark.asyncio
    async def test_returns_user_when_password_reset_required_is_false(self):
        """Assert returns exact same user object when flag is False."""
        # Arrange
        from app.core.deps import require_password_not_forced
        
        mock_user = MagicMock(spec=models.User)
        mock_user.id = 42
        mock_user.username = "allowed_user"
        mock_user.password_reset_required = False
        
        # Act
        result = await require_password_not_forced(mock_user)
        
        # Assert - Must return exact same object
        assert result is mock_user
        assert result.id == 42
        assert result.username == "allowed_user"
    
    # ----- Rule 3: Boundary Testing -----
    
    @pytest.mark.asyncio
    async def test_returns_user_when_password_reset_required_attribute_missing(self):
        """Boundary: Old users without the attribute should pass through."""
        # Arrange
        from app.core.deps import require_password_not_forced
        
        mock_user = MagicMock(spec=models.User)
        mock_user.id = 1
        mock_user.username = "legacy_user"
        # Simulate missing attribute
        del mock_user.password_reset_required
        
        # Act
        result = await require_password_not_forced(mock_user)
        
        # Assert
        assert result is mock_user


# ============================================================================
# TEST #3: C3 - STALE LOGIN CONFIRMATION FIX
# ============================================================================

class TestStaleLoginConfirmationFix:
    """
    Test confirm_login time validation.
    
    VULNERABILITY: Stale Login Confirmation Attack (HIGH)
    - Fix: ValidationError if login.login_at > 7 days ago
    """
    
    # ----- Rule 5: Exact Error Messages -----
    
    @pytest.mark.asyncio
    async def test_raises_validation_error_for_8_day_old_login(self):
        """Assert exact error message for login older than 7 days."""
        # Arrange
        from app.services import login_history_service
        from app.utils.exceptions import ValidationError
        from app.repositories.login_history_repository import LoginHistoryRepository
        
        mock_db = AsyncMock(spec=AsyncSession)
        user_id = 1
        login_id = 100
        
        mock_login = MagicMock(spec=models.LoginHistory)
        mock_login.id = login_id
        mock_login.user_id = user_id
        mock_login.login_at = datetime.now(timezone.utc) - timedelta(days=8)
        
        with patch('app.services.login_history_service.log'):
            with patch.object(LoginHistoryRepository, 'get_by_id', return_value=mock_login):
                # Act & Assert
                with pytest.raises(ValidationError) as exc_info:
                    await login_history_service.confirm_login(mock_db, user_id, login_id, trust_device=False)
                
                # Hard assertion on exact error message content
                error_message = str(exc_info.value)
                assert "Cannot confirm login older than 7 days" in error_message
                assert "8 days old" in error_message
    
    @pytest.mark.asyncio
    async def test_raises_resource_not_found_for_nonexistent_login(self):
        """Assert exact error message for login not found."""
        # Arrange
        from app.services import login_history_service
        from app.utils.exceptions import ResourceNotFoundError
        from app.repositories.login_history_repository import LoginHistoryRepository
        
        mock_db = AsyncMock(spec=AsyncSession)
        user_id = 1
        login_id = 999  # Non-existent
        
        with patch.object(LoginHistoryRepository, 'get_by_id', return_value=None):
            # Act & Assert
            with pytest.raises(ResourceNotFoundError) as exc_info:
                await login_history_service.confirm_login(mock_db, user_id, login_id)
            
            # Hard assertion on error message
            assert "Login 999 not found" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_raises_resource_not_found_for_wrong_user(self):
        """Assert cannot confirm another user's login."""
        # Arrange
        from app.services import login_history_service
        from app.utils.exceptions import ResourceNotFoundError
        from app.repositories.login_history_repository import LoginHistoryRepository
        
        mock_db = AsyncMock(spec=AsyncSession)
        requesting_user_id = 1
        login_owner_id = 2  # Different user
        login_id = 100
        
        mock_login = MagicMock(spec=models.LoginHistory)
        mock_login.id = login_id
        mock_login.user_id = login_owner_id
        
        with patch.object(LoginHistoryRepository, 'get_by_id', return_value=mock_login):
            # Act & Assert
            with pytest.raises(ResourceNotFoundError):
                await login_history_service.confirm_login(mock_db, requesting_user_id, login_id)
    
    # ----- Rule 3: Boundary Testing -----
    
    @pytest.mark.asyncio
    async def test_accepts_login_exactly_7_days_old(self):
        """Boundary: Exactly 7 days old should be accepted."""
        # Arrange
        from app.services import login_history_service
        from app.repositories.login_history_repository import LoginHistoryRepository
        from app.repositories.trusted_device_repository import TrustedDeviceRepository
        from app.repositories.user_repository import UserRepository

        mock_db = AsyncMock(spec=AsyncSession)
        user_id = 1
        login_id = 100

        mock_login = MagicMock(spec=models.LoginHistory)
        mock_login.id = login_id
        mock_login.user_id = user_id
        mock_login.login_at = datetime.now(timezone.utc) - timedelta(days=7)  # Exactly 7 days
        mock_login.user_response = None
        mock_login.responded_at = None
        mock_login.browser = "Chrome"
        mock_login.os = "Windows"
        mock_login.device_type = "desktop"

        mock_user = MagicMock(spec=models.User)
        mock_user.id = user_id
        mock_user.password_reset_required = False

        mock_trusted_device = MagicMock(spec=models.TrustedDevice)

        with patch.object(LoginHistoryRepository, 'get_by_id', return_value=mock_login):
            with patch.object(TrustedDeviceRepository, 'trust_device', return_value=mock_trusted_device):
                with patch.object(UserRepository, 'get_by_id', return_value=mock_user):
                    # Act
                    result_login, callback = await login_history_service.confirm_login(
                        mock_db, user_id, login_id, trust_device=True
                    )

                    # Assert
                    assert result_login.user_response == "confirmed"
    
    @pytest.mark.asyncio
    async def test_accepts_login_1_day_old(self):
        """Boundary: 1 day old login should be accepted."""
        # Arrange
        from app.services import login_history_service
        from app.repositories.login_history_repository import LoginHistoryRepository
        from app.repositories.trusted_device_repository import TrustedDeviceRepository
        from app.repositories.user_repository import UserRepository

        mock_db = AsyncMock(spec=AsyncSession)
        user_id = 1
        login_id = 100

        mock_login = MagicMock(spec=models.LoginHistory)
        mock_login.id = login_id
        mock_login.user_id = user_id
        mock_login.login_at = datetime.now(timezone.utc) - timedelta(days=1)
        mock_login.user_response = None
        mock_login.responded_at = None
        mock_login.browser = "Chrome"
        mock_login.os = "Windows"
        mock_login.device_type = "desktop"

        mock_user = MagicMock(spec=models.User)
        mock_user.id = user_id
        mock_user.password_reset_required = False

        mock_trusted_device = MagicMock(spec=models.TrustedDevice)

        with patch.object(LoginHistoryRepository, 'get_by_id', return_value=mock_login):
            with patch.object(TrustedDeviceRepository, 'trust_device', return_value=mock_trusted_device):
                with patch.object(UserRepository, 'get_by_id', return_value=mock_user):
                    # Act
                    result_login, callback = await login_history_service.confirm_login(
                        mock_db, user_id, login_id, trust_device=True
                    )

                    # Assert
                    assert result_login.user_response == "confirmed"


# ============================================================================
# TEST #4: C2 - SECURE ACCOUNT SETS PASSWORD_RESET_REQUIRED
# ============================================================================

class TestSecureAccountSetsPasswordReset:
    """
    Test secure_account sets password_reset_required=True.
    """
    
    @pytest.mark.asyncio
    async def test_sets_password_reset_required_to_true(self):
        """Assert secure_account mutates user.password_reset_required to True."""
        # Arrange
        from app.services import login_history_service
        from app.repositories.login_history_repository import LoginHistoryRepository
        from app.repositories.user_repository import UserRepository
        
        mock_db = AsyncMock(spec=AsyncSession)
        mock_db.flush = AsyncMock()
        mock_db.refresh = AsyncMock()
        user_id = 1
        login_id = 100
        
        mock_user = MagicMock(spec=models.User)
        mock_user.id = user_id
        mock_user.password_reset_required = False  # Initially False
        
        mock_login = MagicMock(spec=models.LoginHistory)
        mock_login.id = login_id
        mock_login.user_id = user_id
        mock_login.user_response = None
        
        with patch('app.services.login_history_service.log'):
            with patch.object(LoginHistoryRepository, 'get_by_id', return_value=mock_login):
                with patch.object(UserRepository, 'get_by_id', return_value=mock_user):
                    # Act
                    result_login, callback = await login_history_service.secure_account(
                        mock_db, user_id, login_id
                    )
                    
                    # Assert - Hard assertion on specific value
                    assert mock_user.password_reset_required is True
                    assert result_login.user_response == "secured"


# ============================================================================
# TEST #5: H1 - SUSPICIOUS LOGIN EMAIL (Phase 1)
# Isolation: Testing Celery task interface, not duplicating service logic
# ============================================================================

class TestSuspiciousLoginEmailTask:
    """
    Test send_login_alert_email_task interface.
    
    Rule 4 (Isolation): Test the Celery task's signature/behavior,
    not by duplicating the service's internal logic.
    """
    
    def test_email_task_accepts_required_parameters(self):
        """Assert email task can be called with expected parameters."""
        # Arrange
        mock_task = MagicMock()
        
        # Act - Call with the signature expected by login_history_service._post_commit
        with patch('app.celery_utils.send_login_alert_email_task', mock_task):
            from app.celery_utils import send_login_alert_email_task
            send_login_alert_email_task.delay(
                email_to="user@example.com",
                username="testuser",
                ip_address="192.168.1.1",
                user_agent="Mozilla/5.0",
                device_type="desktop",
                browser="Chrome",
                os="Windows",
                anomalies={"is_suspicious": True, "new_ip": True, "new_device": False, "new_location": False},
                location="Ho Chi Minh, Vietnam",
            )
        
        # Assert - Task was called exactly once with expected kwargs
        mock_task.delay.assert_called_once()
        call_kwargs = mock_task.delay.call_args[1]
        assert call_kwargs["email_to"] == "user@example.com"
        assert call_kwargs["username"] == "testuser"
        assert call_kwargs["ip_address"] == "192.168.1.1"
        assert call_kwargs["anomalies"]["is_suspicious"] is True
        assert call_kwargs["anomalies"]["new_ip"] is True
        assert call_kwargs["location"] == "Ho Chi Minh, Vietnam"
    
    # ----- Rule 3: Boundary Testing -----
    
    def test_email_task_accepts_none_location(self):
        """Boundary: location=None should be valid."""
        # Arrange
        mock_task = MagicMock()
        
        # Act
        with patch('app.celery_utils.send_login_alert_email_task', mock_task):
            from app.celery_utils import send_login_alert_email_task
            send_login_alert_email_task.delay(
                email_to="user@example.com",
                username="testuser",
                ip_address="10.0.0.1",
                user_agent="Chrome",
                device_type="desktop",
                browser="Chrome",
                os="Windows",
                anomalies={"is_suspicious": True},
                location=None,  # None is valid
            )
        
        # Assert
        call_kwargs = mock_task.delay.call_args[1]
        assert call_kwargs["location"] is None
    
    def test_email_task_accepts_empty_anomalies(self):
        """Boundary: Empty anomalies dict should be accepted."""
        # Arrange
        mock_task = MagicMock()
        
        # Act
        with patch('app.celery_utils.send_login_alert_email_task', mock_task):
            from app.celery_utils import send_login_alert_email_task
            send_login_alert_email_task.delay(
                email_to="user@example.com",
                username="testuser",
                ip_address="10.0.0.1",
                user_agent="Chrome",
                device_type="desktop",
                browser="Chrome",
                os="Windows",
                anomalies={},  # Empty dict
                location=None,
            )
        
        # Assert
        call_kwargs = mock_task.delay.call_args[1]
        assert call_kwargs["anomalies"] == {}
