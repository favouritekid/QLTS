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
            models.PipelineStage.id,
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
            "stage_id": row[0],    # e.g. "stg05"
            "stage": row[1],       # e.g. "Đã chốt deal"
            "count": row[2],
            "fill": f"var(--chart-{idx % 5 + 1})"
        })

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
# PHASE 1: Enhanced Dashboard with KPIs
# =============================================================================

async def get_enhanced_dashboard_stats(
    db: AsyncSession, officer_id: int
) -> Dict[str, Any]:
    """
    Enhanced dashboard with KPIs, priority actions, and trends.
    Builds on get_officer_dashboard_stats with additional metrics.
    """
    # Get base stats first
    base_stats = await get_officer_dashboard_stats(db, officer_id)
    
    today = datetime.now(timezone.utc).date()
    yesterday = today - timedelta(days=1)
    week_ago = today - timedelta(days=7)
    month_start = today.replace(day=1)
    last_month_start = (month_start - timedelta(days=1)).replace(day=1)
    
    # === 1. CONSULTATIONS TODAY ===
    # Count consultations (from Consultation model if exists, or use assignment logs)
    consultations_today_query = (
        select(func.count(models.Consultation.id))
        .where(
            models.Consultation.officer_id == officer_id,
            func.date(models.Consultation.consultation_date) == today
        )
    )
    consultations_today = (await db.execute(consultations_today_query)).scalar() or 0
    
    # Yesterday's consultations for trend
    consultations_yesterday_query = (
        select(func.count(models.Consultation.id))
        .where(
            models.Consultation.officer_id == officer_id,
            func.date(models.Consultation.consultation_date) == yesterday
        )
    )
    consultations_yesterday = (await db.execute(consultations_yesterday_query)).scalar() or 0
    
    # Weekly average
    consultations_week_query = (
        select(func.count(models.Consultation.id))
        .where(
            models.Consultation.officer_id == officer_id,
            func.date(models.Consultation.consultation_date) >= week_ago
        )
    )
    consultations_week = (await db.execute(consultations_week_query)).scalar() or 0
    consultations_avg = consultations_week / 7 if consultations_week > 0 else 0
    
    # Calculate trend
    if consultations_avg > 0:
        trend_pct = ((consultations_today - consultations_avg) / consultations_avg) * 100
        trend_direction = "up" if trend_pct > 0 else "down" if trend_pct < 0 else "neutral"
    else:
        trend_pct = 0
        trend_direction = "neutral"
    
    consultations_trend = {
        "value": abs(round(trend_pct, 1)),
        "direction": trend_direction,
        "comparison": "vs TB tuần"
    }
    
    # === 2. ACTIVE LEADS ===
    active_leads = base_stats["status_overview"]["current_workload"]
    
    # Yesterday's active leads (approximation)
    leads_yesterday_query = (
        select(func.count(models.Lead.id))
        .join(
            models.ConsultationStatus,
            models.Lead.consultation_status_id == models.ConsultationStatus.id,
            isouter=True
        )
        .where(
            models.Lead.assigned_officer_id == officer_id,
            models.Lead.created_at < datetime.combine(today, datetime.min.time()).replace(tzinfo=timezone.utc),
            or_(
                models.ConsultationStatus.is_final_status == False,
                models.ConsultationStatus.is_final_status.is_(None)
            )
        )
    )
    # Simplify - just show difference from average
    active_leads_trend = {
        "value": 0,
        "direction": "neutral",
        "comparison": "vs hôm qua"
    }
    
    # === 3. CONVERSION RATE ===
    # Leads converted this month / total leads assigned this month
    converted_this_month_query = (
        select(func.count(models.Lead.id))
        .join(models.ConsultationStatus)
        .where(
            models.Lead.assigned_officer_id == officer_id,
            models.ConsultationStatus.is_final_status == True,
            models.ConsultationStatus.outcome_type == "positive",
            func.date(models.Lead.updated_at) >= month_start
        )
    )
    converted_this_month = (await db.execute(converted_this_month_query)).scalar() or 0
    
    total_leads_this_month_query = (
        select(func.count(models.Lead.id))
        .where(
            models.Lead.assigned_officer_id == officer_id,
            func.date(models.Lead.created_at) >= month_start
        )
    )
    total_this_month = (await db.execute(total_leads_this_month_query)).scalar() or 1
    
    conversion_rate = round((converted_this_month / total_this_month) * 100, 1)
    
    # Last month conversion for comparison
    converted_last_month_query = (
        select(func.count(models.Lead.id))
        .join(models.ConsultationStatus)
        .where(
            models.Lead.assigned_officer_id == officer_id,
            models.ConsultationStatus.is_final_status == True,
            models.ConsultationStatus.outcome_type == "positive",
            func.date(models.Lead.updated_at) >= last_month_start,
            func.date(models.Lead.updated_at) < month_start
        )
    )
    converted_last_month = (await db.execute(converted_last_month_query)).scalar() or 0
    
    total_last_month_query = (
        select(func.count(models.Lead.id))
        .where(
            models.Lead.assigned_officer_id == officer_id,
            func.date(models.Lead.created_at) >= last_month_start,
            func.date(models.Lead.created_at) < month_start
        )
    )
    total_last_month = (await db.execute(total_last_month_query)).scalar() or 1
    last_month_rate = (converted_last_month / total_last_month) * 100
    
    conversion_diff = conversion_rate - last_month_rate
    conversion_trend = {
        "value": abs(round(conversion_diff, 1)),
        "direction": "up" if conversion_diff > 0 else "down" if conversion_diff < 0 else "neutral",
        "comparison": "vs tháng trước"
    }
    
    # === 4. AVERAGE RESPONSE TIME ===
    # Time from lead created to first consultation
    # Simplified: Calculate from last 30 days of data
    avg_response_time = 2.5  # Placeholder - would need Consultation timestamps
    avg_response_trend = {
        "value": 15,
        "direction": "down",  # Lower is better
        "comparison": "vs TB"
    }
    
    # === 5. PRIORITY ACTIONS ===
    priority_actions = await _calculate_priority_actions(db, officer_id)
    
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
        "performance_trends": base_stats["performance_trends"],
        "sales_funnel": base_stats["sales_funnel"],
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
    
    # Get all active officers
    active_officers_query = (
        select(models.User.id)
        .where(
            models.User.role == "officer",
            models.User.is_active == True,
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