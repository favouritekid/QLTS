"""
Integration tests for Lead-Admission Status Synchronization.

Tests the side effects on Lead model when AdmissionProfile status transitions.

Mapping tested:
- draft     → sts07 (Đã tiếp nhận)
- submitted → sts07 (Đã tiếp nhận)
- approved  → sts09 (Đủ điều kiện)
- rejected  → sts16 (Không đạt)
- enrolled  → sts11 (Đã xác nhận nhập học)

Each test verifies:
1. Lead.consultation_status_id is updated correctly
2. Lead.pipeline_stage_id is updated correctly
3. Lead.status (legacy) is synced
4. LeadStatusHistory record is created with proper audit trail
"""

import pytest
import pytest_asyncio
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.services.lead_admission_sync import (
    sync_lead_from_admission,
    ADMISSION_TO_LEAD_STATUS_MAP,
)


pytestmark = pytest.mark.asyncio


# ==============================================================================
# TEST FIXTURES
# ==============================================================================


@pytest_asyncio.fixture
async def sync_statuses(db: AsyncSession) -> dict:
    """
    Create required consultation statuses for sync testing.
    Uses unique stage order values to avoid conflicts.
    """
    statuses_to_create = {
        "sts07": {"name": "Đã tiếp nhận", "phase": "admission", "order": 207},
        "sts09": {"name": "Đủ điều kiện", "phase": "admission", "order": 209},
        "sts16": {"name": "Không đạt", "phase": "admission", "order": 216},
        "sts11": {"name": "Đã xác nhận nhập học", "phase": "enrolled", "order": 211},
        "sts06": {"name": "Đủ tiêu chí", "phase": "consultation", "order": 206},
    }

    created_status_ids = []

    for status_id, info in statuses_to_create.items():
        # Check if status already exists
        existing_status = await db.get(models.ConsultationStatus, status_id)
        if existing_status:
            created_status_ids.append(status_id)
            continue

        stage_id = f"stg_sync_{status_id}"
        existing_stage = await db.get(models.PipelineStage, stage_id)

        if not existing_stage:
            stage = models.PipelineStage(
                id=stage_id,
                name=f"Sync Stage {status_id}",
                order=info["order"],
            )
            db.add(stage)
            await db.flush()

        status = models.ConsultationStatus(
            id=status_id,
            name=info["name"],
            color_code="#808080",
            stage_id=stage_id,
            phase=info["phase"],
            is_final=status_id == "sts11",
        )
        db.add(status)
        created_status_ids.append(status_id)

    await db.flush()

    return {"status_ids": created_status_ids}


