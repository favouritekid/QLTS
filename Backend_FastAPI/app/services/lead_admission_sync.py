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
    - record_application_fee_payment() → sts13 (Đã hoàn lệ phí xét tuyển)
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
from ..core.admission_event_mapping import get_projection

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

# Application fee status from event mapping (Single Source of Truth)
# Uses admission_event_mapping.py -> "application_fee_paid" event
_FEE_PROJECTION = get_projection("application_fee_paid")
FEE_PAID_STATUS = _FEE_PROJECTION.consultation_status_id if _FEE_PROJECTION else "sts13"
FEE_PAID_STAGE = _FEE_PROJECTION.pipeline_stage_id if _FEE_PROJECTION else "stg03"


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


# =============================================================================
# SYNC FUNCTION FOR FEE PAYMENT
# =============================================================================

async def sync_lead_fee_paid(
    db: AsyncSession,
    profile: models.AdmissionProfile,
    changed_by_user_id: Optional[int] = None,
    reason: Optional[str] = None,
) -> bool:
    """
    Sync lead consultation status when application fee is paid.

    Moves lead to sts13 (Đã hoàn tất lệ phí xét tuyển).

    Args:
        db: Database session (same transaction as caller)
        profile: AdmissionProfile with lead relationship loaded
        changed_by_user_id: User who triggered the change (for audit)
        reason: Reason for the status change (for audit log)

    Returns:
        bool: True if sync was performed, False if skipped
    """
    lead = profile.lead
    if not lead:
        log.warning(
            "sync_lead_fee_paid: Lead not loaded on profile",
            profile_id=profile.id,
        )
        return False

    target_status_id = FEE_PAID_STATUS  # sts13

    # Skip if already at target status (idempotent)
    if lead.consultation_status_id == target_status_id:
        log.debug(
            "sync_lead_fee_paid: Already at fee paid status, skipping",
            lead_id=lead.id,
            current_status=lead.consultation_status_id,
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
            "sync_lead_fee_paid: FEE_PAID_STATUS not found",
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
        reason=reason or "Application fee payment confirmed",
    )
    db.add(history)

    await db.flush()

    log.info(
        "sync_lead_fee_paid: Lead status synced to fee paid",
        lead_id=lead.id,
        profile_id=profile.id,
        old_consultation_status=old_consultation_status_id,
        new_consultation_status=target_status_id,
    )

    return True


# =============================================================================
# SYNC FUNCTIONS FOR TUITION FEE EVENTS (Finance Phase)
# =============================================================================

# Get projections from event mapping (Single Source of Truth)
_TUITION_CALC_PROJECTION = get_projection("tuition_fee_calculated")
_TUITION_PAID_PROJECTION = get_projection("tuition_fee_paid")
_TUITION_REFUND_PROJECTION = get_projection("tuition_fee_refunded")

TUITION_CALCULATED_STATUS = _TUITION_CALC_PROJECTION.consultation_status_id if _TUITION_CALC_PROJECTION else "sts14"
TUITION_PAID_STATUS = _TUITION_PAID_PROJECTION.consultation_status_id if _TUITION_PAID_PROJECTION else "sts10"
TUITION_REFUNDED_STATUS = _TUITION_REFUND_PROJECTION.consultation_status_id if _TUITION_REFUND_PROJECTION else "sts18"


async def sync_lead_tuition_calculated(
    db: AsyncSession,
    profile: models.AdmissionProfile,
    fee_amount: str = "",
    changed_by_user_id: Optional[int] = None,
    reason: Optional[str] = None,
) -> bool:
    """
    Sync lead consultation status when tuition fee is calculated.

    Moves lead to sts14 (Chưa hoàn tất học phí / Chờ đóng học phí).

    This indicates the profile is approved and waiting for tuition payment.

    Args:
        db: Database session (same transaction as caller)
        profile: AdmissionProfile with lead relationship loaded
        fee_amount: Fee amount for note template
        changed_by_user_id: User who triggered the change (for audit)
        reason: Reason for the status change (for audit log)

    Returns:
        bool: True if sync was performed, False if skipped
    """
    lead = profile.lead
    if not lead:
        log.warning(
            "sync_lead_tuition_calculated: Lead not loaded on profile",
            profile_id=profile.id,
        )
        return False

    target_status_id = TUITION_CALCULATED_STATUS  # sts14

    # Skip if already at target status (idempotent)
    if lead.consultation_status_id == target_status_id:
        log.debug(
            "sync_lead_tuition_calculated: Already at target status, skipping",
            lead_id=lead.id,
            current_status=lead.consultation_status_id,
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
            "sync_lead_tuition_calculated: Target ConsultationStatus not found",
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
        reason=reason or f"Tuition fee calculated: {fee_amount} VND",
    )
    db.add(history)

    await db.flush()

    log.info(
        "sync_lead_tuition_calculated: Lead status synced to tuition pending",
        lead_id=lead.id,
        profile_id=profile.id,
        old_consultation_status=old_consultation_status_id,
        new_consultation_status=target_status_id,
        fee_amount=fee_amount,
    )

    return True


