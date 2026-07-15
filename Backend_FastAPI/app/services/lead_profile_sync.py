# app/services/lead_profile_sync.py
"""
Lead ↔ AdmissionProfile Sync Service.

Architecture Philosophy (V3.0):
===============================
- BIDIRECTIONAL SYNC: Lead ↔ Profile (both directions allowed)
- CONDITIONAL: Only for EDITABLE profiles (draft/submitted)
- LOCKED PROFILES: No sync in either direction when approved/rejected/enrolled
- IDENTITY PROTECTION: Lead identity fields locked when profile is in legal state

Sync Rules Matrix:
------------------
| Profile Status     | Lead → Profile | Profile → Lead | Lead Identity Edit |
|--------------------|----------------|----------------|--------------------|
| draft              | ✅ Sync        | ✅ Sync (guard)| ✅ Allowed         |
| submitted          | ✅ Sync        | ❌ Can't edit  | ✅ Allowed         |
| rejected           | ❌ Snapshot    | ✅ Sync (guard)| ✅ Allowed         |
| revision_requested | ❌ Snapshot    | ✅ Sync (guard)| ✅ Allowed         |
| approved           | ❌ Snapshot    | ❌ Locked      | ❌ BLOCKED         |
| enrolled           | ❌ Snapshot    | ❌ Locked      | ❌ BLOCKED         |

Note: chiều Profile → Lead nay đi qua ``sync_lead_from_profile`` với ĐẦY ĐỦ
guard (identity-lock + terminal-lock + normalize/validate phone + phone2≠phone +
phone/email conflict + identity-registry + version + audit). "Sync (guard)".

Why Conditional Sync?
---------------------
1. EDITABLE PHASE (draft/submitted):
   - Data entry in progress, officer may fill complete info in Profile
   - Lead list should show updated names for officer convenience
   - Example: Lead "anh A" → Profile "Nguyễn Văn A" → Lead updated

2. LOCKED PHASE (approved/rejected/enrolled):
   - Profile is legal snapshot, must not change
   - Lead is operational CRM, may need contact updates
   - No sync to avoid dual identity confusion

Field Classifications:
----------------------
1. IDENTITY_FIELDS (Legal/Snapshot):
   - full_name, phone, email
   - Synced bidirectionally when profile is editable
   - LOCKED on Lead when profile is approved/rejected/enrolled

2. OPERATIONAL_FIELDS (CRM):
   - phone2, location, officer_summary, etc.
   - Can always be updated on Lead
   - Never synced to any profiles

Usage:
------
- Lead → Profile: Called from lead_service.py after update_lead()
- Profile → Lead: Called from admission_service.py after update_profile()
"""

from typing import Optional, List, Tuple, Set
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import models

log = structlog.get_logger(__name__)


# =============================================================================
# FIELD CLASSIFICATION CONSTANTS
# =============================================================================

# 🔒 IDENTITY FIELDS - Legal/Snapshot fields
# These are used in official documents, enrollment decisions, etc.
# LOCKED when AdmissionProfile is in approved/rejected/enrolled state
IDENTITY_FIELDS: Set[str] = frozenset({
    "full_name",    # Họ tên - dùng cho giấy báo trúng tuyển
    "phone",        # SĐT chính - liên lạc chính thức
    "email",        # Email - gửi thông báo chính thức
})

# 🟡 OPERATIONAL FIELDS - CRM/Operational fields
# Can be updated anytime, not synced to locked profiles
OPERATIONAL_FIELDS: Set[str] = frozenset({
    "phone2",              # SĐT phụ (backup contact)
    "location",            # Địa chỉ (có thể thay đổi)
    "officer_rating",      # Đánh giá của officer
    "officer_summary",     # Ghi chú nội bộ
    "education_level",     # Có thể bổ sung sau
    "gpa",                 # Có thể cập nhật
    "birth_year",          # Fit score
    "location_proximity",  # Fit score
    "occupation_relevance", # Fit score
    "academic_performance", # Fit score
})

