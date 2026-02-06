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
from .status_helper import StatusHelper, AssignmentStatus

# Lấy logger chuẩn ở đây, dùng làm fallback
default_log = logging.getLogger(__name__)


# Thêm tham số logger=None
async def automatically_assign_lead(
    lead_id: int, db: AsyncSession, logger: logging.Logger = None
) -> dict:
    """
    Logic nghiệp vụ chính để tự động phân công Lead.
    Sử dụng logger được truyền vào hoặc logger mặc định.
    Sử dụng 'SKIP LOCKED' để xử lý concurrency khi khóa officers.
    Xử lý lock contention trên Lead bằng Celery Retry.

    Returns:
        dict: Result with "status" key:
            - "assigned": Lead successfully assigned to officer
            - "failed": No officers available or all at capacity
            - "skipped": Lead already assigned or not found
    """
    log = logger or default_log
    log.info(f"[Lead ID: {lead_id}] Auto-assign task started")

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
                return {"status": AssignmentResult.SKIPPED, "reason": AssignmentFailureReason.LEAD_NOT_FOUND, "lead_id": lead_id}
            
            # ✅ FIX: Check if lead is deleted (soft delete)
            elif lead.deleted_at is not None:
                log.warning(
                    f"[Lead ID: {lead_id}] Lead is soft-deleted, skipping assignment."
                )
                return {"status": AssignmentResult.SKIPPED, "reason": AssignmentFailureReason.LEAD_DELETED, "lead_id": lead_id}
            
            elif lead.assigned_officer_id:
                log.info(
                    f"[Lead ID: {lead_id}] Lead already assigned to officer {lead.assigned_officer_id}, skipping."
                )
                return {"status": AssignmentResult.SKIPPED, "reason": AssignmentFailureReason.ALREADY_ASSIGNED, "lead_id": lead_id, "officer_id": lead.assigned_officer_id}
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
                        await dispatch(
                            db=db,
                            event=SystemEvents.LEAD_ASSIGNMENT_FAILED,
                            payload={
                                "lead_id": lead_id,
                                "unit_id": lead_unit_id,
                                "reason": "No officers available",
                                "lead_name": lead.full_name or "Unknown",
                                "actor_id": 0,  # System actor
                                "actor_name": "System",  # ✅ Added for template
                            },
                            dedupe_key=f"lead_assignment_failed:{lead_id}:no_officers",
                            auto_commit=True  # Critical for Celery context
                        )
                    except Exception as e:
                        log.error(
                            f"[Lead ID: {lead_id}] Failed to dispatch assignment failure notification: {e}"
                        )

                    return {"status": AssignmentResult.FAILED, "reason": AssignmentFailureReason.NO_OFFICERS, "lead_id": lead_id, "unit_id": lead_unit_id}

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
                        # Chỉ đếm lead chưa kết thúc (is_final_status = False hoặc NULL)
                        (models.ConsultationStatus.is_final_status == False) |
                        (models.ConsultationStatus.is_final_status.is_(None))
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
                    # Kiểm tra capacity (đảm bảo max_capacity không phải None và > 0)
                    capacity = (
                        officer.max_capacity
                        if officer.max_capacity is not None
                        else 100
                    )  # Giá trị mặc định an toàn
                    if capacity <= 0:
                        capacity = 1  # Tránh chia cho 0

                    if workload < capacity:
                        utilization = workload / capacity
                        officer_loads.append(
                            {
                                "officer": officer,
                                "workload": workload,
                                "utilization": utilization,
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
                        await dispatch(
                            db=db,
                            event=SystemEvents.LEAD_ASSIGNMENT_FAILED,
                            payload={
                                "lead_id": lead_id,
                                "unit_id": lead_unit_id,
                                "reason": "All officers at full capacity",
                                "lead_name": lead.full_name or "Unknown",
                                "actor_id": 0,  # System actor
                                "actor_name": "System",  # ✅ Added for template
                            },
                            dedupe_key=f"lead_assignment_failed:{lead_id}:capacity",
                            auto_commit=True  # Critical for Celery context
                        )
                    except Exception as e:
                        log.error(
                            f"[Lead ID: {lead_id}] Failed to dispatch assignment failure notification: {e}"
                        )

                    return {"status": AssignmentResult.FAILED, "reason": AssignmentFailureReason.AT_CAPACITY, "lead_id": lead_id, "unit_id": lead_unit_id}

                # === BƯỚC 5: Sắp xếp và Chọn Officer (HYBRID THRESHOLD ROUND ROBIN) ===
                # ✅ REFACTORED: Thuật toán mới chống "Flooding" cho nhân viên mới
                # Ngưỡng an toàn: 80% utilization
                # Ưu tiên:
                # 1. Nhóm chưa quá tải (utilization < 0.8) trước nhóm sắp quá tải (>= 0.8)
                # 2. Trong cùng nhóm, ưu tiên người được gán lâu nhất (Round Robin công bằng)
                SAFETY_THRESHOLD = 0.8
                officer_loads.sort(
                    key=lambda x: (
                        x["utilization"] >= SAFETY_THRESHOLD,  # False (nhóm an toàn) < True (nhóm quá tải)
                        x["last_assigned"],  # Sắp xếp theo datetime - người gán lâu nhất được ưu tiên
                    )
                )

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

            notification_payload = {
                "lead_id": lead.id,
                "officer_id": chosen_one.id,
                "actor_id": 0,  # System actor for automatic assignments
                "lead_name": lead.full_name or "Unknown",
                "lead_phone": lead.phone or "",
                "offering_name": offering_name,
                "actor_name": "System (Auto Assignment)",  # ✅ Added for template
                "is_automatic": True,  # ✅ NEW: For frontend to show "Tự động" badge
                "assignment_method": "automatic",  # ✅ NEW: Match AssignmentLog.method
            }

            # Dispatch notification (saves to DB + commits + sends via Socket.IO/Email)
            # ✅ FIX: Use auto_commit=True so callback executes (socket emit, cache update)
            # Without this, Celery workers create notifications but never emit to Socket.IO
            await dispatch(
                db=db,
                event=SystemEvents.LEAD_ASSIGNED,
                payload=notification_payload,
                dedupe_key=f"lead_assigned:{lead.id}:{chosen_one.id}",
                auto_commit=True  # Critical for Celery context
            )

            log.info(
                f"[Lead ID: {lead_id}] Automatic assignment notification dispatched to officer {chosen_one.id}."
            )
        except Exception as e:
            # Log but don't fail - lead assignment already succeeded
            log.error(
                f"[Lead ID: {lead_id}] Failed to dispatch assignment notification: {e}"
            )

        # Return success result
        return {"status": AssignmentResult.ASSIGNED, "lead_id": lead_id, "officer_id": chosen_one.id}

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
