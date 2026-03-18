"""
Unit + Integration tests for Security Bugfixes

Bug #1: get_suspicious_logins — operator precedence (| vs or_())
Bug #2: DELETE /trusted-devices/{device_id} — missing HTTPException import
Bug #3: check_device_seen_before — type annotation str vs dict

SDET Rules Applied:
1. AAA Pattern: Strictly Arrange-Act-Assert
2. Hard Assertions: Assert specific values, not truthy checks
3. Boundary Testing: Empty inputs, null values, edge cases
4. Isolation: Mock only external dependencies (DB, Network)
5. Failure Scenarios: Verify specific error messages

Run with:
    pytest tests/security/test_security_bugfixes.py -v
"""
import inspect

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy.ext.asyncio import AsyncSession

from app import models


# ============================================================================
# BUG #1: get_suspicious_logins — or_() QUERY FIX
# ============================================================================


class TestSuspiciousLoginsQueryFix:
    """
    Bug: Operator precedence in get_suspicious_logins filter.

    Old code:  is_new_ip == True | is_new_device == True  (wrong: | binds tighter than ==)
    Fix:       or_(is_new_ip == True, is_new_device == True, is_new_location == True)
    """

    # ----- Rule 2: Hard Assertions -----

    def test_or_imported_in_repository(self):
        """Assert or_ is imported in login_history_repository module."""
        # Arrange
        import app.repositories.login_history_repository as repo_module

        # Act & Assert
        assert hasattr(repo_module, 'or_'), \
            "or_ must be imported in login_history_repository"

    @pytest.mark.asyncio
    async def test_service_delegates_to_repository_with_pending_true(self):
        """Assert get_suspicious_logins calls repository with pending_only=True."""
        # Arrange
        from app.services import login_history_service
        from app.repositories.login_history_repository import LoginHistoryRepository

        mock_db = AsyncMock(spec=AsyncSession)
        user_id = 42
        expected_logins = [MagicMock(spec=models.LoginHistory)]

        with patch.object(
            LoginHistoryRepository, 'get_suspicious_logins',
            return_value=expected_logins
        ) as mock_get:
            # Act
            result = await login_history_service.get_suspicious_logins(
                mock_db, user_id, pending_only=True
            )

            # Assert
            mock_get.assert_called_once_with(user_id, True)
            assert result is expected_logins

    @pytest.mark.asyncio
    async def test_service_delegates_to_repository_with_pending_false(self):
        """Assert get_suspicious_logins forwards pending_only=False."""
        # Arrange
        from app.services import login_history_service
        from app.repositories.login_history_repository import LoginHistoryRepository

        mock_db = AsyncMock(spec=AsyncSession)

        with patch.object(
            LoginHistoryRepository, 'get_suspicious_logins',
            return_value=[]
        ) as mock_get:
            # Act
            await login_history_service.get_suspicious_logins(
                mock_db, user_id=1, pending_only=False
            )

            # Assert
            mock_get.assert_called_once_with(1, False)


# ============================================================================
# BUG #1 INTEGRATION: Verify or_() query against real DB
# ============================================================================


