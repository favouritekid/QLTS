# app/services/assignment_service.py
"""
Lead Assignment Service - Automatic lead distribution logic.

✅ REFACTORED: Now uses notification_dispatcher for all notifications.
This ensures notifications are persisted to database AND sent via Socket.IO/Email.
"""
import logging
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError  # Dùng để bắt LockNotAvailableError
from sqlalchemy.ext.asyncio import AsyncSession

from .. import models
from ..core.constants import UserRole
from ..core.events import SystemEvents
from ..core.task_constants import AssignmentResult, AssignmentFailureReason
from ..utils.exceptions import LockContentionError
from .notification_dispatcher import dispatch
from .notification_payloads import EventPayload
from .status_helper import StatusHelper, AssignmentStatus

# Lấy logger chuẩn ở đây, dùng làm fallback
default_log = logging.getLogger(__name__)

# Ngưỡng tải an toàn (utilization). Officer có utilization >= ngưỡng này bị
# xếp sau trong round-robin (BƯỚC 5) và bị nhánh referral né (Phần C). Tách ra
# module-level để assignment_service + lead_service dùng chung một con số.
SAFETY_THRESHOLD = 0.8


def _non_final_status_filter():
    """
    SQL condition: a lead's consultation_status is non-final (is_final False or
    NULL). Single source of truth for "counts as active workload", shared by
    is_officer_at_threshold and automatically_assign_lead BƯỚC 3 so the referral
    fast-path and the balancer can never drift on what "load" means.
    """
    return (
        (models.ConsultationStatus.is_final == False) |  # noqa: E712
        (models.ConsultationStatus.is_final.is_(None))
    )


def _safe_capacity(officer: models.User) -> int:
    """Officer capacity with a safe fallback (default 100, never <= 0).
    Shared by the referral threshold check and the assignment loop (BƯỚC 4)."""
    capacity = officer.max_capacity if officer.max_capacity is not None else 100
    return capacity if capacity > 0 else 1


def _safe_weight(officer: models.User) -> int:
    """Officer member-assignment weight with a safe fallback (default 1, never <= 0).

    Mirrors ``_safe_capacity``. A higher weight makes the officer look emptier in
    ``eff_util = workload / (capacity * weight)`` so they receive more leads. None
    is coerced to 1 — an unflushed / mock ``User`` (tests) has ``assignment_weight``
    still unset (the column ``default=1`` only fires at INSERT), so weight 1 keeps
    ``eff_util == real_util`` and the balancer stays regression-safe."""
    weight = getattr(officer, "assignment_weight", None)
    if weight is None:
        return 1
    return weight if weight > 0 else 1


async def is_officer_at_threshold(
    db: AsyncSession,
    officer: models.User,
    threshold: float = SAFETY_THRESHOLD,
) -> bool:
    """
    Trả True nếu tải hiện tại của officer đã đạt/vượt ngưỡng an toàn
    (workload / capacity >= threshold).

    Workload được định nghĩa GIỐNG HỆT automatically_assign_lead BƯỚC 3-4: đếm
    số lead (chưa xóa, deleted_at IS NULL) được gán cho officer mà
    consultation_status.is_final là False hoặc NULL (một lead ở sts04 "Từ chối
    tư vấn" is_final=false vẫn tính tải). Dùng bởi nhánh referral (lead_service)
    để KHÔNG gán thẳng referral lead cho managing officer đã đầy tải — thay vào
    đó fallback sang auto-assign cân bằng. Giữ cùng định nghĩa workload với thuật
    toán né officer, nên kết luận ở đây khớp với việc officer có bị auto-assign né.
    """
    workload_stmt = (
        select(func.count(models.Lead.id))
        .join(
            models.ConsultationStatus,
            models.Lead.consultation_status_id == models.ConsultationStatus.id,
            isouter=True,  # LEFT JOIN để bao gồm cả lead chưa có status
        )
        .where(
            models.Lead.assigned_officer_id == officer.id,
            models.Lead.deleted_at.is_(None),  # lead đã xóa không tính tải
            _non_final_status_filter(),
        )
    )
    workload = (await db.execute(workload_stmt)).scalar_one() or 0

    return (workload / _safe_capacity(officer)) >= threshold


