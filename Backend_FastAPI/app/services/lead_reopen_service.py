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
from typing import Callable, List, Optional, Tuple

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .. import models
from ..core.constants import UserRole
from ..services import audit_service
from ..utils.exceptions import (
    BusinessRuleViolation,
    ConflictError,
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


async def _lock_terminal_lead(db: AsyncSession, lead_id: int) -> models.Lead:
    """Lock lead row (FOR UPDATE, đọc fresh dưới lock) + verify chưa xóa + đang ở
    consultation-terminal. Raise nếu không hợp lệ. Trả lead đã khóa.

    Dùng chung cho reopen trực tiếp (Phase A) và request/approve (Phase B).
    """
    repo = LeadRepository(db)
    lead = await repo.get_by_id_for_update(lead_id, populate_existing=True)
    if lead is None:
        raise ResourceNotFoundError(detail=f"Lead with id {lead_id} not found")
    if lead.deleted_at is not None:
        raise BusinessRuleViolation(detail="Không thể mở lại một lead đã bị xóa.")
    current_cs = (
        await db.get(models.ConsultationStatus, lead.consultation_status_id)
        if lead.consultation_status_id
        else None
    )
    if not is_consultation_terminal_status(current_cs):
        raise BusinessRuleViolation(
            detail=(
                "Chỉ thao tác được khi lead đang ở trạng thái cuối phase tư vấn "
                "(đã ngừng tư vấn). Lead này không ở trạng thái đó."
            )
        )
    return lead


async def _apply_reopen(
    db: AsyncSession,
    lead: models.Lead,
    reviewer: models.User,
    reason_text: str,
) -> None:
    """Lõi mutate reopen sts20→sts04 — GIẢ ĐỊNH lead đã được lock + đã verify terminal.

    Dùng chung Phase A (``reopen_lead``) và Phase B (``approve_reopen``). KHÔNG tự
    lock / begin_nested (caller giữ lock). Suy status/stage từ sts04, set mốc re-engage,
    reset đồng hồ SLA, bump version, ghi history + audit.
    """
    old_state = _get_current_lead_state(lead)
    old_cs_id = lead.consultation_status_id

    target_cs = await db.get(models.ConsultationStatus, REOPEN_TARGET_STATUS_ID)
    if target_cs is None:
        raise ResourceNotFoundError(
            detail=f"Thiếu trạng thái re-engage '{REOPEN_TARGET_STATUS_ID}'."
        )

    now = datetime.now(timezone.utc)
    await StatusHelper.sync_lead_status(lead, target_cs)
    lead.consultation_reengaged_at = now
    lead.updated_at = now
    # Reset đồng hồ SLA (close_stale dùng coalesce(last_consultation_at,...)) + bump
    # version (optimistic-lock — mọi thay đổi trạng thái phải tăng version).
    lead.last_consultation_at = now
    lead.version = (lead.version or 1) + 1

    new_state = _get_current_lead_state(lead)
    await _log_lead_state_change(
        db, lead, old_state, new_state,
        changed_by=reviewer, reason=f"reopen: {reason_text}",
    )
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
        reason=f"reopen: {reason_text}",
        source="api",
    )
    log.info(
        "Lead reopened",
        lead_id=lead.id,
        from_consultation_status=old_cs_id,
        to_consultation_status=REOPEN_TARGET_STATUS_ID,
        reviewer_id=reviewer.id,
    )


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
    reason_text = (reason or "").strip()
    if len(reason_text) < _REASON_MIN_LEN:
        raise ValidationError(
            detail=f"Lý do mở lại là bắt buộc (tối thiểu {_REASON_MIN_LEN} ký tự)."
        )

    async with db.begin_nested():
        lead = await _lock_terminal_lead(db, lead_id)
        await _apply_reopen(db, lead, reviewer, reason_text)

    async def _post_commit() -> None:
        # MVP: no-op. Phase C: dispatch LEAD_REOPEN_* notifications here.
        return None

    return lead, _post_commit


# ===========================================================================
# Phase B — officer xin mở lại → manager/admin duyệt (lead_reopen_request)
# ===========================================================================

