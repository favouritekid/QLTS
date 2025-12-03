import structlog
from datetime import datetime, timedelta, timezone, date
from typing import List, Dict, Any, Callable, Tuple

from sqlalchemy import select, func, or_, desc, case, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload, joinedload, aliased

from .. import models, schemas
from ..core.events import SystemEvents
from .notification_dispatcher import dispatch

log = structlog.get_logger(__name__)


async def get_officer_dashboard_stats(
    db: AsyncSession, officer_id: int
) -> Dict[str, Any]:
    """
    Lấy thống kê tổng hợp cho Officer Dashboard.
    Logic Workload khớp với assignment_service (dựa trên is_final_status).
    """
    # 1. Lấy thông tin User (Officer)
    user = await db.get(models.User, officer_id)
    if not user:
        raise ValueError(f"User {officer_id} not found")

    # 2. TÍNH TOÁN WORKLOAD & CAPACITY
    # Logic: Chỉ đếm những Lead mà status của nó CÓ is_final_status = False (hoặc NULL)
    # Điều này đồng bộ với logic phân phối trong assignment_service
    workload_query = (
        select(func.count(models.Lead.id))
        .join(
            models.ConsultationStatus,
            models.Lead.consultation_status_id == models.ConsultationStatus.id,
            isouter=True,  # LEFT JOIN để lấy cả Lead chưa có status
        )
        .where(
            models.Lead.assigned_officer_id == officer_id,
            or_(
                models.ConsultationStatus.is_final_status == False,
                models.ConsultationStatus.is_final_status.is_(None),
            ),
        )
    )
    current_workload = (await db.execute(workload_query)).scalar() or 0
    
    max_capacity = user.max_capacity or 100
    # Tránh chia cho 0
    utilization = 0.0
    if max_capacity > 0:
        utilization = round((current_workload / max_capacity) * 100, 1)

    # 3. PERFORMANCE TRENDS (7 ngày qua)
    # Chúng ta cần thống kê 3 chỉ số theo ngày:
    # - Assigned: Số lead được gán (dựa vào AssignmentLog hoặc created_at nếu gán ngay)
    # - Consultations: Số lượt tương tác (dựa vào bảng Consultation - nếu có)
    # - Converted: Số lead chuyển đổi thành công (Status final & positive)
    
    today = datetime.now(timezone.utc).date()
    seven_days_ago = today - timedelta(days=6)
    
    # A. Query số lượng Lead được gán theo ngày (Dựa trên AssignmentLog)
    # Nếu chưa có bảng AssignmentLog đầy đủ, có thể tạm dùng Lead.created_at cho lead mới
    assigned_query = (
        select(
            func.date(models.AssignmentLog.timestamp).label("date"),
            func.count(models.AssignmentLog.id)
        )
        .where(
            models.AssignmentLog.officer_id == officer_id,
            func.date(models.AssignmentLog.timestamp) >= seven_days_ago
        )
        .group_by(func.date(models.AssignmentLog.timestamp))
    )
    assigned_res = (await db.execute(assigned_query)).all()

    # B. Query số lượng Consultation (Tương tác) theo ngày
    # Giả định bạn có model Consultation, nếu chưa có bảng này thì trả về 0
    # consultation_query = (...) 
    # Ở đây tôi để placeholder để code không lỗi nếu thiếu bảng
    consultations_res = [] 
    # Nếu có bảng Consultation, uncomment đoạn dưới:
    """
    consultation_query = (
        select(
            func.date(models.Consultation.created_at).label("date"),
            func.count(models.Consultation.id)
        )
        .where(
            models.Consultation.officer_id == officer_id,
            func.date(models.Consultation.created_at) >= seven_days_ago
        )
        .group_by(func.date(models.Consultation.created_at))
    )
    consultations_res = (await db.execute(consultation_query)).all()
    """

    # C. Query số lượng Lead Chốt đơn (Converted) theo ngày cập nhật
    # (Dựa trên Lead.updated_at và status positive)
    converted_query = (
        select(
            func.date(models.Lead.updated_at).label("date"),
            func.count(models.Lead.id)
        )
        .join(models.ConsultationStatus, models.Lead.consultation_status_id == models.ConsultationStatus.id)
        .where(
            models.Lead.assigned_officer_id == officer_id,
            models.ConsultationStatus.outcome_type == "positive",
            models.ConsultationStatus.is_final_status == True,
            func.date(models.Lead.updated_at) >= seven_days_ago
        )
        .group_by(func.date(models.Lead.updated_at))
    )
    converted_res = (await db.execute(converted_query)).all()

    # Tổng hợp dữ liệu vào Dict để fill những ngày trống
    trends_map = {}
    for i in range(7):
        d = seven_days_ago + timedelta(days=i)
        d_str = d.strftime("%Y-%m-%d")
        trends_map[d_str] = {
            "date": d_str, 
            "assigned": 0, 
            "consultations": 0, 
            "converted": 0
        }

    for row in assigned_res:
        d_str = str(row.date)
        if d_str in trends_map:
            trends_map[d_str]["assigned"] = row[1]
            
    for row in consultations_res:
        d_str = str(row.date)
        if d_str in trends_map:
            trends_map[d_str]["consultations"] = row[1]

    for row in converted_res:
        d_str = str(row.date)
        if d_str in trends_map:
            trends_map[d_str]["converted"] = row[1]

    performance_trends = list(trends_map.values())

    # 4. SALES FUNNEL (Phễu bán hàng)
    # Đếm số lượng Lead theo từng Stage (Pipeline Stage)
    funnel_query = (
        select(
            models.PipelineStage.name,
            func.count(models.Lead.id),
            models.PipelineStage.order
        )
        .select_from(models.Lead)
        .join(models.PipelineStage, models.Lead.pipeline_stage_id == models.PipelineStage.id)
        .where(models.Lead.assigned_officer_id == officer_id)
        .group_by(models.PipelineStage.id, models.PipelineStage.name, models.PipelineStage.order)
        .order_by(models.PipelineStage.order.asc())
    )
    funnel_res = (await db.execute(funnel_query)).all()
    
    # Format màu sắc cho đẹp (Chart 1 -> 5)
    sales_funnel = []
    for idx, row in enumerate(funnel_res):
        sales_funnel.append({
            "stage": row[0],
            "count": row[1],
            "fill": f"var(--chart-{idx % 5 + 1})"
        })

    # 5. ACTIONABLE LISTS (Danh sách cần xử lý)
    
    # A. High Score Leads (Top 5 điểm cao chưa chốt)
    high_score_query = (
        select(models.Lead)
        .join(models.ConsultationStatus, models.Lead.consultation_status_id == models.ConsultationStatus.id, isouter=True)
        .where(
            models.Lead.assigned_officer_id == officer_id,
            # Chỉ lấy lead chưa final
            or_(
                models.ConsultationStatus.is_final_status == False,
                models.ConsultationStatus.is_final_status.is_(None)
            )
        )
        .order_by(models.Lead.lead_score.desc().nulls_last())
        .limit(5)
    )
    high_score_leads = (await db.execute(high_score_query)).scalars().all()

    # B. Stale Leads (Lead "nguội" - Không cập nhật > 3 ngày)
    stale_date = datetime.now(timezone.utc) - timedelta(days=3)
    stale_query = (
        select(models.Lead)
        .join(models.ConsultationStatus, models.Lead.consultation_status_id == models.ConsultationStatus.id, isouter=True)
        .where(
            models.Lead.assigned_officer_id == officer_id,
            models.Lead.updated_at < stale_date,
            or_(
                models.ConsultationStatus.is_final_status == False,
                models.ConsultationStatus.is_final_status.is_(None)
            )
        )
        .order_by(models.Lead.updated_at.asc()) # Cũ nhất lên đầu
        .limit(5)
    )
    stale_leads = (await db.execute(stale_query)).scalars().all()

    # C. Upcoming (Lịch hẹn sắp tới)
    # Placeholder: Trả về rỗng nếu chưa có bảng Consultation/Task
    upcoming = []

    return {
        "status_overview": {
            "current_workload": current_workload,
            "max_capacity": max_capacity,
            "utilization": utilization,
            "availability_status": user.availability_status or "offline"
        },
        "performance_trends": performance_trends,
        "sales_funnel": sales_funnel,
        "actionable_lists": {
            "high_score": high_score_leads,
            "stale": stale_leads,
            "upcoming": upcoming
        }
    }


