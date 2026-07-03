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


def _safe_positive_int(value: int | None, default: int) -> int:
    """Coerce to a usable positive int: None → ``default``, any value <= 0 → 1.
    Single backbone for _safe_capacity / _safe_weight."""
    if value is None:
        return default
    return value if value > 0 else 1


def _safe_capacity(officer: models.User) -> int:
    """Officer capacity with a safe fallback (default 100, never <= 0).
    Shared by the referral threshold check and the assignment loop (BƯỚC 4)."""
    return _safe_positive_int(officer.max_capacity, 100)


def _safe_weight(officer: models.User) -> int:
    """Officer member-assignment weight with a safe fallback (default 1, never <= 0).

    A higher weight lowers ``eff_util = workload / (capacity * weight)`` so the
    officer is treated as emptier and receives more leads. Weight 1 makes
    ``eff_util == real_util`` — but note that with ENABLE_MEMBER_WEIGHTED_ASSIGNMENT
    ON this is NOT identical to legacy round-robin: member mode orders by eff_util
    (workload-proportional), whereas legacy ignores workload magnitude in its
    tie-break. Direct attribute access (not getattr) so an attribute-name typo
    surfaces instead of silently returning 1. The None fallback only matters for an
    unflushed/mock ``User`` in tests (the prod column is NOT NULL + server_default
    '1' + CHECK 1..100)."""
    return _safe_positive_int(officer.assignment_weight, 1)


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
                        # real_util = tải THẬT (workload/capacity), KHÔNG nhân weight —
                        # cổng an toàn `overloaded` LUÔN đọc con số này. eff_util = tải
                        # hiệu dụng có nhân weight: weight cao ⇒ eff_util thấp ⇒ officer
                        # "được coi là vơi hơn" ⇒ nhận nhiều lead hơn (khi member ON).
                        real_util = workload / capacity
                        weight = _safe_weight(officer)
                        eff_util = workload / (capacity * weight)
                        officer_loads.append(
                            {
                                "officer": officer,
                                "workload": workload,
                                "real_util": real_util,
                                "eff_util": eff_util,
                                "weight": weight,
                                # Cổng an toàn theo tải THẬT — đặt sẵn ở đây, khỏi cần
                                # vòng lặp phụ ở BƯỚC 5 (weight không bao giờ phá trần).
                                "overloaded": real_util >= SAFETY_THRESHOLD,
                                # score = giá trị dùng để SẮP XẾP; mặc định real_util,
                                # các nhánh weighted ở BƯỚC 5 ghi đè. Ở nhánh legacy/
                                # fallback score GIỮ real_util nhưng KHÔNG quyết định thứ
                                # tự (sort chỉ theo overloaded+last_assigned) — chỉ mang
                                # tính thông tin cho snapshot.
                                "score": real_util,
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

                # `overloaded` (cổng an toàn theo tải THẬT) đã đặt sẵn ở BƯỚC 4 —
                # SAFETY_THRESHOLD là hằng module (chia sẻ với referral fast-path qua
                # is_officer_at_threshold). weight KHÔNG BAO GIỜ phá cổng này.

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

                # --- Quyết định CHẾ ĐỘ chấm điểm theo 2 flag độc lập + đủ history ---
                #   member_fairness: fairness ON + member ON + đủ pool-history (>=10)
                #   fairness:        fairness ON + member OFF + đủ unit-history (>=10) — Y HỆT P2-2 cũ
                #   member:          member ON (gồm cả fallback fairness+member thiếu history)
                #   legacy:          cả 2 OFF, HOẶC fairness ON + member OFF + thiếu history — Y HỆT hôm nay
                # (member scoring viết ở MỘT nơi duy nhất bên dưới, tránh trùng lặp.)
                if member_on and fairness_on:
                    # Target & actual PHẢI cùng pool = officer_loads (sau lọc capacity).
                    # KHÔNG dùng total_hist toàn unit: history officer offline/đầy tải sẽ
                    # loãng mẫu số ⇒ officer đã vượt share trong pool vẫn bị coi là dưới
                    # target. Pool đồng đều weight ⇒ pressure = actual − 1/N.
                    eligible_hist_total = sum(hist_counts.get(e["officer"].id, 0) for e in officer_loads)
                    scoring = "member_fairness" if eligible_hist_total >= 10 else "member"
                elif fairness_on:
                    total_hist = sum(hist_counts.values())
                    scoring = "fairness" if total_hist >= 10 else "legacy"
                elif member_on:
                    scoring = "member"
                else:
                    scoring = "legacy"

                # --- Áp chế độ: đặt score + reason. Mỗi weight >= 1 và các ngưỡng
                # history >= 10 đã đảm bảo mọi mẫu số dưới đây đều > 0 (không div-0). ---
                if scoring == "member_fairness":
                    total_weight = sum(e["weight"] for e in officer_loads)
                    for e in officer_loads:
                        target_share = e["weight"] / total_weight
                        actual_share = hist_counts.get(e["officer"].id, 0) / eligible_hist_total
                        # pressure = actual − target (<0 ⇒ dưới target ⇒ đẩy lên; >0 ⇒ phạt)
                        e["score"] = 0.6 * e["eff_util"] + 0.4 * (actual_share - target_share)
                    assign_reason = "member_fairness_weighted"
                    log.info(f"[Lead ID: {lead_id}] Member+fairness weighted (pool_hist={eligible_hist_total})")
                elif scoring == "fairness":
                    for e in officer_loads:
                        share = hist_counts.get(e["officer"].id, 0) / total_hist
                        e["score"] = 0.6 * e["real_util"] + 0.4 * share  # Y HỆT P2-2 cũ
                    assign_reason = "fairness_weighted"
                    log.info(f"[Lead ID: {lead_id}] Using fairness-weighted scoring (history={total_hist})")
                elif scoring == "member":
                    # Tie-break đầu là eff_util (weight cao ⇒ eff_util thấp ⇒ ưu tiên),
                    # rồi last_assigned. ⚠️ Weight ĐỒNG ĐỀU (đều =1) ⇒ eff_util == real_util
                    # ⇒ order theo TẢI THẬT (workload-proportional), KHÔNG phải round-robin
                    # thuần như legacy — đây là chủ đích của member mode, KHÁC legacy dù
                    # chưa phân hoá weight (xem test_matrix_member_on_uniform_weight...).
                    for e in officer_loads:
                        e["score"] = e["eff_util"]
                    assign_reason = "member_weighted"
                    log.info(f"[Lead ID: {lead_id}] Using member-weighted scoring")
                else:  # legacy — Y HỆT hôm nay
                    assign_reason = "lowest_workload"
                    log.info(f"[Lead ID: {lead_id}] Using legacy round-robin")

                # Legacy sắp xếp KHÔNG dùng score (round-robin thuần theo last_assigned);
                # các chế độ weighted chèn score làm tie-break thứ 2 (sau cổng overloaded).
                if scoring == "legacy":
                    officer_loads.sort(key=lambda x: (x["overloaded"], x["last_assigned"]))
                else:
                    officer_loads.sort(key=lambda x: (x["overloaded"], x["score"], x["last_assigned"]))

                chosen_officer_data = officer_loads[0]
                chosen_one = chosen_officer_data["officer"]
                chosen_workload = chosen_officer_data["workload"]
                log.info(
                    f"[Lead ID: {lead_id}] Selected officer {chosen_one.id} ({chosen_one.username}). "
                    f"Current Workload: {chosen_workload}, Max Capacity: {chosen_one.max_capacity}, "
                    f"Utilization: {chosen_officer_data['real_util']:.2f}, "
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
                # scores_snapshot (thuần audit — KHÔNG consumer runtime nào đọc;
                # fairness_service chỉ đọc capacity_snapshot):
                #  - Chế độ weighted → dict {real_util, eff_util, weight, score}
                #    (`score` là thành phần SẮP XẾP; đọc kèm `reason`).
                #  - Legacy/round-robin → gọn: chỉ real_util (eff_util==real_util,
                #    weight==1, score==real_util nên 3 field kia thừa; sort chỉ theo
                #    overloaded + last_assigned).
                await _log_assignment_decision(
                    db, lead_id=lead_id, assigned_officer_id=chosen_one.id,
                    eligible_officer_ids=officer_ids, unit_id=lead_unit_id,
                    channel="auto", reason=assign_reason,
                    scores_snapshot=(
                        {
                            str(ol["officer"].id): round(ol["real_util"], 4)
                            for ol in officer_loads
                        }
                        if scoring == "legacy"
                        else {
                            str(ol["officer"].id): {
                                "real_util": round(ol["real_util"], 4),
                                "eff_util": round(ol["eff_util"], 4),
                                "weight": ol["weight"],
                                "score": round(ol["score"], 4),
                            }
                            for ol in officer_loads
                        }
                    ),
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
