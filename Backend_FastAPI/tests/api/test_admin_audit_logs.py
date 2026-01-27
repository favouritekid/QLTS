# tests/api/test_admin_audit_logs.py
"""
API tests for /api/admin/audit-logs endpoints.

Tests cover:
- List audit logs with filters
- Get entity audit history
- Get audit log summary statistics
- Authorization tests (admin/manager only access)
"""
import logging
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select

from app import models
from app.database import AsyncSessionLocal
from app.services import audit_service

try:
    from tests.fixtures.constants import (
        NON_EXISTENT_ID,
        AdminURLs,
        TestOrgData,
    )
except ImportError:
    pytest.fail("Could not import constants from tests.fixtures.constants.")

log = logging.getLogger(__name__)


# ============================================================================
# FIXTURES
# ============================================================================


@pytest_asyncio.fixture(scope="function")
async def seed_audit_logs(setup_test_database):
    """
    Create sample audit log entries for testing.
    Returns the created audit log IDs and data.
    """
    log.info("--- [FIXTURE] Seeding audit log entries ---")

    async with AsyncSessionLocal() as session:
        async with session.begin():
            # Create audit log entries
            log1 = models.EntityAuditLog(
                entity_type="Lead",
                entity_id=100,
                action="created",
                actor_user_id=None,
                field_name=None,
                old_value=None,
                new_value={"full_name": "Test Lead", "phone": "0901234567"},
                changes=None,
                reason=None,
                source="api",
                created_at=datetime(2024, 6, 1, 10, 0, 0, tzinfo=timezone.utc),
            )
            log2 = models.EntityAuditLog(
                entity_type="Lead",
                entity_id=100,
                action="updated",
                actor_user_id=None,
                field_name="status",
                old_value="new",
                new_value="contacted",
                changes={"status": {"old": "new", "new": "contacted"}},
                reason="Status update",
                source="api",
                created_at=datetime(2024, 6, 2, 10, 0, 0, tzinfo=timezone.utc),
            )
            log3 = models.EntityAuditLog(
                entity_type="Consultation",
                entity_id=200,
                action="created",
                actor_user_id=None,
                field_name=None,
                old_value=None,
                new_value={"notes": "First consultation"},
                changes=None,
                reason=None,
                source="api",
                created_at=datetime(2024, 6, 3, 10, 0, 0, tzinfo=timezone.utc),
            )
            log4 = models.EntityAuditLog(
                entity_type="Lead",
                entity_id=101,
                action="deleted",
                actor_user_id=None,
                field_name=None,
                old_value={"full_name": "Deleted Lead"},
                new_value=None,
                changes=None,
                reason="User requested deletion",
                source="api",
                created_at=datetime(2024, 6, 4, 10, 0, 0, tzinfo=timezone.utc),
            )
            session.add_all([log1, log2, log3, log4])
            await session.flush()

            log_ids = [log1.id, log2.id, log3.id, log4.id]

    log.info(f"--- [FIXTURE] Audit logs seeded (IDs: {log_ids}) ---")
    return {
        "log_ids": log_ids,
        "lead_100_count": 2,  # log1 and log2
        "consultation_count": 1,  # log3
        "total_count": 4,
    }


# ============================================================================
# TEST: List Audit Logs
# ============================================================================