# Fields that sync from Lead → Profile (only for editable profiles)
SYNCABLE_FIELDS: List[str] = list(IDENTITY_FIELDS)

# AdmissionProfile statuses that allow EDITING (and thus sync)
# - draft: Initial data entry phase
# - submitted: Waiting for review (Lead → Profile sync ok, but Profile can't be edited)
# - rejected: Can edit to fix issues and resubmit
EDITABLE_PROFILE_STATUSES: Set[str] = frozenset({"draft", "submitted"})

# AdmissionProfile statuses that allow Profile UPDATE (and Profile → Lead sync)
# Note: "submitted" cannot be edited (waiting for decision). Must mirror the
# function-level gate in admission_service.update_profile
# ({draft, rejected, revision_requested}); nếu lệch, profile
# ``revision_requested`` sẽ sửa được nhưng KHÔNG sync xuống Lead → drift.
PROFILE_UPDATE_ALLOWED_STATUSES: Set[str] = frozenset(
    {"draft", "rejected", "revision_requested"}
)

# AdmissionProfile statuses that LOCK identity fields on Lead
# These are "legal snapshots" - data is frozen for official records.
# ``admitted`` is the choice-engine equivalent of legacy ``approved`` (Phase 3
# state machine T7 outcome); kept here for forward-compat so identity fields
# stay frozen the moment Phase 1 widens the CHECK constraint and #16 wires
# the writes — no follow-up patch required at this site.
LOCKED_PROFILE_STATUSES: Set[str] = frozenset({"approved", "admitted", "enrolled"})


# =============================================================================
# VALIDATION: CAN LEAD IDENTITY FIELDS BE UPDATED?
# =============================================================================

async def check_lead_identity_update_allowed(
    db: AsyncSession,
    lead_id: int,
    fields_to_update: List[str],
) -> Tuple[bool, Optional[str], Optional[int]]:
    """
    Check if Lead identity fields can be updated.

    Identity fields (full_name, phone, email) are LOCKED when the Lead has
    an AdmissionProfile in approved/rejected/enrolled state.

    Args:
        db: Database session
        lead_id: Lead ID to check
        fields_to_update: List of field names being updated

    Returns:
        Tuple of (allowed: bool, block_reason: str | None, profile_id: int | None)

    Example:
        allowed, reason, profile_id = await check_lead_identity_update_allowed(
            db, lead_id=123, fields_to_update=["full_name", "phone"]
        )
        if not allowed:
            raise BusinessRuleViolation(reason)
    """
    # Check if any identity fields are being updated
    identity_fields_in_update = [f for f in fields_to_update if f in IDENTITY_FIELDS]

    if not identity_fields_in_update:
        # No identity fields being updated - always allowed
        return True, None, None

    # Check if Lead has a locked AdmissionProfile
    result = await db.execute(
        select(models.AdmissionProfile.id, models.AdmissionProfile.status)
        .where(models.AdmissionProfile.lead_id == lead_id)
        .where(models.AdmissionProfile.status.in_(LOCKED_PROFILE_STATUSES))
        .limit(1)
    )
    locked_profile = result.first()

    if locked_profile:
        profile_id, profile_status = locked_profile

        # Map status to Vietnamese for user-friendly message
        status_labels = {
            "approved": "Đã duyệt",
            "rejected": "Đã từ chối",
            "enrolled": "Đã nhập học",
        }
        status_label = status_labels.get(profile_status, profile_status)

        blocked_fields_str = ", ".join(identity_fields_in_update)

        reason = (
            f"Không thể cập nhật thông tin định danh ({blocked_fields_str}) "
            f"vì Lead đã có hồ sơ xét tuyển ở trạng thái '{status_label}' (#{profile_id}). "
            f"Thông tin này đã được sử dụng trong hồ sơ chính thức. "
            f"Nếu cần sửa, vui lòng liên hệ quản lý để tạo yêu cầu điều chỉnh."
        )

        log.warning(
            "Lead identity update blocked: Profile in locked state",
            lead_id=lead_id,
            profile_id=profile_id,
            profile_status=profile_status,
            blocked_fields=identity_fields_in_update,
        )

        return False, reason, profile_id

    # No locked profile - update allowed
    return True, None, None


