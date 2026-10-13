"""Guard parity cho chiều Profile → Lead (``sync_lead_from_profile``).

Nâng cấp Fix B (mở rộng): đường sửa hồ sơ tuyển sinh (admission_service.
update_profile) KHÔNG còn ghi thẳng ``profile.lead.phone/full_name/email`` —
mọi thay đổi identity đẩy xuống Lead qua ``sync_lead_from_profile`` với ĐẦY ĐỦ
guard (parity với ``lead_service.update_lead``):

  - normalize + VALIDATE phone (normalize KHÔNG phải validator)
  - phone2 ≠ phone
  - check_phone_conflict (GLOBAL, cross-slot)
  - check_email_conflict (scope theo UNIT)
  - identity-lock (Lead có profile locked) + terminal-lock (đã ngừng tư vấn)
  - update_phone_identities (đồng bộ ``lead_phone_identity`` — hết drift)
  - bump lead.version + audit "Lead"
  - race unique map sạch trong ``begin_nested`` (không poison outer transaction)

Ref: sự cố PROD 14-07 (leads list/search 500 do ``phone2 == phone``).
"""
from datetime import datetime, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app import models
from app.models.lead_phone import LeadPhoneIdentity
from app.repositories.lead_repository import LeadRepository
from app.services.lead_profile_sync import sync_lead_from_profile
from app.utils.exceptions import (
    BusinessRuleViolation,
    DuplicateResourceError,
    ValidationError,
)

pytestmark = pytest.mark.asyncio


# =============================================================================
# HELPERS
# =============================================================================

async def _make_lead(db, deps, *, phone, email=None, phone2=None, unit_id=None,
                     full_name="Lead X", cs_id=None, register_identity=True):
    lead = models.Lead(
        full_name=full_name,
        phone=phone,
        phone2=phone2,
        email=email,
        source="website",
        unit_id=unit_id if unit_id is not None else deps["unit_id"],
        consultation_status_id=cs_id or deps["initial_status_id"],
        status="new",
    )
    db.add(lead)
    await db.flush()
    await db.refresh(lead)
    # Sinh lead_phone_identity như create_lead thật → để đường update_phone_identities
    # (hard-delete row cũ + register mới) thực sự được test (chống drift prod).
    if register_identity:
        await LeadRepository(db).register_phone_identities(lead.id, phone, phone2)
        await db.flush()
    return lead


async def _make_draft_profile(db, lead, *, status="draft", cid_prefix="9",
                              academic_year=2025):
    ts = datetime.now(timezone.utc).timestamp()
    profile = models.AdmissionProfile(
        lead_id=lead.id,
        status=status,
        citizen_id=f"{cid_prefix}{ts:.0f}"[:12],
        version=1,
        applied_rules={},
        academic_year=academic_year,  # uq_admission_profile_lead_year: 1 profile/năm
        full_name=lead.full_name,
        phone=lead.phone,
        email=lead.email,
    )
    db.add(profile)
    await db.flush()
    # Reload với lead eager-loaded (mirror update_profile L5049 selectinload) →
    # tránh lazy-load profile.lead trong sync context (MissingGreenlet).
    result = await db.execute(
        select(models.AdmissionProfile)
        .where(models.AdmissionProfile.id == profile.id)
        .options(selectinload(models.AdmissionProfile.lead))
    )
    return result.scalar_one()


# =============================================================================
# PHONE — normalize / validate / conflict / phone2
# =============================================================================

