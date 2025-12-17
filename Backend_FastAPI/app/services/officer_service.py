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
    # Đồng bộ logic với funnel: dùng pipeline_stage.is_final_stage
    # thay vì consultation_status.is_final_status
    workload_query = (
        select(func.count(models.Lead.id))
        .join(
            models.PipelineStage,
            models.Lead.pipeline_stage_id == models.PipelineStage.id,
            isouter=True,  # LEFT JOIN để lấy cả Lead chưa có stage
        )
        .where(
            models.Lead.assigned_officer_id == officer_id,
            models.Lead.deleted_at.is_(None),  # Exclude soft-deleted leads
            or_(
                models.PipelineStage.is_final_stage == False,
                models.PipelineStage.is_final_stage.is_(None),
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

    # 4. SALES FUNNEL (Phễu bán hàng) - ACTUAL DISTRIBUTION
    # Changed from cumulative to actual count per stage
    # This reflects the true current distribution of leads across pipeline stages
    
    # First, get total leads assigned to this officer (baseline = 100%)
    # Exclude soft-deleted leads (deleted_at IS NULL)
    total_leads_query = (
        select(func.count(models.Lead.id))
        .where(
            models.Lead.assigned_officer_id == officer_id,
            models.Lead.deleted_at.is_(None)  # Exclude soft-deleted leads
        )
    )
    total_leads = (await db.execute(total_leads_query)).scalar() or 0
    
    # Get all pipeline stages ordered
    stages_query = (
        select(models.PipelineStage)
        .order_by(models.PipelineStage.order.asc())
    )
    all_stages = (await db.execute(stages_query)).scalars().all()
    
    # For each stage, count leads CURRENTLY AT that stage
    # Also calculate outcome breakdown based on latest consultation's outcome_type
    sales_funnel = []
    total_dropoff = 0  # Total leads with negative outcome
    
    for idx, stage in enumerate(all_stages):
        # Count leads at THIS specific stage (not cumulative)
        # Exclude soft-deleted leads
        stage_count_query = (
            select(func.count(models.Lead.id))
            .where(
                models.Lead.assigned_officer_id == officer_id,
                models.Lead.pipeline_stage_id == stage.id,
                models.Lead.deleted_at.is_(None)  # Exclude soft-deleted leads
            )
        )
        stage_count = (await db.execute(stage_count_query)).scalar() or 0
        
        # Count leads by outcome_type of their latest consultation
        # Subquery to get latest consultation for each lead
        from sqlalchemy import case, literal_column
        
        # Get outcome breakdown for leads at this stage
        outcome_query = (
            select(
                models.ConsultationStatus.outcome_type,
                func.count(models.Lead.id).label("count")
            )
            .join(models.ConsultationStatus, models.Lead.consultation_status_id == models.ConsultationStatus.id)
            .where(
                models.Lead.assigned_officer_id == officer_id,
                models.Lead.pipeline_stage_id == stage.id,
                models.Lead.deleted_at.is_(None)
            )
            .group_by(models.ConsultationStatus.outcome_type)
        )
        outcome_result = await db.execute(outcome_query)
        outcome_counts = {row[0]: row[1] for row in outcome_result.fetchall()}
        
        positive_count = outcome_counts.get("positive", 0)
        negative_count = outcome_counts.get("negative", 0)
        neutral_count = outcome_counts.get("neutral", 0)
        
        total_dropoff += negative_count
        
        sales_funnel.append({
            "stage_id": stage.id,              # e.g. "stg05"
            "stage_name": stage.name,          # e.g. "Đã nộp học phí"
            "stage_order": stage.order,        # For frontend sorting
            "lead_count": stage_count,         # Actual count at this stage
            "is_final_stage": stage.is_final_stage,  # For separating outcomes
            "fill": f"var(--chart-{idx % 5 + 1})",
            "conversion_rate": None,  # Will be calculated below
            "outcome_breakdown": {
                "positive": positive_count,
                "negative": negative_count,
                "neutral": neutral_count,
            }
        })

    # 4.1 HISTORICAL CONVERSION RATES (from lead_status_history)
    # Calculate actual transition rates between stages over the past 30 days
    thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
    
    # Query: count transitions from each stage to next stages
    # FIX: Use changed_by_user_id from history table instead of Lead.assigned_officer_id
    # This ensures we count transitions made BY this officer, not just current assignments
    # (Leads may have been reassigned since the transition was made)
    transition_query = (
        select(
            models.LeadStatusHistory.old_pipeline_stage_id,
            models.LeadStatusHistory.new_pipeline_stage_id,
            func.count().label("transition_count")
        )
        .where(
            models.LeadStatusHistory.changed_by_user_id == officer_id,
            models.LeadStatusHistory.changed_at >= thirty_days_ago,
            models.LeadStatusHistory.old_pipeline_stage_id.isnot(None),
            models.LeadStatusHistory.new_pipeline_stage_id.isnot(None),
            models.LeadStatusHistory.old_pipeline_stage_id != models.LeadStatusHistory.new_pipeline_stage_id
        )
        .group_by(
            models.LeadStatusHistory.old_pipeline_stage_id,
            models.LeadStatusHistory.new_pipeline_stage_id
        )
    )
    transition_result = await db.execute(transition_query)
    transitions = transition_result.fetchall()
    
    # Build transition map: {from_stage: {to_stage: count, ...}}
    transition_map: Dict[str, Dict[str, int]] = {}
    for row in transitions:
        from_stage, to_stage, count = row
        if from_stage not in transition_map:
            transition_map[from_stage] = {}
        transition_map[from_stage][to_stage] = count
    
    # Calculate conversion rate for each stage (to next stage)
    # Conversion = leads that moved to HIGHER non-final stage / total leads that left this stage
    # FIX: Exclude transitions to FINAL stages (stg06, stg07) from progressive count
    # because stg07 (lost) has higher order but is NOT a progression
    for i, funnel_stage in enumerate(sales_funnel):
        stage_id = funnel_stage["stage_id"]
        stage_order = funnel_stage["stage_order"]
        
        if stage_id in transition_map:
            transitions_from = transition_map[stage_id]
            total_out = sum(transitions_from.values())
            
            # Count transitions to higher NON-FINAL stages (true progression)
            progressive_count = 0
            for to_stage_id, count in transitions_from.items():
                # Find to_stage and check if it's a progression
                for s in all_stages:
                    if s.id == to_stage_id:
                        # Only count as progressive if:
                        # 1. Higher order AND
                        # 2. NOT a final stage (final stages like stg06/stg07 are outcomes, not progression)
                        if s.order > stage_order and not s.is_final_stage:
                            progressive_count += count
                        break
            
            if total_out > 0:
                conversion_rate = round((progressive_count / total_out) * 100, 1)
                sales_funnel[i]["conversion_rate"] = conversion_rate

    # 5. ACTIONABLE LISTS (Danh sách cần xử lý)
    
    # A. High Score Leads (Top 5 điểm cao chưa chốt)
    high_score_query = (
        select(models.Lead)
        .options(selectinload(models.Lead.pipeline_stage))  # Eager load for stage_name
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
        .options(selectinload(models.Lead.pipeline_stage))  # Eager load for stage_name
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

    # Convert Lead objects to LeadPreview format
    def lead_to_preview(lead: models.Lead) -> dict:
        """Convert Lead model to LeadPreview schema format."""
        return {
            "id": lead.id,
            "name": lead.full_name or "",  # Map full_name to name
            "email": lead.email,
            "phone": lead.phone,
            "lead_score": lead.lead_score or 0,
            "updated_at": lead.updated_at,
            "stage_name": lead.pipeline_stage.name if lead.pipeline_stage else None,
        }

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
            "high_score": [lead_to_preview(lead) for lead in high_score_leads],
            "stale": [lead_to_preview(lead) for lead in stale_leads],
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
                },
                auto_commit=True  # ✅ Auto-commit for service callback
            )
        except Exception as e:
            log.warning(
                "Failed to dispatch officer availability notification",
                officer_id=officer_id,
                error=str(e)
            )

    return user, _post_commit


# =============================================================================
# HELPER: Sales Funnel with Date Range Filter
# =============================================================================

async def _get_sales_funnel_in_range(
    db: AsyncSession,
    officer_id: int,
    filter_start: date,
    filter_end: date
) -> List[Dict[str, Any]]:
    """
    Get sales funnel data filtered by date range.
    Only counts leads created within the date range.
    """
    # Query pipeline stages ordered (no is_active, all stages are active)
    stages_query = (
        select(models.PipelineStage)
        .order_by(models.PipelineStage.order)
    )
    stages_result = await db.execute(stages_query)
    all_stages = stages_result.scalars().all()
    
    sales_funnel = []
    for idx, stage in enumerate(all_stages):
        # Count leads in this stage created within date range
        count_query = (
            select(func.count(models.Lead.id))
            .where(
                models.Lead.assigned_officer_id == officer_id,
                models.Lead.pipeline_stage_id == stage.id,
                func.date(models.Lead.created_at) >= filter_start,
                func.date(models.Lead.created_at) <= filter_end,
            )
        )
        lead_count = (await db.execute(count_query)).scalar() or 0
        
        # Outcome breakdown for final stages (within date range)
        positive_count = 0
        negative_count = 0
        neutral_count = 0
        
        if stage.is_final_stage:
            # Get outcome distribution
            outcome_query = (
                select(
                    models.ConsultationStatus.outcome_type,
                    func.count(models.Lead.id)
                )
                .join(models.ConsultationStatus, models.Lead.consultation_status_id == models.ConsultationStatus.id)
                .where(
                    models.Lead.assigned_officer_id == officer_id,
                    models.Lead.pipeline_stage_id == stage.id,
                    func.date(models.Lead.created_at) >= filter_start,
                    func.date(models.Lead.created_at) <= filter_end,
                )
                .group_by(models.ConsultationStatus.outcome_type)
            )
            outcome_result = await db.execute(outcome_query)
            for row in outcome_result:
                if row[0] == "positive":
                    positive_count = row[1]
                elif row[0] == "negative":
                    negative_count = row[1]
                else:
                    neutral_count = row[1]
        
        sales_funnel.append({
            "stage_id": stage.id,
            "stage_name": stage.name,
            "stage_order": stage.order,
            "lead_count": lead_count,
            "is_final_stage": stage.is_final_stage,
            "fill": f"var(--chart-{idx % 5 + 1})",
            "conversion_rate": None,
            "outcome_breakdown": {
                "positive": positive_count,
                "negative": negative_count,
                "neutral": neutral_count,
            }
        })
    
    # Calculate conversion rates from transition history (within date range)
    transition_query = (
        select(
            models.LeadStatusHistory.old_pipeline_stage_id,
            models.LeadStatusHistory.new_pipeline_stage_id,
            func.count().label("transition_count")
        )
        .where(
            models.LeadStatusHistory.changed_by_user_id == officer_id,
            func.date(models.LeadStatusHistory.changed_at) >= filter_start,
            func.date(models.LeadStatusHistory.changed_at) <= filter_end,
            models.LeadStatusHistory.old_pipeline_stage_id.isnot(None),
            models.LeadStatusHistory.new_pipeline_stage_id.isnot(None),
            models.LeadStatusHistory.old_pipeline_stage_id != models.LeadStatusHistory.new_pipeline_stage_id
        )
        .group_by(
            models.LeadStatusHistory.old_pipeline_stage_id,
            models.LeadStatusHistory.new_pipeline_stage_id
        )
    )
    transition_result = await db.execute(transition_query)
    transitions = transition_result.fetchall()
    
    transition_map: Dict[str, Dict[str, int]] = {}
    for row in transitions:
        from_stage, to_stage, count = row
        if from_stage not in transition_map:
            transition_map[from_stage] = {}
        transition_map[from_stage][to_stage] = count
    
    for i, funnel_stage in enumerate(sales_funnel):
        stage_id = funnel_stage["stage_id"]
        stage_order = funnel_stage["stage_order"]
        
        if stage_id in transition_map:
            transitions_from = transition_map[stage_id]
            total_out = sum(transitions_from.values())
            
            progressive_count = 0
            for to_stage_id, count in transitions_from.items():
                for s in all_stages:
                    if s.id == to_stage_id:
                        if s.order > stage_order and not s.is_final_stage:
                            progressive_count += count
                        break
            
            if total_out > 0:
                conversion_rate = round((progressive_count / total_out) * 100, 1)
                sales_funnel[i]["conversion_rate"] = conversion_rate
    
    return sales_funnel


# =============================================================================
# PHASE 1: Enhanced Dashboard with KPIs (+ Date Range Filter)
# =============================================================================


async def get_enhanced_dashboard_stats(
    db: AsyncSession, 
    officer_id: int,
    start_date: str = None,  # ISO format YYYY-MM-DD
    end_date: str = None,    # ISO format YYYY-MM-DD
) -> Dict[str, Any]:
    """
    Enhanced dashboard with KPIs, priority actions, and trends.
    Builds on get_officer_dashboard_stats with additional metrics.
    
    Args:
        db: Database session
        officer_id: Officer user ID
        start_date: Optional start date filter (YYYY-MM-DD)
        end_date: Optional end date filter (YYYY-MM-DD)
    """
    # Parse date range if provided
    today = datetime.now(timezone.utc).date()
    if start_date and end_date:
        try:
            filter_start = date.fromisoformat(start_date)
            filter_end = date.fromisoformat(end_date)
            log.info(
                "Dashboard with date filter",
                officer_id=officer_id,
                start_date=start_date,
                end_date=end_date
            )
        except ValueError:
            filter_start = today - timedelta(days=6)
            filter_end = today
    else:
        # Default: last 7 days
        filter_start = today - timedelta(days=6)
        filter_end = today
    
    # Get base stats first
    base_stats = await get_officer_dashboard_stats(db, officer_id)
    
    yesterday = today - timedelta(days=1)
    week_ago = today - timedelta(days=7)
    month_start = today.replace(day=1)
    last_month_start = (month_start - timedelta(days=1)).replace(day=1)
    
    # Calculate days in filter range for averages
    filter_days = (filter_end - filter_start).days + 1
    
    # === 1. CONSULTATIONS IN DATE RANGE ===
    # Count consultations within the selected date range
    consultations_range_query = (
        select(func.count(models.Consultation.id))
        .where(
            models.Consultation.officer_id == officer_id,
            func.date(models.Consultation.consultation_date) >= filter_start,
            func.date(models.Consultation.consultation_date) <= filter_end
        )
    )
    consultations_in_range = (await db.execute(consultations_range_query)).scalar() or 0
    
    # Today's consultations (always show today regardless of filter)
    consultations_today_query = (
        select(func.count(models.Consultation.id))
        .where(
            models.Consultation.officer_id == officer_id,
            func.date(models.Consultation.consultation_date) == today
        )
    )
    consultations_today = (await db.execute(consultations_today_query)).scalar() or 0
    
    # Calculate daily average for the selected period
    consultations_avg = consultations_in_range / filter_days if filter_days > 0 else 0
    
    # Compare today vs average in selected period
    if consultations_avg > 0:
        trend_pct = ((consultations_today - consultations_avg) / consultations_avg) * 100
        trend_direction = "up" if trend_pct > 0 else "down" if trend_pct < 0 else "neutral"
    else:
        trend_pct = 0
        trend_direction = "neutral"
    
    consultations_trend = {
        "value": abs(round(trend_pct, 1)),
        "direction": trend_direction,
        "comparison": f"vs TB {filter_days} ngày"
    }
    
    # === 2. ACTIVE LEADS (in date range) ===
    # Count leads created within the date range that are still active
    active_leads_range_query = (
        select(func.count(models.Lead.id))
        .join(
            models.ConsultationStatus,
            models.Lead.consultation_status_id == models.ConsultationStatus.id,
            isouter=True
        )
        .where(
            models.Lead.assigned_officer_id == officer_id,
            func.date(models.Lead.created_at) >= filter_start,
            func.date(models.Lead.created_at) <= filter_end,
            or_(
                models.ConsultationStatus.is_final_status == False,
                models.ConsultationStatus.is_final_status.is_(None)
            )
        )
    )
    active_leads = (await db.execute(active_leads_range_query)).scalar() or 0
    
    active_leads_trend = {
        "value": 0,
        "direction": "neutral",
        "comparison": f"trong {filter_days} ngày"
    }
    
    # === 3. CONVERSION RATE (in date range) ===
    # Leads CREATED in date range AND converted (cohort analysis)
    converted_range_query = (
        select(func.count(models.Lead.id))
        .join(models.ConsultationStatus)
        .where(
            models.Lead.assigned_officer_id == officer_id,
            models.ConsultationStatus.is_final_status == True,
            models.ConsultationStatus.outcome_type == "positive",
            func.date(models.Lead.created_at) >= filter_start,
            func.date(models.Lead.created_at) <= filter_end,
        )
    )
    converted_in_range = (await db.execute(converted_range_query)).scalar() or 0
    
    total_leads_range_query = (
        select(func.count(models.Lead.id))
        .where(
            models.Lead.assigned_officer_id == officer_id,
            func.date(models.Lead.created_at) >= filter_start,
            func.date(models.Lead.created_at) <= filter_end,
        )
    )
    total_in_range = (await db.execute(total_leads_range_query)).scalar() or 1
    
    conversion_rate = round((converted_in_range / total_in_range) * 100, 1)
    
    # Compare with previous period of same length
    prev_filter_end = filter_start - timedelta(days=1)
    prev_filter_start = prev_filter_end - timedelta(days=filter_days - 1)
    
    converted_prev_query = (
        select(func.count(models.Lead.id))
        .join(models.ConsultationStatus)
        .where(
            models.Lead.assigned_officer_id == officer_id,
            models.ConsultationStatus.is_final_status == True,
            models.ConsultationStatus.outcome_type == "positive",
            func.date(models.Lead.created_at) >= prev_filter_start,
            func.date(models.Lead.created_at) <= prev_filter_end,
        )
    )
    converted_prev = (await db.execute(converted_prev_query)).scalar() or 0
    
    total_prev_query = (
        select(func.count(models.Lead.id))
        .where(
            models.Lead.assigned_officer_id == officer_id,
            func.date(models.Lead.created_at) >= prev_filter_start,
            func.date(models.Lead.created_at) <= prev_filter_end,
        )
    )
    total_prev = (await db.execute(total_prev_query)).scalar() or 1
    prev_rate = (converted_prev / total_prev) * 100
    
    conversion_diff = conversion_rate - prev_rate
    conversion_trend = {
        "value": abs(round(conversion_diff, 1)),
        "direction": "up" if conversion_diff > 0 else "down" if conversion_diff < 0 else "neutral",
        "comparison": f"vs {filter_days} ngày trước"
    }
    
    # === 4. AVERAGE RESPONSE TIME ===
    avg_response_time = 2.5  # Placeholder
    avg_response_trend = {
        "value": 15,
        "direction": "down",
        "comparison": "vs TB"
    }
    
    # === 5. PRIORITY ACTIONS ===
    priority_actions = await _calculate_priority_actions(db, officer_id)
    
    # === 6. PERFORMANCE TRENDS (within date range) ===
    # Generate trend data for each day in the date range
    performance_trends = []
    current_date = filter_start
    while current_date <= filter_end:
        # Consultations for this day
        day_consults_query = (
            select(func.count(models.Consultation.id))
            .where(
                models.Consultation.officer_id == officer_id,
                func.date(models.Consultation.consultation_date) == current_date
            )
        )
        day_consults = (await db.execute(day_consults_query)).scalar() or 0
        
        # Leads assigned on this day
        day_assigned_query = (
            select(func.count(models.AssignmentLog.id))
            .where(
                models.AssignmentLog.officer_id == officer_id,
                func.date(models.AssignmentLog.timestamp) == current_date
            )
        )
        day_assigned = (await db.execute(day_assigned_query)).scalar() or 0
        
        # Leads converted on this day (status changed to final positive)
        day_converted_query = (
            select(func.count(models.LeadStatusHistory.id))
            .join(models.Lead, models.LeadStatusHistory.lead_id == models.Lead.id)
            .join(models.PipelineStage, models.LeadStatusHistory.new_pipeline_stage_id == models.PipelineStage.id)
            .where(
                models.LeadStatusHistory.changed_by_user_id == officer_id,
                func.date(models.LeadStatusHistory.changed_at) == current_date,
                models.PipelineStage.is_final_stage == True
            )
        )
        day_converted = (await db.execute(day_converted_query)).scalar() or 0
        
        performance_trends.append({
            "date": current_date.isoformat(),
            "assigned": day_assigned,
            "consultations": day_consults,
            "converted": day_converted
        })
        current_date += timedelta(days=1)
    
    # === 7. SALES FUNNEL (within date range) ===
    # Get funnel stages with leads created in date range
    sales_funnel = await _get_sales_funnel_in_range(db, officer_id, filter_start, filter_end)
    
    # Build enhanced response
    return {
        "kpis": {
            "consultations_today": consultations_today,
            "consultations_target": 10,
            "consultations_trend": consultations_trend,
            "active_leads": active_leads,
            "active_leads_trend": active_leads_trend,
            "conversion_rate": conversion_rate,
            "conversion_rate_trend": conversion_trend,
            "avg_response_time": avg_response_time,
            "avg_response_time_trend": avg_response_trend,
        },
        "status_overview": base_stats["status_overview"],
        "priority_actions": priority_actions,
        "performance_trends": performance_trends,
        "sales_funnel": sales_funnel,
        "actionable_lists": base_stats["actionable_lists"],
    }


async def _calculate_priority_actions(
    db: AsyncSession, officer_id: int, limit: int = 5
) -> List[Dict[str, Any]]:
    """
    Calculate AI-powered priority actions based on scoring algorithm.
    
    Priority Score = 
        (Lead Score × 0.3) +
        (Days Since Contact × 0.3) +
        (Urgency Score × 0.2) +
        (Is Hot Lead × 0.2)
    """
    today = datetime.now(timezone.utc)
    stale_threshold = today - timedelta(days=3)
    
    # Get leads needing attention
    leads_query = (
        select(models.Lead)
        .options(selectinload(models.Lead.pipeline_stage))
        .join(
            models.ConsultationStatus,
            models.Lead.consultation_status_id == models.ConsultationStatus.id,
            isouter=True
        )
        .where(
            models.Lead.assigned_officer_id == officer_id,
            or_(
                models.ConsultationStatus.is_final_status == False,
                models.ConsultationStatus.is_final_status.is_(None)
            )
        )
        .order_by(
            models.Lead.cached_urgency_score.desc().nulls_last(),
            models.Lead.lead_score.desc().nulls_last()
        )
        .limit(20)  # Get more to filter/score
    )
    leads = (await db.execute(leads_query)).scalars().all()
    
    actions = []
    for lead in leads:
        # Calculate priority score
        lead_score = lead.lead_score or 0
        urgency_score = lead.cached_urgency_score or 0
        last_contact = lead.last_consultation_at or lead.created_at
        days_since_contact = (today - last_contact.replace(tzinfo=timezone.utc)).days if last_contact else 999
        
        # Determine action type and priority
        if lead_score >= 70:
            action_type = "hot_lead"
            priority = "urgent" if days_since_contact >= 2 else "high"
            reason = f"Lead điểm cao ({lead_score}), cần liên hệ sớm"
        elif days_since_contact >= 3:
            action_type = "overdue"
            priority = "urgent" if days_since_contact >= 5 else "high"
            reason = f"Chưa liên hệ {days_since_contact} ngày"
        elif urgency_score >= 70:
            action_type = "follow_up"
            priority = "high"
            reason = f"Độ khẩn cấp cao ({urgency_score}%)"
        elif days_since_contact == 0 and lead.created_at.date() == today.date():
            action_type = "new_lead"
            priority = "high"
            reason = "Lead mới được gán hôm nay"
        else:
            action_type = "follow_up"
            priority = "medium"
            reason = f"Cần follow-up"
        
        # Score for sorting
        score = (lead_score * 0.3) + (min(days_since_contact, 10) * 3) + (urgency_score * 0.2)
        if action_type == "hot_lead":
            score += 30
        if action_type == "overdue":
            score += 40
        
        actions.append({
            "id": f"action_{lead.id}",
            "type": action_type,
            "priority": priority,
            "lead_id": lead.id,
            "lead_name": lead.full_name or "Unknown",
            "lead_score": lead_score,
            "reason": reason,
            "days_since_contact": days_since_contact,
            "_score": score  # For sorting
        })
    
    # Sort by score and take top N
    actions.sort(key=lambda x: x["_score"], reverse=True)
    
    # Remove internal score before returning
    for action in actions[:limit]:
        del action["_score"]
    
    return actions[:limit]


# =============================================================================
# PHASE 4: Leaderboard & Gamification
# =============================================================================

async def get_weekly_leaderboard(
    db: AsyncSession, officer_id: int, limit: int = 5
) -> Dict[str, Any]:
    """
    Get weekly leaderboard for gamification.
    Shows top officers by consultations and conversions this week.
    Includes current officer's rank even if not in top N.
    PHASE 6: Now includes rank change vs previous week.
    """
    today = datetime.now(timezone.utc).date()
    week_start = today - timedelta(days=today.weekday())  # Monday
    prev_week_start = week_start - timedelta(days=7)
    prev_week_end = week_start - timedelta(days=1)
    
    # Get all officers' stats for THIS week
    leaderboard_query = (
        select(
            models.User.id,
            models.User.username,
            models.User.full_name,
            func.count(models.Consultation.id).label("consultations"),
        )
        .join(models.Consultation, models.Consultation.officer_id == models.User.id)
        .where(
            models.User.role == "officer",
            func.date(models.Consultation.consultation_date) >= week_start
        )
        .group_by(models.User.id, models.User.username, models.User.full_name)
        .order_by(func.count(models.Consultation.id).desc())
    )
    
    result = await db.execute(leaderboard_query)
    all_officers = result.fetchall()
    
    # Get PREVIOUS week ranks for comparison
    prev_week_query = (
        select(
            models.User.id,
            func.count(models.Consultation.id).label("consultations"),
        )
        .join(models.Consultation, models.Consultation.officer_id == models.User.id)
        .where(
            models.User.role == "officer",
            func.date(models.Consultation.consultation_date) >= prev_week_start,
            func.date(models.Consultation.consultation_date) <= prev_week_end
        )
        .group_by(models.User.id)
        .order_by(func.count(models.Consultation.id).desc())
    )
    prev_result = await db.execute(prev_week_query)
    prev_officers = prev_result.fetchall()
    
    # Build previous week rank lookup
    prev_ranks = {officer.id: rank for rank, officer in enumerate(prev_officers, 1)}
    
    # Build leaderboard with ranks
    leaderboard = []
    current_user_rank = None
    current_user_stats = None
    
    for rank, officer in enumerate(all_officers, 1):
        prev_rank = prev_ranks.get(officer.id)
        # Calculate rank change: positive = improved, negative = dropped
        rank_change = (prev_rank - rank) if prev_rank else None
        
        entry = {
            "rank": rank,
            "user_id": officer.id,
            "username": officer.username,
            "full_name": officer.full_name or officer.username,
            "consultations": officer.consultations,
            "is_current_user": officer.id == officer_id,
            "rank_change": rank_change,  # +2 = up 2 spots, -1 = down 1 spot, None = new
        }
        
        if officer.id == officer_id:
            current_user_rank = rank
            current_user_stats = entry
        
        if rank <= limit:
            leaderboard.append(entry)
    
    # If current user not in top N, add them at the end
    if current_user_rank and current_user_rank > limit and current_user_stats:
        leaderboard.append(current_user_stats)
    
    # If current user has no consultations this week, add with 0
    if current_user_rank is None:
        user = await db.get(models.User, officer_id)
        if user:
            prev_rank = prev_ranks.get(officer_id)
            leaderboard.append({
                "rank": len(all_officers) + 1,
                "user_id": officer_id,
                "username": user.username,
                "full_name": user.full_name or user.username,
                "consultations": 0,
                "is_current_user": True,
                "rank_change": (prev_rank - (len(all_officers) + 1)) if prev_rank else None,
            })
            current_user_rank = len(all_officers) + 1
    
    return {
        "week_start": week_start.isoformat(),
        "total_officers": len(all_officers) + (1 if current_user_rank is None else 0),
        "current_user_rank": current_user_rank or (len(all_officers) + 1),
        "leaderboard": leaderboard,
    }


async def get_team_stats(
    db: AsyncSession,
    officer_id: int,
    days: int = 30
) -> Dict[str, Any]:
    """
    Get team average statistics for performance comparison.
    
    Returns:
        - team_avg_consultations: Average daily consultations across all officers
        - team_avg_conversions: Average daily conversions across all officers
        - officer_rank_percentile: Current officer's rank percentile
    """
    today = datetime.now(timezone.utc).date()
    start_date = today - timedelta(days=days - 1)
    
    # Get all active officers (status = 'active', not is_active)
    active_officers_query = (
        select(models.User.id)
        .where(
            models.User.role == "officer",
            models.User.status == "active",  # Fixed: use status instead of is_active
        )
    )
    active_officers = (await db.execute(active_officers_query)).scalars().all()
    
    if len(active_officers) == 0:
        return {
            "team_avg_consultations": 0,
            "team_avg_conversions": 0,
            "officer_rank_percentile": 0,
            "total_officers": 0,
        }
    
    # Get total consultations per officer in the period
    consultations_query = (
        select(
            models.Consultation.officer_id,
            func.count(models.Consultation.id).label("count")
        )
        .where(
            models.Consultation.officer_id.in_(active_officers),
            func.date(models.Consultation.consultation_date) >= start_date,
        )
        .group_by(models.Consultation.officer_id)
    )
    consultations_res = (await db.execute(consultations_query)).all()
    
    # Calculate team total and average
    officer_consultations = {row[0]: row[1] for row in consultations_res}
    total_consultations = sum(officer_consultations.values())
    team_avg = round(total_consultations / len(active_officers) / days, 1) if active_officers else 0
    
    # Get current officer's consultations
    current_officer_count = officer_consultations.get(officer_id, 0)
    
    # Calculate rank percentile
    officers_with_fewer = sum(1 for count in officer_consultations.values() if count < current_officer_count)
    rank_percentile = round((officers_with_fewer / len(active_officers)) * 100) if active_officers else 0
    
    # Get conversion stats (leads with final positive status)
    conversions_query = (
        select(
            models.Lead.assigned_officer_id,
            func.count(models.Lead.id).label("count")
        )
        .join(models.ConsultationStatus)
        .where(
            models.Lead.assigned_officer_id.in_(active_officers),
            models.ConsultationStatus.is_final_status == True,
            func.date(models.Lead.updated_at) >= start_date,
        )
        .group_by(models.Lead.assigned_officer_id)
    )
    conversions_res = (await db.execute(conversions_query)).all()
    
    total_conversions = sum(row[1] for row in conversions_res)
    team_avg_conversions = round(total_conversions / len(active_officers) / days, 2) if active_officers else 0
    
    return {
        "team_avg_consultations": team_avg,
        "team_avg_conversions": team_avg_conversions,
        "officer_rank_percentile": rank_percentile,
        "total_officers": len(active_officers),
        "period_days": days,
    }


async def get_upcoming_activities(
    db: AsyncSession,
    officer_id: int,
    month: int,
    year: int
) -> Dict[str, Any]:
    """
    Lấy các hoạt động sắp tới (leads có next_activity_at) cho officer.
    Trả về danh sách activities và các ngày có activities.
    
    Args:
        db: Database session
        officer_id: Officer user ID
        month: Month (1-12)
        year: Year (e.g., 2025)
        
    Returns:
        Dict with activities list and dates with activities
    """
    # Tính start/end của tháng
    start_of_month = datetime(year, month, 1, tzinfo=timezone.utc)
    if month == 12:
        end_of_month = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end_of_month = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    
    # Query leads có next_activity_at trong tháng này
    query = (
        select(models.Lead)
        .where(
            models.Lead.assigned_officer_id == officer_id,
            models.Lead.next_activity_at.isnot(None),
            models.Lead.next_activity_at >= start_of_month,
            models.Lead.next_activity_at < end_of_month,
            models.Lead.deleted_at.is_(None),  # Exclude soft-deleted
        )
        .order_by(models.Lead.next_activity_at.asc())
    )
    
    result = await db.execute(query)
    leads = result.scalars().all()
    
    # Build activities list and dates with activities
    activities = []
    dates_with_activities = set()
    
    for lead in leads:
        activity_date = lead.next_activity_at
        if activity_date:
            # Add to dates set (just the day number)
            dates_with_activities.add(activity_date.day)
            
            # Add to activities list
            activities.append({
                "id": lead.id,
                "lead_id": lead.id,
                "lead_name": lead.full_name,
                "time": activity_date.strftime("%H:%M"),
                "date": activity_date.strftime("%Y-%m-%d"),
                "day": activity_date.day,
            })
    
    return {
        "activities": activities,
        "dates_with_activities": list(dates_with_activities),
        "month": month,
        "year": year,
    }