async def update_officer_availability(
    db: AsyncSession,
    officer_id: int,
    availability_status: str
) -> Tuple[models.User, Callable]:
    """
    Cập nhật trạng thái nhận việc (Available/Busy) và bắn Socket.

    IMPORTANT: This function does NOT commit the transaction.
    Router must call db.commit() and then execute the returned callback.

    Returns:
        Tuple of (user, post_commit_callback)
    """
    user = await db.get(models.User, officer_id)
    if not user:
        raise ValueError("User not found")

    old_status = user.availability_status
    user.availability_status = availability_status
    db.add(user)

    # ✅ TRANSACTION FIX: Flush instead of commit
    await db.flush()
    await db.refresh(user)

    # ✅ Create post-commit callback
    async def _post_commit():
        """Execute after router commits the transaction."""
        # Dispatch notification for officer availability change
        try:
            await dispatch(
                db=db,
                event=SystemEvents.OFFICER_AVAILABILITY_CHANGED,
                payload={
                    "officer_id": officer_id,
                    "new_status": availability_status,
                    "old_status": old_status,
                    "username": user.username,
                    "unit_id": user.unit_id,
                    "actor_id": officer_id,  # Officer changes their own status
                }
            )
        except Exception as e:
            log.warning(
                "Failed to dispatch officer availability notification",
                officer_id=officer_id,
                error=str(e)
            )

    return user, _post_commit