@pytest.mark.integration
class TestSuspiciousLoginsQueryIntegration:
    """
    Integration test: verify or_() produces correct SQL filtering.

    Creates LoginHistory records with various anomaly flag combinations
    and verifies get_suspicious_logins returns the correct set.

    The old | operator bug would cause only is_new_ip=True logins to match
    (or produce malformed SQL). With or_(), each flag independently qualifies.
    """

    @pytest.mark.asyncio
    async def test_returns_login_with_only_new_ip(self, setup_test_database):
        """Login with only is_new_ip=True should be returned."""
        # Arrange
        from app.database import AsyncSessionLocal
        from app.repositories.login_history_repository import LoginHistoryRepository

        async with AsyncSessionLocal() as session:
            async with session.begin():
                user = models.User(
                    username="bugfix_ip_user",
                    email="bugfix_ip@test.com",
                    password_hash="fakehash",
                    role="user",
                    status="active",
                )
                session.add(user)
                await session.flush()

                login = models.LoginHistory(
                    user_id=user.id,
                    login_at=datetime.now(timezone.utc),
                    ip_address="1.2.3.4",
                    is_new_ip=True,
                    is_new_device=False,
                    is_new_location=False,
                    risk_score=30,
                )
                session.add(login)
                await session.flush()

                # Act
                repo = LoginHistoryRepository(session)
                results = await repo.get_suspicious_logins(user.id, pending_only=False)

                # Assert
                assert len(results) == 1
                assert results[0].is_new_ip is True
                assert results[0].is_new_device is False
                assert results[0].is_new_location is False

    @pytest.mark.asyncio
    async def test_returns_login_with_only_new_device(self, setup_test_database):
        """Login with only is_new_device=True should be returned.

        This is the PRIMARY regression test for Bug #1.
        With the old | operator, this query would fail to match
        a login where only is_new_device=True.
        """
        # Arrange
        from app.database import AsyncSessionLocal
        from app.repositories.login_history_repository import LoginHistoryRepository

        async with AsyncSessionLocal() as session:
            async with session.begin():
                user = models.User(
                    username="bugfix_device_user",
                    email="bugfix_device@test.com",
                    password_hash="fakehash",
                    role="user",
                    status="active",
                )
                session.add(user)
                await session.flush()

                login = models.LoginHistory(
                    user_id=user.id,
                    login_at=datetime.now(timezone.utc),
                    ip_address="5.6.7.8",
                    is_new_ip=False,
                    is_new_device=True,
                    is_new_location=False,
                    risk_score=40,
                )
                session.add(login)
                await session.flush()

                # Act
                repo = LoginHistoryRepository(session)
                results = await repo.get_suspicious_logins(user.id, pending_only=False)

                # Assert
                assert len(results) == 1
                assert results[0].is_new_device is True

    @pytest.mark.asyncio
    async def test_returns_login_with_only_new_location(self, setup_test_database):
        """Login with only is_new_location=True should be returned."""
        # Arrange
        from app.database import AsyncSessionLocal
        from app.repositories.login_history_repository import LoginHistoryRepository

        async with AsyncSessionLocal() as session:
            async with session.begin():
                user = models.User(
                    username="bugfix_location_user",
                    email="bugfix_location@test.com",
                    password_hash="fakehash",
                    role="user",
                    status="active",
                )
                session.add(user)
                await session.flush()

                login = models.LoginHistory(
                    user_id=user.id,
                    login_at=datetime.now(timezone.utc),
                    ip_address="9.10.11.12",
                    is_new_ip=False,
                    is_new_device=False,
                    is_new_location=True,
                    risk_score=50,
                )
                session.add(login)
                await session.flush()

                # Act
                repo = LoginHistoryRepository(session)
                results = await repo.get_suspicious_logins(user.id, pending_only=False)

                # Assert
                assert len(results) == 1
                assert results[0].is_new_location is True

    @pytest.mark.asyncio
    async def test_excludes_login_with_no_anomaly_flags(self, setup_test_database):
        """Login with all flags False should NOT be returned."""
        # Arrange
        from app.database import AsyncSessionLocal
        from app.repositories.login_history_repository import LoginHistoryRepository

        async with AsyncSessionLocal() as session:
            async with session.begin():
                user = models.User(
                    username="bugfix_normal_user",
                    email="bugfix_normal@test.com",
                    password_hash="fakehash",
                    role="user",
                    status="active",
                )
                session.add(user)
                await session.flush()

                login = models.LoginHistory(
                    user_id=user.id,
                    login_at=datetime.now(timezone.utc),
                    ip_address="10.0.0.1",
                    is_new_ip=False,
                    is_new_device=False,
                    is_new_location=False,
                    risk_score=0,
                )
                session.add(login)
                await session.flush()

                # Act
                repo = LoginHistoryRepository(session)
                results = await repo.get_suspicious_logins(user.id, pending_only=False)

                # Assert
                assert len(results) == 0

    @pytest.mark.asyncio
    async def test_pending_only_excludes_responded_logins(self, setup_test_database):
        """pending_only=True should exclude logins with user_response set."""
        # Arrange
        from app.database import AsyncSessionLocal
        from app.repositories.login_history_repository import LoginHistoryRepository

        async with AsyncSessionLocal() as session:
            async with session.begin():
                user = models.User(
                    username="bugfix_pending_user",
                    email="bugfix_pending@test.com",
                    password_hash="fakehash",
                    role="user",
                    status="active",
                )
                session.add(user)
                await session.flush()

                # Suspicious but already confirmed
                confirmed_login = models.LoginHistory(
                    user_id=user.id,
                    login_at=datetime.now(timezone.utc) - timedelta(hours=2),
                    ip_address="1.1.1.1",
                    is_new_ip=True,
                    is_new_device=False,
                    is_new_location=False,
                    risk_score=30,
                    user_response="confirmed",
                    responded_at=datetime.now(timezone.utc),
                )
                # Suspicious and pending
                pending_login = models.LoginHistory(
                    user_id=user.id,
                    login_at=datetime.now(timezone.utc),
                    ip_address="2.2.2.2",
                    is_new_ip=True,
                    is_new_device=True,
                    is_new_location=False,
                    risk_score=70,
                    user_response=None,
                )
                session.add_all([confirmed_login, pending_login])
                await session.flush()

                # Act
                repo = LoginHistoryRepository(session)
                results = await repo.get_suspicious_logins(user.id, pending_only=True)

                # Assert
                assert len(results) == 1
                assert results[0].ip_address == "2.2.2.2"
                assert results[0].user_response is None

    # ----- Rule 3: Boundary Testing -----

    @pytest.mark.asyncio
    async def test_returns_login_with_all_flags_true(self, setup_test_database):
        """Boundary: Login with all anomaly flags True should be returned once."""
        # Arrange
        from app.database import AsyncSessionLocal
        from app.repositories.login_history_repository import LoginHistoryRepository

        async with AsyncSessionLocal() as session:
            async with session.begin():
                user = models.User(
                    username="bugfix_allflags_user",
                    email="bugfix_allflags@test.com",
                    password_hash="fakehash",
                    role="user",
                    status="active",
                )
                session.add(user)
                await session.flush()

                login = models.LoginHistory(
                    user_id=user.id,
                    login_at=datetime.now(timezone.utc),
                    ip_address="99.99.99.99",
                    is_new_ip=True,
                    is_new_device=True,
                    is_new_location=True,
                    risk_score=100,
                )
                session.add(login)
                await session.flush()

                # Act
                repo = LoginHistoryRepository(session)
                results = await repo.get_suspicious_logins(user.id, pending_only=False)

                # Assert - Should return exactly 1 (not duplicated by OR)
                assert len(results) == 1