# =============================================================================
# SYNC: LEAD → ADMISSION PROFILE (One-Way)
# =============================================================================

async def sync_profile_from_lead(
    db: AsyncSession,
    lead: models.Lead,
    changed_fields: Optional[List[str]] = None,
    changed_by_user_id: Optional[int] = None,
) -> Tuple[bool, List[int]]:
    """
    Sync personal info from Lead to its AdmissionProfiles (ONE-WAY).

    Only syncs to profiles in EDITABLE states (draft, submitted).
    Profiles that are approved/rejected/enrolled are NOT synced
    to preserve the legal snapshot.

    Args:
        db: Database session (same transaction as caller)
        lead: Lead model with updated personal info
        changed_fields: List of field names that changed (optional, syncs all if None)
        changed_by_user_id: User who triggered the change (for audit)

    Returns:
        Tuple of (sync_performed: bool, synced_profile_ids: List[int])

    Example:
        synced, profile_ids = await sync_profile_from_lead(
            db=db,
            lead=lead,
            changed_fields=["phone"],
            changed_by_user_id=current_user.id,
        )
    """
    fields_to_sync = changed_fields or SYNCABLE_FIELDS

    # Filter to only syncable fields
    fields_to_sync = [f for f in fields_to_sync if f in SYNCABLE_FIELDS]

    if not fields_to_sync:
        return False, []

    # Get EDITABLE profiles only (draft, submitted)
    result = await db.execute(
        select(models.AdmissionProfile)
        .where(models.AdmissionProfile.lead_id == lead.id)
        .where(models.AdmissionProfile.status.in_(EDITABLE_PROFILE_STATUSES))
    )
    profiles = result.scalars().all()

    if not profiles:
        log.debug(
            "sync_profile_from_lead: No editable profiles to sync",
            lead_id=lead.id,
        )
        return False, []

    synced_profile_ids = []

    for profile in profiles:
        changes_made = False

        for field in fields_to_sync:
            lead_value = getattr(lead, field, None)
            profile_value = getattr(profile, field, None)

            if lead_value != profile_value:
                setattr(profile, field, lead_value)
                changes_made = True

                log.info(
                    "sync_profile_from_lead: Field synced",
                    lead_id=lead.id,
                    profile_id=profile.id,
                    field=field,
                    old_value=profile_value,
                    new_value=lead_value,
                )

        if changes_made:
            synced_profile_ids.append(profile.id)

    if synced_profile_ids:
        await db.flush()

        log.info(
            "sync_profile_from_lead: Sync completed",
            lead_id=lead.id,
            synced_profile_ids=synced_profile_ids,
            fields=fields_to_sync,
            changed_by_user_id=changed_by_user_id,
        )

    return bool(synced_profile_ids), synced_profile_ids


# =============================================================================
# SYNC: ADMISSION PROFILE → LEAD (Conditional)
# =============================================================================

def _format_lead_conflict_detail(dup: models.Lead, kind: str) -> str:
    """Message xung đột phone/email — GIỮ CÙNG format với ``lead_service.
    update_lead`` để 2 đường sửa identity không trả câu lỗi khác nhau."""
    officer_name = (
        dup.assigned_officer.full_name if dup.assigned_officer else "Chưa phân công"
    )
    if kind == "email":
        return (
            f"Email này đã được sử dụng. Lead: {dup.full_name} "
            f"(SĐT: {dup.phone}) - Đang được quản lý bởi: {officer_name}"
        )
    unit_name = dup.unit.name if getattr(dup, "unit", None) else "N/A"
    return (
        f"Số điện thoại này đã được sử dụng. Lead: {dup.full_name} "
        f"(SĐT: {dup.phone}) - Đơn vị: {unit_name} - Quản lý bởi: {officer_name}"
    )