async def sync_lead_tuition_paid(
    db: AsyncSession,
    profile: models.AdmissionProfile,
    transaction_id: str = "",
    changed_by_user_id: Optional[int] = None,
    reason: Optional[str] = None,
) -> bool:
    """
    Sync lead consultation status when tuition fee is fully paid or waived.

    Moves lead to sts10 (Đã hoàn tất học phí).

    This indicates the profile is ready for enrollment (fee gate passed).

    Args:
        db: Database session (same transaction as caller)
        profile: AdmissionProfile with lead relationship loaded
        transaction_id: Payment transaction ID for note template
        changed_by_user_id: User who triggered the change (for audit)
        reason: Reason for the status change (for audit log)

    Returns:
        bool: True if sync was performed, False if skipped
    """
    lead = profile.lead
    if not lead:
        log.warning(
            "sync_lead_tuition_paid: Lead not loaded on profile",
            profile_id=profile.id,
        )
        return False

    target_status_id = TUITION_PAID_STATUS  # sts10

    # Skip if already at target status (idempotent)
    if lead.consultation_status_id == target_status_id:
        log.debug(
            "sync_lead_tuition_paid: Already at tuition paid status, skipping",
            lead_id=lead.id,
            current_status=lead.consultation_status_id,
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
            "sync_lead_tuition_paid: TUITION_PAID_STATUS not found",
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
        reason=reason or f"Tuition fee paid/waived. Transaction: {transaction_id}",
    )
    db.add(history)

    await db.flush()

    log.info(
        "sync_lead_tuition_paid: Lead status synced to tuition paid",
        lead_id=lead.id,
        profile_id=profile.id,
        old_consultation_status=old_consultation_status_id,
        new_consultation_status=target_status_id,
        transaction_id=transaction_id,
    )

    return True


async def sync_lead_tuition_refunded(
    db: AsyncSession,
    profile: models.AdmissionProfile,
    refund_amount: str = "",
    changed_by_user_id: Optional[int] = None,
    reason: Optional[str] = None,
) -> bool:
    """
    Sync lead consultation status when tuition fee is refunded.

    Moves lead to sts18 (Đã hoàn học phí).

    This is a terminal state indicating the student has withdrawn after payment.

    Args:
        db: Database session (same transaction as caller)
        profile: AdmissionProfile with lead relationship loaded
        refund_amount: Refund amount for note template
        changed_by_user_id: User who triggered the change (for audit)
        reason: Reason for the status change (for audit log)

    Returns:
        bool: True if sync was performed, False if skipped
    """
    lead = profile.lead
    if not lead:
        log.warning(
            "sync_lead_tuition_refunded: Lead not loaded on profile",
            profile_id=profile.id,
        )
        return False

    target_status_id = TUITION_REFUNDED_STATUS  # sts18

    # Skip if already at target status (idempotent)
    if lead.consultation_status_id == target_status_id:
        log.debug(
            "sync_lead_tuition_refunded: Already at refunded status, skipping",
            lead_id=lead.id,
            current_status=lead.consultation_status_id,
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
            "sync_lead_tuition_refunded: TUITION_REFUNDED_STATUS not found",
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
        reason=reason or f"Tuition fee refunded: {refund_amount} VND",
    )
    db.add(history)

    await db.flush()

    log.info(
        "sync_lead_tuition_refunded: Lead status synced to refunded",
        lead_id=lead.id,
        profile_id=profile.id,
        old_consultation_status=old_consultation_status_id,
        new_consultation_status=target_status_id,
        refund_amount=refund_amount,
    )

    return True