class TestListAuditLogs:
    """Tests for GET /admin/audit-logs endpoint."""

    @pytest.mark.asyncio
    async def test_list_audit_logs_success(
        self,
        client: AsyncClient,
        admin_token_headers: dict,
        seed_audit_logs: dict,
    ):
        """Test that admin can list all audit logs."""
        log.info("--- Running: test_list_audit_logs_success ---")

        response = await client.get(
            AdminURLs.AUDIT_LOGS,
            headers=admin_token_headers,
        )

        assert response.status_code == 200, f"Response: {response.text}"
        data = response.json()

        assert "items" in data
        assert "total" in data
        assert "page" in data
        assert "page_size" in data
        assert "has_more" in data

        assert data["total"] == seed_audit_logs["total_count"]
        assert len(data["items"]) == seed_audit_logs["total_count"]
        log.info("✅ Admin can list all audit logs successfully")

    @pytest.mark.asyncio
    async def test_list_audit_logs_filter_by_entity_type(
        self,
        client: AsyncClient,
        admin_token_headers: dict,
        seed_audit_logs: dict,
    ):
        """Test filtering audit logs by entity type."""
        log.info("--- Running: test_list_audit_logs_filter_by_entity_type ---")

        response = await client.get(
            AdminURLs.AUDIT_LOGS,
            params={"entity_type": "Lead"},
            headers=admin_token_headers,
        )

        assert response.status_code == 200, f"Response: {response.text}"
        data = response.json()

        # Should return only Lead entries (log1, log2, log4)
        assert data["total"] == 3
        for item in data["items"]:
            assert item["entity_type"] == "Lead"
        log.info("✅ Filtering by entity_type works correctly")

    @pytest.mark.asyncio
    async def test_list_audit_logs_filter_by_action(
        self,
        client: AsyncClient,
        admin_token_headers: dict,
        seed_audit_logs: dict,
    ):
        """Test filtering audit logs by action type."""
        log.info("--- Running: test_list_audit_logs_filter_by_action ---")

        response = await client.get(
            AdminURLs.AUDIT_LOGS,
            params={"action": "created"},
            headers=admin_token_headers,
        )

        assert response.status_code == 200, f"Response: {response.text}"
        data = response.json()

        # Should return only "created" entries (log1, log3)
        assert data["total"] == 2
        for item in data["items"]:
            assert item["action"] == "created"
        log.info("✅ Filtering by action works correctly")

    @pytest.mark.asyncio
    async def test_list_audit_logs_filter_by_entity_id(
        self,
        client: AsyncClient,
        admin_token_headers: dict,
        seed_audit_logs: dict,
    ):
        """Test filtering audit logs by entity ID."""
        log.info("--- Running: test_list_audit_logs_filter_by_entity_id ---")

        response = await client.get(
            AdminURLs.AUDIT_LOGS,
            params={"entity_type": "Lead", "entity_id": 100},
            headers=admin_token_headers,
        )

        assert response.status_code == 200, f"Response: {response.text}"
        data = response.json()

        # Should return only Lead ID 100 entries (log1, log2)
        assert data["total"] == seed_audit_logs["lead_100_count"]
        for item in data["items"]:
            assert item["entity_type"] == "Lead"
            assert item["entity_id"] == 100
        log.info("✅ Filtering by entity_id works correctly")

    @pytest.mark.asyncio
    async def test_list_audit_logs_pagination(
        self,
        client: AsyncClient,
        admin_token_headers: dict,
        seed_audit_logs: dict,
    ):
        """Test pagination works correctly."""
        log.info("--- Running: test_list_audit_logs_pagination ---")

        # Page 1 with page_size=2
        response = await client.get(
            AdminURLs.AUDIT_LOGS,
            params={"page": 1, "page_size": 2},
            headers=admin_token_headers,
        )

        assert response.status_code == 200, f"Response: {response.text}"
        data = response.json()

        assert data["page"] == 1
        assert data["page_size"] == 2
        assert len(data["items"]) == 2
        assert data["total"] == seed_audit_logs["total_count"]
        assert data["has_more"] is True

        # Page 2 with page_size=2
        response2 = await client.get(
            AdminURLs.AUDIT_LOGS,
            params={"page": 2, "page_size": 2},
            headers=admin_token_headers,
        )

        assert response2.status_code == 200
        data2 = response2.json()

        assert data2["page"] == 2
        assert len(data2["items"]) == 2
        assert data2["has_more"] is False
        log.info("✅ Pagination works correctly")

    @pytest.mark.asyncio
    async def test_list_audit_logs_empty(
        self,
        client: AsyncClient,
        admin_token_headers: dict,
        setup_test_database,
    ):
        """Test listing audit logs when none exist."""
        log.info("--- Running: test_list_audit_logs_empty ---")

        response = await client.get(
            AdminURLs.AUDIT_LOGS,
            headers=admin_token_headers,
        )

        assert response.status_code == 200, f"Response: {response.text}"
        data = response.json()

        assert data["total"] == 0
        assert len(data["items"]) == 0
        assert data["has_more"] is False
        log.info("✅ Empty list returns correctly")


# ============================================================================
# TEST: Get Entity Audit History
# ============================================================================