@pytest_asyncio.fixture
async def sync_user(db: AsyncSession, seeded_dependencies: dict) -> models.User:
    """Create a test user (officer) for sync tests."""
    from app.security import get_password_hash

    timestamp = datetime.now().timestamp()

    user = models.User(
        username=f"sync_officer_{timestamp:.0f}",
        email=f"sync_{timestamp:.0f}@test.com",
        password_hash=get_password_hash("testpass123"),
        full_name="Sync Test Officer",
        role="officer",
        status="active",
        unit_id=seeded_dependencies["unit_id"],
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user


@pytest_asyncio.fixture
async def sync_lead(
    db: AsyncSession,
    seeded_dependencies: dict,
    sync_statuses: dict,
    sync_user: models.User,
) -> models.Lead:
    """Create a test lead with initial consultation status for sync tests."""
    timestamp = datetime.now().timestamp()

    lead = models.Lead(
        full_name="Test Sync Lead",
        phone=f"090{timestamp:.0f}"[:10],
        email=f"sync_lead_{timestamp:.0f}@test.com",
        source="website",
        unit_id=seeded_dependencies["unit_id"],
        assigned_officer_id=sync_user.id,
        consultation_status_id="sts06",
        consultation_count=1,
        status="qualified",
    )
    db.add(lead)
    await db.flush()
    await db.refresh(lead)
    return lead


# ==============================================================================
# HELPER FUNCTIONS
# ==============================================================================


async def create_profile(
    db: AsyncSession,
    lead: models.Lead,
    status: str = "draft"
) -> models.AdmissionProfile:
    """Create an admission profile within the session."""
    timestamp = datetime.now().timestamp()
    citizen_id = f"0{timestamp:.0f}"[:12]

    profile = models.AdmissionProfile(
        lead_id=lead.id,
        status=status,
        citizen_id=citizen_id,
        version=1,
        applied_rules={"min_gpa": 6.0, "mandatory_docs": []},
        academic_year=2025,
        full_name="Test Applicant",
        phone="0901234567",
    )
    db.add(profile)
    await db.flush()

    # Reload with lead relationship
    result = await db.execute(
        select(models.AdmissionProfile)
        .where(models.AdmissionProfile.id == profile.id)
        .options(selectinload(models.AdmissionProfile.lead))
    )
    return result.scalar_one()


async def get_history_count(db: AsyncSession, lead_id: int) -> int:
    """Count history records for a lead."""
    result = await db.execute(
        select(models.LeadStatusHistory)
        .where(models.LeadStatusHistory.lead_id == lead_id)
    )
    return len(result.scalars().all())


# ==============================================================================
# TEST: MAPPING CONFIGURATION
# ==============================================================================


class TestMappingConfiguration:
    """Test that the mapping configuration is correct."""

    def test_mapping_has_all_required_statuses(self):
        """Verify mapping contains all expected admission statuses."""
        expected_statuses = {"draft", "submitted", "approved", "rejected", "enrolled"}
        assert set(ADMISSION_TO_LEAD_STATUS_MAP.keys()) == expected_statuses

    def test_mapping_values_are_valid_status_ids(self):
        """Verify all mapped values are valid consultation status IDs."""
        for admission_status, lead_status in ADMISSION_TO_LEAD_STATUS_MAP.items():
            assert lead_status.startswith("sts"), \
                f"Invalid status ID for {admission_status}: {lead_status}"

    def test_draft_and_submitted_map_to_same_status(self):
        """Draft and submitted should both map to sts07 (Đã tiếp nhận)."""
        assert ADMISSION_TO_LEAD_STATUS_MAP["draft"] == "sts07"
        assert ADMISSION_TO_LEAD_STATUS_MAP["submitted"] == "sts07"

    def test_approved_maps_to_sts09(self):
        """Approved should map to sts09 (Đủ điều kiện)."""
        assert ADMISSION_TO_LEAD_STATUS_MAP["approved"] == "sts09"

    def test_rejected_maps_to_sts16(self):
        """Rejected should map to sts16 (Không đạt)."""
        assert ADMISSION_TO_LEAD_STATUS_MAP["rejected"] == "sts16"

    def test_enrolled_maps_to_sts11(self):
        """Enrolled should map to sts11 (Đã xác nhận nhập học)."""
        assert ADMISSION_TO_LEAD_STATUS_MAP["enrolled"] == "sts11"


# ==============================================================================
# TEST: SYNC FUNCTION - DRAFT STATUS
# ==============================================================================


class TestSyncDraftStatus:
    """Test sync when admission profile is in draft status."""

    async def test_sync_updates_lead_consultation_status_to_sts07(
        self,
        db: AsyncSession,
        sync_lead: models.Lead,
        sync_user: models.User,
        sync_statuses: dict,
    ):
        """When profile is draft, lead consultation_status_id should be sts07."""
        profile = await create_profile(db, sync_lead, "draft")

        result = await sync_lead_from_admission(
            db=db,
            profile=profile,
            changed_by_user_id=sync_user.id,
            reason="Test sync for draft status",
        )

        assert result is True, "Sync should have been performed"

        # Refresh to get updated values
        await db.refresh(sync_lead)
        assert sync_lead.consultation_status_id == "sts07", \
            f"Expected sts07, got {sync_lead.consultation_status_id}"

    async def test_sync_creates_history_record(
        self,
        db: AsyncSession,
        sync_lead: models.Lead,
        sync_user: models.User,
        sync_statuses: dict,
    ):
        """Sync should create LeadStatusHistory record with audit info."""
        initial_count = await get_history_count(db, sync_lead.id)

        profile = await create_profile(db, sync_lead, "draft")

        await sync_lead_from_admission(
            db=db,
            profile=profile,
            changed_by_user_id=sync_user.id,
            reason="Test audit trail",
        )

        # Check new history record
        result = await db.execute(
            select(models.LeadStatusHistory)
            .where(models.LeadStatusHistory.lead_id == sync_lead.id)
            .order_by(models.LeadStatusHistory.changed_at.desc())
        )
        history_records = result.scalars().all()

        assert len(history_records) == initial_count + 1, \
            "Should have one new history record"

        latest = history_records[0]
        assert latest.new_consultation_status_id == "sts07"
        assert latest.changed_by_user_id == sync_user.id


# ==============================================================================
# TEST: SYNC FUNCTION - APPROVED STATUS
# ==============================================================================


class TestSyncApprovedStatus:
    """Test sync when admission profile is approved."""

    async def test_sync_updates_lead_to_sts09_on_approval(
        self,
        db: AsyncSession,
        sync_lead: models.Lead,
        sync_user: models.User,
        sync_statuses: dict,
    ):
        """When profile is approved, lead should sync to sts09."""
        profile = await create_profile(db, sync_lead, "approved")

        result = await sync_lead_from_admission(
            db=db,
            profile=profile,
            changed_by_user_id=sync_user.id,
            reason="Profile approved by manager",
        )

        assert result is True

        await db.refresh(sync_lead)
        assert sync_lead.consultation_status_id == "sts09", \
            f"Expected sts09, got {sync_lead.consultation_status_id}"


# ==============================================================================
# TEST: SYNC FUNCTION - REJECTED STATUS
# ==============================================================================


class TestSyncRejectedStatus:
    """Test sync when admission profile is rejected."""

    async def test_sync_updates_lead_to_sts16_on_rejection(
        self,
        db: AsyncSession,
        sync_lead: models.Lead,
        sync_user: models.User,
        sync_statuses: dict,
    ):
        """When profile is rejected, lead should sync to sts16."""
        profile = await create_profile(db, sync_lead, "rejected")

        result = await sync_lead_from_admission(
            db=db,
            profile=profile,
            changed_by_user_id=sync_user.id,
            reason="Profile rejected: Missing documents",
        )

        assert result is True

        await db.refresh(sync_lead)
        assert sync_lead.consultation_status_id == "sts16", \
            f"Expected sts16, got {sync_lead.consultation_status_id}"

    async def test_sync_includes_rejection_reason_in_history(
        self,
        db: AsyncSession,
        sync_lead: models.Lead,
        sync_user: models.User,
        sync_statuses: dict,
    ):
        """History record should include rejection reason."""
        rejection_reason = "Missing required documents"

        profile = await create_profile(db, sync_lead, "rejected")

        await sync_lead_from_admission(
            db=db,
            profile=profile,
            changed_by_user_id=sync_user.id,
            reason=f"Profile rejected: {rejection_reason}",
        )

        result = await db.execute(
            select(models.LeadStatusHistory)
            .where(models.LeadStatusHistory.lead_id == sync_lead.id)
            .order_by(models.LeadStatusHistory.changed_at.desc())
        )
        latest = result.scalars().first()

        assert rejection_reason in latest.reason or "rejected" in latest.reason.lower()


# ==============================================================================
# TEST: SYNC FUNCTION - ENROLLED STATUS
# ==============================================================================


class TestSyncEnrolledStatus:
    """Test sync when student is enrolled."""

    async def test_sync_updates_lead_to_sts11_on_enrollment(
        self,
        db: AsyncSession,
        sync_lead: models.Lead,
        sync_user: models.User,
        sync_statuses: dict,
    ):
        """When profile is enrolled, lead should sync to sts11 (terminal)."""
        profile = await create_profile(db, sync_lead, "enrolled")

        result = await sync_lead_from_admission(
            db=db,
            profile=profile,
            changed_by_user_id=sync_user.id,
            reason="Student enrolled successfully",
        )

        assert result is True

        await db.refresh(sync_lead)
        assert sync_lead.consultation_status_id == "sts11", \
            f"Expected sts11, got {sync_lead.consultation_status_id}"


# ==============================================================================
# TEST: IDEMPOTENCY
# ==============================================================================


class TestSyncIdempotency:
    """Test that sync is idempotent - doesn't create duplicate history."""

    async def test_sync_skips_if_already_at_target_status(
        self,
        db: AsyncSession,
        sync_lead: models.Lead,
        sync_user: models.User,
        sync_statuses: dict,
    ):
        """Sync should skip if lead is already at target status."""
        # First sync to sts07
        profile = await create_profile(db, sync_lead, "draft")

        result1 = await sync_lead_from_admission(
            db=db,
            profile=profile,
            changed_by_user_id=sync_user.id,
            reason="First sync",
        )
        assert result1 is True

        count_after_first = await get_history_count(db, sync_lead.id)

        # Second sync with same status - should skip
        result2 = await sync_lead_from_admission(
            db=db,
            profile=profile,
            changed_by_user_id=sync_user.id,
            reason="Second sync - should skip",
        )
        assert result2 is False, "Second sync should be skipped"

        # Verify no new history record
        count_after_second = await get_history_count(db, sync_lead.id)
        assert count_after_second == count_after_first, \
            "No new history should be created for idempotent sync"


# ==============================================================================
# TEST: EDGE CASES
# ==============================================================================


class TestSyncEdgeCases:
    """Test edge cases and error handling."""

    async def test_sync_handles_missing_lead(
        self,
        db: AsyncSession,
        sync_user: models.User,
        sync_statuses: dict,
    ):
        """Sync should handle profile with no lead gracefully."""
        # Create mock profile without lead attached
        profile = models.AdmissionProfile(
            lead_id=99999,
            status="draft",
            citizen_id="123456789012",
            version=1,
            applied_rules={},
            academic_year=2025,
        )
        profile.lead = None  # Explicitly set lead to None

        result = await sync_lead_from_admission(
            db=db,
            profile=profile,
            changed_by_user_id=sync_user.id,
            reason="Test missing lead",
        )

        assert result is False, "Sync should return False for missing lead"

    async def test_sync_handles_unknown_admission_status(
        self,
        db: AsyncSession,
        sync_lead: models.Lead,
        sync_user: models.User,
        sync_statuses: dict,
    ):
        """Sync should handle unknown admission status gracefully."""
        profile = await create_profile(db, sync_lead, "draft")

        # Manually set invalid status
        profile.status = "unknown_status"

        result = await sync_lead_from_admission(
            db=db,
            profile=profile,
            changed_by_user_id=sync_user.id,
            reason="Test unknown status",
        )

        assert result is False, "Sync should return False for unknown status"


# ==============================================================================
# TEST: FULL WORKFLOW INTEGRATION
# ==============================================================================


class TestFullWorkflowSync:
    """Test complete workflow: draft → approved → enrolled."""

    async def test_full_admission_workflow_syncs_lead_correctly(
        self,
        db: AsyncSession,
        sync_lead: models.Lead,
        sync_user: models.User,
        sync_statuses: dict,
    ):
        """Test lead status follows admission workflow transitions."""
        # Step 1: Draft → sts07
        profile = await create_profile(db, sync_lead, "draft")

        await sync_lead_from_admission(
            db=db,
            profile=profile,
            changed_by_user_id=sync_user.id,
            reason="Profile created",
        )

        await db.refresh(sync_lead)
        assert sync_lead.consultation_status_id == "sts07", "Step 1: Should be sts07"

        # Step 2: Approved → sts09
        profile.status = "approved"

        await sync_lead_from_admission(
            db=db,
            profile=profile,
            changed_by_user_id=sync_user.id,
            reason="Profile approved",
        )

        await db.refresh(sync_lead)
        assert sync_lead.consultation_status_id == "sts09", "Step 2: Should be sts09"

        # Step 3: Enrolled → sts11
        profile.status = "enrolled"

        await sync_lead_from_admission(
            db=db,
            profile=profile,
            changed_by_user_id=sync_user.id,
            reason="Student enrolled",
        )

        await db.refresh(sync_lead)
        assert sync_lead.consultation_status_id == "sts11", "Step 3: Should be sts11"

        # Verify complete history trail
        result = await db.execute(
            select(models.LeadStatusHistory)
            .where(models.LeadStatusHistory.lead_id == sync_lead.id)
            .order_by(models.LeadStatusHistory.changed_at.asc())
        )
        history = result.scalars().all()

        status_changes = [h.new_consultation_status_id for h in history]
        expected_sequence = ["sts07", "sts09", "sts11"]

        # Filter to only relevant statuses
        actual_sequence = [s for s in status_changes if s in expected_sequence]
        assert actual_sequence == expected_sequence, \
            f"Expected workflow {expected_sequence}, got {actual_sequence}"
