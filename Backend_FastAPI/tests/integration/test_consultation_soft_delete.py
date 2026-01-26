"""
Integration tests for Consultation Soft Delete.

Verifies that:
1. delete_consultation() uses soft delete (sets deleted_at) instead of hard delete
2. Soft-deleted consultations are excluded from queries
3. Cannot delete an already soft-deleted consultation
"""

import pytest
import pytest_asyncio
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.services import lead_service


pytestmark = pytest.mark.asyncio


# ==============================================================================
# TEST FIXTURES
# ==============================================================================


@pytest_asyncio.fixture
async def soft_delete_user(db: AsyncSession, seeded_dependencies: dict) -> models.User:
    """Create a test admin user for soft delete tests."""
    from app.security import get_password_hash

    timestamp = datetime.now().timestamp()

    user = models.User(
        username=f"soft_delete_admin_{timestamp:.0f}",
        email=f"soft_delete_{timestamp:.0f}@test.com",
        password_hash=get_password_hash("testpass123"),
        full_name="Soft Delete Test Admin",
        role="admin",
        status="active",
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user


@pytest_asyncio.fixture
async def soft_delete_lead(
    db: AsyncSession,
    seeded_dependencies: dict,
    soft_delete_user: models.User,
) -> models.Lead:
    """Create a test lead for soft delete tests."""
    timestamp = datetime.now().timestamp()

    lead = models.Lead(
        full_name="Soft Delete Test Lead",
        phone=f"090{timestamp:.0f}"[:10],
        email=f"soft_delete_lead_{timestamp:.0f}@test.com",
        source="website",
        unit_id=seeded_dependencies["unit_id"],
        assigned_officer_id=soft_delete_user.id,
        consultation_status_id=seeded_dependencies["initial_status_id"],
        consultation_count=0,
        status="new",
    )
    db.add(lead)
    await db.flush()
    await db.refresh(lead)
    return lead


@pytest_asyncio.fixture
async def test_consultation(
    db: AsyncSession,
    soft_delete_lead: models.Lead,
    soft_delete_user: models.User,
    seeded_dependencies: dict,
) -> models.Consultation:
    """Create a test consultation directly (bypassing FSM validation)."""
    consultation = models.Consultation(
        lead_id=soft_delete_lead.id,
        officer_id=soft_delete_user.id,
        consultation_date=datetime.now(timezone.utc),
        method="phone",
        notes="Test consultation for soft delete",
        consultation_status_id=seeded_dependencies["initial_status_id"],
    )
    db.add(consultation)
    await db.flush()
    await db.refresh(consultation)

    # Update lead consultation count
    soft_delete_lead.consultation_count = 1
    await db.flush()

    return consultation


# ==============================================================================
# TEST: SOFT DELETE BEHAVIOR
# ==============================================================================


class TestConsultationSoftDelete:
    """Test that consultation deletion uses soft delete."""

    async def test_delete_sets_deleted_at_instead_of_removing(
        self,
        db: AsyncSession,
        soft_delete_lead: models.Lead,
        soft_delete_user: models.User,
        test_consultation: models.Consultation,
    ):
        """Deleting a consultation should set deleted_at, not remove from DB."""
        consultation_id = test_consultation.id

        # Act - delete the consultation
        await lead_service.delete_consultation(
            db=db,
            lead_id=soft_delete_lead.id,
            consultation_id=consultation_id,
            current_user=soft_delete_user,
        )
        await db.commit()

        # Assert - consultation still exists in DB with deleted_at set
        result = await db.execute(
            select(models.Consultation)
            .where(models.Consultation.id == consultation_id)
        )
        deleted_consultation = result.scalar_one_or_none()

        assert deleted_consultation is not None, "Consultation should still exist in DB"
        assert deleted_consultation.deleted_at is not None, "deleted_at should be set"
        assert deleted_consultation.deleted_at <= datetime.now(timezone.utc)

    async def test_soft_deleted_consultation_excluded_from_latest_query(
        self,
        db: AsyncSession,
        soft_delete_lead: models.Lead,
        soft_delete_user: models.User,
        test_consultation: models.Consultation,
    ):
        """Soft-deleted consultation should not appear in latest consultation query."""
        from app.repositories import LeadRepository

        repo = LeadRepository(db)

        # Verify consultation is found before delete
        latest_before = await repo.get_latest_consultation(soft_delete_lead.id)
        assert latest_before is not None
        assert latest_before.id == test_consultation.id

        # Soft delete the consultation
        await lead_service.delete_consultation(
            db=db,
            lead_id=soft_delete_lead.id,
            consultation_id=test_consultation.id,
            current_user=soft_delete_user,
        )
        await db.commit()

        # Verify consultation is NOT found after delete
        latest_after = await repo.get_latest_consultation(soft_delete_lead.id)
        assert latest_after is None, "Soft-deleted consultation should not be returned"

    async def test_cannot_delete_already_deleted_consultation(
        self,
        db: AsyncSession,
        soft_delete_lead: models.Lead,
        soft_delete_user: models.User,
        test_consultation: models.Consultation,
    ):
        """Attempting to delete an already soft-deleted consultation should fail."""
        from app.utils.exceptions import ResourceNotFoundError

        # First delete
        await lead_service.delete_consultation(
            db=db,
            lead_id=soft_delete_lead.id,
            consultation_id=test_consultation.id,
            current_user=soft_delete_user,
        )
        await db.commit()

        # Second delete should fail
        with pytest.raises(ResourceNotFoundError) as exc_info:
            await lead_service.delete_consultation(
                db=db,
                lead_id=soft_delete_lead.id,
                consultation_id=test_consultation.id,
                current_user=soft_delete_user,
            )

        assert "not found or already deleted" in str(exc_info.value.detail)


# ==============================================================================
# TEST: TIMELINE EXCLUDES SOFT-DELETED
# ==============================================================================


class TestTimelineExcludesSoftDeleted:
    """Test that timeline excludes soft-deleted consultations."""

    async def test_timeline_excludes_soft_deleted_consultations(
        self,
        db: AsyncSession,
        soft_delete_lead: models.Lead,
        soft_delete_user: models.User,
        test_consultation: models.Consultation,
    ):
        """Soft-deleted consultations should not appear in lead timeline."""
        # Get timeline before delete
        timeline_before = await lead_service.get_lead_timeline(
            db=db,
            lead_id=soft_delete_lead.id,
        )

        consultation_items_before = [
            item for item in timeline_before
            if item.get("type") == "consultation"
        ]
        assert len(consultation_items_before) == 1, "Should have 1 consultation before delete"

        # Soft delete the consultation
        await lead_service.delete_consultation(
            db=db,
            lead_id=soft_delete_lead.id,
            consultation_id=test_consultation.id,
            current_user=soft_delete_user,
        )
        await db.commit()

        # Refresh lead to get updated consultations
        await db.refresh(soft_delete_lead, ["consultations"])

        # Get timeline after delete
        timeline_after = await lead_service.get_lead_timeline(
            db=db,
            lead_id=soft_delete_lead.id,
        )

        consultation_items_after = [
            item for item in timeline_after
            if item.get("type") == "consultation"
        ]
        assert len(consultation_items_after) == 0, "Should have 0 consultations after delete"