class TestPhoneGuards:
    async def test_duplicate_phone_global_raises(self, db, seeded_dependencies, officer_user):
        deps = seeded_dependencies
        other = await _make_lead(db, deps, phone="0388888888", full_name="Owner")
        lead = await _make_lead(db, deps, phone="0901111111")
        profile = await _make_draft_profile(db, lead)

        profile.phone = other.phone  # 0388888888 đã thuộc lead khác
        with pytest.raises(DuplicateResourceError):
            await sync_lead_from_profile(
                db, profile, changed_fields=["phone"], changed_by_user_id=officer_user.id
            )

    async def test_invalid_phone_after_normalize_raises(self, db, seeded_dependencies, officer_user):
        lead = await _make_lead(db, seeded_dependencies, phone="0901111111")
        profile = await _make_draft_profile(db, lead)

        profile.phone = "0123"  # sai format VN (validate sau normalize)
        with pytest.raises(ValidationError):
            await sync_lead_from_profile(
                db, profile, changed_fields=["phone"], changed_by_user_id=officer_user.id
            )

    async def test_phone2_equals_phone_raises(self, db, seeded_dependencies, officer_user):
        lead = await _make_lead(
            db, seeded_dependencies, phone="0901111111", phone2="0977777777"
        )
        profile = await _make_draft_profile(db, lead)

        profile.phone = "0977777777"  # trùng phone2 của chính lead
        with pytest.raises(ValidationError):
            await sync_lead_from_profile(
                db, profile, changed_fields=["phone"], changed_by_user_id=officer_user.id
            )

    async def test_phone_change_syncs_identity_registry(self, db, seeded_dependencies, officer_user):
        lead = await _make_lead(db, seeded_dependencies, phone="0901111111")
        profile = await _make_draft_profile(db, lead)

        profile.phone = "0909999999"
        ok = await sync_lead_from_profile(
            db, profile, changed_fields=["phone"], changed_by_user_id=officer_user.id
        )
        assert ok is True
        await db.refresh(lead)
        assert lead.phone == "0909999999"

        rows = (await db.execute(
            select(LeadPhoneIdentity).where(
                LeadPhoneIdentity.lead_id == lead.id,
                LeadPhoneIdentity.deleted_at.is_(None),
            )
        )).scalars().all()
        actives = {r.phone_normalized for r in rows}
        assert "0909999999" in actives          # số mới đã đăng ký
        assert "0901111111" not in actives      # số CŨ đã bị dọn (hết drift — đường hard-delete chạy thật)

    async def test_phone_change_preserves_phone2_identity_row(
        self, db, seeded_dependencies, officer_user
    ):
        """Chỉ đổi phone qua hồ sơ → slot 'phone2' identity GIỮ NGUYÊN (không bị
        rewrite bằng lead.phone2 stale → chống clobber thay đổi phone2 đồng thời)."""
        lead = await _make_lead(
            db, seeded_dependencies, phone="0901111111", phone2="0977777777"
        )
        profile = await _make_draft_profile(db, lead)

        profile.phone = "0909999999"
        ok = await sync_lead_from_profile(
            db, profile, changed_fields=["phone"], changed_by_user_id=officer_user.id
        )
        assert ok is True

        rows = (await db.execute(
            select(LeadPhoneIdentity).where(
                LeadPhoneIdentity.lead_id == lead.id,
                LeadPhoneIdentity.deleted_at.is_(None),
            )
        )).scalars().all()
        by_slot = {r.slot: r.phone_normalized for r in rows}
        assert by_slot.get("phone") == "0909999999"     # slot phone cập nhật
        assert by_slot.get("phone2") == "0977777777"    # slot phone2 GIỮ NGUYÊN

    async def test_legacy_unnormalized_lead_phone_echoed_is_noop(
        self, db, seeded_dependencies, officer_user
    ):
        """lead.phone legacy CHƯA chuẩn hóa ('84…') + profile echo số canonical
        tương đương → KHÔNG coi là đổi (so delta normalize CẢ 2 phía). Không
        version-bump / churn / terminal-lock oan."""
        lead = await _make_lead(
            db, seeded_dependencies, phone="84901234567", register_identity=False,
        )
        v0 = lead.version
        profile = await _make_draft_profile(db, lead)

        profile.phone = "0901234567"  # cùng số, dạng canonical
        ok = await sync_lead_from_profile(
            db, profile, changed_fields=["phone"], changed_by_user_id=officer_user.id
        )
        assert ok is False            # đồng nhất sau normalize → no-op
        await db.refresh(lead)
        assert lead.version == v0      # KHÔNG bump version oan

    async def test_phone_normalizes_plus84(self, db, seeded_dependencies, officer_user):
        """+84 → 0 (normalize) khi đẩy xuống lead + ghi lại profile.phone chuẩn."""
        lead = await _make_lead(db, seeded_dependencies, phone="0901111111")
        profile = await _make_draft_profile(db, lead)

        profile.phone = "+84907654321"
        ok = await sync_lead_from_profile(
            db, profile, changed_fields=["phone"], changed_by_user_id=officer_user.id
        )
        assert ok is True
        await db.refresh(lead)
        assert lead.phone == "0907654321"      # đã normalize +84→0
        assert profile.phone == "0907654321"   # profile cũng được ghi lại chuẩn


# =============================================================================
# EMAIL — conflict theo UNIT
# =============================================================================