class TestGetEntityAuditHistory:
    """Tests for GET /admin/audit-logs/entity/{entity_type}/{entity_id} endpoint."""

    @pytest.mark.asyncio
    async def test_get_entity_history_success(
        self,
        client: AsyncClient,
        admin_token_headers: dict,
        seed_audit_logs: dict,
    ):
        """Test getting audit history for a specific entity."""
        log.info("--- Running: test_get_entity_history_success ---")

        response = await client.get(
            AdminURLs.AUDIT_LOGS_ENTITY("Lead", 100),
            headers=admin_token_headers,
        )

        assert response.status_code == 200, f"Response: {response.text}"
        data = response.json()

        assert data["total"] == seed_audit_logs["lead_100_count"]
        for item in data["items"]:
            assert item["entity_type"] == "Lead"
            assert item["entity_id"] == 100
        log.info("✅ Entity audit history retrieved successfully")

    @pytest.mark.asyncio
    async def test_get_entity_history_empty(
        self,
        client: AsyncClient,
        admin_token_headers: dict,
        seed_audit_logs: dict,
    ):
        """Test getting audit history for entity with no logs."""
        log.info("--- Running: test_get_entity_history_empty ---")

        response = await client.get(
            AdminURLs.AUDIT_LOGS_ENTITY("Lead", NON_EXISTENT_ID),
            headers=admin_token_headers,
        )

        assert response.status_code == 200, f"Response: {response.text}"
        data = response.json()

        assert data["total"] == 0
        assert len(data["items"]) == 0
        log.info("✅ Empty entity history returns correctly")

    @pytest.mark.asyncio
    async def test_get_entity_history_pagination(
        self,
        client: AsyncClient,
        admin_token_headers: dict,
        seed_audit_logs: dict,
    ):
        """Test pagination in entity history."""
        log.info("--- Running: test_get_entity_history_pagination ---")

        response = await client.get(
            AdminURLs.AUDIT_LOGS_ENTITY("Lead", 100),
            params={"page": 1, "page_size": 1},
            headers=admin_token_headers,
        )

        assert response.status_code == 200, f"Response: {response.text}"
        data = response.json()

        assert len(data["items"]) == 1
        assert data["total"] == seed_audit_logs["lead_100_count"]
        assert data["has_more"] is True
        log.info("✅ Entity history pagination works correctly")


# ============================================================================
# TEST: Get Audit Log Summary
# ============================================================================


class TestGetAuditSummary:
    """Tests for GET /admin/audit-logs/summary endpoint."""

    @pytest.mark.asyncio
    async def test_get_summary_success(
        self,
        client: AsyncClient,
        admin_token_headers: dict,
        seed_audit_logs: dict,
    ):
        """Test getting audit log summary statistics."""
        log.info("--- Running: test_get_summary_success ---")

        response = await client.get(
            AdminURLs.AUDIT_LOGS_SUMMARY,
            headers=admin_token_headers,
        )

        assert response.status_code == 200, f"Response: {response.text}"
        data = response.json()

        assert "total" in data
        assert "by_entity_type" in data
        assert "by_action" in data

        assert data["total"] == seed_audit_logs["total_count"]
        assert data["by_entity_type"]["Lead"] == 3
        assert data["by_entity_type"]["Consultation"] == seed_audit_logs["consultation_count"]
        assert data["by_action"]["created"] == 2
        assert data["by_action"]["updated"] == 1
        assert data["by_action"]["deleted"] == 1
        log.info("✅ Summary statistics retrieved successfully")

    @pytest.mark.asyncio
    async def test_get_summary_empty(
        self,
        client: AsyncClient,
        admin_token_headers: dict,
        setup_test_database,
    ):
        """Test getting summary when no audit logs exist."""
        log.info("--- Running: test_get_summary_empty ---")

        response = await client.get(
            AdminURLs.AUDIT_LOGS_SUMMARY,
            headers=admin_token_headers,
        )

        assert response.status_code == 200, f"Response: {response.text}"
        data = response.json()

        assert data["total"] == 0
        assert data["by_entity_type"] == {}
        assert data["by_action"] == {}
        log.info("✅ Empty summary returns correctly")


# ============================================================================
# AUTHORIZATION TESTS
# ============================================================================


