# app/core/admission_event_mapping.py
"""
Admission Event to Pipeline Projection (Single Source of Truth)

This module defines the CANONICAL MAPPING between admission events and the
consultation pipeline system. Following the Golden Rule:

🔒 GOLDEN RULE: No Admission Event may occur without:
    1. Being tied to a Consultation Status
    2. Being tied to a Pipeline Stage
    3. Creating a Consultation record (even if SYSTEM-generated)

This ensures the consultation pipeline and admission workflow remain synchronized,
providing officers with a complete audit trail and accurate reporting.

Architecture:
- Single config dictionary as Source of Truth
- Services MUST use this mapping (no hardcoding)
- Changes here propagate system-wide
- Validates against consultation_status.csv and pipeline_stage.csv
"""

from dataclasses import dataclass
from typing import Optional
import structlog

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class AdmissionEventProjection:
    """
    Immutable projection of an admission event onto the consultation pipeline.

    Attributes:
        event: Admission event identifier (e.g., "profile_submitted")
        admission_status: AdmissionProfile.status value
        consultation_status_id: Target consultation status (e.g., "sts07")
        consultation_name: Human-readable status name
        pipeline_stage_id: Target pipeline stage (e.g., "stg03")
        stage_name: Human-readable stage name
        system_note_template: Template for auto-generated consultation note
        skip_if_converted: If True, skip update if lead already "converted"
    """
    event: str
    admission_status: Optional[str]  # None for lead-only events
    consultation_status_id: str
    consultation_name: str
    pipeline_stage_id: str
    stage_name: str
    system_note_template: str
    skip_if_converted: bool = True  # Default: respect terminal state


# =============================================================================
# CANONICAL ADMISSION EVENT PROJECTIONS
# =============================================================================
# This is the SINGLE SOURCE OF TRUTH for admission-pipeline synchronization
#
# ⚠️ CRITICAL: Do NOT hardcode stage/status IDs anywhere else in the codebase
# ⚠️ Changing these values synchronizes the entire system
# =============================================================================

