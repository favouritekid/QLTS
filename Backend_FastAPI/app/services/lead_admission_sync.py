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
    - create_profile() → sts06 (Đồng ý tư vấn) via milestone consultation
    - submit_and_evaluate() → sts07 (Đã tiếp nhận)
    - record_application_fee_payment() → sts13 (Đã hoàn lệ phí xét tuyển)
    - approve_profile() → sts09 (Đủ điều kiện)
    - reject_profile() → sts16 (Không đạt)
    - request_revision() → sts17 (Yêu cầu bổ sung hồ sơ)
    - enroll_student() → sts11 (Đã xác nhận nhập học)

================================================================================
HỢP ĐỒNG CHIẾU TÀI CHÍNH → LEAD  (nguồn chuẩn — canonical)
================================================================================

Đây là nguồn chuẩn cho **điều kiện kích hoạt, cổng ở phía gọi, no-op, đường
đảo, và quyền sở hữu giao dịch**. Nó KHÔNG phải nguồn chuẩn cho ID trạng
thái/giai đoạn — thứ đó thuộc ``app/core/admission_event_mapping.py``.

Thêm một lượt chiếu tài chính mới mà không thêm dòng ở đây là đúng lớp lỗi
bảng này sinh ra để chặn. ``tests/unit/test_lead_finance_projection_contract.py``
đọc mã bằng AST và ĐỎ khi tập callsite lệch khỏi bảng.

--------------------------------------------------------------------------------
1. Đích KHÔNG hardcode
--------------------------------------------------------------------------------
Bốn hằng dưới đây đọc từ ``admission_event_mapping.get_projection(<event_key>)``;
mã ``stsNN`` chỉ là GIÁ TRỊ DỰ PHÒNG khi projection vắng mặt. Hợp đồng là
``event_key``, không phải chuỗi ``"sts14"``.

    event_key                 hằng trong tệp này            dự phòng
    ------------------------- ----------------------------- --------
    application_fee_paid      FEE_PAID_STATUS               sts13
    tuition_fee_calculated    TUITION_CALCULATED_STATUS     sts14
    tuition_fee_paid          TUITION_PAID_STATUS           sts10
    tuition_fee_refunded      TUITION_REFUNDED_STATUS       sts18

Bốn mã dự phòng ấy cũng chính là ``FEE_OVERLAY_LEAD_STATUSES`` — tập mà
submit/resubmit phải GIỮ, không được kéo lead về sts07.

--------------------------------------------------------------------------------
2. Bảng chiếu: forward ↔ reverse, và AI gọi
--------------------------------------------------------------------------------
    | Sự kiện tài chính     | Forward                      | Nơi gọi (service.hàm)                                    |
    |-----------------------|------------------------------|----------------------------------------------------------|
    | Lệ phí xét tuyển đóng | sync_lead_fee_paid           | admission_service.record_application_fee_payment          |
    | Học phí HK1 đã TÍNH   | sync_lead_tuition_calculated | fee_calculation_service.FeeCalculationService.calculate_fee |
    | Học phí HK1 SETTLED   | sync_lead_tuition_paid       | payment_service.PaymentService.verify_payment              |
    |                       |                              | payment_intent_service.PaymentIntentService._create_payment_from_intent |
    |                       |                              | payment_import_service.commit_batch                        |
    |                       |                              | fee_calculation_service.FeeCalculationService.waive_fee    |
    |                       |                              | fee_calculation_service.FeeCalculationService.reprice_for_major_change |
    | Học phí HK1 đã hoàn   | sync_lead_tuition_refunded   | payment_service.RefundService.process_approved_refund      |

    | Đường ĐẢO                     | Reverse                        | Nơi gọi                                                  |
    |-------------------------------|--------------------------------|----------------------------------------------------------|
    | Huỷ khoản phí                 | revert_lead_tuition_calculated | fee_calculation_service.FeeCalculationService.cancel_fee  |
    | Void lô import / đổi ngành    | revert_lead_tuition_paid       | payment_import_service.void_batch                          |
    |                               |                                | fee_calculation_service.FeeCalculationService.reprice_for_major_change |
    | Lệ phí xét tuyển              | **KHÔNG CÓ** — lệ phí không hoàn (cố ý)                                                   |

Tổng: **11 callsite trong 5 service**. Con số này được test AST khoá lại.

