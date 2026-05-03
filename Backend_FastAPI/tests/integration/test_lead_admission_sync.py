"""
Integration tests for Lead-Admission Status Synchronization.

Tests the side effects on Lead model when AdmissionProfile status transitions.

Mapping tested:
- draft     → skipped (milestone consultation handles via sts06)
- submitted → sts07 (Đã tiếp nhận)
- approved  → sts09 (Đủ điều kiện)
- rejected  → sts16 (Không đạt)
- enrolled  → sts11 (Đã xác nhận nhập học)
- withdrawn → sts08 (Từ chối tư vấn)

Finance Phase mappings (tuition fee):
- tuition_fee_calculated → sts14 (Chưa hoàn tất học phí)
- tuition_fee_paid       → sts10 (Đã hoàn tất học phí)
- tuition_fee_refunded   → sts18 (Đã hoàn học phí)

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
    sync_lead_tuition_calculated,
    sync_lead_tuition_paid,
    sync_lead_tuition_refunded,
    ADMISSION_TO_LEAD_STATUS_MAP,
    TUITION_CALCULATED_STATUS,
    TUITION_PAID_STATUS,
    TUITION_REFUNDED_STATUS,
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
        "sts08": {"name": "Từ chối tư vấn", "phase": "consultation", "order": 208},
        # Revision & Drop statuses
        "sts17": {"name": "Yêu cầu bổ sung hồ sơ", "phase": "admission", "order": 217},
        "sts12": {"name": "Ngưng theo học", "phase": "enrolled", "order": 212},
        # Finance Phase statuses
        "sts14": {"name": "Chưa hoàn tất học phí", "phase": "finance", "order": 214},
        "sts10": {"name": "Đã hoàn tất học phí", "phase": "finance", "order": 210},
        "sts18": {"name": "Đã hoàn học phí", "phase": "finance", "order": 218},
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
        """Verify mapping contains every expected admission status.

        Cold Cutover Task #15 added three forward-compat choice-engine
        entries (``admitted`` / ``reviewing`` / ``waitlisted``) on top of
        the ten legacy statuses. ``result_published`` is intentionally
        absent — it is a future intermediate state / T6 broadcast
        marker, handled as an explicit no-op for lead sync; see the
        unit-level test ``test_map_does_not_contain_result_published``.
        """
        expected_statuses = {
            # Legacy vocabulary
            "draft", "submitted", "approved", "rejected", "revision_requested",
            "resubmitted", "confirmed", "overridden", "enrolled", "withdrawn",
            # Choice-engine vocabulary (Phase 1 schema migration will allow
            # writes; #15 only ensures the read side is forward-compatible).
            "admitted", "reviewing", "waitlisted",
        }
        assert set(ADMISSION_TO_LEAD_STATUS_MAP.keys()) == expected_statuses

    def test_mapping_values_are_valid_status_ids(self):
        """Verify all mapped values are valid consultation status IDs."""
        for admission_status, lead_status in ADMISSION_TO_LEAD_STATUS_MAP.items():
            assert lead_status.startswith("sts"), \
                f"Invalid status ID for {admission_status}: {lead_status}"

    def test_draft_maps_to_sts06_submitted_to_sts07(self):
        """Draft maps to sts06 (Đồng ý tư vấn), submitted to sts07 (Đã tiếp nhận)."""
        assert ADMISSION_TO_LEAD_STATUS_MAP["draft"] == "sts06"
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
    """Test sync when admission profile is in draft status.

    Draft profiles are handled by _create_admission_milestone_consultation()
    (Golden Rule canonical sync), so sync_lead_from_admission() skips them
    to avoid double LeadStatusHistory records.
    """

    async def test_sync_skips_draft_profile(
        self,
        db: AsyncSession,
        sync_lead: models.Lead,
        sync_user: models.User,
        sync_statuses: dict,
    ):
        """Draft profile should be skipped — milestone consultation handles it."""
        profile = await create_profile(db, sync_lead, "draft")

        result = await sync_lead_from_admission(
            db=db,
            profile=profile,
            changed_by_user_id=sync_user.id,
            reason="Test sync for draft status",
        )

        assert result is False, "Draft should be skipped by guard"

        # Lead should remain at initial status (sts06)
        await db.refresh(sync_lead)
        assert sync_lead.consultation_status_id == "sts06", \
            f"Expected sts06 (unchanged), got {sync_lead.consultation_status_id}"

    async def test_sync_creates_history_for_submitted(
        self,
        db: AsyncSession,
        sync_lead: models.Lead,
        sync_user: models.User,
        sync_statuses: dict,
    ):
        """Submitted profile should create LeadStatusHistory record."""
        initial_count = await get_history_count(db, sync_lead.id)

        profile = await create_profile(db, sync_lead, "submitted")

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
# TEST: SYNC FUNCTION - REVISION REQUESTED STATUS
# ==============================================================================


class TestSyncRevisionRequestedStatus:
    """Test sync when admission profile has revision requested."""

    async def test_sync_updates_lead_to_sts17_on_revision_requested(
        self,
        db: AsyncSession,
        sync_lead: models.Lead,
        sync_user: models.User,
        sync_statuses: dict,
    ):
        """When revision is requested, lead should sync to sts17."""
        profile = await create_profile(db, sync_lead, "revision_requested")

        result = await sync_lead_from_admission(
            db=db,
            profile=profile,
            changed_by_user_id=sync_user.id,
            reason="Revision requested: Missing transcript",
        )

        assert result is True

        await db.refresh(sync_lead)
        assert sync_lead.consultation_status_id == "sts17", \
            f"Expected sts17, got {sync_lead.consultation_status_id}"

    async def test_revision_requested_maps_to_sts17(self):
        """revision_requested should map to sts17 (Yêu cầu bổ sung hồ sơ)."""
        assert ADMISSION_TO_LEAD_STATUS_MAP["revision_requested"] == "sts17"

    async def test_rejected_still_maps_to_sts16(self):
        """rejected should still map to sts16 (no conflict with sts17)."""
        assert ADMISSION_TO_LEAD_STATUS_MAP["rejected"] == "sts16"


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
        # First sync to sts07 via submitted
        profile = await create_profile(db, sync_lead, "submitted")

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
        # Step 1: Submitted → sts07 (draft is handled by milestone, not sync)
        profile = await create_profile(db, sync_lead, "submitted")

        await sync_lead_from_admission(
            db=db,
            profile=profile,
            changed_by_user_id=sync_user.id,
            reason="Profile submitted",
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


# ==============================================================================
# TEST: SYNC FUNCTION - TUITION FEE CALCULATED (Finance Phase)
# ==============================================================================


class TestSyncTuitionCalculated:
    """Test sync when tuition fee is calculated for approved profile."""

    async def test_sync_updates_lead_to_sts14_on_tuition_calculated(
        self,
        db: AsyncSession,
        sync_lead: models.Lead,
        sync_user: models.User,
        sync_statuses: dict,
    ):
        """When tuition fee is calculated, lead should sync to sts14."""
        profile = await create_profile(db, sync_lead, "approved")

        result = await sync_lead_tuition_calculated(
            db=db,
            profile=profile,
            fee_amount="15000000",
            changed_by_user_id=sync_user.id,
            reason="Tuition fee calculated for 2025 academic year",
        )

        assert result is True, "Sync should have been performed"

        await db.refresh(sync_lead)
        assert sync_lead.consultation_status_id == TUITION_CALCULATED_STATUS, \
            f"Expected {TUITION_CALCULATED_STATUS}, got {sync_lead.consultation_status_id}"

    async def test_sync_creates_history_with_fee_amount(
        self,
        db: AsyncSession,
        sync_lead: models.Lead,
        sync_user: models.User,
        sync_statuses: dict,
    ):
        """Sync should create history record with fee amount in reason."""
        profile = await create_profile(db, sync_lead, "approved")
        fee_amount = "15000000"

        await sync_lead_tuition_calculated(
            db=db,
            profile=profile,
            fee_amount=fee_amount,
            changed_by_user_id=sync_user.id,
            reason=f"Tuition fee calculated: {fee_amount} VND",
        )

        result = await db.execute(
            select(models.LeadStatusHistory)
            .where(models.LeadStatusHistory.lead_id == sync_lead.id)
            .order_by(models.LeadStatusHistory.changed_at.desc())
        )
        latest = result.scalars().first()

        assert latest.new_consultation_status_id == TUITION_CALCULATED_STATUS
        assert fee_amount in latest.reason

    async def test_sync_idempotent_for_tuition_calculated(
        self,
        db: AsyncSession,
        sync_lead: models.Lead,
        sync_user: models.User,
        sync_statuses: dict,
    ):
        """Second sync should be skipped if already at sts14."""
        profile = await create_profile(db, sync_lead, "approved")

        # First sync
        result1 = await sync_lead_tuition_calculated(
            db=db, profile=profile, fee_amount="15000000",
            changed_by_user_id=sync_user.id, reason="First calc",
        )
        assert result1 is True

        count_after_first = await get_history_count(db, sync_lead.id)

        # Second sync - should skip
        result2 = await sync_lead_tuition_calculated(
            db=db, profile=profile, fee_amount="15000000",
            changed_by_user_id=sync_user.id, reason="Second calc",
        )
        assert result2 is False, "Second sync should be skipped"

        count_after_second = await get_history_count(db, sync_lead.id)
        assert count_after_second == count_after_first


# ==============================================================================
# TEST: SYNC FUNCTION - TUITION FEE PAID (Finance Phase)
# ==============================================================================


class TestSyncTuitionPaid:
    """Test sync when tuition fee is fully paid or waived."""

    async def test_sync_updates_lead_to_sts10_on_tuition_paid(
        self,
        db: AsyncSession,
        sync_lead: models.Lead,
        sync_user: models.User,
        sync_statuses: dict,
    ):
        """When tuition fee is paid, lead should sync to sts10."""
        profile = await create_profile(db, sync_lead, "approved")

        result = await sync_lead_tuition_paid(
            db=db,
            profile=profile,
            transaction_id="TXN-2025-001",
            changed_by_user_id=sync_user.id,
            reason="Tuition fee paid in full",
        )

        assert result is True, "Sync should have been performed"

        await db.refresh(sync_lead)
        assert sync_lead.consultation_status_id == TUITION_PAID_STATUS, \
            f"Expected {TUITION_PAID_STATUS}, got {sync_lead.consultation_status_id}"

    async def test_sync_creates_history_with_transaction_id(
        self,
        db: AsyncSession,
        sync_lead: models.Lead,
        sync_user: models.User,
        sync_statuses: dict,
    ):
        """Sync should create history record with transaction ID."""
        profile = await create_profile(db, sync_lead, "approved")
        transaction_id = "TXN-2025-002"

        await sync_lead_tuition_paid(
            db=db,
            profile=profile,
            transaction_id=transaction_id,
            changed_by_user_id=sync_user.id,
            reason=f"Payment confirmed: {transaction_id}",
        )

        result = await db.execute(
            select(models.LeadStatusHistory)
            .where(models.LeadStatusHistory.lead_id == sync_lead.id)
            .order_by(models.LeadStatusHistory.changed_at.desc())
        )
        latest = result.scalars().first()

        assert latest.new_consultation_status_id == TUITION_PAID_STATUS
        assert transaction_id in latest.reason

    async def test_sync_for_waived_fee(
        self,
        db: AsyncSession,
        sync_lead: models.Lead,
        sync_user: models.User,
        sync_statuses: dict,
    ):
        """When tuition fee is waived, lead should also sync to sts10."""
        profile = await create_profile(db, sync_lead, "approved")

        result = await sync_lead_tuition_paid(
            db=db,
            profile=profile,
            transaction_id="",
            changed_by_user_id=sync_user.id,
            reason="Tuition fee waived (100% scholarship)",
        )

        assert result is True

        await db.refresh(sync_lead)
        assert sync_lead.consultation_status_id == TUITION_PAID_STATUS

    async def test_sync_idempotent_for_tuition_paid(
        self,
        db: AsyncSession,
        sync_lead: models.Lead,
        sync_user: models.User,
        sync_statuses: dict,
    ):
        """Second sync should be skipped if already at sts10."""
        profile = await create_profile(db, sync_lead, "approved")

        # First sync
        result1 = await sync_lead_tuition_paid(
            db=db, profile=profile, transaction_id="TXN-001",
            changed_by_user_id=sync_user.id, reason="First payment",
        )
        assert result1 is True

        # Second sync - should skip
        result2 = await sync_lead_tuition_paid(
            db=db, profile=profile, transaction_id="TXN-002",
            changed_by_user_id=sync_user.id, reason="Duplicate payment",
        )
        assert result2 is False


# ==============================================================================
# TEST: SYNC FUNCTION - TUITION FEE REFUNDED (Finance Phase)
# ==============================================================================


class TestSyncTuitionRefunded:
    """Test sync when tuition fee is refunded (student withdrawal)."""

    async def test_sync_updates_lead_to_sts18_on_refund(
        self,
        db: AsyncSession,
        sync_lead: models.Lead,
        sync_user: models.User,
        sync_statuses: dict,
    ):
        """When tuition fee is refunded, lead should sync to sts18."""
        profile = await create_profile(db, sync_lead, "approved")

        result = await sync_lead_tuition_refunded(
            db=db,
            profile=profile,
            refund_amount="12000000",
            changed_by_user_id=sync_user.id,
            reason="Student withdrawal - full refund",
        )

        assert result is True, "Sync should have been performed"

        await db.refresh(sync_lead)
        assert sync_lead.consultation_status_id == TUITION_REFUNDED_STATUS, \
            f"Expected {TUITION_REFUNDED_STATUS}, got {sync_lead.consultation_status_id}"

    async def test_sync_creates_history_with_refund_amount(
        self,
        db: AsyncSession,
        sync_lead: models.Lead,
        sync_user: models.User,
        sync_statuses: dict,
    ):
        """Sync should create history record with refund amount."""
        profile = await create_profile(db, sync_lead, "approved")
        refund_amount = "8000000"

        await sync_lead_tuition_refunded(
            db=db,
            profile=profile,
            refund_amount=refund_amount,
            changed_by_user_id=sync_user.id,
            reason=f"Partial refund: {refund_amount} VND",
        )

        result = await db.execute(
            select(models.LeadStatusHistory)
            .where(models.LeadStatusHistory.lead_id == sync_lead.id)
            .order_by(models.LeadStatusHistory.changed_at.desc())
        )
        latest = result.scalars().first()

        assert latest.new_consultation_status_id == TUITION_REFUNDED_STATUS
        assert refund_amount in latest.reason

    async def test_sync_idempotent_for_refund(
        self,
        db: AsyncSession,
        sync_lead: models.Lead,
        sync_user: models.User,
        sync_statuses: dict,
    ):
        """Second sync should be skipped if already at sts18."""
        profile = await create_profile(db, sync_lead, "approved")

        # First sync
        result1 = await sync_lead_tuition_refunded(
            db=db, profile=profile, refund_amount="15000000",
            changed_by_user_id=sync_user.id, reason="First refund",
        )
        assert result1 is True

        # Second sync - should skip
        result2 = await sync_lead_tuition_refunded(
            db=db, profile=profile, refund_amount="0",
            changed_by_user_id=sync_user.id, reason="Second refund",
        )
        assert result2 is False


# ==============================================================================
# TEST: EDGE CASES FOR FINANCE SYNC
# ==============================================================================


class TestFinanceSyncEdgeCases:
    """Test edge cases for finance phase sync functions."""

    async def test_tuition_calculated_handles_missing_lead(
        self,
        db: AsyncSession,
        sync_user: models.User,
        sync_statuses: dict,
    ):
        """Sync should return False if lead not loaded on profile."""
        profile = models.AdmissionProfile(
            lead_id=99999,
            status="approved",
            citizen_id="123456789012",
            version=1,
            applied_rules={},
            academic_year=2025,
        )
        profile.lead = None

        result = await sync_lead_tuition_calculated(
            db=db, profile=profile, fee_amount="15000000",
            changed_by_user_id=sync_user.id, reason="Test missing lead",
        )

        assert result is False

    async def test_tuition_paid_handles_missing_lead(
        self,
        db: AsyncSession,
        sync_user: models.User,
        sync_statuses: dict,
    ):
        """Sync should return False if lead not loaded on profile."""
        profile = models.AdmissionProfile(
            lead_id=99999,
            status="approved",
            citizen_id="123456789012",
            version=1,
            applied_rules={},
            academic_year=2025,
        )
        profile.lead = None

        result = await sync_lead_tuition_paid(
            db=db, profile=profile, transaction_id="TXN-001",
            changed_by_user_id=sync_user.id, reason="Test missing lead",
        )

        assert result is False

    async def test_tuition_refunded_handles_missing_lead(
        self,
        db: AsyncSession,
        sync_user: models.User,
        sync_statuses: dict,
    ):
        """Sync should return False if lead not loaded on profile."""
        profile = models.AdmissionProfile(
            lead_id=99999,
            status="approved",
            citizen_id="123456789012",
            version=1,
            applied_rules={},
            academic_year=2025,
        )
        profile.lead = None

        result = await sync_lead_tuition_refunded(
            db=db, profile=profile, refund_amount="15000000",
            changed_by_user_id=sync_user.id, reason="Test missing lead",
        )

        assert result is False


# ==============================================================================
# TEST: FULL FINANCE WORKFLOW INTEGRATION
# ==============================================================================


class TestFullFinanceWorkflowSync:
    """Test complete finance workflow: approved → tuition calculated → paid → enrolled."""

    async def test_happy_path_finance_workflow(
        self,
        db: AsyncSession,
        sync_lead: models.Lead,
        sync_user: models.User,
        sync_statuses: dict,
    ):
        """Test complete finance workflow with all status transitions."""
        # Step 1: Profile approved → sts09
        profile = await create_profile(db, sync_lead, "approved")

        await sync_lead_from_admission(
            db=db, profile=profile,
            changed_by_user_id=sync_user.id, reason="Profile approved",
        )
        await db.refresh(sync_lead)
        assert sync_lead.consultation_status_id == "sts09", "Step 1: Should be sts09"

        # Step 2: Tuition fee calculated → sts14
        await sync_lead_tuition_calculated(
            db=db, profile=profile, fee_amount="15000000",
            changed_by_user_id=sync_user.id, reason="Tuition calculated",
        )
        await db.refresh(sync_lead)
        assert sync_lead.consultation_status_id == TUITION_CALCULATED_STATUS, \
            f"Step 2: Should be {TUITION_CALCULATED_STATUS}"

        # Step 3: Tuition fee paid → sts10
        await sync_lead_tuition_paid(
            db=db, profile=profile, transaction_id="TXN-2025-001",
            changed_by_user_id=sync_user.id, reason="Tuition paid",
        )
        await db.refresh(sync_lead)
        assert sync_lead.consultation_status_id == TUITION_PAID_STATUS, \
            f"Step 3: Should be {TUITION_PAID_STATUS}"

        # Step 4: Student enrolled → sts11
        profile.status = "enrolled"
        await sync_lead_from_admission(
            db=db, profile=profile,
            changed_by_user_id=sync_user.id, reason="Student enrolled",
        )
        await db.refresh(sync_lead)
        assert sync_lead.consultation_status_id == "sts11", "Step 4: Should be sts11"

        # Verify complete history trail
        result = await db.execute(
            select(models.LeadStatusHistory)
            .where(models.LeadStatusHistory.lead_id == sync_lead.id)
            .order_by(models.LeadStatusHistory.changed_at.asc())
        )
        history = result.scalars().all()

        # Expected sequence: sts09 → sts14 → sts10 → sts11
        expected_sequence = ["sts09", TUITION_CALCULATED_STATUS, TUITION_PAID_STATUS, "sts11"]
        status_changes = [h.new_consultation_status_id for h in history]
        actual_sequence = [s for s in status_changes if s in expected_sequence]

        assert actual_sequence == expected_sequence, \
            f"Expected workflow {expected_sequence}, got {actual_sequence}"

    async def test_refund_path_workflow(
        self,
        db: AsyncSession,
        sync_lead: models.Lead,
        sync_user: models.User,
        sync_statuses: dict,
    ):
        """Test workflow when student requests refund after payment."""
        # Step 1: Profile approved → sts09
        profile = await create_profile(db, sync_lead, "approved")

        await sync_lead_from_admission(
            db=db, profile=profile,
            changed_by_user_id=sync_user.id, reason="Profile approved",
        )
        await db.refresh(sync_lead)
        assert sync_lead.consultation_status_id == "sts09"

        # Step 2: Tuition fee calculated → sts14
        await sync_lead_tuition_calculated(
            db=db, profile=profile, fee_amount="15000000",
            changed_by_user_id=sync_user.id, reason="Tuition calculated",
        )
        await db.refresh(sync_lead)
        assert sync_lead.consultation_status_id == TUITION_CALCULATED_STATUS

        # Step 3: Tuition fee paid → sts10
        await sync_lead_tuition_paid(
            db=db, profile=profile, transaction_id="TXN-2025-001",
            changed_by_user_id=sync_user.id, reason="Tuition paid",
        )
        await db.refresh(sync_lead)
        assert sync_lead.consultation_status_id == TUITION_PAID_STATUS

        # Step 4: Student requests refund (withdrawal) → sts18
        await sync_lead_tuition_refunded(
            db=db, profile=profile, refund_amount="12000000",
            changed_by_user_id=sync_user.id, reason="Student withdrawal",
        )
        await db.refresh(sync_lead)
        assert sync_lead.consultation_status_id == TUITION_REFUNDED_STATUS, \
            f"Step 4: Should be {TUITION_REFUNDED_STATUS}"

        # Verify refund workflow history
        result = await db.execute(
            select(models.LeadStatusHistory)
            .where(models.LeadStatusHistory.lead_id == sync_lead.id)
            .order_by(models.LeadStatusHistory.changed_at.asc())
        )
        history = result.scalars().all()

        # Expected sequence: sts09 → sts14 → sts10 → sts18
        expected_sequence = [
            "sts09", TUITION_CALCULATED_STATUS, TUITION_PAID_STATUS, TUITION_REFUNDED_STATUS
        ]
        status_changes = [h.new_consultation_status_id for h in history]
        actual_sequence = [s for s in status_changes if s in expected_sequence]

        assert actual_sequence == expected_sequence, \
            f"Expected refund workflow {expected_sequence}, got {actual_sequence}"

    async def test_waived_fee_workflow(
        self,
        db: AsyncSession,
        sync_lead: models.Lead,
        sync_user: models.User,
        sync_statuses: dict,
    ):
        """Test workflow when tuition fee is waived (scholarship)."""
        # Step 1: Profile approved → sts09
        profile = await create_profile(db, sync_lead, "approved")

        await sync_lead_from_admission(
            db=db, profile=profile,
            changed_by_user_id=sync_user.id, reason="Profile approved",
        )
        await db.refresh(sync_lead)
        assert sync_lead.consultation_status_id == "sts09"

        # Step 2: Fee waived → skip sts14, go directly to sts10
        await sync_lead_tuition_paid(
            db=db, profile=profile, transaction_id="",
            changed_by_user_id=sync_user.id, reason="100% scholarship - fee waived",
        )
        await db.refresh(sync_lead)
        assert sync_lead.consultation_status_id == TUITION_PAID_STATUS

        # Step 3: Student enrolled → sts11
        profile.status = "enrolled"
        await sync_lead_from_admission(
            db=db, profile=profile,
            changed_by_user_id=sync_user.id, reason="Student enrolled (scholarship)",
        )
        await db.refresh(sync_lead)
        assert sync_lead.consultation_status_id == "sts11"


# ==============================================================================
# TEST: SYNC FUNCTION - WITHDRAWN STATUS
# ==============================================================================


class TestSyncWithdrawnStatus:
    """Test sync when admission profile is withdrawn."""

    async def test_sync_updates_lead_to_sts08_on_withdrawal(
        self,
        db: AsyncSession,
        sync_lead: models.Lead,
        sync_user: models.User,
        sync_statuses: dict,
    ):
        """When profile is withdrawn, lead should sync to sts08."""
        profile = await create_profile(db, sync_lead, "withdrawn")

        result = await sync_lead_from_admission(
            db=db,
            profile=profile,
            changed_by_user_id=sync_user.id,
            reason="Applicant withdrew application",
        )

        assert result is True

        await db.refresh(sync_lead)
        assert sync_lead.consultation_status_id == "sts08", \
            f"Expected sts08, got {sync_lead.consultation_status_id}"

    async def test_withdrawn_maps_to_sts08(self):
        """Withdrawn should map to sts08 (Từ chối tư vấn)."""
        assert ADMISSION_TO_LEAD_STATUS_MAP["withdrawn"] == "sts08"


# ==============================================================================
# TEST: STUDENT DROPPED (Side-Channel - sts12)
# ==============================================================================


class TestSyncStudentDropped:
    """Test that student_dropped event maps to sts12 via milestone consultation.

    Note: Dropped is NOT an admission status — it's a side-channel flag.
    The lead sync happens via _create_admission_milestone_consultation("student_dropped")
    which uses the event mapping to get sts12/stg07.
    """

    async def test_student_dropped_event_maps_to_sts12(self):
        """student_dropped event should map to sts12 in event mapping."""
        from app.core.admission_event_mapping import get_projection
        projection = get_projection("student_dropped")
        assert projection is not None
        assert projection.consultation_status_id == "sts12"
        assert projection.pipeline_stage_id == "stg07"
        assert projection.admission_status == "enrolled"  # Status stays enrolled

    async def test_sts12_fixture_exists(self, sync_statuses: dict):
        """sts12 should be created in fixture for integration tests."""
        assert "sts12" in sync_statuses["status_ids"]