# ============================================================================
# BUG #2: DELETE /trusted-devices/{device_id} — HTTPException IMPORT FIX
# ============================================================================


class TestTrustedDeviceEndpointFix:
    """
    Bug: HTTPException not imported in security.py router.

    The DELETE /trusted-devices/{device_id} endpoint raises HTTPException(404)
    when device not found, but HTTPException was missing from imports.
    """

    # ----- Rule 2: Hard Assertions -----

    def test_httpexception_is_imported_in_security_router(self):
        """Assert HTTPException is accessible in the security router module."""
        # Arrange & Act
        from app.routers import security as security_module

        # Assert
        source = inspect.getsource(security_module)
        assert 'HTTPException' in source, \
            "HTTPException must be imported in security.py"

    def test_httpexception_in_fastapi_import_line(self):
        """Assert HTTPException appears in the fastapi import statement."""
        # Arrange
        from app.routers import security as security_module

        # Act
        source = inspect.getsource(security_module)
        # Find the fastapi import line
        for line in source.splitlines():
            if 'from fastapi import' in line and 'HTTPException' in line:
                break
        else:
            pytest.fail("HTTPException not found in 'from fastapi import ...' line")


# ============================================================================
# BUG #2 INTEGRATION: DELETE /trusted-devices/{id} returns 404
# ============================================================================


@pytest.mark.integration
class TestTrustedDeviceEndpoint404Integration:
    """
    Integration test: DELETE non-existent device returns 404.

    Before the fix, this endpoint would crash with NameError
    because HTTPException was not imported.
    """

    @pytest.mark.asyncio
    async def test_delete_nonexistent_device_returns_404(
        self, client, admin_user_in_db, admin_token_headers
    ):
        """Assert DELETE /api/security/trusted-devices/99999 returns 404."""
        # Arrange
        nonexistent_device_id = 99999

        # Act
        response = await client.delete(
            f"/api/security/trusted-devices/{nonexistent_device_id}",
            headers=admin_token_headers,
        )

        # Assert
        assert response.status_code == 404
        assert "Device not found" in response.json().get("detail", "")

    @pytest.mark.asyncio
    async def test_delete_device_requires_authentication(self, client):
        """Assert DELETE without auth returns 401."""
        # Act
        response = await client.delete("/api/security/trusted-devices/1")

        # Assert
        assert response.status_code == 401


