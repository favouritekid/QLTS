"""
Integration tests for Bidirectional Personal Info Sync.

Tests the sync between Lead and AdmissionProfile when either entity
has personal info (full_name, phone, email) updated.

Sync Rules:
- Lead update → Sync to AdmissionProfiles (only in draft/submitted status)
- Profile update → Sync to Lead (always)
"""

import pytest
import pytest_asyncio
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.orm.attributes import set_committed_value
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.services.lead_profile_sync import (
    sync_profile_from_lead,
    sync_lead_from_profile,
    detect_changed_personal_fields,
    SYNCABLE_FIELDS,
    EDITABLE_PROFILE_STATUSES,
)


pytestmark = pytest.mark.asyncio


# ==============================================================================
# TEST FIXTURES
# ==============================================================================


@pytest_asyncio.fixture
async def bidirectional_sync_user(db: AsyncSession, seeded_dependencies: dict) -> models.User:
    """Create a test user for sync tests."""
    from app.security import get_password_hash

    timestamp = datetime.now().timestamp()

    user = models.User(
        username=f"bidi_sync_user_{timestamp:.0f}",
        email=f"bidi_sync_{timestamp:.0f}@test.com",
        password_hash=get_password_hash("testpass123"),
        full_name="Bidirectional Sync Test User",
        role="officer",
        status="active",
        unit_id=seeded_dependencies["unit_id"],
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user


@pytest_asyncio.fixture
async def bidirectional_sync_lead(
    db: AsyncSession,
    seeded_dependencies: dict,
    bidirectional_sync_user: models.User,
) -> models.Lead:
    """Create a test lead for sync tests."""
    timestamp = datetime.now().timestamp()

    lead = models.Lead(
        full_name="Original Lead Name",
        phone="0901111111",
        email="original_lead@test.com",
        source="website",
        unit_id=seeded_dependencies["unit_id"],
        assigned_officer_id=bidirectional_sync_user.id,
        consultation_status_id=seeded_dependencies["initial_status_id"],
        consultation_count=1,
        status="new",
    )
    db.add(lead)
    await db.flush()
    await db.refresh(lead)
    return lead


@pytest_asyncio.fixture
async def draft_profile(
    db: AsyncSession,
    bidirectional_sync_lead: models.Lead,
) -> models.AdmissionProfile:
    """Create a draft admission profile linked to the lead."""
    timestamp = datetime.now().timestamp()

    profile = models.AdmissionProfile(
        lead_id=bidirectional_sync_lead.id,
        status="draft",
        citizen_id=f"0{timestamp:.0f}"[:12],
        version=1,
        applied_rules={"min_gpa": 6.0},
        academic_year=2025,
        full_name=bidirectional_sync_lead.full_name,
        phone=bidirectional_sync_lead.phone,
        email=bidirectional_sync_lead.email,
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


@pytest_asyncio.fixture
async def approved_profile(
    db: AsyncSession,
    bidirectional_sync_lead: models.Lead,
) -> models.AdmissionProfile:
    """Create an approved admission profile (should NOT be synced from Lead)."""
    timestamp = datetime.now().timestamp()

    profile = models.AdmissionProfile(
        lead_id=bidirectional_sync_lead.id,
        status="approved",  # Not in EDITABLE_PROFILE_STATUSES
        citizen_id=f"1{timestamp:.0f}"[:12],
        version=1,
        applied_rules={"min_gpa": 6.0},
        academic_year=2025,
        full_name=bidirectional_sync_lead.full_name,
        phone=bidirectional_sync_lead.phone,
        email=bidirectional_sync_lead.email,
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


# ==============================================================================
# TEST: HELPER FUNCTION - detect_changed_personal_fields
# ==============================================================================


class TestDetectChangedPersonalFields:
    """Test the field change detection helper."""

    def test_detect_no_changes(self):
        """No changes should return empty list."""
        old = {"full_name": "A", "phone": "123", "email": "a@b.com"}
        new = {"full_name": "A", "phone": "123", "email": "a@b.com"}

        changed = detect_changed_personal_fields(old, new)
        assert changed == []

    def test_detect_single_field_change(self):
        """Single field change should be detected."""
        old = {"full_name": "A", "phone": "123", "email": "a@b.com"}
        new = {"full_name": "A", "phone": "456", "email": "a@b.com"}

        changed = detect_changed_personal_fields(old, new)
        assert changed == ["phone"]

    def test_detect_multiple_field_changes(self):
        """Multiple field changes should all be detected."""
        old = {"full_name": "A", "phone": "123", "email": "a@b.com"}
        new = {"full_name": "B", "phone": "456", "email": "c@d.com"}

        changed = detect_changed_personal_fields(old, new)
        assert set(changed) == {"full_name", "phone", "email"}

    def test_detect_coi_none_la_gia_tri_that_khong_bo_qua(self):
        """Xoá trắng một trường LÀ một thay đổi, và phải được báo cáo.

        Ca cũ đòi "None trong dict mới thì bỏ qua". Tiền đề ấy mâu thuẫn với
        đường ghi: ``sync_profile_from_lead`` chạy thẳng
        ``setattr(profile, field, lead_value)`` mà KHÔNG lọc None. Nếu ``detect``
        bỏ qua None, một lần xoá email trên Lead sẽ không bao giờ lan sang hồ sơ
        draft, và hồ sơ giữ lại một email đã bị xoá — đúng loại dữ liệu thiu mà
        cơ chế đồng bộ sinh ra để tránh.

        (Hồ sơ ở trạng thái không sửa được vẫn được bảo vệ, nhưng bằng bộ lọc
        ``EDITABLE_PROFILE_STATUSES`` ở tầng trên, không phải bằng việc giấu
        thay đổi ở đây.)
        """
        old = {"full_name": "A", "phone": "123", "email": "a@b.com"}
        new = {"full_name": None, "phone": "456", "email": None}

        changed = detect_changed_personal_fields(old, new)
        # So theo TẬP: `SYNCABLE_FIELDS` sinh từ `frozenset` nên thứ tự tuỳ ý —
        # khẳng định bằng list là buộc kết quả vào thứ tự lặp của set.
        assert set(changed) == {"full_name", "phone", "email"}

    def test_detect_none_o_ca_hai_ben_khong_phai_thay_doi(self):
        """None -> None không phải thay đổi; chỉ chuyển TỪ/SANG None mới là."""
        old = {"full_name": "A", "phone": "123", "email": None}
        new = {"full_name": "A", "phone": "123", "email": None}

        assert detect_changed_personal_fields(old, new) == []


# ==============================================================================
# TEST: LEAD → PROFILE SYNC
# ==============================================================================


class TestLeadToProfileSync:
    """Test syncing personal info from Lead to AdmissionProfile."""

    async def test_sync_updates_draft_profile(
        self,
        db: AsyncSession,
        bidirectional_sync_lead: models.Lead,
        draft_profile: models.AdmissionProfile,
        bidirectional_sync_user: models.User,
    ):
        """When Lead is updated, draft profile should be synced."""
        # Update lead personal info
        bidirectional_sync_lead.full_name = "Updated Lead Name"
        bidirectional_sync_lead.phone = "0909999999"
        bidirectional_sync_lead.email = "updated_lead@test.com"

        # Sync to profiles
        synced, synced_ids = await sync_profile_from_lead(
            db=db,
            lead=bidirectional_sync_lead,
            changed_fields=["full_name", "phone", "email"],
            changed_by_user_id=bidirectional_sync_user.id,
        )

        assert synced is True
        assert draft_profile.id in synced_ids

        # Verify profile was updated
        await db.refresh(draft_profile)
        assert draft_profile.full_name == "Updated Lead Name"
        assert draft_profile.phone == "0909999999"
        assert draft_profile.email == "updated_lead@test.com"

    async def test_sync_skips_approved_profile(
        self,
        db: AsyncSession,
        bidirectional_sync_lead: models.Lead,
        approved_profile: models.AdmissionProfile,
        bidirectional_sync_user: models.User,
    ):
        """Approved profiles should NOT be synced (preserves snapshot)."""
        original_name = approved_profile.full_name
        original_phone = approved_profile.phone

        # Update lead personal info
        bidirectional_sync_lead.full_name = "Updated Lead Name"
        bidirectional_sync_lead.phone = "0909999999"

        # Try to sync
        synced, synced_ids = await sync_profile_from_lead(
            db=db,
            lead=bidirectional_sync_lead,
            changed_fields=["full_name", "phone"],
            changed_by_user_id=bidirectional_sync_user.id,
        )

        # Sync should report no profiles synced
        assert synced is False
        assert approved_profile.id not in synced_ids

        # Verify profile was NOT updated
        await db.refresh(approved_profile)
        assert approved_profile.full_name == original_name
        assert approved_profile.phone == original_phone

    async def test_sync_only_specified_fields(
        self,
        db: AsyncSession,
        bidirectional_sync_lead: models.Lead,
        draft_profile: models.AdmissionProfile,
        bidirectional_sync_user: models.User,
    ):
        """Only specified fields should be synced."""
        original_email = draft_profile.email

        # Update all lead fields
        bidirectional_sync_lead.full_name = "Updated Name"
        bidirectional_sync_lead.phone = "0909999999"
        bidirectional_sync_lead.email = "updated@test.com"

        # Only sync phone
        synced, _ = await sync_profile_from_lead(
            db=db,
            lead=bidirectional_sync_lead,
            changed_fields=["phone"],
            changed_by_user_id=bidirectional_sync_user.id,
        )

        assert synced is True

        # Verify only phone was updated
        await db.refresh(draft_profile)
        assert draft_profile.phone == "0909999999"
        # Email should remain unchanged
        assert draft_profile.email == original_email


# ==============================================================================
# TEST: PROFILE → LEAD SYNC
# ==============================================================================


class TestProfileToLeadSync:
    """Test syncing personal info from AdmissionProfile to Lead."""

    async def test_sync_updates_lead(
        self,
        db: AsyncSession,
        bidirectional_sync_lead: models.Lead,
        draft_profile: models.AdmissionProfile,
        bidirectional_sync_user: models.User,
    ):
        """When Profile is updated, Lead should be synced."""
        # Update profile personal info
        draft_profile.full_name = "Updated Profile Name"
        draft_profile.phone = "0908888888"
        draft_profile.email = "updated_profile@test.com"

        # Sync to lead
        synced = await sync_lead_from_profile(
            db=db,
            profile=draft_profile,
            changed_fields=["full_name", "phone", "email"],
            changed_by_user_id=bidirectional_sync_user.id,
        )

        assert synced is True

        # Verify lead was updated
        await db.refresh(bidirectional_sync_lead)
        assert bidirectional_sync_lead.full_name == "Updated Profile Name"
        assert bidirectional_sync_lead.phone == "0908888888"
        assert bidirectional_sync_lead.email == "updated_profile@test.com"

    async def test_sync_skips_if_values_match(
        self,
        db: AsyncSession,
        bidirectional_sync_lead: models.Lead,
        draft_profile: models.AdmissionProfile,
        bidirectional_sync_user: models.User,
    ):
        """Sync should skip if values already match."""
        # Ensure values match
        draft_profile.full_name = bidirectional_sync_lead.full_name
        draft_profile.phone = bidirectional_sync_lead.phone
        draft_profile.email = bidirectional_sync_lead.email

        # Try to sync
        synced = await sync_lead_from_profile(
            db=db,
            profile=draft_profile,
            changed_fields=["full_name", "phone", "email"],
            changed_by_user_id=bidirectional_sync_user.id,
        )

        assert synced is False  # No changes needed


# ==============================================================================
# TEST: BIDIRECTIONAL CONSISTENCY
# ==============================================================================


class TestBidirectionalConsistency:
    """Test that both entities stay in sync."""

    async def test_after_lead_update_both_match(
        self,
        db: AsyncSession,
        bidirectional_sync_lead: models.Lead,
        draft_profile: models.AdmissionProfile,
        bidirectional_sync_user: models.User,
    ):
        """After Lead update + sync, both entities should have same values."""
        new_name = "Consistent Name"
        new_phone = "0907777777"
        new_email = "consistent@test.com"

        # Update lead
        bidirectional_sync_lead.full_name = new_name
        bidirectional_sync_lead.phone = new_phone
        bidirectional_sync_lead.email = new_email

        # Sync to profile
        await sync_profile_from_lead(
            db=db,
            lead=bidirectional_sync_lead,
            changed_fields=["full_name", "phone", "email"],
            changed_by_user_id=bidirectional_sync_user.id,
        )

        # Verify both match
        await db.refresh(draft_profile)
        assert bidirectional_sync_lead.full_name == draft_profile.full_name == new_name
        assert bidirectional_sync_lead.phone == draft_profile.phone == new_phone
        assert bidirectional_sync_lead.email == draft_profile.email == new_email

    async def test_after_profile_update_both_match(
        self,
        db: AsyncSession,
        bidirectional_sync_lead: models.Lead,
        draft_profile: models.AdmissionProfile,
        bidirectional_sync_user: models.User,
    ):
        """After Profile update + sync, both entities should have same values."""
        new_name = "Profile Updated Name"
        new_phone = "0906666666"
        new_email = "profile_updated@test.com"

        # Update profile
        draft_profile.full_name = new_name
        draft_profile.phone = new_phone
        draft_profile.email = new_email

        # Sync to lead
        await sync_lead_from_profile(
            db=db,
            profile=draft_profile,
            changed_fields=["full_name", "phone", "email"],
            changed_by_user_id=bidirectional_sync_user.id,
        )

        # Verify both match
        await db.refresh(bidirectional_sync_lead)
        assert bidirectional_sync_lead.full_name == draft_profile.full_name == new_name
        assert bidirectional_sync_lead.phone == draft_profile.phone == new_phone
        assert bidirectional_sync_lead.email == draft_profile.email == new_email


# ==============================================================================
# TEST: EDGE CASES
# ==============================================================================


class TestSyncEdgeCases:
    """Test edge cases for sync functionality."""

    async def test_sync_handles_lead_without_profiles(
        self,
        db: AsyncSession,
        bidirectional_sync_lead: models.Lead,
        bidirectional_sync_user: models.User,
    ):
        """Sync should handle lead with no profiles gracefully."""
        # Ensure no profiles exist for this lead
        # (bidirectional_sync_lead fixture creates lead without profile)

        # This should not raise an error
        synced, synced_ids = await sync_profile_from_lead(
            db=db,
            lead=bidirectional_sync_lead,
            changed_fields=["phone"],
            changed_by_user_id=bidirectional_sync_user.id,
        )

        assert synced is False
        assert synced_ids == []

    async def test_sync_handles_profile_with_detached_lead(
        self,
        db: AsyncSession,
        bidirectional_sync_lead: models.Lead,
        bidirectional_sync_user: models.User,
    ):
        """Sync should load lead internally if profile.lead is explicitly None."""
        timestamp = datetime.now().timestamp()

        # Create profile
        profile = models.AdmissionProfile(
            lead_id=bidirectional_sync_lead.id,
            status="draft",
            citizen_id=f"2{timestamp:.0f}"[:12],
            version=1,
            applied_rules={},
            academic_year=2025,
            full_name="Profile Only",
            phone="0905555555",
            email="profile_only@test.com",
        )
        db.add(profile)
        await db.flush()

        # Mô phỏng "quan hệ chưa được nạp": `profile.lead` đọc ra None trong khi
        # `profile.lead_id` VẪN nguyên — đúng trạng thái mà nhánh dự phòng của
        # `sync_lead_from_profile` phục vụ (`if not lead: SELECT ... WHERE
        # id == profile.lead_id`).
        #
        # ⚠️ KHÔNG dùng `profile.lead = None`. Gán vào quan hệ không "detach" mà
        # GỠ LIÊN KẾT: SQLAlchemy đồng bộ FK theo, nên lúc flush nó phát
        # `UPDATE admission_profile SET lead_id = NULL` và đâm thẳng vào ràng
        # buộc NOT NULL — ca đỏ ở `NotNullViolationError`, một lỗi không liên
        # quan gì tới thứ ca này định kiểm.
        #
        # `set_committed_value` đặt giá trị như thể vừa nạp từ CSDL: thuộc tính
        # không vào lịch sử thay đổi, không có UPDATE nào được sinh ra.
        set_committed_value(profile, "lead", None)

        # Sync should still work (loads lead internally via query)
        synced = await sync_lead_from_profile(
            db=db,
            profile=profile,
            changed_fields=["phone"],
            changed_by_user_id=bidirectional_sync_user.id,
        )

        assert synced is True

        # Verify lead was updated
        await db.refresh(bidirectional_sync_lead)
        assert bidirectional_sync_lead.phone == "0905555555"