--------------------------------------------------------------------------------
3. SETTLED nghĩa là gì  (đừng dùng chữ "cleared" — nó là ngữ nghĩa CŨ)
--------------------------------------------------------------------------------
``sync_lead_tuition_paid`` chỉ được bắn khi HK1 đạt **SETTLED**:

    settled  ⇔  paid  OR  waived  OR  remaining (final − paid − waived) ≤ 0

Một lần trả **MỘT PHẦN** (remaining > 0) **KHÔNG** phải settled — lead ở lại
``TUITION_CALCULATED_STATUS``. Chỉ bắn MỘT lần, ở lượt chuyển
``chưa-settled → settled``. Vị từ chuẩn: ``fee_calculation_service.is_hk1_settled``.

--------------------------------------------------------------------------------
4. Cổng nằm ở PHÍA GỌI — đọc thân hàm sẽ không thấy
--------------------------------------------------------------------------------
    | Cổng                                        | Ở đâu                                   |
    |---------------------------------------------|-----------------------------------------|
    | Hoàn tiền TRONG quy trình rút thì KHÔNG chiếu sts18 | ``payment_service`` — điều kiện ``profile.status != "withdrawal_pending"`` ngay trước lời gọi ``sync_lead_tuition_refunded``. Hoàn tiền NGOÀI quy trình rút vẫn chiếu bình thường. |
    | Chỉ bắn ở lượt chuyển sang settled          | ``payment_service`` — ``if not was_hk1_settled and now_hk1_settled`` |

--------------------------------------------------------------------------------
5. Hai nhánh KHÔNG chiếu — cũng là hợp đồng
--------------------------------------------------------------------------------
Đây không phải "forward thiếu reverse"; đây là "cố ý không forward".

    | profile.status       | Hằng                        | Vì sao                                    |
    |----------------------|-----------------------------|-------------------------------------------|
    | ``result_published`` | ``_RESULT_PUBLISHED_NO_OP`` | công bố kết quả không tự nó đổi bước tư vấn |
    | ``withdrawal_pending`` | ``_WITHDRAWAL_PENDING_NO_OP`` | GIỮ lead tại chỗ tới khi hoàn xong. Finalize (→ ``withdrawn``) mới đẩy sts08; admin huỷ rút (→ ``draft``) rơi vào short-circuit draft |

--------------------------------------------------------------------------------
6. ``_revert_lead_projection`` — hai hàng rào
--------------------------------------------------------------------------------
Cả hai ``revert_*`` đều uỷ quyền cho helper này:

  1. Chỉ hành động khi lead ĐANG ở đúng ``projected_status``. Lead đã đi xa hơn
     (đã nhập học…) thì để yên.
  2. Khôi phục trạng thái trước đó ĐỌC NGUYÊN VĂN từ hàng ``LeadStatusHistory``
     gần nhất đã đặt ``projected_status`` — không tái suy, không đích cứng.
     Không có hàng lịch sử nào ⇒ bỏ qua, trả ``False``.

--------------------------------------------------------------------------------
7. ``force=True`` — đường DUY NHẤT bypass floor của ``sync_lead_from_admission``
--------------------------------------------------------------------------------
(Không phải "đường duy nhất đi lùi" — hai ``revert_*`` ở mục 6 cũng đưa lead về
trạng thái trước. Khác biệt: ``revert_*`` đọc ``LeadStatusHistory``, còn
``force`` bỏ qua hàng rào rồi đi thẳng tới ánh xạ draft.)

``sync_lead_from_admission(..., force=False)``. Với ``force=True`` hàm bỏ qua
CẢ HAI hàng rào chống-lùi: short-circuit ``profile.status == "draft"`` và sàn
``_should_apply_admission_floor``.

Chỉ MỘT nơi gọi: ``admission_service.cancel_withdrawal`` (``withdrawal_pending``
→ ``draft``), kéo lead về ánh xạ draft cho khớp hồ sơ vừa kích hoạt lại.

⚠️ Khác hai ``revert_*``: ``force`` **KHÔNG** đọc ``LeadStatusHistory`` — nó đi
thẳng tới ánh xạ draft. Nên câu "reverse khôi phục nguyên văn từ lịch sử" đúng
cho ``revert_*``, KHÔNG đúng cho ``force``.