async def sync_lead_from_profile(
    db: AsyncSession,
    profile: models.AdmissionProfile,
    changed_fields: Optional[List[str]] = None,
    changed_by_user_id: Optional[int] = None,
) -> bool:
    """
    Sync identity info (full_name/phone/email) from AdmissionProfile → Lead.

    Đây là ĐƯỜNG DUY NHẤT hợp lệ cho chiều Profile → Lead — thay thế việc ghi
    thẳng ``profile.lead.<field> = ...`` trong admission_service.update_profile
    (đã bỏ qua toàn bộ guard, là nguyên nhân gốc sự cố list/search 500 do
    ``phone2 == phone`` + drift bảng ``lead_phone_identity``).

    Áp CÙNG guard với ``lead_service.update_lead`` (parity đầy đủ):
      1. Status gate: chỉ profile ∈ PROFILE_UPDATE_ALLOWED_STATUSES.
      2. Identity-lock: chặn nếu Lead có profile khác ở trạng thái locked
         (approved/admitted/enrolled) — ``check_lead_identity_update_allowed``.
      3. phone: normalize → VALIDATE (normalize KHÔNG phải validator) →
         terminal-lock (không đổi số khi lead đã ngừng tư vấn) → phone2 ≠ phone
         → ``check_phone_conflict`` (global).
      4. email: ``check_email_conflict`` (scope theo unit — KHÁC phone global).
      5. Ghi Lead + ``update_phone_identities`` + bump version, bọc trong
         ``begin_nested()`` để race unique (``uq_lead_phone_active`` /
         ``uq_lead_email_unit_active``) được map sạch qua
         ``_handle_lead_integrity_error`` mà KHÔNG poison outer transaction của
         update_profile (vốn không dùng savepoint riêng). Cuối cùng audit "Lead".

    Args:
        db: Database session (same transaction as caller)
        profile: AdmissionProfile với identity đã set (full_name/phone/email)
        changed_fields: Field đã đổi (mặc định SYNCABLE_FIELDS)
        changed_by_user_id: User trigger (audit)

    Returns:
        bool: True nếu có ghi xuống Lead, False nếu skip.

    Raises:
        BusinessRuleViolation: identity-lock / terminal-lock.
        ValidationError: phone sai format sau normalize / phone2 == phone.
        DuplicateResourceError: phone (global) hoặc email (cùng unit) trùng lead khác.
    """
    from sqlalchemy.exc import IntegrityError

    from app.repositories.lead_repository import LeadRepository
    from app.utils.phone_helpers import (
        normalize_vietnam_phone,
        validate_vietnam_phone,
    )
    from app.core.status_mapping import is_consultation_terminal_status
    from app.utils.exceptions import (
        BusinessRuleViolation,
        DuplicateResourceError,
        ValidationError,
    )
    from . import audit_service
    from .lead_service import _get_lead_audit_state, _handle_lead_integrity_error

    # ── Status gate ──────────────────────────────────────────────────────────
    if profile.status not in PROFILE_UPDATE_ALLOWED_STATUSES:
        log.info(
            "sync_lead_from_profile: Blocked - Profile in locked state",
            profile_id=profile.id,
            profile_status=profile.status,
            lead_id=profile.lead_id,
        )
        return False

    fields_to_sync = [
        f for f in (changed_fields or SYNCABLE_FIELDS) if f in SYNCABLE_FIELDS
    ]
    if not fields_to_sync:
        return False

    # Ensure lead is loaded
    lead = profile.lead
    if not lead:
        result = await db.execute(
            select(models.Lead).where(models.Lead.id == profile.lead_id)
        )
        lead = result.scalar_one_or_none()
        if not lead:
            log.warning(
                "sync_lead_from_profile: Lead not found",
                profile_id=profile.id,
                lead_id=profile.lead_id,
            )
            return False

    repo = LeadRepository(db)

    # ── Phòng tuyến 1: xác định DELTA thật (field identity ĐỔI so với lead),
    # rồi identity-lock + validate + conflict CHỈ áp cho field đổi. Tính delta
    # TRƯỚC guard để tránh chặn oan khi FE echo lại identity không đổi (vd chỉ
    # sửa dob nhưng gửi kèm full_name/phone/email cũ). Chạy NGOÀI savepoint.
    new_full_name = None
    new_email = None
    new_phone = None

    _pf_phone = profile.phone
    if "phone" in fields_to_sync and _pf_phone is not None and str(_pf_phone).strip():
        normalized = normalize_vietnam_phone(_pf_phone)
        # Đồng nhất profile.phone về dạng chuẩn (nếu parse được) để 2 bảng khớp.
        if normalized is not None:
            profile.phone = normalized
        # So delta trên GIÁ TRỊ ĐÃ NORMALIZE CẢ 2 PHÍA: lead.phone legacy có thể
        # chưa chuẩn hóa (vd '84…') — so với raw sẽ báo "đổi" oan cho số echo
        # không đổi, kích terminal-lock/conflict/version-churn thừa (giống lỗi
        # phone2 đã vá bên dưới). CHỈ coi là đổi (và validate) khi khác thật.
        existing_phone = normalize_vietnam_phone(lead.phone) if lead.phone else lead.phone
        if normalized != existing_phone:
            if normalized is None or not validate_vietnam_phone(
                normalized, normalize=False
            ):
                raise ValidationError(
                    detail=(
                        "Số điện thoại không hợp lệ. Vui lòng nhập số điện thoại "
                        "Việt Nam (VD: 0901234567)."
                    )
                )
            new_phone = normalized

    if "email" in fields_to_sync and profile.email:
        if not lead.email or profile.email.lower() != lead.email.lower():
            new_email = profile.email

    if (
        "full_name" in fields_to_sync
        and profile.full_name is not None
        and str(profile.full_name).strip()
        and profile.full_name != lead.full_name
    ):
        new_full_name = profile.full_name

    changed_fields = [
        name for name, val in (
            ("full_name", new_full_name),
            ("email", new_email),
            ("phone", new_phone),
        ) if val is not None
    ]
    if not changed_fields:
        return False

    # ── GUARD: identity-lock — Lead có profile khác ở trạng thái locked
    # (approved/admitted/enrolled) → identity là snapshot pháp lý. KHÁC
    # update_lead (raise 400 chặn): ở đường SỬA-HỒ-SƠ ta SKIP đẩy identity xuống
    # Lead (hồ sơ vẫn lưu các field khác, Lead giữ snapshot) thay vì abort toàn
    # bộ edit — tránh khóa cứng luồng returning-student. Chỉ xét field THẬT đổi.
    allowed, block_reason, _ = await check_lead_identity_update_allowed(
        db=db, lead_id=lead.id, fields_to_update=changed_fields
    )
    if not allowed:
        log.info(
            "sync_lead_from_profile: identity locked — SKIP Lead sync "
            "(hồ sơ giữ giá trị, Lead giữ snapshot)",
            lead_id=lead.id,
            profile_id=profile.id,
            changed_fields=changed_fields,
            reason=block_reason,
        )
        return False

    # Snapshot audit state TRƯỚC mọi mutation lead (khớp pattern update_lead).
    old_audit_state = _get_lead_audit_state(lead)

    if new_phone is not None:
        # Terminal-lock: không đổi SĐT khi lead đã ngừng tư vấn (mirror §9.1 B-2).
        if lead.consultation_status_id:
            term_cs = await db.get(
                models.ConsultationStatus, lead.consultation_status_id
            )
            if is_consultation_terminal_status(term_cs):
                raise BusinessRuleViolation(
                    detail=(
                        "Lead đang ở trạng thái đã ngừng tư vấn — không thể đổi "
                        "số điện thoại. Vui lòng mở lại tư vấn (reopen) trước khi "
                        "chỉnh sửa."
                    )
                )
        # phone2 ≠ phone — NORMALIZE lead.phone2 trước khi so (phone2 legacy có
        # thể chưa chuẩn hóa, vd '84…' — so raw sẽ lọt guard rồi đụng unique).
        existing_phone2 = normalize_vietnam_phone(lead.phone2) if lead.phone2 else None
        if existing_phone2 and new_phone == existing_phone2:
            raise ValidationError(
                detail="Số điện thoại phụ không thể trùng với số điện thoại chính."
            )
        # Conflict GLOBAL (cross-slot).
        dup = await repo.check_phone_conflict(
            phone=new_phone, phone2=lead.phone2, exclude_id=lead.id
        )
        if dup:
            raise DuplicateResourceError(
                detail=_format_lead_conflict_detail(dup, "phone")
            )

    if new_email is not None:
        # Conflict scope theo UNIT (khác phone global) — mirror update_lead.
        dup = await repo.check_email_conflict(
            email=new_email, unit_id=lead.unit_id, exclude_id=lead.id
        )
        if dup:
            raise DuplicateResourceError(
                detail=_format_lead_conflict_detail(dup, "email")
            )

    # ── Write: Lead + phone-identity, bọc savepoint để map race unique sạch ──
    # Chỉ phần này nằm trong savepoint (KHÔNG phải mọi write của update_profile).
    # Mục tiêu: Lead/identity write + IntegrityError (uq_lead_phone_active /
    # uq_lead_email_unit_active) được map thành domain error mà không poison
    # outer transaction. Phòng tuyến 1 ở trên đã chặn phần lớn xung đột.
    try:
        async with db.begin_nested():
            if new_full_name is not None:
                lead.full_name = new_full_name
            if new_email is not None:
                lead.email = new_email
            if new_phone is not None:
                lead.phone = new_phone  # đã normalized
                # CHỈ thay slot 'phone' (đường này KHÔNG đổi phone2). KHÔNG
                # rewrite slot phone2 bằng lead.phone2 có thể STALE (lead
                # eager-loaded, không lock) → tránh clobber thay đổi phone2 đồng
                # thời của update_lead. phone2==phone vẫn được uq_lead_phone_active
                # bắt ở INSERT. (Tránh lock lead → không gây deadlock lock-order.)
                await repo.update_phone_slot_identity(
                    lead_id=lead.id, phone=lead.phone
                )
            # Optimistic-lock: bump version của Lead (đường inline cũ đã bỏ sót).
            lead.version = (lead.version or 1) + 1
            await db.flush()
    except IntegrityError as exc:
        # Map uq_lead_phone_active → SĐT, uq_lead_email_unit_active → email;
        # re-raise constraint lạ. Savepoint đã rollback → session sạch.
        _handle_lead_integrity_error(exc)

    # Audit "Lead" (khớp pattern update_lead; đường inline cũ KHÔNG audit).
    audit_changes = audit_service.detect_changes(
        old_audit_state,
        _get_lead_audit_state(lead),
        exclude_fields=["_sa_instance_state", "updated_at", "created_at"],
    )
    if audit_changes:
        await audit_service.log_changes(
            db,
            entity_type="Lead",
            entity_id=lead.id,
            action="updated",
            changes=audit_changes,
            actor_user_id=changed_by_user_id,
            source="api",
        )

    log.info(
        "sync_lead_from_profile: Sync completed (guarded)",
        profile_id=profile.id,
        lead_id=lead.id,
        changed_fields=changed_fields,
        changed_by_user_id=changed_by_user_id,
    )
    return True


# =============================================================================
# HELPER: DETECT CHANGED FIELDS
# =============================================================================

def detect_changed_personal_fields(
    old_info: dict,
    new_info: dict,
) -> List[str]:
    """
    Detect which personal info fields changed between old and new state.

    Args:
        old_info: Dict with old values {"full_name": "...", "phone": "...", "email": "..."}
        new_info: Dict with new values

    Returns:
        List of field names that changed

    Example:
        changed = detect_changed_personal_fields(
            old_info={"full_name": "A", "phone": "123"},
            new_info={"full_name": "B", "phone": "123"},
        )
        # Returns: ["full_name"]
    """
    changed = []

    for field in SYNCABLE_FIELDS:
        old_val = old_info.get(field)
        new_val = new_info.get(field)

        if old_val != new_val:
            changed.append(field)

    return changed
