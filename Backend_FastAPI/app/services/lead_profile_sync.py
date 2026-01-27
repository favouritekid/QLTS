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
| Profile Status | Lead → Profile | Profile → Lead | Lead Identity Edit |
|----------------|----------------|----------------|-------------------|
| draft          | ✅ Sync        | ✅ Sync        | ✅ Allowed        |
| submitted      | ✅ Sync        | ❌ Can't edit  | ✅ Allowed        |
| rejected       | ❌ Snapshot    | ✅ Sync (fix)  | ✅ Allowed        |
| approved       | ❌ Snapshot    | ❌ Locked      | ❌ BLOCKED        |
| enrolled       | ❌ Snapshot    | ❌ Locked      | ❌ BLOCKED        |

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
# Note: "submitted" cannot be edited (waiting for decision), only draft/rejected
PROFILE_UPDATE_ALLOWED_STATUSES: Set[str] = frozenset({"draft", "rejected"})

# AdmissionProfile statuses that LOCK identity fields on Lead
# These are "legal snapshots" - data is frozen for official records
LOCKED_PROFILE_STATUSES: Set[str] = frozenset({"approved", "enrolled"})


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

async def sync_lead_from_profile(
    db: AsyncSession,
    profile: models.AdmissionProfile,
    changed_fields: Optional[List[str]] = None,
    changed_by_user_id: Optional[int] = None,
) -> bool:
    """
    Sync personal info from AdmissionProfile back to its Lead (CONDITIONAL).

    ⚠️ IMPORTANT: Only syncs when profile is in EDITABLE state (draft/submitted).
    When profile is LOCKED (approved/rejected/enrolled), sync is BLOCKED to
    preserve the Lead's operational data integrity.

    Use Case:
        - Lead created with partial name: "anh A"
        - Officer creates Profile with full name: "Nguyễn Văn A"
        - Sync updates Lead so officer sees correct name in Lead list

    Security:
        - draft/submitted: ✅ Sync allowed (data entry phase)
        - approved/rejected/enrolled: ❌ Sync blocked (legal snapshot)

    Args:
        db: Database session (same transaction as caller)
        profile: AdmissionProfile model with updated personal info
        changed_fields: List of field names that changed (optional, syncs all if None)
        changed_by_user_id: User who triggered the change (for audit)

    Returns:
        bool: True if sync was performed, False if skipped/blocked
    """
    # Check if profile is in updatable state (draft or rejected)
    # Note: "submitted" profiles can't be edited (waiting for decision)
    if profile.status not in PROFILE_UPDATE_ALLOWED_STATUSES:
        log.info(
            "sync_lead_from_profile: Blocked - Profile in locked state",
            profile_id=profile.id,
            profile_status=profile.status,
            lead_id=profile.lead_id,
            message="Profile → Lead sync blocked for locked profiles to preserve data integrity",
        )
        return False

    fields_to_sync = changed_fields or SYNCABLE_FIELDS

    # Filter to only syncable fields
    fields_to_sync = [f for f in fields_to_sync if f in SYNCABLE_FIELDS]

    if not fields_to_sync:
        return False

    # Ensure lead is loaded
    lead = profile.lead
    if not lead:
        # Try to load lead
        result = await db.execute(
            select(models.Lead)
            .where(models.Lead.id == profile.lead_id)
        )
        lead = result.scalar_one_or_none()

        if not lead:
            log.warning(
                "sync_lead_from_profile: Lead not found",
                profile_id=profile.id,
                lead_id=profile.lead_id,
            )
            return False

    changes_made = False

    for field in fields_to_sync:
        profile_value = getattr(profile, field, None)
        lead_value = getattr(lead, field, None)

        if profile_value != lead_value:
            setattr(lead, field, profile_value)
            changes_made = True

            log.info(
                "sync_lead_from_profile: Field synced",
                profile_id=profile.id,
                lead_id=lead.id,
                field=field,
                old_value=lead_value,
                new_value=profile_value,
            )

    if changes_made:
        await db.flush()

        log.info(
            "sync_lead_from_profile: Sync completed",
            profile_id=profile.id,
            lead_id=lead.id,
            fields=fields_to_sync,
            changed_by_user_id=changed_by_user_id,
        )

    return changes_made


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
