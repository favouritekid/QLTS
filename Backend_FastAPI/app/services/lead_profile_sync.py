# app/services/lead_profile_sync.py
"""
Bidirectional Personal Info Sync Between Lead and AdmissionProfile.

Purpose:
    Maintains consistency of personal info (full_name, phone, email) between
    Lead and AdmissionProfile entities when either is updated.

Architecture:
    - Bidirectional sync: Lead ↔ AdmissionProfile
    - Same transaction: Uses flush(), not commit() for atomicity
    - Conditional sync: Only syncs profiles in editable states (draft, submitted)
    - Audit trail: Logs all sync operations

Usage:
    Called from:
    - lead_service.py after update_lead() modifies personal info
    - admission_service.py after update_profile() modifies personal info
"""

from typing import Optional, List, Tuple
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .. import models

log = structlog.get_logger(__name__)


# =============================================================================
# SYNC CONFIGURATION
# =============================================================================

# Fields to sync between Lead and AdmissionProfile
SYNCABLE_FIELDS = ["full_name", "phone", "email"]

# AdmissionProfile statuses that allow sync (editable states)
EDITABLE_PROFILE_STATUSES = {"draft", "submitted"}


# =============================================================================
# SYNC: LEAD → ADMISSION PROFILE
# =============================================================================

async def sync_profile_from_lead(
    db: AsyncSession,
    lead: models.Lead,
    changed_fields: Optional[List[str]] = None,
    changed_by_user_id: Optional[int] = None,
) -> Tuple[bool, List[int]]:
    """
    Sync personal info from Lead to its AdmissionProfiles.

    Only syncs to profiles in editable states (draft, submitted).
    Profiles that are approved/rejected/enrolled are NOT synced
    to preserve the snapshot at approval time.

    Args:
        db: Database session (same transaction as caller)
        lead: Lead model with updated personal info
        changed_fields: List of field names that changed (optional, syncs all if None)
        changed_by_user_id: User who triggered the change (for audit)

    Returns:
        Tuple of (sync_performed: bool, synced_profile_ids: List[int])

    Example:
        # After updating lead.phone
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

    # Get editable profiles for this lead
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
# SYNC: ADMISSION PROFILE → LEAD
# =============================================================================

async def sync_lead_from_profile(
    db: AsyncSession,
    profile: models.AdmissionProfile,
    changed_fields: Optional[List[str]] = None,
    changed_by_user_id: Optional[int] = None,
) -> bool:
    """
    Sync personal info from AdmissionProfile back to its Lead.

    This ensures the Lead always has the most up-to-date contact info,
    which is important for:
    - Officer callbacks
    - Lead list display
    - Future consultations

    Args:
        db: Database session (same transaction as caller)
        profile: AdmissionProfile model with updated personal info
        changed_fields: List of field names that changed (optional, syncs all if None)
        changed_by_user_id: User who triggered the change (for audit)

    Returns:
        bool: True if sync was performed, False if skipped

    Example:
        # After updating profile.phone
        synced = await sync_lead_from_profile(
            db=db,
            profile=profile,
            changed_fields=["phone"],
            changed_by_user_id=current_user.id,
        )
    """
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
    old_values: dict,
    new_values: dict,
) -> List[str]:
    """
    Detect which personal info fields have changed.

    Args:
        old_values: Dict with old field values {"full_name": "...", "phone": "...", "email": "..."}
        new_values: Dict with new field values

    Returns:
        List of field names that changed

    Example:
        old = {"full_name": "A", "phone": "123", "email": "a@b.com"}
        new = {"full_name": "A", "phone": "456", "email": "a@b.com"}
        changed = detect_changed_personal_fields(old, new)
        # Result: ["phone"]
    """
    changed = []

    for field in SYNCABLE_FIELDS:
        old_val = old_values.get(field)
        new_val = new_values.get(field)

        if new_val is not None and old_val != new_val:
            changed.append(field)

    return changed
