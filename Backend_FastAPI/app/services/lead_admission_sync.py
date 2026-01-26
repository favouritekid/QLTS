# app/services/lead_admission_sync.py
"""
Lead-Admission Status Synchronization Service.

Purpose:
    Maintains consistency between Lead.consultation_status_id and
    AdmissionProfile.status when admission status changes.

Architecture:
    - One-way sync: Admission → Lead (Admission drives lead status in later phases)
    - Same transaction: Uses flush(), not commit() for atomicity
    - Audit trail: Creates LeadStatusHistory for all synced changes

Usage:
    Called from admission_service.py after status transitions:
    - create_profile() → sts07 (Đã tiếp nhận)
    - submit_and_evaluate() → sts07 (Đã tiếp nhận)
    - approve_profile() → sts09 (Đủ điều kiện)
    - reject_profile() → sts16 (Không đạt)
    - enroll_student() → sts11 (Đã xác nhận nhập học)
"""

from typing import Optional
import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .. import models
from ..core.status_mapping import sync_lead_status_from_consultation

log = structlog.get_logger(__name__)


# =============================================================================
# MAPPING: Admission Status → Lead Consultation Status
# =============================================================================

ADMISSION_TO_LEAD_STATUS_MAP = {
    # Admission Status    → Lead ConsultationStatus ID
    "draft":        "sts07",   # Đã tiếp nhận (hồ sơ mới tạo)
    "submitted":    "sts07",   # Đã tiếp nhận (đã nộp, chờ duyệt)
    "approved":     "sts09",   # Đủ điều kiện (đã duyệt)
    "rejected":     "sts16",   # Không đạt (bị từ chối)
    "enrolled":     "sts11",   # Đã xác nhận nhập học (terminal)
}


# =============================================================================
# SYNC FUNCTION
# =============================================================================

async def sync_lead_from_admission(
    db: AsyncSession,
    profile: models.AdmissionProfile,
    changed_by_user_id: Optional[int] = None,
    reason: Optional[str] = None,
) -> bool:
    """
    Sync lead consultation status when admission profile status changes.

    This ensures data consistency between Lead and AdmissionProfile.
    Called from admission_service after status transitions.

    Args:
        db: Database session (same transaction as caller)
        profile: AdmissionProfile with lead relationship loaded
        changed_by_user_id: User who triggered the change (for audit)
        reason: Reason for the status change (for audit log)

    Returns:
        bool: True if sync was performed, False if skipped

    Side Effects:
        - Updates lead.consultation_status_id
        - Updates lead.pipeline_stage_id
        - Updates lead.status (legacy field)
        - Creates LeadStatusHistory record
    """
    # Safety check: Ensure lead is loaded
    lead = profile.lead
    if not lead:
        log.warning(
            "sync_lead_from_admission: Lead not loaded on profile",
            profile_id=profile.id,
        )
        return False

    # Get target consultation status from mapping
    target_status_id = ADMISSION_TO_LEAD_STATUS_MAP.get(profile.status)
    if not target_status_id:
        log.warning(
            "sync_lead_from_admission: Unknown admission status",
            profile_id=profile.id,
            admission_status=profile.status,
        )
        return False

    # Skip if already at target status (idempotent)
    if lead.consultation_status_id == target_status_id:
        log.debug(
            "sync_lead_from_admission: Already at target status, skipping",
            lead_id=lead.id,
            current_status=lead.consultation_status_id,
            target_status=target_status_id,
        )
        return False

    # Store old values for history
    old_consultation_status_id = lead.consultation_status_id
    old_pipeline_stage_id = lead.pipeline_stage_id
    old_status = lead.status

    # Get new consultation status with stage relationship
    new_status = await db.get(
        models.ConsultationStatus,
        target_status_id,
        options=[selectinload(models.ConsultationStatus.stage)]
    )

    if not new_status:
        log.error(
            "sync_lead_from_admission: Target ConsultationStatus not found",
            target_status_id=target_status_id,
        )
        return False

    # Update lead fields
    lead.consultation_status_id = target_status_id
    lead.pipeline_stage_id = new_status.stage_id

    # Sync legacy lead.status using existing mapping function
    sync_lead_status_from_consultation(lead, new_status)

    # Create history record for audit trail
    history = models.LeadStatusHistory(
        lead_id=lead.id,
        old_status=old_status,
        new_status=lead.status,
        old_consultation_status_id=old_consultation_status_id,
        new_consultation_status_id=target_status_id,
        old_pipeline_stage_id=old_pipeline_stage_id,
        new_pipeline_stage_id=new_status.stage_id,
        changed_by_user_id=changed_by_user_id,
        reason=reason or f"Auto-sync from admission status: {profile.status}",
    )
    db.add(history)

    await db.flush()

    log.info(
        "sync_lead_from_admission: Lead status synced successfully",
        lead_id=lead.id,
        profile_id=profile.id,
        admission_status=profile.status,
        old_consultation_status=old_consultation_status_id,
        new_consultation_status=target_status_id,
        old_lead_status=old_status,
        new_lead_status=lead.status,
    )

    return True