class TestEmailGuards:
    async def test_duplicate_email_same_unit_raises(self, db, seeded_dependencies, officer_user):
        deps = seeded_dependencies
        await _make_lead(db, deps, phone="0388888888", email="dup@test.com")
        lead = await _make_lead(db, deps, phone="0901111111", email="orig@test.com")
        profile = await _make_draft_profile(db, lead)

        profile.email = "dup@test.com"
        with pytest.raises(DuplicateResourceError):
            await sync_lead_from_profile(
                db, profile, changed_fields=["email"], changed_by_user_id=officer_user.id
            )

    async def test_duplicate_email_other_unit_allowed(self, db, seeded_dependencies, officer_user):
        deps = seeded_dependencies
        other_unit = models.OrganizationUnit(name="Other Unit", type="department")
        db.add(other_unit)
        await db.flush()
        # email E thuộc lead ở UNIT KHÁC → không tính trùng (scope unit)
        await _make_lead(db, deps, phone="0388888888", email="e@test.com",
                         unit_id=other_unit.id)
        lead = await _make_lead(db, deps, phone="0901111111", email="orig@test.com")
        profile = await _make_draft_profile(db, lead)

        profile.email = "e@test.com"
        ok = await sync_lead_from_profile(
            db, profile, changed_fields=["email"], changed_by_user_id=officer_user.id
        )
        assert ok is True
        await db.refresh(lead)
        assert lead.email == "e@test.com"


# =============================================================================
# STATE LOCKS — identity-lock / terminal-lock
# =============================================================================

class TestStateLocks:
    async def test_identity_lock_skips_sync_when_sibling_locked(self, db, seeded_dependencies, officer_user):
        """Lead có sibling profile approved (identity đóng băng) → SKIP đẩy
        identity xuống Lead (KHÔNG raise): hồ sơ giữ giá trị mới, Lead giữ
        snapshot. (Quyết định nghiệp vụ: đường sửa-hồ-sơ nới hơn update_lead.)"""
        lead = await _make_lead(db, seeded_dependencies, phone="0901111111",
                                full_name="Tên Gốc")
        # profile năm 2024 approved (locked) + profile năm 2025 draft đang sửa
        # (uq_admission_profile_lead_year: mỗi năm chỉ 1 profile/lead).
        await _make_draft_profile(db, lead, status="approved", cid_prefix="1",
                                  academic_year=2024)
        draft = await _make_draft_profile(db, lead, status="draft", cid_prefix="2",
                                          academic_year=2025)

        draft.full_name = "Tên Mới"
        ok = await sync_lead_from_profile(
            db, draft, changed_fields=["full_name"], changed_by_user_id=officer_user.id
        )
        assert ok is False                    # SKIP — không đẩy xuống lead
        await db.refresh(lead)
        assert lead.full_name == "Tên Gốc"    # Lead giữ snapshot pháp lý
        assert draft.full_name == "Tên Mới"   # hồ sơ vẫn giữ giá trị đã sửa

    async def test_terminal_lock_blocks_phone_change(self, db, seeded_dependencies, officer_user):
        deps = seeded_dependencies
        term = models.ConsultationStatus(
            id="sts_term_test",
            name="Đã ngừng tư vấn (Test)",
            color_code="#000000",
            stage_id=deps["stage_id"],
            phase="consultation",
            is_final=True,
        )
        db.add(term)
        await db.flush()

        lead = await _make_lead(db, deps, phone="0901111111", cs_id="sts_term_test")
        profile = await _make_draft_profile(db, lead)

        profile.phone = "0909999999"
        with pytest.raises(BusinessRuleViolation):
            await sync_lead_from_profile(
                db, profile, changed_fields=["phone"], changed_by_user_id=officer_user.id
            )


# =============================================================================
# VERSION + AUDIT + RACE
# =============================================================================

class TestVersionAuditRace:
    async def test_version_bumped_and_audit_logged(self, db, seeded_dependencies, officer_user):
        lead = await _make_lead(db, seeded_dependencies, phone="0901111111",
                                full_name="Cũ")
        v0 = lead.version
        profile = await _make_draft_profile(db, lead)

        profile.full_name = "Nguyễn Văn Mới"
        ok = await sync_lead_from_profile(
            db, profile, changed_fields=["full_name"], changed_by_user_id=officer_user.id
        )
        assert ok is True
        await db.refresh(lead)
        assert lead.full_name == "Nguyễn Văn Mới"
        assert lead.version == (v0 or 1) + 1

        # Audit ghi ĐÚNG NỘI DUNG: full_name cũ→mới + đúng actor.
        audit = (await db.execute(
            select(models.EntityAuditLog).where(
                models.EntityAuditLog.entity_type == "Lead",
                models.EntityAuditLog.entity_id == lead.id,
            )
        )).scalars().all()
        assert len(audit) == 1
        entry = audit[0]
        assert entry.actor_user_id == officer_user.id
        changes = entry.changes or {}
        assert "full_name" in changes
        assert changes["full_name"]["new"] == "Nguyễn Văn Mới"
        assert changes["full_name"]["old"] == "Cũ"

    async def test_race_unique_maps_to_duplicate_not_raw(self, db, seeded_dependencies, officer_user):
        """Race unique: check_phone_conflict (đọc bảng lead) LỌT nhưng identity
        INSERT đụng uq_lead_phone_active. Savepoint bắt IntegrityError →
        _handle_lead_integrity_error map thành DuplicateResourceError (SĐT) —
        KHÔNG lọt IntegrityError thô (500) cũng KHÔNG map nhầm 'CCCD'."""
        deps = seeded_dependencies
        repo = LeadRepository(db)
        # decoy: lead.phone KHÁC (check_phone_conflict trên bảng lead không thấy)
        # nhưng chiếm identity 0909999999 → đụng uq_lead_phone_active khi register.
        decoy = await _make_lead(db, deps, phone="0366666666")
        await repo.register_phone_identities(decoy.id, "0909999999", None)
        await db.flush()

        lead = await _make_lead(db, deps, phone="0901111111")
        profile = await _make_draft_profile(db, lead)

        profile.phone = "0909999999"
        with pytest.raises(DuplicateResourceError) as exc_info:
            await sync_lead_from_profile(
                db, profile, changed_fields=["phone"], changed_by_user_id=officer_user.id
            )
        # Đúng lỗi SĐT (savepoint + _handle_lead_integrity_error), không phải CCCD.
        msg = str(exc_info.value).lower()
        assert "điện thoại" in msg or "sử dụng" in msg
        assert "cccd" not in msg


