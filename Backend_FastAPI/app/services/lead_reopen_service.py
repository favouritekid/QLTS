# app/services/lead_reopen_service.py
"""Lead reopen service (Phase A) — mở lại lead consultation-terminal (sts20).

Xem ``Documents/LEAD_REOPEN_WORKFLOW_PLAN.md``.

Reopen KHÔNG dùng FSM transition thường và KHÔNG seed
``allowed_transition sts20→sts04`` (nếu seed, manager đổi được sts20→sts04 qua
``add_consultation`` thường, bỏ qua kiểm soát). Đây là service chuyên dụng,
trong 1 transaction:

1. ``SELECT ... FOR UPDATE`` lead (chống double-reopen / TOCTOU — pattern #345).
2. Re-check (theo DB, không tin client) lead đang ở trạng thái cuối phase tư vấn
   (``is_final && phase=='consultation'``, vd sts20) → nếu không thì
   ``BusinessRuleViolation``.
3. Suy ``status`` + ``pipeline_stage_id`` từ sts04 bằng
   ``StatusHelper.sync_lead_status`` (KHÔNG hardcode 'contacted'/'stg02') + set
   mốc ``consultation_reengaged_at = now()``.
4. Ghi ``lead_status_history`` (changed_by = reviewer) + ``audit_service``. KHÔNG
   xóa history nào — mốc thời gian cho phép beat auto-close lại lần sau (RULE
   #13.2 đổi sang semantics "since last re-engage", xem
   ``fsm_engine.execute_system_transition``).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, Tuple

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from .. import models
from ..services import audit_service
from ..utils.exceptions import (
    BusinessRuleViolation,
    ResourceNotFoundError,
    ValidationError,
)
from ..repositories import LeadRepository
from ..core.status_mapping import is_consultation_terminal_status
from .status_helper import StatusHelper
from .lead_service import _get_current_lead_state, _log_lead_state_change

log = structlog.get_logger(__name__)

# Điểm re-engage chuẩn của phase tư vấn: sts04 (CONSULT_REJECTED, is_final=false →
# officer tiếp tục luồng tư vấn bình thường sts04→sts03/05/06).
REOPEN_TARGET_STATUS_ID = "sts04"

# Lý do bắt buộc — min length (service-side guard; schema cũng validate cho đường API).
_REASON_MIN_LEN = 5


async def reopen_lead(
    db: AsyncSession,
    lead_id: int,
    reviewer: models.User,
    reason: str,
) -> Tuple[models.Lead, Callable]:
    """Mở lại một lead consultation-terminal (sts20) → sts04.

    Args:
        db: AsyncSession (router commit; service chỉ flush qua helper).
        lead_id: Lead cần mở lại.
        reviewer: Manager/Admin thực hiện (ghi vào history + audit).
        reason: Lý do bắt buộc (>= 5 ký tự), lưu nguyên văn để audit.

    Returns:
        ``(lead, post_commit_callback)`` — callback no-op ở MVP (chỗ cắm notification
        Phase C). Router phải ``await callback()`` sau commit.

    Raises:
        ResourceNotFoundError: lead không tồn tại (404).
        BusinessRuleViolation: lead đã xóa / không ở trạng thái cuối phase tư vấn.
        ValidationError: thiếu lý do.
    """
    if not reason or len(reason.strip()) < _REASON_MIN_LEN:
        raise ValidationError(
            detail=f"Lý do mở lại là bắt buộc (tối thiểu {_REASON_MIN_LEN} ký tự)."
        )

    repo = LeadRepository(db)

    async with db.begin_nested():
        # 1. Lock lead row (chống double-reopen / TOCTOU). populate_existing=True để
        #    ĐỌC LẠI giá trị từ row đã khóa — nếu không, LeadAccessDep đã nạp lead vào
        #    identity-map trước đó (không khóa) và SQLAlchemy trả instance cũ KHÔNG
        #    refresh → re-check bên dưới sẽ chạy trên snapshot pre-lock.
        lead = await repo.get_by_id_for_update(lead_id, populate_existing=True)
        if lead is None:
            raise ResourceNotFoundError(detail=f"Lead with id {lead_id} not found")
        if lead.deleted_at is not None:
            raise BusinessRuleViolation(detail="Không thể mở lại một lead đã bị xóa.")

        # 2. Re-check trạng thái cuối phase tư vấn (DB, giá trị đã refresh dưới lock).
        current_cs = (
            await db.get(models.ConsultationStatus, lead.consultation_status_id)
            if lead.consultation_status_id
            else None
        )
        if not is_consultation_terminal_status(current_cs):
            raise BusinessRuleViolation(
                detail=(
                    "Chỉ mở lại được lead đang ở trạng thái cuối phase tư vấn "
                    "(đã ngừng tư vấn). Lead này không ở trạng thái đó."
                )
            )

        # 3. Capture old state TRƯỚC khi đổi.
        old_state = _get_current_lead_state(lead)
        old_cs_id = lead.consultation_status_id

        target_cs = await db.get(models.ConsultationStatus, REOPEN_TARGET_STATUS_ID)
        if target_cs is None:
            # Cấu hình thiếu trạng thái re-engage — fail-closed, không mutate.
            raise ResourceNotFoundError(
                detail=f"Thiếu trạng thái re-engage '{REOPEN_TARGET_STATUS_ID}'."
            )

        # 4. Mutate + sync (KHÔNG gán literal status/stage — suy từ sts04).
        now = datetime.now(timezone.utc)
        await StatusHelper.sync_lead_status(lead, target_cs)
        lead.consultation_reengaged_at = now
        lead.updated_at = now
        # Reset đồng hồ SLA: nếu không, coalesce(last_consultation_at, updated_at,
        # created_at) trong close_stale_rejected_leads vẫn thấy mốc give-up cũ → beat
        # auto-close lại NGAY lần chạy kế, vô hiệu hóa reopen khi bật
        # SLA_AUTO_GIVEUP_ENABLED. Cho lead một cửa sổ SLA mới kể từ lúc mở lại.
        lead.last_consultation_at = now
        # Optimistic-lock: mọi thay đổi trạng thái phải tăng version (đồng bộ
        # update_lead) để một edit dựa trên snapshot pre-reopen bị chặn 409 đúng cách.
        lead.version = (lead.version or 1) + 1

        # 5. Ghi history từ state đã capture + ĐỌC LẠI status/stage SAU sync.
        new_state = _get_current_lead_state(lead)
        await _log_lead_state_change(
            db,
            lead,
            old_state,
            new_state,
            changed_by=reviewer,
            reason=f"reopen: {reason.strip()}",
        )

        # 6. Audit.
        await audit_service.log_audit(
            db,
            entity_type="Lead",
            entity_id=lead.id,
            action="consultation_reopened",
            actor_user_id=reviewer.id,
            changes={
                "consultation_status_id": {
                    "old": old_cs_id,
                    "new": REOPEN_TARGET_STATUS_ID,
                },
                "status": {"old": old_state.get("status"), "new": lead.status},
            },
            reason=f"reopen: {reason.strip()}",
            source="api",
        )

        log.info(
            "Lead reopened",
            lead_id=lead.id,
            from_consultation_status=old_cs_id,
            to_consultation_status=REOPEN_TARGET_STATUS_ID,
            reviewer_id=reviewer.id,
            reengaged_at=now,
        )

    async def _post_commit() -> None:
        # MVP: no-op. Phase C: dispatch LEAD_REOPEN_* notifications here.
        return None

    return lead, _post_commit