--------------------------------------------------------------------------------
8. Quyền sở hữu giao dịch
--------------------------------------------------------------------------------
Mọi hàm ở tệp này dùng ``flush()``, **không** ``commit()``. Chúng chạy trong
giao dịch của người gọi và người gọi là bên commit. Một hàm chiếu tự commit sẽ
chốt nửa vời khi phần nghiệp vụ phía sau đổ.
"""

from typing import Optional
import structlog
from sqlalchemy import select
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
    # ----- Legacy vocabulary (currently writable; CHECK constraint allowed) -----
    "draft":        "sts06",   # Đồng ý tư vấn (chưa nộp, chỉ khởi tạo)
    "submitted":    "sts07",   # Đã tiếp nhận (đã nộp, chờ duyệt)
    "resubmitted":  "sts07",   # Đã tiếp nhận (nộp lại sau reject)
    "approved":     "sts09",   # Đủ điều kiện (đã duyệt)
    "confirmed":    "sts09",   # Đủ điều kiện (xác nhận ý định nhập học)
    "overridden":   "sts09",   # Đủ điều kiện (admin override)
    "rejected":     "sts16",   # Không đạt (bị từ chối)
    "revision_requested": "sts17",  # Yêu cầu bổ sung hồ sơ
    "enrolled":     "sts11",   # Đã xác nhận nhập học (terminal)
    "withdrawn":    "sts08",   # Từ chối tư vấn (rút hồ sơ, terminal)
    # ----- Choice-engine vocabulary (forward-compat for #15 / Phase 1) -----
    # NOT YET WRITABLE: CHECK constraint ck_admission_profile_status still
    # rejects these strings on prod. Sites that READ this map therefore
    # behave correctly the moment Phase 1 ships the constraint extension
    # and #16 wires the writes — no follow-up patch required here.
    "admitted":     "sts09",   # Equivalent of legacy approved/overridden
    "reviewing":    "sts07",   # FLOOR — see PRE_APPLICATION_LEAD_STATUSES
    "waitlisted":   "sts07",   # FLOOR — see PRE_APPLICATION_LEAD_STATUSES
    # ``result_published`` is intentionally absent. It is a future
    # intermediate state / T6 broadcast marker; ``sync_lead_from_admission``
    # short-circuits it as an explicit no-op so the lead pipeline is never
    # mutated when the choice-engine state machine lands the string on
    # ``profile.status`` (per PLAN). See _RESULT_PUBLISHED_NO_OP below.
}

# Profile statuses that should only floor a lead UP from a pre-application
# consultation status, never DOWN from a later admission/fee/enrolled state.
# Rationale: a profile being re-evaluated (``reviewing``) or that enters the
# waitlist (``waitlisted``) must not regress a lead already past sts07
# (e.g. ``sts09`` Đủ điều kiện, ``sts10`` Đã hoàn tất học phí, ``sts11`` Đã
# nhập học). Floor only applies when the lead is still in the consultation
# phase or has no consultation status set.
FLOOR_FROM_PROFILE_STATUSES: frozenset[str] = frozenset({"reviewing", "waitlisted"})

# Lead consultation statuses considered "below the admission floor".
# Values come from the canonical seed (``scripts/data/consultation_status_v3.csv``):
# the consultation-phase ids plus ``None`` for newly created leads. Universal
# statuses (sts01/sts15/sts19) are NOT included — they overlay an underlying
# pipeline_stage_id that may already be at sts07+, so flooring them up could
# overwrite a valid mid-admission state.
PRE_APPLICATION_LEAD_STATUSES: frozenset = frozenset({
    None, "sts00", "sts02", "sts03", "sts04", "sts05", "sts06",
})

# Profile submit transitions that must not REGRESS a lead already carrying a
# finance overlay. ``submitted`` / ``resubmitted`` normally floor the lead up to
# sts07 (Đã tiếp nhận hồ sơ), but with the prepay fast-track a lead can reach
# sts13 (lệ phí đã đóng) — or a later tuition overlay — while the profile is
# still ``draft``. Submitting then must NOT pull the lead back down to sts07 and
# erase the "đã đóng tiền" signal. This is regression SL1.
SUBMIT_FLOOR_PROFILE_STATUSES: frozenset[str] = frozenset({"submitted", "resubmitted"})

# Lead consultation statuses representing a finance overlay that sits ABOVE the
# "hồ sơ đã tiếp nhận" milestone — application fee paid (sts13) plus the HK1
# tuition lifecycle (sts14 chờ đóng / sts10 đã đóng / sts18 đã hoàn). A
# submit/resubmit must PRESERVE these. NOTE: rejected (sts16) and
# revision_requested (sts17) are intentionally ABSENT so a genuine resubmit
# after a reject/revision still floors the lead back up to sts07.
FEE_OVERLAY_LEAD_STATUSES: frozenset[str] = frozenset(
    {"sts13", "sts14", "sts10", "sts18"}
)

# Admission milestone events that represent a submit/resubmit transition.
# ``_create_admission_milestone_consultation`` is the CANONICAL writer of lead
# state on submit — it runs BEFORE the officer-independent
# ``sync_lead_from_admission`` fallback and sets the lead unconditionally. It
# must therefore apply the same FEE_OVERLAY floor as ``_should_apply_admission_floor``;
# otherwise the overlay regresses to sts07 on the officer path before the sync
# guard ever sees it (SL1). Keep this set in sync with SUBMIT_FLOOR_PROFILE_STATUSES.
SUBMIT_FLOOR_EVENTS: frozenset[str] = frozenset(
    {"profile_submitted", "profile_resubmitted"}
)

# Sentinel for ``profile.status == "result_published"``. Kept as a constant
# so the test suite can lock the no-op contract without restringifying the
# value at the call site.
_RESULT_PUBLISHED_NO_OP: str = "result_published"

# Sentinel for ``profile.status == "withdrawal_pending"`` (PR-B). While a
# withdrawal waits for its refund to be processed, the lead KEEPS its current
# consultation status (owner decision): sync is an explicit no-op here. The
# pipeline only moves to sts08 when the withdrawal finalizes (status →
# ``withdrawn``, handled by the withdrawn mapping), or stays put if the admin
# cancels the withdrawal (status → ``draft``, handled by the draft short-circuit).
_WITHDRAWAL_PENDING_NO_OP: str = "withdrawal_pending"


def _should_apply_admission_floor(
    profile_status: str,
    lead_consultation_status_id: Optional[str],
) -> bool:
    """Pure decision rule guarding regression-prone profile statuses.

    Returns ``True`` when the sync should proceed and ``False`` to preserve a
    later lead state. Two guarded families:

    1. ``reviewing`` / ``waitlisted`` (choice-engine floor-up): only progress a
       lead still in the pre-application phase; never regress one past sts07.
    2. ``submitted`` / ``resubmitted``: floor the lead up to sts07 UNLESS it
       already carries a finance overlay (sts13/sts14/sts10/sts18). This stops
       the prepay regression (SL1) where submitting after paying the
       application fee dragged the lead sts13 → sts07. Resubmits from
       rejected/revision (sts16/sts17) are NOT overlays, so they still progress.

    Every other status short-circuits to ``True`` so the existing fall-through
    logic applies unchanged.
    """
    if profile_status in FLOOR_FROM_PROFILE_STATUSES:
        return lead_consultation_status_id in PRE_APPLICATION_LEAD_STATUSES
    if profile_status in SUBMIT_FLOOR_PROFILE_STATUSES:
        return lead_consultation_status_id not in FEE_OVERLAY_LEAD_STATUSES
    return True


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
    force: bool = False,
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

    # Skip draft — milestone consultation is the canonical sync for profile creation.
    # Avoids double LeadStatusHistory records when create_profile() calls both
    # sync_lead_from_admission() and _create_admission_milestone_consultation().
    # F7: ``force=True`` (admin cancel-withdrawal, wpend→draft) DELIBERATELY
    # resets the held lead back to the draft mapping (sts06) so the reactivated
    # draft profile and its lead are consistent — there is no milestone
    # consultation on this path, so no double-history risk.
    if profile.status == "draft" and not force:
        log.debug(
            "sync_lead_from_admission: Skipping draft, milestone consultation handles this",
            profile_id=profile.id,
        )
        return False

    # Explicit no-op for ``result_published``. Treated as a future
    # intermediate state / T6 broadcast marker — the per-profile lead
    # transition is owned by the subsequent T7 (``admitted``) / T8
    # (``waitlisted``) / T9 (``rejected``) status. Short-circuiting
    # here keeps the sync silent during the broadcast and prevents an
    # unmapped fall-through from logging a misleading "unknown status"
    # warning if a future state machine lands the string transiently
    # on ``profile.status``.
    if profile.status == _RESULT_PUBLISHED_NO_OP:
        log.debug(
            "sync_lead_from_admission: result_published is a future intermediate "
            "state / T6 broadcast marker — explicit no-op for lead sync",
            profile_id=profile.id,
        )
        return False

    # Explicit no-op for ``withdrawal_pending`` (PR-B). Holds the lead at its
    # current consultation status until the refund finalizes (→ withdrawn → sts08)
    # or is cancelled (→ draft, short-circuited above). Prevents an unmapped
    # fall-through from logging a misleading "unknown status" warning.
    if profile.status == _WITHDRAWAL_PENDING_NO_OP:
        log.debug(
            "sync_lead_from_admission: withdrawal_pending holds the lead status "
            "until the refund finalizes — explicit no-op for lead sync",
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

    # Regression guard: floor-only statuses (``reviewing`` / ``waitlisted``)
    # must not regress a lead past sts07, and ``submitted`` / ``resubmitted``
    # must not erase a finance overlay (sts13/sts14/sts10/sts18 — SL1). See the
    # _should_apply_admission_floor docstring for the rationale.
    # F7: ``force`` bypasses the anti-regression floor — a cancel-withdrawal
    # reset INTENDS to move the lead backward (sts07/sts14 → sts06 draft).
    if not force and not _should_apply_admission_floor(
        profile.status, lead.consultation_status_id
    ):
        log.debug(
            "sync_lead_from_admission: Floor-only status, lead already past "
            "pre-application phase — preserving later state",
            lead_id=lead.id,
            profile_id=profile.id,
            profile_status=profile.status,
            current_lead_status=lead.consultation_status_id,
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

    # Guard: verify DB consultation_status.stage_id matches admission_event_mapping.
    # This detects silent drift between code projections and DB seed data.
    # Logs ERROR (triggers monitoring alerts) but does NOT raise — allows operation
    # to proceed with DB-authoritative value to avoid blocking runtime.
    _event_key = f"profile_{profile.status}"
    _projection = get_projection(_event_key)
    if _projection and new_status.stage_id != _projection.pipeline_stage_id:
        log.error(
            "STAGE DRIFT DETECTED: DB consultation_status.stage_id does not match "
            "admission_event_mapping projection. Seed data may be out of sync with code. "
            "Proceeding with DB value but this MUST be investigated.",
            status_id=target_status_id,
            db_stage_id=new_status.stage_id,
            expected_stage_id=_projection.pipeline_stage_id,
            admission_status=profile.status,
            event_key=_event_key,
        )

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
    Sync lead consultation status when HK1 tuition fee is calculated.

    Moves lead to sts14 (Chưa hoàn tất học phí / Chờ đóng học phí).

    ADR-002 PR 5: This function is for HK1 only. Callers MUST gate
    invocation to semester_no == 1 before calling. HK2+ fee creation
    must not project into the admission pipeline.

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
    Sync lead consultation status when HK1 tuition reaches SETTLED state.

    Moves lead to sts10 (Đã hoàn tất học phí).

    "Settled" means paid, waived, or remaining (final - paid - waived) <= 0.
    A PARTIAL payment is NOT settled — the lead stays at sts14 "Chưa hoàn
    tất học phí". (This is stricter than the enrollment gate, which per
    ADR-002 still lets a partial payment pass.) Callers MUST:
    1. Gate invocation to semester_no == 1 (HK1 only)
    2. Fire only on the first transition into settled state (use
       is_hk1_settled pre/post pattern to avoid duplicate syncs)

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


async def _revert_lead_projection(
    db: AsyncSession,
    profile: models.AdmissionProfile,
    *,
    projected_status: str,
    default_reason: str,
    log_label: str,
    changed_by_user_id: Optional[int] = None,
    reason: Optional[str] = None,
) -> bool:
    """Shared body for reverting a finance→lead projection.

    Restores the lead to the status it held BEFORE it was projected into
    ``projected_status`` — read VERBATIM (no re-derive) from the most-recent
    ``LeadStatusHistory`` row that set it. Symmetric to the forward sync.

    Safety (same for both the sts10 and sts14 reverts):
      1. Only acts when the lead is CURRENTLY at ``projected_status`` — a lead
         that advanced afterwards is left untouched (never drag the pipeline
         back).
      2. No forward history row → cannot know the prior state → skip + log.

    Returns True if reverted, False if skipped.
    """
    lead = profile.lead
    if not lead:
        log.warning(f"{log_label}: Lead not loaded", profile_id=profile.id)
        return False

    # Guard 1: only revert while the lead still sits at the projected status.
    if lead.consultation_status_id != projected_status:
        log.debug(
            f"{log_label}: lead not at projected status, skip",
            lead_id=lead.id,
            current_status=lead.consultation_status_id,
        )
        return False

    # Most-recent forward row (→ projected_status) carries the prior state.
    hist = (
        await db.execute(
            select(models.LeadStatusHistory)
            .where(
                models.LeadStatusHistory.lead_id == lead.id,
                models.LeadStatusHistory.new_consultation_status_id
                == projected_status,
            )
            .order_by(models.LeadStatusHistory.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if hist is None:
        log.warning(f"{log_label}: no forward history, skip", lead_id=lead.id)
        return False

    cur_status = lead.status
    cur_consult = lead.consultation_status_id
    cur_stage = lead.pipeline_stage_id

    # Restore the pre-projection values. lead.status is NOT NULL → fall back to
    # the current value if the history old_status is empty (≈never: default 'new').
    lead.consultation_status_id = hist.old_consultation_status_id
    lead.pipeline_stage_id = hist.old_pipeline_stage_id
    lead.status = hist.old_status or cur_status

    db.add(
        models.LeadStatusHistory(
            lead_id=lead.id,
            old_status=cur_status,
            new_status=lead.status,
            old_consultation_status_id=cur_consult,
            new_consultation_status_id=lead.consultation_status_id,
            old_pipeline_stage_id=cur_stage,
            new_pipeline_stage_id=lead.pipeline_stage_id,
            changed_by_user_id=changed_by_user_id,
            reason=reason or default_reason,
        )
    )
    await db.flush()

    log.info(
        f"{log_label}: lead reverted",
        lead_id=lead.id,
        profile_id=profile.id,
        to_consultation_status=lead.consultation_status_id,
    )
    return True


async def revert_lead_tuition_paid(
    db: AsyncSession,
    profile: models.AdmissionProfile,
    changed_by_user_id: Optional[int] = None,
    reason: Optional[str] = None,
) -> bool:
    """Đảo projection "HK1 đã đóng": đưa lead VỀ status TRƯỚC khi
    ``sync_lead_tuition_paid`` đẩy lên sts10 (Đã hoàn tất học phí).

    Dùng khi VOID (đảo) lô import đã ghi nhận học phí HK1 — KẾ TOÁN SỬA NHẦM ghi
    nhận, KHÔNG phải học sinh rút (luồng rút = ``sync_lead_tuition_refunded`` →
    sts18). Caller PHẢI gate: chỉ HK1 + chỉ khi fee KHÔNG còn settled sau đảo.
    """
    return await _revert_lead_projection(
        db,
        profile,
        projected_status=TUITION_PAID_STATUS,
        default_reason="Đảo ghi nhận học phí (void lô import)",
        log_label="revert_lead_tuition_paid",
        changed_by_user_id=changed_by_user_id,
        reason=reason,
    )


async def revert_lead_tuition_calculated(
    db: AsyncSession,
    profile: models.AdmissionProfile,
    changed_by_user_id: Optional[int] = None,
    reason: Optional[str] = None,
) -> bool:
    """Đảo projection "HK1 đã tính học phí": đưa lead VỀ status TRƯỚC khi
    ``sync_lead_tuition_calculated`` đẩy lên sts14 (Chưa hoàn tất học phí).

    Dùng khi HUỶ khoản học phí HK1 tính NHẦM (``cancel_fee``). KHÔNG hardcode đích
    (vd sts09): khôi phục đúng status TRƯỚC đó từ history — ca thực tế có thể là
    sts13 "đã hoàn lệ phí" khi profile vẫn ``submitted``, ÉP sts09 sẽ nâng sai
    lên "đủ điều kiện". Caller PHẢI gate: chỉ HK1 tuition + fee bị huỷ
    (paid_amount == 0) + lead không còn nợ HK1 năm/profile khác.
    """
    return await _revert_lead_projection(
        db,
        profile,
        projected_status=TUITION_CALCULATED_STATUS,
        default_reason="Huỷ khoản học phí tính nhầm (cancel_fee)",
        log_label="revert_lead_tuition_calculated",
        changed_by_user_id=changed_by_user_id,
        reason=reason,
    )


async def sync_lead_tuition_refunded(
    db: AsyncSession,
    profile: models.AdmissionProfile,
    refund_amount: str = "",
    changed_by_user_id: Optional[int] = None,
    reason: Optional[str] = None,
) -> bool:
    """
    Sync lead consultation status when HK1 tuition fee is refunded.

    Moves lead to sts18 (Đã hoàn học phí).

    ADR-002 PR 5: HK1-only. Callers MUST gate invocation to
    semester_no == 1. HK2+ refunds must not affect the admission pipeline.

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