ADMISSION_EVENT_PROJECTIONS = {
    # -------------------------------------------------------------------------
    # Lead Creation (before admission)
    # -------------------------------------------------------------------------
    "lead_created": AdmissionEventProjection(
        event="lead_created",
        admission_status=None,  # No profile yet
        consultation_status_id="sts00",
        consultation_name="Chưa tiếp cận",  # Updated name
        pipeline_stage_id="stg01",
        stage_name="Chưa tư vấn",
        system_note_template="[HỆ THỐNG] Lead được tạo trên hệ thống",
        skip_if_converted=False,  # Initial state, always apply
    ),

    # -------------------------------------------------------------------------
    # Officer Contact (consultation begins)
    # -------------------------------------------------------------------------
    "officer_contacted": AdmissionEventProjection(
        event="officer_contacted",
        admission_status=None,
        consultation_status_id="sts05",
        consultation_name="Hẹn liên hệ lại",  # Updated name
        pipeline_stage_id="stg02",
        stage_name="Đang tư vấn",
        system_note_template="[HỆ THỐNG] Bắt đầu quá trình tư vấn",
        skip_if_converted=False,
    ),

    # -------------------------------------------------------------------------
    # Lead Agrees to Consult
    # -------------------------------------------------------------------------
    "lead_agrees": AdmissionEventProjection(
        event="lead_agrees",
        admission_status=None,
        consultation_status_id="sts06",
        consultation_name="Đồng ý tư vấn",
        pipeline_stage_id="stg02",
        stage_name="Đang tư vấn",
        system_note_template="Học viên đồng ý tìm hiểu chương trình",
        skip_if_converted=False,
    ),

    # -------------------------------------------------------------------------
    # Admission Profile CREATED (draft state)
    # -------------------------------------------------------------------------
    "profile_created": AdmissionEventProjection(
        event="profile_created",
        admission_status="draft",
        consultation_status_id="sts06",  # Stay in "Đồng ý tư vấn"
        consultation_name="Đồng ý tư vấn",
        pipeline_stage_id="stg02",  # Stay in "Đang tư vấn"
        stage_name="Đang tư vấn",
        system_note_template="[HỆ THỐNG] Hồ sơ xét tuyển được khởi tạo (Draft) - Profile #{profile_id}",
        skip_if_converted=True,
    ),

    # -------------------------------------------------------------------------
    # ✅ Admission Profile SUBMITTED
    # -------------------------------------------------------------------------
    "profile_submitted": AdmissionEventProjection(
        event="profile_submitted",
        admission_status="submitted",
        consultation_status_id="sts07",
        consultation_name="Đã tiếp nhận hồ sơ",  # Updated name
        pipeline_stage_id="stg03",  # ✅ Move to "Đã nộp hồ sơ"
        stage_name="Đã nộp hồ sơ",
        system_note_template="[HỆ THỐNG] Hồ sơ xét tuyển đã được nộp - Profile #{profile_id}",
        skip_if_converted=True,
    ),

    # -------------------------------------------------------------------------
    # ✅ APPLICATION FEE PAID (lệ phí xét tuyển - before approval)
    # -------------------------------------------------------------------------
    "application_fee_paid": AdmissionEventProjection(
        event="application_fee_paid",
        admission_status="submitted",  # Still submitted, waiting for approval
        consultation_status_id="sts13",
        consultation_name="Đã hoàn tất lệ phí xét tuyển",
        pipeline_stage_id="stg03",  # Stay in "Đã nộp hồ sơ" (fee is part of submission)
        stage_name="Đã nộp hồ sơ",
        system_note_template="[HỆ THỐNG] Đã xác nhận thanh toán lệ phí xét tuyển - Profile #{profile_id}, Mã GD: {transaction_id}",
        skip_if_converted=True,
    ),

    # -------------------------------------------------------------------------
    # ✅ Admission Profile APPROVED
    # -------------------------------------------------------------------------
    "profile_approved": AdmissionEventProjection(
        event="profile_approved",
        admission_status="approved",
        consultation_status_id="sts09",
        consultation_name="Đủ điều kiện nhập học",  # Updated name
        pipeline_stage_id="stg04",  # ✅ Move to "Chờ nhập học"
        stage_name="Chờ nhập học",
        system_note_template="[HỆ THỐNG] Hồ sơ xét tuyển đã được duyệt - Profile #{profile_id}",
        skip_if_converted=True,
    ),

    # -------------------------------------------------------------------------
    # Admission Profile CONFIRMED (student confirms enrollment intent)
    # -------------------------------------------------------------------------
    # ⚠️ NOTE: This is an intent confirmation, not a pipeline milestone.
    # Lead remains in "Chờ nhập học".
    "profile_confirmed": AdmissionEventProjection(
        event="profile_confirmed",
        admission_status="confirmed",
        consultation_status_id="sts09",  # Stay at "Đủ điều kiện nhập học"
        consultation_name="Đủ điều kiện nhập học",  # Updated name
        pipeline_stage_id="stg04",  # Stay at "Chờ nhập học"
        stage_name="Chờ nhập học",
        system_note_template="[HỆ THỐNG] Học viên xác nhận ý định nhập học - Profile #{profile_id}",
        skip_if_converted=True,
    ),

    # -------------------------------------------------------------------------
    # TUITION FEE CALCULATED (Finance Phase - Gate 1)
    # -------------------------------------------------------------------------
    # Triggers when tuition fee is calculated for approved profile
    # Lead moves to "Chờ học phí" - waiting for payment
    "tuition_fee_calculated": AdmissionEventProjection(
        event="tuition_fee_calculated",
        admission_status="approved",  # Profile is approved, waiting for fee payment
        consultation_status_id="sts14",
        consultation_name="Chưa hoàn tất học phí",
        pipeline_stage_id="stg05",  # Move to "Đã nộp học phí" stage (fee phase)
        stage_name="Đã nộp học phí",
        system_note_template="[HỆ THỐNG] Học phí đã được tính toán - Profile #{profile_id}, Số tiền: {amount} VND",
        skip_if_converted=True,
    ),

    # -------------------------------------------------------------------------
    # TUITION FEE PAID (Finance Phase - Gate 2 Passed)
    # -------------------------------------------------------------------------
    # Triggers when tuition fee is fully paid or waived
    # Lead moves to "Đã hoàn tất học phí" - ready for enrollment
    "tuition_fee_paid": AdmissionEventProjection(
        event="tuition_fee_paid",
        admission_status="confirmed",  # Profile is confirmed, fee cleared
        consultation_status_id="sts10",
        consultation_name="Đã hoàn tất học phí",
        pipeline_stage_id="stg05",  # Stay in "Đã nộp học phí" stage
        stage_name="Đã nộp học phí",
        system_note_template="[HỆ THỐNG] Học phí đã được thanh toán đầy đủ - Profile #{profile_id}, Mã GD: {transaction_id}",
        skip_if_converted=True,
    ),

    # -------------------------------------------------------------------------
    # TUITION FEE REFUNDED (Finance Phase - Withdrawal)
    # -------------------------------------------------------------------------
    # Triggers when tuition fee is refunded (full or partial leading to withdrawal)
    "tuition_fee_refunded": AdmissionEventProjection(
        event="tuition_fee_refunded",
        admission_status="confirmed",  # Was confirmed but withdrew
        consultation_status_id="sts18",
        consultation_name="Đã hoàn học phí",
        pipeline_stage_id="stg05",  # Stay in Fee stage
        stage_name="Đã nộp học phí",
        system_note_template="[HỆ THỐNG] Học phí đã được hoàn trả - Profile #{profile_id}, Số tiền hoàn: {amount} VND",
        skip_if_converted=False,  # Allow transition even if converted (dropout)
    ),

    # -------------------------------------------------------------------------
    # Fee Recorded (manual by officer) - LEGACY
    # -------------------------------------------------------------------------
    # ⚠️ NOTE: Manual financial confirmation event. Use tuition_fee_paid instead.
    "fee_recorded": AdmissionEventProjection(
        event="fee_recorded",
        admission_status="confirmed",  # Still confirmed, not yet enrolled
        consultation_status_id="sts10",
        consultation_name="Đã hoàn tất học phí",  # Updated name
        pipeline_stage_id="stg05",  # Move to "Đã nộp học phí"
        stage_name="Đã nộp học phí",
        system_note_template="[HỆ THỐNG] Học viên đã hoàn tất học phí - Profile #{profile_id}",
        skip_if_converted=True,
    ),

    # -------------------------------------------------------------------------
    # ✅ Student ENROLLED (final success state)
    # -------------------------------------------------------------------------
    "profile_enrolled": AdmissionEventProjection(
        event="profile_enrolled",
        admission_status="enrolled",
        consultation_status_id="sts11",
        consultation_name="Đã xác nhận nhập học",  # Updated name
        pipeline_stage_id="stg06",  # ✅ Move to "Đã nhập học"
        stage_name="Đã nhập học",
        system_note_template="[HỆ THỐNG] Học viên đã nhập học chính thức - Profile #{profile_id}, Mã SV: {student_code}",
        skip_if_converted=False,  # Allow update to enrolled even if already converted
    ),

    # -------------------------------------------------------------------------
    # Admission Profile REJECTED (Request Changes)
    # -------------------------------------------------------------------------
    "profile_rejected": AdmissionEventProjection(
        event="profile_rejected",
        admission_status="rejected",
        consultation_status_id="sts16",  # ✅ "Hồ sơ không đạt yêu cầu"
        consultation_name="Hồ sơ không đạt yêu cầu",  # Updated name
        pipeline_stage_id="stg04",  # Move to "Chờ nhập học" (stg04)
        stage_name="Chờ nhập học",
        system_note_template="[HỆ THỐNG] Hồ sơ không đạt yêu cầu - Profile #{profile_id}. Lý do: {reason}",
        skip_if_converted=True,
    ),

    # -------------------------------------------------------------------------
    # Admission Profile RESUBMITTED (after rejection)
    # -------------------------------------------------------------------------
    "profile_resubmitted": AdmissionEventProjection(
        event="profile_resubmitted",
        admission_status="resubmitted",
        consultation_status_id="sts07",
        consultation_name="Đã tiếp nhận hồ sơ",  # Updated name
        pipeline_stage_id="stg03",  # Back to "Đã nộp hồ sơ"
        stage_name="Đã nộp hồ sơ",
        system_note_template="[HỆ THỐNG] Hồ sơ xét tuyển được nộp lại sau khi chỉnh sửa - Profile #{profile_id}",
        skip_if_converted=True,
    ),

    # -------------------------------------------------------------------------
    # Admin Override (force approve without validation)
    # -------------------------------------------------------------------------
    "profile_overridden": AdmissionEventProjection(
        event="profile_overridden",
        admission_status="overridden",
        consultation_status_id="sts09",
        consultation_name="Đủ điều kiện nhập học",  # Updated name
        pipeline_stage_id="stg04",
        stage_name="Chờ nhập học",
        system_note_template="[HỆ THỐNG] Hồ sơ được duyệt đặc biệt bởi Admin - Profile #{profile_id}. Lý do: {reason}",
        skip_if_converted=True,
    ),

    # -------------------------------------------------------------------------
    # Student Drop / Refund (negative terminal states)
    # -------------------------------------------------------------------------
    "student_dropped": AdmissionEventProjection(
        event="student_dropped",
        admission_status="enrolled",  # Still enrolled in admission system
        consultation_status_id="sts12",
        consultation_name="Ngưng theo học",  # Updated name
        pipeline_stage_id="stg07",  # Move to "Không đi học"
        stage_name="Không đi học",
        system_note_template="[HỆ THỐNG] Học viên không tiếp tục theo học - Profile #{profile_id}",
        skip_if_converted=False,  # Allow transition from converted to dropped
    ),

    # -------------------------------------------------------------------------
    # Admission Profile REVISION REQUESTED (officer requests document fix)
    # -------------------------------------------------------------------------
    "profile_revision_requested": AdmissionEventProjection(
        event="profile_revision_requested",
        admission_status="revision_requested",  # Dedicated status for revision requests
        consultation_status_id="sts17",
        consultation_name="Yêu cầu bổ sung hồ sơ",
        pipeline_stage_id="stg03",  # Stay in "Đã nộp hồ sơ"
        stage_name="Đã nộp hồ sơ",
        system_note_template="[HỆ THỐNG] Yêu cầu bổ sung/chỉnh sửa hồ sơ - Profile #{profile_id}. Lý do: {reason}",
        skip_if_converted=True,
    ),

    # -------------------------------------------------------------------------
    # Admission Profile WITHDRAWN (applicant/officer withdraws)
    # -------------------------------------------------------------------------
    "profile_withdrawn": AdmissionEventProjection(
        event="profile_withdrawn",
        admission_status="withdrawn",
        consultation_status_id="sts08",
        consultation_name="Từ chối tư vấn",
        pipeline_stage_id="stg07",  # Move to "Không đi học"
        stage_name="Không đi học",
        system_note_template="[HỆ THỐNG] Hồ sơ xét tuyển đã bị rút - Profile #{profile_id}. Lý do: {reason}",
        skip_if_converted=False,  # Allow withdrawal even if converted
    ),

    "student_refunded": AdmissionEventProjection(
        event="student_refunded",
        admission_status="confirmed",  # Was confirmed but withdrew
        consultation_status_id="sts18",  # Changed to sts18 - "Đã hoàn học phí"
        consultation_name="Đã hoàn học phí",  # Updated name
        pipeline_stage_id="stg05",  # Stay in Fee stage
        stage_name="Đã nộp học phí",
        system_note_template="[HỆ THỐNG] Học viên đã hoàn học phí - Profile #{profile_id}",
        skip_if_converted=True,
    ),
}


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def get_projection(event: str) -> Optional[AdmissionEventProjection]:
    """
    Get the canonical projection for an admission event.

    Args:
        event: Event identifier (e.g., "profile_submitted")

    Returns:
        AdmissionEventProjection or None if event not found

    Example:
        >>> projection = get_projection("profile_submitted")
        >>> projection.pipeline_stage_id
        "stg03"
    """
    return ADMISSION_EVENT_PROJECTIONS.get(event)