# =============================================================================
# END-TO-END qua admission_service.update_profile (wiring thật — chỗ từng vỡ prod)
# =============================================================================

class TestUpdateProfileEndToEnd:
    async def test_update_profile_syncs_identity_to_lead_through_guards(
        self, db, seeded_dependencies, admin_user
    ):
        """update_profile (đường HTTP thật) phải đẩy identity xuống lead QUA
        sync_lead_from_profile — không còn ghi thẳng profile.lead.* (bug prod)."""
        from app.services import admission_service

        lead = await _make_lead(
            db, seeded_dependencies, phone="0901111111", full_name="Tên Cũ",
            email="old@test.com",
        )
        profile = await _make_draft_profile(db, lead)
        await db.flush()

        updated = await admission_service.update_profile(
            db=db,
            profile_id=profile.id,
            data={"phone": "0909999999", "full_name": "Tên Mới"},
            current_user=admin_user,
        )

        await db.refresh(lead)
        assert lead.phone == "0909999999"        # đồng bộ xuống lead
        assert lead.full_name == "Tên Mới"
        assert updated.phone == "0909999999"     # profile giữ dạng chuẩn

        rows = (await db.execute(
            select(LeadPhoneIdentity).where(
                LeadPhoneIdentity.lead_id == lead.id,
                LeadPhoneIdentity.deleted_at.is_(None),
            )
        )).scalars().all()
        actives = {r.phone_normalized for r in rows}
        assert "0909999999" in actives
        assert "0901111111" not in actives       # số cũ dọn qua đường thật


# =============================================================================
# SCHEMA: AdmissionProfileUpdate.phone mirror validate_vietnam_phone (chặn 422)
# =============================================================================

class TestAdmissionPhoneSchema:
    """Pattern schema phải MIRROR VIETNAM_PHONE_REGEX ([0-9] ASCII) để số xấu bị
    chặn ở 422, KHÔNG lọt xuống service rồi 400."""

    async def test_schema_accepts_valid_vn_phone(self):
        from app.schemas.admission import AdmissionProfileUpdate
        assert AdmissionProfileUpdate(phone="0901234567", version=1).phone == "0901234567"
        # 02x cố định hợp lệ (mirror VIETNAM_PHONE_REGEX, KHÔNG mobile-only)
        assert AdmissionProfileUpdate(phone="0212345678", version=1).phone == "0212345678"

    async def test_schema_rejects_fullwidth_unicode_digit(self):
        """'090１２３４５６７' (full-width): \\d cũ khớp Unicode digit → lọt; [0-9]
        ASCII phải reject ở 422 (khớp validate_vietnam_phone)."""
        from pydantic import ValidationError as PydanticValidationError
        from app.schemas.admission import AdmissionProfileUpdate
        with pytest.raises(PydanticValidationError) as exc:
            AdmissionProfileUpdate(phone="090１２３４５６７", version=1)
        assert "phone" in str(exc.value)   # fail ĐÚNG do phone, không phải field khác

    async def test_schema_rejects_landline_04x(self):
        from pydantic import ValidationError as PydanticValidationError
        from app.schemas.admission import AdmissionProfileUpdate
        with pytest.raises(PydanticValidationError) as exc:
            AdmissionProfileUpdate(phone="0412345678", version=1)
        assert "phone" in str(exc.value)
