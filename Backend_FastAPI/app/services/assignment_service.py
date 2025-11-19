# app/services/assignment_service.py
import logging
from datetime import datetime, timezone

from celery.exceptions import Retry  # Dùng để retry task
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError  # Dùng để bắt LockNotAvailableError
from sqlalchemy.ext.asyncio import AsyncSession

from .. import models
from ..config import settings
from ..socket_manager import emit_lead_assigned

# Lấy logger chuẩn ở đây, dùng làm fallback
default_log = logging.getLogger(__name__)


# Thêm tham số logger=None
async def automatically_assign_lead(
    lead_id: int, db: AsyncSession, logger: logging.Logger = None
):
    """
    Logic nghiệp vụ chính để tự động phân công Lead.
    Sử dụng logger được truyền vào hoặc logger mặc định.
    Sử dụng 'SKIP LOCKED' để xử lý concurrency khi khóa officers.
    Xử lý lock contention trên Lead bằng Celery Retry.
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
                return  # Kết thúc task nếu lead không tồn tại
            elif lead.assigned_officer_id:
                log.info(
                    f"[Lead ID: {lead_id}] Lead already assigned to officer {lead.assigned_officer_id}, skipping."
                )
                return  # Kết thúc task nếu lead đã được gán
            else:
                lead_unit_id = lead.unit_id
                log.debug(
                    f"[Lead ID: {lead_id}] Lead found and locked (Unit: {lead_unit_id}). Status: '{lead.status}'"
                )

                # === BƯỚC 2: Khóa các Officer liên quan (SỬ DỤNG SKIP LOCKED) ===
                available_officers_query = (
                    select(models.User).where(
                        models.User.role == "officer",
                        models.User.status == "active",
                        models.User.availability_status
                        == "available",  # Chỉ lấy officer đang sẵn sàng
                        models.User.unit_id == lead_unit_id,  # Cùng đơn vị với Lead
                    )
                    # ✅ CẢI TIẾN: Bỏ qua các officer đang bị khóa bởi transaction khác
                    .with_for_update(skip_locked=True)
                )
                officer_results = await db.execute(available_officers_query)
                # Lấy danh sách officer chưa bị khóa
                available_officers = officer_results.scalars().all()

                # --- Xử lý khi không có Officer ---
                if not available_officers:
                    log.warning(
                        f"[Lead ID: {lead_id}] No available (and unlocked) officers found for unit {lead_unit_id}. Setting status to unassigned."
                    )
                    lead.status = settings.DEFAULT_UNASSIGNED_LEAD_STATUS
                    # Ghi lại lịch sử thay đổi trạng thái (Optional nhưng nên có)
                    # await _log_lead_state_change(...) # Cần hàm helper này nếu muốn log
                    db.add(lead)
                    # Commit transaction lồng nhau ở đây vì đã kết thúc logic
                    # await db.commit() # Không cần commit tường minh khi dùng `async with`
                    return  # Kết thúc task

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
                        f"[Lead ID: {lead_id}] All available officers ({len(available_officers)}) in unit {lead_unit_id} are at full capacity. Setting status to unassigned."
                    )
                    lead.status = settings.DEFAULT_UNASSIGNED_LEAD_STATUS
                    # await _log_lead_state_change(...)
                    db.add(lead)
                    # await db.commit()
                    return  # Kết thúc task

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
                lead.status = settings.DEFAULT_ASSIGNED_LEAD_STATUS

                chosen_one.last_assigned_at = now_utc

                log_entry = models.AssignmentLog(
                    lead_id=lead.id,  # Lead ID chắc chắn đã có
                    officer_id=chosen_one.id,
                    method="automatic",
                    reason="Assigned by system (utilization routing)",
                    timestamp=now_utc,
                )

                # await _log_lead_state_change(...) # Ghi lại sự thay đổi trạng thái lead

                # Thêm tất cả các thay đổi vào session
                db.add_all([lead, chosen_one, log_entry])
                log.info(
                    f"[Lead ID: {lead_id}] Lead assignment successful to officer {chosen_one.id}."
                )

                # === BƯỚC 7: Emit Socket.IO Event for Real-time Notification ===
                # Load relationships để lấy thông tin đầy đủ cho event payload
                await db.refresh(lead, ["unit", "program_offering"])

                # Prepare lead data for socket event
                lead_data = {
                    "name": f"{lead.first_name or ''} {lead.last_name or ''}".strip() or "Unknown",
                    "phone": lead.phone or "",
                    "email": lead.email or "",
                    "offering_name": lead.program_offering.name if lead.program_offering else "N/A",
                    "unit_name": lead.unit.name if lead.unit else "N/A",
                    "priority": "normal"  # Can be enhanced with actual priority field
                }

                # Emit event to officer's room
                await emit_lead_assigned(
                    lead_id=lead.id,
                    officer_id=chosen_one.id,
                    lead_data=lead_data,
                    assignment_type="automatic"
                )
                log.info(
                    f"[Lead ID: {lead_id}] Socket.IO 'lead_assigned' event emitted to officer {chosen_one.id}."
                )

        # Kết thúc `async with db.begin_nested()` - Tự động commit nếu không có lỗi

    except OperationalError as e:
        # Bắt lỗi "LockNotAvailableError" (chủ yếu cho việc khóa Lead ban đầu)
        if (
            "could not obtain lock" in str(e).lower()
            or "lock not available" in str(e).lower()
        ):
            log.warning(
                f"[Lead ID: {lead_id}] Lock contention detected (possibly on Lead row). Retrying task in 5s..."
            )
            # Ném lỗi Retry để Celery tự động thử lại task sau
            raise Retry(exc=e, countdown=5, max_retries=5)  # Giới hạn số lần retry
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

    log.info(f"[Lead ID: {lead_id}] Auto-assign task finished successfully.")