async def _lock_request(
    db: AsyncSession, request_id: int
) -> models.LeadReopenRequest:
    """Lock 1 reopen request row (FOR UPDATE). Raise 404 nếu không có.

    populate_existing=True: dep IDOR ``get_reopen_request_for_user`` đã nạp request vào
    identity-map (không khóa) trước handler → FOR UPDATE phải refresh để re-check status
    đọc giá trị fresh dưới lock (cùng bài học bug #2 của lead).
    """
    req = (
        await db.execute(
            select(models.LeadReopenRequest)
            .where(models.LeadReopenRequest.id == request_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if req is None:
        raise ResourceNotFoundError(
            detail=f"Reopen request {request_id} not found"
        )
    return req


async def request_reopen(
    db: AsyncSession,
    lead_id: int,
    requested_by: models.User,
    reason: str,
) -> Tuple[models.LeadReopenRequest, Callable]:
    """Officer GỬI yêu cầu mở lại lead terminal (KHÔNG tự mở — chờ duyệt).

    IDOR (officer assigned) đã enforce ở dep ``get_lead_for_user``. Guard: lead
    terminal + chưa có pending (partial-unique cũng chặn; check trước cho 409 rõ).
    """
    reason_text = (reason or "").strip()
    if len(reason_text) < _REASON_MIN_LEN:
        raise ValidationError(
            detail=f"Lý do là bắt buộc (tối thiểu {_REASON_MIN_LEN} ký tự)."
        )

    async with db.begin_nested():
        lead = await _lock_terminal_lead(db, lead_id)

        existing = (
            await db.execute(
                select(models.LeadReopenRequest)
                .where(
                    models.LeadReopenRequest.lead_id == lead_id,
                    models.LeadReopenRequest.status == "pending",
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if existing is not None:
            raise ConflictError(
                detail="Lead này đã có một yêu cầu mở lại đang chờ duyệt."
            )

        req = models.LeadReopenRequest(
            lead_id=lead_id,
            requested_by_id=requested_by.id,
            reason=reason_text,
            status="pending",
            unit_id=lead.unit_id,
        )
        db.add(req)
        await db.flush()

        await audit_service.log_audit(
            db,
            entity_type="LeadReopenRequest",
            entity_id=req.id,
            action="created",
            actor_user_id=requested_by.id,
            reason=f"reopen-request: {reason_text}",
            source="api",
        )
        log.info(
            "Reopen request created",
            request_id=req.id,
            lead_id=lead_id,
            requested_by=requested_by.id,
        )

    async def _post_commit() -> None:
        # Phase C: dispatch LEAD_REOPEN_REQUESTED → manager unit.
        return None

    return req, _post_commit


async def approve_reopen(
    db: AsyncSession,
    request_id: int,
    reviewer: models.User,
    note: Optional[str] = None,
) -> Tuple[models.LeadReopenRequest, Callable]:
    """Manager/admin DUYỆT yêu cầu → gọi lõi reopen. FOR UPDATE cả request + lead;
    re-check request pending + lead vẫn terminal."""
    async with db.begin_nested():
        req = await _lock_request(db, request_id)
        if req.status != "pending":
            raise BusinessRuleViolation(
                detail=f"Yêu cầu đã được xử lý ('{req.status}'), không thể duyệt."
            )

        # Lock lead + re-check terminal (có thể đã được mở lại bởi đường khác).
        lead = await _lock_terminal_lead(db, req.lead_id)
        await _apply_reopen(db, lead, reviewer, req.reason)

        req.status = "approved"
        req.reviewed_by_id = reviewer.id
        req.review_note = (note or "").strip() or None
        req.reviewed_at = datetime.now(timezone.utc)
        await db.flush()

        await audit_service.log_audit(
            db,
            entity_type="LeadReopenRequest",
            entity_id=req.id,
            action="approved",
            actor_user_id=reviewer.id,
            reason=req.review_note,
            source="api",
        )
        log.info(
            "Reopen request approved",
            request_id=req.id,
            lead_id=req.lead_id,
            reviewer_id=reviewer.id,
        )

    async def _post_commit() -> None:
        # Phase C: dispatch LEAD_REOPEN_APPROVED → officer xin.
        return None

    return req, _post_commit


async def reject_reopen(
    db: AsyncSession,
    request_id: int,
    reviewer: models.User,
    note: str,
) -> Tuple[models.LeadReopenRequest, Callable]:
    """Manager/admin TỪ CHỐI yêu cầu (note bắt buộc); lead giữ nguyên sts20."""
    note_text = (note or "").strip()
    if len(note_text) < _REASON_MIN_LEN:
        raise ValidationError(
            detail=f"Lý do từ chối là bắt buộc (tối thiểu {_REASON_MIN_LEN} ký tự)."
        )

    async with db.begin_nested():
        req = await _lock_request(db, request_id)
        if req.status != "pending":
            raise BusinessRuleViolation(
                detail=f"Yêu cầu đã được xử lý ('{req.status}'), không thể từ chối."
            )

        req.status = "rejected"
        req.reviewed_by_id = reviewer.id
        req.review_note = note_text
        req.reviewed_at = datetime.now(timezone.utc)
        await db.flush()

        await audit_service.log_audit(
            db,
            entity_type="LeadReopenRequest",
            entity_id=req.id,
            action="rejected",
            actor_user_id=reviewer.id,
            reason=note_text,
            source="api",
        )
        log.info(
            "Reopen request rejected",
            request_id=req.id,
            lead_id=req.lead_id,
            reviewer_id=reviewer.id,
        )

    async def _post_commit() -> None:
        # Phase C: dispatch LEAD_REOPEN_REJECTED → officer xin.
        return None

    return req, _post_commit


async def cancel_reopen(
    db: AsyncSession,
    request_id: int,
    requester: models.User,
) -> models.LeadReopenRequest:
    """Officer tự HỦY yêu cầu pending của CHÍNH mình. Người khác → 404 (không lộ)."""
    async with db.begin_nested():
        req = await _lock_request(db, request_id)
        # Chỉ người xin tự hủy. Trả 404 (không 403) để không lộ tồn tại request.
        if req.requested_by_id != requester.id:
            raise ResourceNotFoundError(
                detail=f"Reopen request {request_id} not found"
            )
        if req.status != "pending":
            raise BusinessRuleViolation(
                detail=f"Yêu cầu đã được xử lý ('{req.status}'), không thể hủy."
            )

        req.status = "cancelled"
        req.reviewed_at = datetime.now(timezone.utc)
        await db.flush()

        await audit_service.log_audit(
            db,
            entity_type="LeadReopenRequest",
            entity_id=req.id,
            action="cancelled",
            actor_user_id=requester.id,
            source="api",
        )
        log.info("Reopen request cancelled", request_id=req.id)

    return req


async def list_reopen_requests(
    db: AsyncSession,
    user: models.User,
    status: Optional[str] = None,
) -> List[models.LeadReopenRequest]:
    """Inbox duyệt cho manager/admin. Admin: toàn hệ thống; manager: scope theo
    ``lead.unit_id`` HIỆN TẠI (join lead, KHÔNG dùng request.unit_id snapshot)."""
    q = (
        select(models.LeadReopenRequest)
        .options(
            selectinload(models.LeadReopenRequest.lead),
            selectinload(models.LeadReopenRequest.requested_by),
            selectinload(models.LeadReopenRequest.reviewed_by),
        )
        .order_by(models.LeadReopenRequest.created_at.desc())
    )
    if status:
        q = q.where(models.LeadReopenRequest.status == status)

    if user.role == UserRole.MANAGER:
        if user.unit_id is None:
            return []
        from ..repositories.organization_repository import OrganizationRepository

        allowed = await OrganizationRepository(db).get_descendant_unit_ids(
            user.unit_id
        )
        q = q.join(
            models.Lead, models.LeadReopenRequest.lead_id == models.Lead.id
        ).where(models.Lead.unit_id.in_(allowed))
    # admin: không lọc unit (toàn hệ thống).

    result = await db.execute(q)
    return list(result.scalars().all())
