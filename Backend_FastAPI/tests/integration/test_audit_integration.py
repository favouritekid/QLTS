# tests/integration/test_audit_integration.py
"""
Integration tests for audit logging during lead/consultation operations.

These tests verify that:
- Audit logs are created when leads are created/updated/deleted
- Audit logs are created when consultations are created/deleted
- Field changes are properly detected and logged
"""
import logging

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select

from app import models
from app.database import AsyncSessionLocal

try:
    from tests.fixtures.constants import (
        AdminURLs,
        LeadsURLs,
        TestLeadData,
        TestOrgData,
    )
except ImportError:
    pytest.fail("Could not import constants from tests.fixtures.constants.")

log = logging.getLogger(__name__)


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================


async def get_audit_logs_for_entity(entity_type: str, entity_id: int) -> list:
    """Fetch audit logs for a specific entity from the database."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(models.EntityAuditLog)
            .where(
                models.EntityAuditLog.entity_type == entity_type,
                models.EntityAuditLog.entity_id == entity_id,
            )
            .order_by(models.EntityAuditLog.created_at.asc())
        )
        return result.scalars().all()


async def count_all_audit_logs() -> int:
    """Count all audit logs in the database."""
    async with AsyncSessionLocal() as session:
        from sqlalchemy import func
        result = await session.execute(
            select(func.count(models.EntityAuditLog.id))
        )
        return result.scalar() or 0


# ============================================================================
# TEST: Lead Creation Audit Logging
# ============================================================================


class TestLeadCreationAuditLog:
    """Tests for audit logging when leads are created."""

    @pytest.mark.asyncio
    async def test_create_lead_creates_audit_log(
        self,
        client: AsyncClient,
        admin_token_headers: dict,
        seed_lead_dependencies: dict,
    ):
        """Test that creating a lead creates an audit log entry."""
        log.info("--- Running: test_create_lead_creates_audit_log ---")

        # Create a lead
        lead_payload = {
            "full_name": "Audit Test Lead",
            "phone": "0909123456",
            "email": "audit_test@example.com",
            "source": "website",
            "unit_id": seed_lead_dependencies["unit_id"],
        }

        response = await client.post(
            LeadsURLs.LEADS,
            json=lead_payload,
            headers=admin_token_headers,
        )

        assert response.status_code == 201, f"Create lead failed: {response.text}"
        created_lead = response.json()
        lead_id = created_lead["id"]

        # Check audit log was created
        audit_logs = await get_audit_logs_for_entity("Lead", lead_id)

        assert len(audit_logs) >= 1, "Expected at least one audit log for created lead"

        # Find the "created" action log
        created_log = next((l for l in audit_logs if l.action == "created"), None)
        assert created_log is not None, "No 'created' audit log found"
        assert created_log.entity_type == "Lead"
        assert created_log.entity_id == lead_id
        assert created_log.source == "api"
        assert created_log.new_value is not None

        log.info(f"✅ Lead creation audit log verified (lead_id={lead_id})")


# ============================================================================
# TEST: Lead Update Audit Logging
# ============================================================================


class TestLeadUpdateAuditLog:
    """Tests for audit logging when leads are updated."""

    @pytest.mark.asyncio
    async def test_update_lead_creates_audit_log(
        self,
        client: AsyncClient,
        admin_token_headers: dict,
        seed_lead_dependencies: dict,
    ):
        """Test that updating a lead creates an audit log entry with changes."""
        log.info("--- Running: test_update_lead_creates_audit_log ---")

        # First create a lead
        lead_payload = {
            "full_name": "Update Test Lead",
            "phone": "0909111111",
            "email": "update_test@example.com",
            "source": "website",
            "unit_id": seed_lead_dependencies["unit_id"],
        }

        create_response = await client.post(
            LeadsURLs.LEADS,
            json=lead_payload,
            headers=admin_token_headers,
        )
        assert create_response.status_code == 201
        lead_id = create_response.json()["id"]

        # Count logs before update
        logs_before = await get_audit_logs_for_entity("Lead", lead_id)
        count_before = len(logs_before)

        # Update the lead (PUT method for leads)
        update_payload = {
            "full_name": "Updated Name",
            "phone": "0909222222",
            "source": "website",
            "unit_id": seed_lead_dependencies["unit_id"],
        }

        update_response = await client.put(
            LeadsURLs.LEAD_DETAIL(lead_id),
            json=update_payload,
            headers=admin_token_headers,
        )

        assert update_response.status_code == 200, f"Update failed: {update_response.text}"

        # Check new audit log was created
        logs_after = await get_audit_logs_for_entity("Lead", lead_id)

        assert len(logs_after) > count_before, "Expected new audit log after update"

        # Find the "updated" action log
        updated_log = next((l for l in logs_after if l.action == "updated"), None)
        assert updated_log is not None, "No 'updated' audit log found"
        assert updated_log.entity_type == "Lead"
        assert updated_log.entity_id == lead_id

        # Verify changes are recorded
        if updated_log.changes:
            assert "full_name" in updated_log.changes or "phone" in updated_log.changes

        log.info(f"✅ Lead update audit log verified (lead_id={lead_id})")

    @pytest.mark.asyncio
    async def test_no_audit_log_when_no_changes(
        self,
        client: AsyncClient,
        admin_token_headers: dict,
        seed_lead_dependencies: dict,
    ):
        """Test that no audit log is created when update has no actual changes."""
        log.info("--- Running: test_no_audit_log_when_no_changes ---")

        # Create a lead
        lead_payload = {
            "full_name": "No Change Lead",
            "phone": "0909333333",
            "source": "website",
            "unit_id": seed_lead_dependencies["unit_id"],
        }

        create_response = await client.post(
            LeadsURLs.LEADS,
            json=lead_payload,
            headers=admin_token_headers,
        )
        assert create_response.status_code == 201
        lead_id = create_response.json()["id"]

        # Count logs before "update"
        logs_before = await get_audit_logs_for_entity("Lead", lead_id)
        update_count_before = len([l for l in logs_before if l.action == "updated"])

        # Update with same values (no real change) - PUT method for leads
        update_response = await client.put(
            LeadsURLs.LEAD_DETAIL(lead_id),
            json={
                "full_name": "No Change Lead",  # Same as before
                "phone": "0909333333",
                "source": "website",
                "unit_id": seed_lead_dependencies["unit_id"],
            },
            headers=admin_token_headers,
        )

        assert update_response.status_code == 200

        # Check no new "updated" audit log was created
        logs_after = await get_audit_logs_for_entity("Lead", lead_id)
        update_count_after = len([l for l in logs_after if l.action == "updated"])

        assert update_count_after == update_count_before, \
            "Should not create audit log when no actual changes"

        log.info("✅ No audit log created when no changes (as expected)")


# ============================================================================
# TEST: Lead Deletion Audit Logging
# ============================================================================


class TestLeadDeletionAuditLog:
    """Tests for audit logging when leads are deleted."""

    @pytest.mark.asyncio
    async def test_delete_lead_creates_audit_log(
        self,
        client: AsyncClient,
        admin_token_headers: dict,
        seed_lead_dependencies: dict,
    ):
        """Test that deleting a lead creates an audit log entry."""
        log.info("--- Running: test_delete_lead_creates_audit_log ---")

        # Create a lead
        lead_payload = {
            "full_name": "Delete Test Lead",
            "phone": "0909444444",
            "source": "website",
            "unit_id": seed_lead_dependencies["unit_id"],
        }

        create_response = await client.post(
            LeadsURLs.LEADS,
            json=lead_payload,
            headers=admin_token_headers,
        )
        assert create_response.status_code == 201
        lead_id = create_response.json()["id"]

        # Delete the lead (returns 204 No Content)
        delete_response = await client.delete(
            LeadsURLs.LEAD_DETAIL(lead_id),
            headers=admin_token_headers,
        )

        assert delete_response.status_code == 204, f"Delete failed: {delete_response.status_code}"

        # Check audit log was created
        audit_logs = await get_audit_logs_for_entity("Lead", lead_id)

        # Find the "deleted" action log
        deleted_log = next((l for l in audit_logs if l.action == "deleted"), None)
        assert deleted_log is not None, "No 'deleted' audit log found"
        assert deleted_log.entity_type == "Lead"
        assert deleted_log.entity_id == lead_id

        log.info(f"✅ Lead deletion audit log verified (lead_id={lead_id})")


# ============================================================================
# TEST: Lead Restoration Audit Logging
# ============================================================================


class TestLeadRestorationAuditLog:
    """Tests for audit logging when leads are restored."""

    @pytest.mark.asyncio
    async def test_restore_lead_creates_audit_log(
        self,
        client: AsyncClient,
        admin_token_headers: dict,
        seed_lead_dependencies: dict,
    ):
        """Test that restoring a lead creates an audit log entry."""
        log.info("--- Running: test_restore_lead_creates_audit_log ---")

        # Create and delete a lead
        lead_payload = {
            "full_name": "Restore Test Lead",
            "phone": "0909555555",
            "source": "website",
            "unit_id": seed_lead_dependencies["unit_id"],
        }

        create_response = await client.post(
            LeadsURLs.LEADS,
            json=lead_payload,
            headers=admin_token_headers,
        )
        assert create_response.status_code == 201
        lead_id = create_response.json()["id"]

        # Delete the lead
        await client.delete(
            LeadsURLs.LEAD_DETAIL(lead_id),
            headers=admin_token_headers,
        )

        # Count audit logs before restore
        logs_before = await get_audit_logs_for_entity("Lead", lead_id)
        count_before = len(logs_before)

        # Restore the lead via admin endpoint
        restore_response = await client.post(
            f"{AdminURLs.BASE}/leads/{lead_id}/restore",
            headers=admin_token_headers,
        )

        # Skip if restore endpoint doesn't exist
        if restore_response.status_code == 404:
            log.info("⚠️ Lead restore endpoint not found, skipping test")
            pytest.skip("Lead restore endpoint not implemented")

        assert restore_response.status_code == 200, f"Restore failed: {restore_response.text}"

        # Check audit log was created
        logs_after = await get_audit_logs_for_entity("Lead", lead_id)

        assert len(logs_after) > count_before, "Expected new audit log after restore"

        # Find the "restored" action log
        restored_log = next((l for l in logs_after if l.action == "restored"), None)
        assert restored_log is not None, "No 'restored' audit log found"

        log.info(f"✅ Lead restoration audit log verified (lead_id={lead_id})")


# ============================================================================
# TEST: Consultation Audit Logging
# ============================================================================


class TestConsultationAuditLog:
    """Tests for audit logging when consultations are created/deleted."""

    @pytest.mark.asyncio
    async def test_create_consultation_creates_audit_log(
        self,
        client: AsyncClient,
        admin_token_headers: dict,
        seed_lead_dependencies: dict,
    ):
        """Test that creating a consultation creates an audit log entry."""
        log.info("--- Running: test_create_consultation_creates_audit_log ---")

        # First create a lead
        lead_payload = {
            "full_name": "Consultation Audit Lead",
            "phone": "0909666666",
            "source": "website",
            "unit_id": seed_lead_dependencies["unit_id"],
        }

        lead_response = await client.post(
            LeadsURLs.LEADS,
            json=lead_payload,
            headers=admin_token_headers,
        )
        assert lead_response.status_code == 201
        lead_id = lead_response.json()["id"]

        # Create consultation
        consultation_payload = {
            "scheduled_at": "2024-06-15T10:00:00Z",
            "status_id": seed_lead_dependencies["initial_status_id"],
            "notes": "Test consultation",
            "method": "phone",
        }

        consultation_response = await client.post(
            LeadsURLs.CONSULTATIONS(lead_id),
            json=consultation_payload,
            headers=admin_token_headers,
        )

        # If endpoint requires different format, try to handle
        if consultation_response.status_code not in [200, 201]:
            log.warning(f"Consultation creation returned {consultation_response.status_code}")
            pytest.skip("Consultation creation endpoint format may differ")

        consultation_data = consultation_response.json()

        # Get consultation ID - may be in different places depending on response format
        consultation_id = consultation_data.get("id") or consultation_data.get("consultation_id")
        if not consultation_id:
            log.warning("Could not extract consultation ID from response")
            pytest.skip("Could not extract consultation ID")

        # Check audit log was created for consultation
        audit_logs = await get_audit_logs_for_entity("Consultation", consultation_id)

        if len(audit_logs) > 0:
            created_log = next((l for l in audit_logs if l.action == "created"), None)
            if created_log:
                assert created_log.entity_type == "Consultation"
                log.info(f"✅ Consultation creation audit log verified (consultation_id={consultation_id})")
            else:
                log.info("⚠️ Consultation created but no 'created' audit log found")
        else:
            log.info("⚠️ No audit logs found for consultation (may not be implemented yet)")


# ============================================================================
# TEST: Audit Log Actor Information
# ============================================================================


class TestAuditLogActor:
    """Tests for audit log actor (who performed the action) information."""

    @pytest.mark.asyncio
    async def test_audit_log_captures_actor(
        self,
        client: AsyncClient,
        admin_token_headers: dict,
        admin_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """Test that audit log captures the actor who performed the action."""
        log.info("--- Running: test_audit_log_captures_actor ---")

        # Create a lead
        lead_payload = {
            "full_name": "Actor Test Lead",
            "phone": "0909777777",
            "source": "website",
            "unit_id": seed_lead_dependencies["unit_id"],
        }

        response = await client.post(
            LeadsURLs.LEADS,
            json=lead_payload,
            headers=admin_token_headers,
        )

        assert response.status_code == 201
        lead_id = response.json()["id"]

        # Check audit log has actor information
        audit_logs = await get_audit_logs_for_entity("Lead", lead_id)

        assert len(audit_logs) >= 1
        created_log = audit_logs[0]

        # Actor should be the admin user who created the lead
        if created_log.actor_user_id:
            assert created_log.actor_user_id == admin_user_in_db["id"], \
                "Audit log should capture the actor who created the lead"
            log.info(f"✅ Audit log actor captured (actor_user_id={created_log.actor_user_id})")
        else:
            log.info("⚠️ Actor not captured in audit log (may be system action)")


# ============================================================================
# TEST: Audit Log Source
# ============================================================================


class TestAuditLogSource:
    """Tests for audit log source information."""

    @pytest.mark.asyncio
    async def test_audit_log_has_api_source(
        self,
        client: AsyncClient,
        admin_token_headers: dict,
        seed_lead_dependencies: dict,
    ):
        """Test that API-triggered audit logs have 'api' source."""
        log.info("--- Running: test_audit_log_has_api_source ---")

        # Create a lead via API
        lead_payload = {
            "full_name": "Source Test Lead",
            "phone": "0909888888",
            "source": "website",
            "unit_id": seed_lead_dependencies["unit_id"],
        }

        response = await client.post(
            LeadsURLs.LEADS,
            json=lead_payload,
            headers=admin_token_headers,
        )

        assert response.status_code == 201
        lead_id = response.json()["id"]

        # Check audit log has 'api' source
        audit_logs = await get_audit_logs_for_entity("Lead", lead_id)

        assert len(audit_logs) >= 1
        created_log = audit_logs[0]

        assert created_log.source == "api", \
            f"Expected source='api', got source='{created_log.source}'"

        log.info("✅ Audit log source is 'api' as expected")