async def _log_assignment_decision(
    db: AsyncSession,
    lead_id: int,
    assigned_officer_id: int | None,
    eligible_officer_ids: list[int],
    unit_id: int | None,
    channel: str,
    reason: str,
    scores_snapshot: dict | None = None,
    capacity_snapshot: dict | None = None,
    log: logging.Logger = default_log,
) -> None:
    """
    Phase A8: Log assignment decision for fairness analysis (v2.1 prep).
    Fail-safe — exceptions are caught and warned, never fail the assign flow.
    """
    try:
        entry = models.AssignmentDecisionLog(
            lead_id=lead_id,
            assigned_officer_id=assigned_officer_id,
            eligible_officer_ids=eligible_officer_ids,
            channel=channel,
            unit_id=unit_id,
            scores_snapshot=scores_snapshot,
            capacity_snapshot=capacity_snapshot,
            reason=reason,
        )
        db.add(entry)
    except Exception as e:
        log.warning(f"[Lead ID: {lead_id}] Failed to log assignment decision: {e}")


# Thêm tham số logger=None
async def automatically_assign_lead(
    lead_id: int, db: AsyncSession, logger: logging.Logger = None
) -> tuple[dict, list]:
    """
    Logic nghiệp vụ chính để tự động phân công Lead.
    Sử dụng logger được truyền vào hoặc logger mặc định.
    Sử dụng 'SKIP LOCKED' để xử lý concurrency khi khóa officers.
    Xử lý lock contention trên Lead bằng Celery Retry.

    Returns:
        tuple[dict, list]: (result_dict, post_commit_callbacks)
            result_dict has "status" key:
            - "assigned": Lead successfully assigned to officer
            - "failed": No officers available or all at capacity
            - "skipped": Lead already assigned or not found
            post_commit_callbacks: list of async callables to run after commit
    """
    log = logger or default_log
    log.info(f"[Lead ID: {lead_id}] Auto-assign task started")
    _post_commit_callbacks = []

    try:
        # Sử dụng transaction lồng nhau để kiểm soát rollback tốt hơn
        async with db.begin_nested():
            # === BƯỚC 1: Lấy VÀ KHÓA Lead (Giữ nguyên nowait=True hoặc đổi sang skip_locked=True) ===
            # Việc khóa lead ít khi xung đột hơn, nhưng nowait giúp phát hiện sớm
            # nếu có transaction khác đang xử lý chính lead này.
            stmt = (
                select(models.Lead)
                .where(models.Lead.id == lead_id)
                .with_for_update(nowait=True)
            )
            result = await db.execute(stmt)
            lead = result.scalar_one_or_none()

            # --- Kiểm tra trạng thái Lead ---
            if not lead:
                log.warning(
                    f"[Lead ID: {lead_id}] Lead not found, skipping assignment."
                )
                return {"status": AssignmentResult.SKIPPED, "reason": AssignmentFailureReason.LEAD_NOT_FOUND, "lead_id": lead_id}, _post_commit_callbacks
            
            # ✅ FIX: Check if lead is deleted (soft delete)
            elif lead.deleted_at is not None:
                log.warning(
                    f"[Lead ID: {lead_id}] Lead is soft-deleted, skipping assignment."
                )
                return {"status": AssignmentResult.SKIPPED, "reason": AssignmentFailureReason.LEAD_DELETED, "lead_id": lead_id}, _post_commit_callbacks
            
            elif lead.assigned_officer_id:
                log.info(
                    f"[Lead ID: {lead_id}] Lead already assigned to officer {lead.assigned_officer_id}, skipping."
                )
                return {"status": AssignmentResult.SKIPPED, "reason": AssignmentFailureReason.ALREADY_ASSIGNED, "lead_id": lead_id, "officer_id": lead.assigned_officer_id}, _post_commit_callbacks
            else:
                lead_unit_id = lead.unit_id
                # Get blacklisted officers for this lead
                blacklisted_officer_ids = lead.rejected_by_officer_ids or []
                log.debug(
                    f"[Lead ID: {lead_id}] Lead found and locked (Unit: {lead_unit_id}). Status: '{lead.status}', Blacklist: {blacklisted_officer_ids}"
                )

                # === BƯỚC 2: Khóa các Officer liên quan (SỬ DỤNG SKIP LOCKED) ===
                # ✅ NEW: Also exclude blacklisted officers
                available_officers_query = (
                    select(models.User).where(
                        models.User.role == UserRole.OFFICER,
                        models.User.status == "active",
                        models.User.availability_status
                        == "available",  # Chỉ lấy officer đang sẵn sàng
                        models.User.unit_id == lead_unit_id,  # Cùng đơn vị với Lead
                    )
                    # ✅ CẢI TIẾN: Bỏ qua các officer đang bị khóa bởi transaction khác
                    .with_for_update(skip_locked=True)
                )
                
                # ✅ BLACKLIST FILTER: Exclude officers who previously reassigned this lead
                if blacklisted_officer_ids:
                    available_officers_query = available_officers_query.where(
                        ~models.User.id.in_(blacklisted_officer_ids)
                    )
                    log.info(
                        f"[Lead ID: {lead_id}] Excluding {len(blacklisted_officer_ids)} blacklisted officers from assignment pool"
                    )
                
                officer_results = await db.execute(available_officers_query)
                # Lấy danh sách officer chưa bị khóa
                available_officers = officer_results.scalars().all()

                # --- Xử lý khi không có Officer ---
                if not available_officers:
                    log.warning(
                        f"[Lead ID: {lead_id}] No available (and unlocked) officers found for unit {lead_unit_id}. Setting assignment_status to failed."
                    )
                    # Update assignment_status to "failed" (no officers available)
                    StatusHelper.set_assignment_status(lead, AssignmentStatus.FAILED)
                    db.add(lead)

                    # ✅ REFACTOR: Dispatch notification for assignment failure
                    try:
                        from app.services.notification_dispatcher import rooms_for_lead
                        _, notif_cb = await dispatch(
                            db=db,
                            event=SystemEvents.LEAD_ASSIGNMENT_FAILED,
                            payload=EventPayload.for_lead_assignment_failed(lead, lead_unit_id, "No officers available"),
                            dedupe_key=f"lead_assignment_failed:{lead_id}:no_officers",
                            rooms=rooms_for_lead(lead),
                        )
                        if notif_cb:
                            _post_commit_callbacks.append(notif_cb)
                    except Exception as e:
                        log.error(
                            f"[Lead ID: {lead_id}] Failed to dispatch assignment failure notification: {e}"
                        )

                    # A8: Log decision — no officers available
                    await _log_assignment_decision(
                        db, lead_id=lead_id, assigned_officer_id=None,
                        eligible_officer_ids=[], unit_id=lead_unit_id,
                        channel="auto", reason="no_officers", log=log,
                    )
                    return {"status": AssignmentResult.FAILED, "reason": AssignmentFailureReason.NO_OFFICERS, "lead_id": lead_id, "unit_id": lead_unit_id}, _post_commit_callbacks

                log.debug(
                    f"[Lead ID: {lead_id}] Found {len(available_officers)} available officers for unit {lead_unit_id}."
                )

                # === BƯỚC 3: TÍNH TOÁN WORKLOAD (Chỉ cho các officer lấy được) ===
                # ✅ REFACTORED: Sử dụng JOIN với ConsultationStatus thay vì danh sách hard-coded
                officer_ids = [o.id for o in available_officers]
                workload_stmt = (
                    select(
                        models.Lead.assigned_officer_id,
                        func.count(models.Lead.id).label("workload"),
                    )
                    .join(
                        models.ConsultationStatus,
                        models.Lead.consultation_status_id == models.ConsultationStatus.id,
                        isouter=True,  # LEFT JOIN để bao gồm cả lead chưa có status
                    )
                    .where(
                        models.Lead.assigned_officer_id.in_(officer_ids),
                        models.Lead.deleted_at.is_(None),  # lead đã xóa không tính tải
                        # Chỉ đếm lead chưa kết thúc — cùng định nghĩa với
                        # is_officer_at_threshold (referral fast-path).
                        _non_final_status_filter(),
                    )
                    .group_by(models.Lead.assigned_officer_id)
                )
                workload_results = await db.execute(workload_stmt)
                workload_map = {
                    row.assigned_officer_id: row.workload for row in workload_results
                }
                log.debug(
                    f"[Lead ID: {lead_id}] Calculated workloads (non-final leads only) for available officers: {workload_map}"
                )

                # === BƯỚC 4: Xây dựng Danh sách Officer Hợp lệ (còn capacity) ===
                officer_loads = []
                for officer in available_officers:
                    workload = workload_map.get(officer.id, 0)
                    # Capacity an toàn (mặc định 100, không bao giờ <= 0) —
                    # cùng helper với is_officer_at_threshold.
                    capacity = _safe_capacity(officer)

                    if workload < capacity:
                        utilization = workload / capacity
                        # real_util = tải THẬT (workload/capacity), không bao giờ
                        # nhân weight — cổng an toàn (BƯỚC 5 `overloaded`) luôn đọc
                        # con số này. eff_util = tải hiệu dụng có nhân weight: weight
                        # cao ⇒ eff_util thấp ⇒ officer "được coi là vơi hơn" ⇒ nhận
                        # nhiều lead hơn (chỉ dùng khi member flag bật).
                        weight = _safe_weight(officer)
                        eff_util = workload / (capacity * weight)
                        officer_loads.append(
                            {
                                "officer": officer,
                                "workload": workload,
                                # Giữ "utilization" (== real_util) để không đổi các
                                # nhánh legacy/fairness cũ đang đọc key này.
                                "utilization": utilization,
                                "real_util": utilization,
                                "eff_util": eff_util,
                                "weight": weight,
                                # Giá trị sort thực (BƯỚC 5 ghi đè theo matrix);
                                # mặc định real_util cho nhánh legacy để snapshot
                                # phản ánh đúng tải thật đã dùng.
                                "score": utilization,
                                # Xử lý last_assigned_at là None (coalesce)
                                "last_assigned": officer.last_assigned_at
                                or datetime.min.replace(tzinfo=timezone.utc),
                            }
                        )
                    else:
                        log.debug(
                            f"[Lead ID: {lead_id}] Officer {officer.id} skipped (at full capacity: {workload}/{capacity})"
                        )

                # --- Xử lý khi tất cả Officer đã đầy tải ---
                if not officer_loads:
                    log.warning(
                        f"[Lead ID: {lead_id}] All available officers ({len(available_officers)}) in unit {lead_unit_id} are at full capacity. Setting assignment_status to failed."
                    )
                    # Update assignment_status to "failed" (all at capacity)
                    StatusHelper.set_assignment_status(lead, AssignmentStatus.FAILED)
                    db.add(lead)

                    # ✅ REFACTOR: Dispatch notification for assignment failure
                    try:
                        from app.services.notification_dispatcher import rooms_for_lead
                        _, notif_cb = await dispatch(
                            db=db,
                            event=SystemEvents.LEAD_ASSIGNMENT_FAILED,
                            payload=EventPayload.for_lead_assignment_failed(lead, lead_unit_id, "All officers at full capacity"),
                            dedupe_key=f"lead_assignment_failed:{lead_id}:capacity",
                            rooms=rooms_for_lead(lead),
                        )
                        if notif_cb:
                            _post_commit_callbacks.append(notif_cb)
                    except Exception as e:
                        log.error(
                            f"[Lead ID: {lead_id}] Failed to dispatch assignment failure notification: {e}"
                        )

                    # A8: Log decision — all at capacity
                    await _log_assignment_decision(
                        db, lead_id=lead_id, assigned_officer_id=None,
                        eligible_officer_ids=officer_ids, unit_id=lead_unit_id,
                        channel="auto", reason="at_capacity",
                        capacity_snapshot={
                            str(o.id): {"current": workload_map.get(o.id, 0),
                                        "max": o.max_capacity or 100}
                            for o in available_officers
                        }, log=log,
                    )
                    return {"status": AssignmentResult.FAILED, "reason": AssignmentFailureReason.AT_CAPACITY, "lead_id": lead_id, "unit_id": lead_unit_id}, _post_commit_callbacks

                # === BƯỚC 5: Sắp xếp và Chọn Officer ===
                # Hai flag ĐỘC LẬP chồng lên logic gốc (KHÔNG thay thế nhánh):
                #   ENABLE_MEMBER_WEIGHTED_ASSIGNMENT   → order theo eff_util (nhân weight)
                #   ENABLE_FAIRNESS_WEIGHTED_ASSIGNMENT → thêm thành phần fairness share
                # order_util = eff_util nếu member ON, ngược lại real_util (=== hôm nay).
                # overloaded = real_util >= SAFETY_THRESHOLD — LUÔN tải thật; weight
                # KHÔNG BAO GIỜ phá cổng an toàn (không dồn quá tải thật).
                from ..config import settings

                member_on = settings.ENABLE_MEMBER_WEIGHTED_ASSIGNMENT
                fairness_on = settings.ENABLE_FAIRNESS_WEIGHTED_ASSIGNMENT

                # SAFETY_THRESHOLD is a module-level constant (shared with the
                # referral fast-path via is_officer_at_threshold). Cổng đọc tải THẬT.
                for entry in officer_loads:
                    entry["overloaded"] = entry["real_util"] >= SAFETY_THRESHOLD

                # Lịch sử phân công của đơn vị — chỉ truy vấn khi fairness bật.
                hist_counts: dict = {}
                if fairness_on:
                    try:
                        from sqlalchemy import select as sel, func as fn
                        hist_q = await db.execute(
                            sel(
                                models.AssignmentDecisionLog.assigned_officer_id,
                                fn.count(models.AssignmentDecisionLog.id).label("cnt"),
                            )
                            .where(
                                models.AssignmentDecisionLog.unit_id == lead_unit_id,
                                models.AssignmentDecisionLog.assigned_officer_id.isnot(None),
                            )
                            .group_by(models.AssignmentDecisionLog.assigned_officer_id)
                        )
                        hist_counts = {r.assigned_officer_id: r.cnt for r in hist_q.all()}
                    except Exception as e:
                        log.warning(f"[Lead ID: {lead_id}] Fairness history query failed, falling back: {e}")

                if fairness_on and member_on:
                    # --- FAIRNESS + MEMBER: áp lực lệch so với TARGET weighted share ---
                    # Target & actual PHẢI cùng pool = officer đang cạnh tranh ở quyết
                    # định này (officer_loads = pool sau lọc capacity BƯỚC 4). KHÔNG
                    # dùng total_hist toàn unit: history của officer offline/đầy tải sẽ
                    # loãng mẫu số, khiến officer đã vượt share trong pool vẫn bị coi là
                    # dưới target. Pool đồng đều weight ⇒ pressure = actual − 1/N.
                    pool_ids = [e["officer"].id for e in officer_loads]
                    eligible_hist_total = sum(hist_counts.get(oid, 0) for oid in pool_ids)
                    total_weight = sum(e["weight"] for e in officer_loads)  # mỗi weight >= 1 ⇒ > 0
                    has_history = eligible_hist_total >= 10  # ngưỡng cho nhánh fairness+member
                    if has_history:
                        for e in officer_loads:
                            oid = e["officer"].id
                            target_share = e["weight"] / total_weight if total_weight > 0 else 0
                            actual_share = (
                                hist_counts.get(oid, 0) / eligible_hist_total
                                if eligible_hist_total > 0 else 0
                            )
                            pressure = actual_share - target_share  # <0 ⇒ đẩy lên, >0 ⇒ phạt
                            e["score"] = 0.6 * e["eff_util"] + 0.4 * pressure
                        assign_reason = "member_fairness_weighted"
                        log.info(f"[Lead ID: {lead_id}] Member+fairness weighted (pool_hist={eligible_hist_total})")
                    else:
                        # Chưa đủ history trong pool ⇒ member-weighted (KHÔNG legacy):
                        # nếu không weight vô tác dụng giai đoạn đầu rollout.
                        for e in officer_loads:
                            e["score"] = e["eff_util"]
                        assign_reason = "member_weighted"
                        log.info(f"[Lead ID: {lead_id}] Member+fairness ON but pool_hist={eligible_hist_total}<10 → member-weighted fallback")
                    officer_loads.sort(key=lambda x: (x["overloaded"], x["score"], x["last_assigned"]))
                elif fairness_on:
                    # --- FAIRNESS ONLY (member OFF): giữ NGUYÊN VẸN hành vi P2-2 ---
                    # raw_share = hist / total_hist TOÀN UNIT (như cũ, không đổi).
                    total_hist = sum(hist_counts.values()) if hist_counts else 0
                    has_history = total_hist >= 10  # minimum threshold (như cũ)
                    if has_history:
                        for entry in officer_loads:
                            oid = entry["officer"].id
                            share = hist_counts.get(oid, 0) / total_hist if total_hist > 0 else 0
                            # 60% utilization THẬT + 40% historical share (như cũ)
                            entry["score"] = 0.6 * entry["real_util"] + 0.4 * share
                        officer_loads.sort(key=lambda x: (x["overloaded"], x["score"], x["last_assigned"]))
                        assign_reason = "fairness_weighted"
                        log.info(f"[Lead ID: {lead_id}] Using fairness-weighted scoring (history={total_hist})")
                    else:
                        # Insufficient history — fall back to legacy (như cũ). score giữ
                        # mặc định real_util (BƯỚC 4) cho snapshot; sort KHÔNG dùng score.
                        officer_loads.sort(key=lambda x: (x["overloaded"], x["last_assigned"]))
                        assign_reason = "lowest_workload"
                        log.info(f"[Lead ID: {lead_id}] Fairness ON but insufficient data ({total_hist}), using legacy")
                elif member_on:
                    # --- MEMBER ONLY: hybrid threshold round robin theo eff_util ---
                    # Cùng cấu trúc legacy nhưng tie-break đầu là eff_util (weight cao
                    # ⇒ eff_util thấp ⇒ ưu tiên), rồi last_assigned (Round Robin).
                    for e in officer_loads:
                        e["score"] = e["eff_util"]
                    officer_loads.sort(key=lambda x: (x["overloaded"], x["score"], x["last_assigned"]))
                    assign_reason = "member_weighted"
                    log.info(f"[Lead ID: {lead_id}] Using member-weighted scoring")
                else:
                    # --- LEGACY: HYBRID THRESHOLD ROUND ROBIN (cả 2 flag OFF) ---
                    # 1. Nhóm chưa quá tải (real_util < 0.8) trước nhóm sắp quá tải (>= 0.8)
                    # 2. Trong cùng nhóm, ưu tiên người được gán lâu nhất (Round Robin công bằng)
                    # === Hành vi Y HỆT hôm nay (score giữ mặc định real_util cho snapshot).
                    officer_loads.sort(key=lambda x: (x["overloaded"], x["last_assigned"]))
                    assign_reason = "lowest_workload"

                chosen_officer_data = officer_loads[0]
                chosen_one = chosen_officer_data["officer"]
                chosen_workload = chosen_officer_data["workload"]
                log.info(
                    f"[Lead ID: {lead_id}] Selected officer {chosen_one.id} ({chosen_one.username}). "
                    f"Current Workload: {chosen_workload}, Max Capacity: {chosen_one.max_capacity}, "
                    f"Utilization: {chosen_officer_data['utilization']:.2f}, "
                    f"Last Assigned: {chosen_officer_data['last_assigned']}"
                )

                # === BƯỚC 6: Gán Lead, Cập nhật Officer và Ghi Log Assignment ===
                now_utc = datetime.now(timezone.utc)
                lead.assigned_officer_id = chosen_one.id
                lead.assigned_at = now_utc
                # Update assignment_status to "assigned"
                StatusHelper.set_assignment_status(lead, AssignmentStatus.ASSIGNED)

                chosen_one.last_assigned_at = now_utc

                log_entry = models.AssignmentLog(
                    lead_id=lead.id,  # Lead ID chắc chắn đã có
                    officer_id=chosen_one.id,
                    method="automatic",
                    reason="Hệ thống phân công tự động",
                    timestamp=now_utc,
                )

                # await _log_lead_state_change(...) # Ghi lại sự thay đổi trạng thái lead

                # Thêm tất cả các thay đổi vào session
                db.add_all([lead, chosen_one, log_entry])

                # A8/P2-2: Log decision — successful assignment. `assign_reason` đã
                # được BƯỚC 5 set theo decision matrix (lowest_workload /
                # fairness_weighted / member_weighted / member_fairness_weighted).
                # scores_snapshot enrich sang dict {real_util, eff_util, weight, score}
                # — KHÔNG consumer nào đọc float phẳng (fairness_service chỉ đọc
                # capacity_snapshot), score = giá trị đã sort thực tế.
                await _log_assignment_decision(
                    db, lead_id=lead_id, assigned_officer_id=chosen_one.id,
                    eligible_officer_ids=officer_ids, unit_id=lead_unit_id,
                    channel="auto", reason=assign_reason,
                    scores_snapshot={
                        str(ol["officer"].id): {
                            "real_util": round(ol["real_util"], 4),
                            "eff_util": round(ol["eff_util"], 4),
                            "weight": ol["weight"],
                            "score": round(ol["score"], 4),
                        }
                        for ol in officer_loads
                    },
                    capacity_snapshot={
                        str(ol["officer"].id): {
                            "current": ol["workload"],
                            "max": ol["officer"].max_capacity or 100,
                        }
                        for ol in officer_loads
                    }, log=log,
                )

                log.info(
                    f"[Lead ID: {lead_id}] Lead assignment successful to officer {chosen_one.id}."
                )

        # Kết thúc `async with db.begin_nested()` - Nested transaction commits (savepoint)

        # === ✅ REFACTOR: Dispatch notification after nested transaction ===
        # This happens after DB changes are saved (in nested transaction)
        # Dispatcher will commit the outer transaction and send notifications
        try:
            # Load relationships for notification payload
            await db.refresh(lead, ["unit", "offering"])

            # Prepare notification payload according to LEAD_ASSIGNED schema
            # Note: offering relationship should be loaded via db.refresh above
            offering_name = "N/A"
            if lead.offering:
                offering_name = getattr(lead.offering, 'offering_type', 'N/A')

            # Dispatch notification (saves to DB via flush, caller commits)
            from app.services.notification_dispatcher import rooms_for_lead
            _, notif_cb = await dispatch(
                db=db,
                event=SystemEvents.LEAD_ASSIGNED,
                payload=EventPayload.for_lead_assigned(
                    lead, chosen_one.id, None,
                    offering_name=offering_name,
                    is_automatic=True,
                    assignment_method="automatic",
                ),
                dedupe_key=f"lead_assigned:{lead.id}:{chosen_one.id}",
                rooms=rooms_for_lead(lead),
            )
            if notif_cb:
                _post_commit_callbacks.append(notif_cb)

            log.info(
                f"[Lead ID: {lead_id}] Automatic assignment notification dispatched to officer {chosen_one.id}."
            )
        except Exception as e:
            # Log but don't fail - lead assignment already succeeded
            log.error(
                f"[Lead ID: {lead_id}] Failed to dispatch assignment notification: {e}"
            )

        # Return success result
        return {"status": AssignmentResult.ASSIGNED, "lead_id": lead_id, "officer_id": chosen_one.id}, _post_commit_callbacks

    except OperationalError as e:
        # Bắt lỗi "LockNotAvailableError" (chủ yếu cho việc khóa Lead ban đầu)
        if (
            "could not obtain lock" in str(e).lower()
            or "lock not available" in str(e).lower()
        ):
            log.warning(
                f"[Lead ID: {lead_id}] Lock contention detected (possibly on Lead row). "
                "Celery will retry automatically via autoretry_for."
            )
            # Raise LockContentionError - Celery's autoretry_for=(Exception,) will handle retry
            raise LockContentionError(
                f"Lock contention on lead {lead_id}",
                context={"lead_id": lead_id, "original_error": str(e)}
            )
        else:
            # Nếu là lỗi OperationalError khác (vd: mất kết nối), log và ném ra
            log.error(
                f"[Lead ID: {lead_id}] OperationalError during transaction.",
                exc_info=True,
            )
            # Rollback sẽ tự động xảy ra khi exception thoát khỏi `async with`
            raise e  # Ném lại lỗi để Celery biết task thất bại
    except Exception as e:
        # Bất kỳ lỗi nào khác cũng sẽ được log và ném ra
        log.error(
            f"[Lead ID: {lead_id}] Auto-assign task failed unexpectedly within transaction.",
            exc_info=True,
        )
        # Rollback tự động
        raise e  # Ném lại lỗi để Celery biết task thất bại