class TestAuditLogsAuthorization:
    """Tests for authorization on audit logs endpoints."""

    @pytest.mark.asyncio
    async def test_list_audit_logs_unauthorized(
        self,
        client: AsyncClient,
    ):
        """Test that unauthenticated users cannot access audit logs."""
        log.info("--- Running: test_list_audit_logs_unauthorized ---")

        response = await client.get(AdminURLs.AUDIT_LOGS)

        assert response.status_code in [401, 403], f"Expected 401/403, got {response.status_code}"
        log.info("✅ Unauthorized access rejected as expected")

    @pytest.mark.asyncio
    async def test_get_entity_history_unauthorized(
        self,
        client: AsyncClient,
    ):
        """Test that unauthenticated users cannot get entity history."""
        log.info("--- Running: test_get_entity_history_unauthorized ---")

        response = await client.get(AdminURLs.AUDIT_LOGS_ENTITY("Lead", 1))

        assert response.status_code in [401, 403], f"Expected 401/403, got {response.status_code}"
        log.info("✅ Unauthorized access rejected as expected")

    @pytest.mark.asyncio
    async def test_get_summary_unauthorized(
        self,
        client: AsyncClient,
    ):
        """Test that unauthenticated users cannot get summary."""
        log.info("--- Running: test_get_summary_unauthorized ---")

        response = await client.get(AdminURLs.AUDIT_LOGS_SUMMARY)

        assert response.status_code in [401, 403], f"Expected 401/403, got {response.status_code}"
        log.info("✅ Unauthorized access rejected as expected")

    @pytest.mark.asyncio
    async def test_list_audit_logs_officer_forbidden(
        self,
        client: AsyncClient,
        officer_token_headers: dict,
        seed_audit_logs: dict,
    ):
        """Test that officers cannot access audit logs (admin/manager only)."""
        log.info("--- Running: test_list_audit_logs_officer_forbidden ---")

        response = await client.get(
            AdminURLs.AUDIT_LOGS,
            headers=officer_token_headers,
        )

        # Officer should be forbidden from admin endpoints
        assert response.status_code == 403, f"Expected 403, got {response.status_code}"
        log.info("✅ Officer access rejected as expected (admin/manager only)")

    @pytest.mark.asyncio
    async def test_list_audit_logs_manager_allowed(
        self,
        client: AsyncClient,
        manager_token_headers: dict,
        seed_audit_logs: dict,
    ):
        """Test that managers can access audit logs."""
        log.info("--- Running: test_list_audit_logs_manager_allowed ---")

        response = await client.get(
            AdminURLs.AUDIT_LOGS,
            headers=manager_token_headers,
        )

        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        log.info("✅ Manager access allowed as expected")


# ============================================================================
# TEST: Audit Log Entry Structure
# ============================================================================


class TestAuditLogEntryStructure:
    """Tests for audit log entry response structure."""

    @pytest.mark.asyncio
    async def test_entry_has_all_fields(
        self,
        client: AsyncClient,
        admin_token_headers: dict,
        seed_audit_logs: dict,
    ):
        """Test that audit log entries have all expected fields."""
        log.info("--- Running: test_entry_has_all_fields ---")

        response = await client.get(
            AdminURLs.AUDIT_LOGS,
            headers=admin_token_headers,
        )

        assert response.status_code == 200
        data = response.json()

        assert len(data["items"]) > 0
        entry = data["items"][0]

        # Required fields
        assert "id" in entry
        assert "entity_type" in entry
        assert "entity_id" in entry
        assert "action" in entry
        assert "created_at" in entry

        # Optional fields (can be None)
        assert "actor" in entry
        assert "field_name" in entry
        assert "old_value" in entry
        assert "new_value" in entry
        assert "changes" in entry
        assert "reason" in entry
        assert "source" in entry
        log.info("✅ Audit log entry has all expected fields")

    @pytest.mark.asyncio
    async def test_entry_with_changes_field(
        self,
        client: AsyncClient,
        admin_token_headers: dict,
        seed_audit_logs: dict,
    ):
        """Test that audit log entries with changes are formatted correctly."""
        log.info("--- Running: test_entry_with_changes_field ---")

        response = await client.get(
            AdminURLs.AUDIT_LOGS,
            params={"action": "updated"},
            headers=admin_token_headers,
        )

        assert response.status_code == 200
        data = response.json()

        assert len(data["items"]) > 0
        entry = data["items"][0]

        assert entry["action"] == "updated"
        assert entry["changes"] is not None
        assert "status" in entry["changes"]
        assert entry["changes"]["status"]["old"] == "new"
        assert entry["changes"]["status"]["new"] == "contacted"
        log.info("✅ Audit log entry with changes formatted correctly")