def validate_projection(event: str) -> AdmissionEventProjection:
    """
    Get projection with validation (raises error if not found).

    Args:
        event: Event identifier

    Returns:
        AdmissionEventProjection

    Raises:
        ValueError: If event not found in mapping
    """
    projection = get_projection(event)
    if projection is None:
        raise ValueError(
            f"No projection defined for admission event: {event}. "
            f"Valid events: {', '.join(ADMISSION_EVENT_PROJECTIONS.keys())}"
        )
    return projection


def list_all_events() -> list[str]:
    """Get list of all defined admission events."""
    return list(ADMISSION_EVENT_PROJECTIONS.keys())


def get_events_for_stage(stage_id: str) -> list[AdmissionEventProjection]:
    """
    Get all events that transition to a specific pipeline stage.

    Args:
        stage_id: Pipeline stage ID (e.g., "stg03")

    Returns:
        List of projections targeting this stage
    """
    return [
        proj for proj in ADMISSION_EVENT_PROJECTIONS.values()
        if proj.pipeline_stage_id == stage_id
    ]


def get_events_for_consultation_status(status_id: str) -> list[AdmissionEventProjection]:
    """
    Get all events that transition to a specific consultation status.

    Args:
        status_id: Consultation status ID (e.g., "sts07")

    Returns:
        List of projections targeting this status
    """
    return [
        proj for proj in ADMISSION_EVENT_PROJECTIONS.values()
        if proj.consultation_status_id == status_id
    ]