# ============================================================================
# BUG #3: check_device_seen_before — TYPE ANNOTATION FIX
# ============================================================================


class TestCheckDeviceSeenBeforeTypeFix:
    """
    Bug: check_device_seen_before type hint was str, actual parameter is dict.

    Service passes Dict[str, str] via _check_device_seen(), but repository
    declared the parameter as str. The method calls .get() on it, which
    only works with dict.
    """

    # ----- Rule 2: Hard Assertions -----

    def test_parameter_type_annotation_is_dict(self):
        """Assert check_device_seen_before parameter type hint is dict."""
        # Arrange
        from app.repositories.login_history_repository import LoginHistoryRepository

        # Act
        sig = inspect.signature(LoginHistoryRepository.check_device_seen_before)
        param = sig.parameters['device_fingerprint']

        # Assert
        assert param.annotation is dict, \
            f"Expected dict, got {param.annotation}"

    @pytest.mark.asyncio
    async def test_service_passes_dict_to_repository(self):
        """Assert _check_device_seen passes dict (not str) to repository."""
        # Arrange
        from app.services.login_history_service import _check_device_seen
        from app.repositories.login_history_repository import LoginHistoryRepository

        mock_db = AsyncMock(spec=AsyncSession)
        repo = LoginHistoryRepository(mock_db)
        device_info = {
            "browser": "Chrome 120.0",
            "os": "Windows 10",
            "device_type": "desktop",
        }

        with patch.object(
            LoginHistoryRepository, 'check_device_seen_before',
            return_value=True
        ) as mock_check:
            # Act
            result = await _check_device_seen(repo, user_id=1, device_info=device_info)

            # Assert
            mock_check.assert_called_once_with(1, device_info)
            assert result is True
            # Verify the argument is actually a dict
            actual_arg = mock_check.call_args[0][1]
            assert isinstance(actual_arg, dict)

    @pytest.mark.asyncio
    async def test_repository_handles_dict_with_get_calls(self):
        """Assert repository correctly calls .get() on the dict parameter."""
        # Arrange
        from app.repositories.login_history_repository import LoginHistoryRepository

        mock_db = AsyncMock(spec=AsyncSession)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        repo = LoginHistoryRepository(mock_db)
        device_dict = {
            "browser": "Firefox 121.0",
            "os": "macOS 14",
            "device_type": "desktop",
        }

        # Act — Should not raise TypeError (str has no .get())
        result = await repo.check_device_seen_before(
            user_id=1, device_fingerprint=device_dict
        )

        # Assert
        assert result is False
        mock_db.execute.assert_called_once()

    # ----- Rule 3: Boundary Testing -----

    @pytest.mark.asyncio
    async def test_repository_returns_true_for_empty_dict(self):
        """Boundary: Empty dict is falsy, guard clause should return True."""
        # Arrange
        from app.repositories.login_history_repository import LoginHistoryRepository

        mock_db = AsyncMock(spec=AsyncSession)
        repo = LoginHistoryRepository(mock_db)

        # Act — {} is falsy in Python, so `if not device_fingerprint` catches it
        result = await repo.check_device_seen_before(
            user_id=1, device_fingerprint={}
        )

        # Assert — Guard clause returns True (treat missing info as "seen")
        assert result is True
        # DB should NOT be queried
        mock_db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_repository_returns_true_for_none(self):
        """Boundary: None should be handled by guard clause."""
        # Arrange
        from app.repositories.login_history_repository import LoginHistoryRepository

        mock_db = AsyncMock(spec=AsyncSession)
        repo = LoginHistoryRepository(mock_db)

        # Act
        result = await repo.check_device_seen_before(
            user_id=1, device_fingerprint=None
        )

        # Assert
        assert result is True
        mock_db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_repository_handles_missing_keys_in_dict(self):
        """Boundary: Dict with missing keys should use defaults from .get()."""
        # Arrange
        from app.repositories.login_history_repository import LoginHistoryRepository

        mock_db = AsyncMock(spec=AsyncSession)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        repo = LoginHistoryRepository(mock_db)
        # Dict with only browser — os and device_type missing
        partial_dict = {"browser": "Safari 17.0"}

        # Act — Should not raise KeyError, .get() returns "" for missing keys
        result = await repo.check_device_seen_before(
            user_id=1, device_fingerprint=partial_dict
        )

        # Assert
        assert result is False
        mock_db.execute.assert_called_once()
