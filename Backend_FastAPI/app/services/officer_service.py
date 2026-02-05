import structlog
from datetime import datetime, timedelta, timezone, date
from typing import List, Dict, Any, Callable, Tuple

from sqlalchemy.ext.asyncio import AsyncSession

from .. import models, schemas
from ..core.events import SystemEvents
from ..repositories import OfficerRepository
from ..repositories.organization_repository import OrganizationRepository
from .notification_dispatcher import dispatch
from . import kpi_service

log = structlog.get_logger(__name__)


async def get_officer_dashboard_stats(
    db: AsyncSession, officer_id: int
) -> Dict[str, Any]:
    """
    Lấy thống kê tổng hợp cho Officer Dashboard.
    
    REFACTORED: Uses OfficerRepository with optimized batch queries.
    - Funnel: 14 queries → 2 queries
    - Trends: 21 queries → 3 queries
    """
    repo = OfficerRepository(db)
    
    # 1. Get officer info
    user = await repo.get_officer_with_capacity(officer_id)
    if not user:
        raise ValueError(f"User {officer_id} not found")
    
    # 2. Workload (optimized single query)
    current_workload = await repo.get_workload_count(officer_id)
    max_capacity = user.max_capacity or 100
    utilization = round((current_workload / max_capacity) * 100, 1) if max_capacity > 0 else 0.0
    
    # 3. Performance Trends (batch query - was 21 queries, now 3)
    today = datetime.now(timezone.utc).date()
    seven_days_ago = today - timedelta(days=6)
    trends_data = await repo.get_performance_trends_batch(officer_id, seven_days_ago, today)
    performance_trends = [
        {"date": tp.date, "assigned": tp.assigned, "consultations": tp.consultations, "converted": tp.converted}
        for tp in trends_data.values()
    ]
    
    # 4. Sales Funnel (batch query - was 14 queries, now 2)
    all_stages = await repo.get_all_pipeline_stages()
    stage_counts = await repo.get_funnel_stage_counts_batch(officer_id)
    transition_rates = await repo.get_stage_transition_rates(officer_id, days=30)

    # Pre-build stage lookup dict for O(1) access (optimization)
    stage_by_id = {s.id: s for s in all_stages}

    # SPEC 2026-02-04: Calculate Net Conversion Rate
    # Formula: Enrolled / (Enrolled + Lost)
    # Enrolled = stage stg06 (is_final_stage=True, positive outcome)
    # Lost = All FINAL leads with negative outcome (includes early exits)
    total_enrolled = 0
    total_lost = 0

    for stage in all_stages:
        stage_data = stage_counts.get(stage.id, {})
        if stage.is_final_stage:
            # Final stage: count positive as Won, negative as Lost
            total_enrolled += stage_data.get("positive", 0)
            total_lost += stage_data.get("negative", 0)
        else:
            # Non-final stage: count early_exit (FINAL + negative) as Lost
            total_lost += stage_data.get("early_exit_count", 0)

    net_conversion_rate = round(
        (total_enrolled / (total_enrolled + total_lost)) * 100, 1
    ) if (total_enrolled + total_lost) > 0 else 0.0

    sales_funnel = []
    for idx, stage in enumerate(all_stages):
        stage_data = stage_counts.get(stage.id, {})
        lead_count = stage_data.get("count", 0)
        positive_count = stage_data.get("positive", 0)
        negative_count = stage_data.get("negative", 0)
        neutral_count = stage_data.get("neutral", 0)
        early_exit_count = stage_data.get("early_exit_count", 0)

        # Calculate conversion rate from transitions (optimized with dict lookup)
        conversion_rate = None
        if stage.id in transition_rates:
            transitions_from = transition_rates[stage.id]
            total_out = sum(transitions_from.values())
            if total_out > 0:
                # Count progressive transitions (to higher non-final stages)
                progressive = sum(
                    count for to_id, count in transitions_from.items()
                    if to_id in stage_by_id
                    and stage_by_id[to_id].order > stage.order
                    and not stage_by_id[to_id].is_final_stage
                )
                conversion_rate = round((progressive / total_out) * 100, 1)

        # SPEC: Calculate move_forward = leads that continue to next stage
        # move_forward = lead_count - early_exit_count (for non-final stages)
        move_forward = lead_count - early_exit_count if not stage.is_final_stage else lead_count

        sales_funnel.append({
            "stage_id": stage.id,
            "stage_name": stage.name,
            "stage_order": stage.order,
            "lead_count": lead_count,
            "is_final_stage": stage.is_final_stage,
            "fill": f"var(--chart-{idx % 5 + 1})",
            "conversion_rate": conversion_rate,
            # SPEC: Early Exit metrics per stage
            "early_exit_count": early_exit_count,
            "move_forward": move_forward,
            "outcome_breakdown": {
                "positive": positive_count,
                "negative": negative_count,
                "neutral": neutral_count,
            }
        })

    # Store net_conversion_rate for response (used in enhanced dashboard)
    # Note: This is stored at module level for now, will be added to response later

    # 5. Actionable Lists (optimized queries)
    high_score_leads = await repo.get_high_score_leads(officer_id, limit=5)
    stale_leads = await repo.get_stale_leads(officer_id, stale_days=3, limit=5)
    upcoming = []
    
    def lead_to_preview(lead: models.Lead) -> dict:
        """Convert Lead model to LeadPreview schema format."""
        return {
            "id": lead.id,
            "name": lead.full_name or "",
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
    
    REFACTORED: Uses OfficerRepository with batch queries.
    """
    repo = OfficerRepository(db)
    
    # Get all stages and batch counts (optimized)
    all_stages = await repo.get_all_pipeline_stages()
    stage_counts = await repo.get_funnel_stage_counts_batch(
        officer_id, start_date=filter_start, end_date=filter_end
    )
    transition_rates = await repo.get_stage_transition_rates(officer_id, days=30)

    # Pre-build stage lookup dict for O(1) access (optimization)
    stage_by_id = {s.id: s for s in all_stages}

    # SPEC 2026-02-04: Calculate Net Conversion Rate
    total_enrolled = 0
    total_lost = 0

    for stage in all_stages:
        stage_data = stage_counts.get(stage.id, {})
        if stage.is_final_stage:
            total_enrolled += stage_data.get("positive", 0)
            total_lost += stage_data.get("negative", 0)
        else:
            total_lost += stage_data.get("early_exit_count", 0)

    net_conversion_rate = round(
        (total_enrolled / (total_enrolled + total_lost)) * 100, 1
    ) if (total_enrolled + total_lost) > 0 else 0.0

    sales_funnel = []
    for idx, stage in enumerate(all_stages):
        stage_data = stage_counts.get(stage.id, {})
        lead_count = stage_data.get("count", 0)
        positive_count = stage_data.get("positive", 0)
        negative_count = stage_data.get("negative", 0)
        neutral_count = stage_data.get("neutral", 0)
        early_exit_count = stage_data.get("early_exit_count", 0)

        # Calculate conversion rate from transitions (optimized with dict lookup)
        conversion_rate = None
        if stage.id in transition_rates:
            transitions_from = transition_rates[stage.id]
            total_out = sum(transitions_from.values())
            if total_out > 0:
                # Count progressive transitions (to higher non-final stages)
                progressive = sum(
                    count for to_id, count in transitions_from.items()
                    if to_id in stage_by_id
                    and stage_by_id[to_id].order > stage.order
                    and not stage_by_id[to_id].is_final_stage
                )
                conversion_rate = round((progressive / total_out) * 100, 1)

        # SPEC: move_forward = lead_count - early_exit_count
        move_forward = lead_count - early_exit_count if not stage.is_final_stage else lead_count

        sales_funnel.append({
            "stage_id": stage.id,
            "stage_name": stage.name,
            "stage_order": stage.order,
            "lead_count": lead_count,
            "is_final_stage": stage.is_final_stage,
            "fill": f"var(--chart-{idx % 5 + 1})",
            "conversion_rate": conversion_rate,
            "early_exit_count": early_exit_count,
            "move_forward": move_forward,
            "outcome_breakdown": {
                "positive": positive_count,
                "negative": negative_count,
                "neutral": neutral_count,
            }
        })

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
    
    # =========================================================================
    # REFACTORED: Use OfficerRepository for KPI stats
    # =========================================================================
    repo = OfficerRepository(db)
    
    # Get base stats first (already uses Repository)
    base_stats = await get_officer_dashboard_stats(db, officer_id)
    
    # Fetch user to get unit_id for KPI inheritance
    user = await repo.get_officer_with_capacity(officer_id)
    
    yesterday = today - timedelta(days=1)
    week_ago = today - timedelta(days=7)
    month_start = today.replace(day=1)
    last_month_start = (month_start - timedelta(days=1)).replace(day=1)
    
    # Calculate days in filter range for averages
    filter_days = (filter_end - filter_start).days + 1
    
    # === Use Repository for KPI stats (was 5 separate queries) ===
    kpi_data = await repo.get_kpi_stats(officer_id, filter_start, filter_end)
    
    consultations_in_range = kpi_data["consultations_in_range"]
    consultations_today = kpi_data["consultations_today"]
    active_leads = kpi_data["active_leads"]
    converted_in_range = kpi_data["converted_count"]
    total_in_range = kpi_data["total_leads"] or 1
    
    # Calculate derived values
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
    
    active_leads_trend = {
        "value": 0,
        "direction": "neutral",
        "comparison": f"trong {filter_days} ngày"
    }
    
    conversion_rate = round((converted_in_range / total_in_range) * 100, 1)
    
    # Compare with previous period of same length
    prev_filter_end = filter_start - timedelta(days=1)
    prev_filter_start = prev_filter_end - timedelta(days=filter_days - 1)
    
    # Get previous period KPIs using Repository
    prev_kpi_data = await repo.get_kpi_stats(officer_id, prev_filter_start, prev_filter_end)
    converted_prev = prev_kpi_data["converted_count"]
    total_prev = prev_kpi_data["total_leads"] or 1
    prev_rate = (converted_prev / total_prev) * 100
    
    conversion_diff = conversion_rate - prev_rate
    conversion_trend = {
        "value": abs(round(conversion_diff, 1)),
        "direction": "up" if conversion_diff > 0 else "down" if conversion_diff < 0 else "neutral",
        "comparison": f"vs {filter_days} ngày trước"
    }

    # === 4. AVERAGE RESPONSE TIME ===
    # Response time = Time from lead assignment to first consultation (in hours)
    repo = OfficerRepository(db)
    avg_response_time = await repo.get_avg_response_time_hours(officer_id, filter_start, filter_end)

    # Default to 0 if no data
    if avg_response_time is None:
        avg_response_time = 0.0

    # Get previous period response time for trend
    prev_response_time = await repo.get_avg_response_time_hours(officer_id, prev_filter_start, prev_filter_end)

    if prev_response_time is not None and prev_response_time > 0:
        # Calculate percentage change (lower is better for response time)
        response_diff_pct = ((avg_response_time - prev_response_time) / prev_response_time) * 100
        avg_response_trend = {
            "value": abs(round(response_diff_pct, 1)),
            # For response time: negative change (faster) is "down" direction, which is good
            "direction": "up" if response_diff_pct > 0 else "down" if response_diff_pct < 0 else "neutral",
            "comparison": f"vs {filter_days} ngày trước"
        }
    else:
        avg_response_trend = {
            "value": 0,
            "direction": "neutral",
            "comparison": "Chưa có dữ liệu"
        }

    # === 5. PRIORITY ACTIONS ===
    priority_actions = await _calculate_priority_actions(db, officer_id)

    # === 6. PERFORMANCE TRENDS (within date range) - OPTIMIZED ===
    # Use batch query instead of N+1 day loop (repo already initialized in section 4)
    trends_data = await repo.get_performance_trends_batch(officer_id, filter_start, filter_end)
    performance_trends = [
        {"date": tp.date, "assigned": tp.assigned, "consultations": tp.consultations, "converted": tp.converted}
        for tp in trends_data.values()
    ]
    
    # === 7. SALES FUNNEL (within date range) ===
    # Get funnel stages with leads created in date range
    sales_funnel = await _get_sales_funnel_in_range(db, officer_id, filter_start, filter_end)
    
    # === 8. ANNUAL PROGRESS (Phase 6: Rolling Targets) ===
    # Get annual target progress for enrollments KPI
    # Use fiscal year from date filter (filter_end.year)
    annual_progress = await kpi_service.get_annual_target_progress(
        db, officer_id, kpi_code="enrollments", fiscal_year=filter_end.year
    )
    
    # Build enhanced response
    return {
        "kpis": {
            "consultations_today": consultations_today,
            "consultations_target": await kpi_service.get_kpi_target(
                db, "consultations_daily", officer_id, user.unit_id, "daily"
            ),
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
        "annual_progress": annual_progress,  # Phase 6: Rolling targets
    }


# =============================================================================
# PHASE 2: Aggregated Dashboard for Manager/Admin
# =============================================================================

async def get_aggregated_dashboard_stats(
    db: AsyncSession,
    scope: str,  # "team" or "organization"
    requesting_user: models.User,
    officer_id: int = None,  # Optional: drill down to specific officer
    unit_id: int = None,     # Optional: filter by unit (admin only)
    start_date: str = None,
    end_date: str = None,
) -> Dict[str, Any]:
    """
    Get aggregated dashboard stats for multiple officers.
    
    REFACTORED: Uses OfficerRepository batch queries.
    - Reduced from 14+ queries to 4 optimized batch queries.
    
    For team scope: Aggregates data from officers in same unit as requester
    For organization scope: Aggregates data from all officers (or filtered by unit)
    
    If officer_id is provided, returns that officer's personal dashboard instead.
    """
    from datetime import date as date_type
    
    repo = OfficerRepository(db)
    
    # If drilling down to specific officer, return their personal dashboard
    if officer_id is not None:
        return await get_enhanced_dashboard_stats(
            db=db,
            officer_id=officer_id,
            start_date=start_date,
            end_date=end_date,
        )
    
    # Parse date range
    today = datetime.now(timezone.utc).date()
    if start_date and end_date:
        try:
            filter_start = date_type.fromisoformat(start_date)
            filter_end = date_type.fromisoformat(end_date)
        except ValueError:
            filter_start = today - timedelta(days=6)
            filter_end = today
    else:
        filter_start = today - timedelta(days=6)
        filter_end = today
    
    filter_days = (filter_end - filter_start).days + 1
    
    # ==========================================================================
    # Get officer IDs using Repository (was direct SQL)
    # ==========================================================================
    target_unit_id = requesting_user.unit_id if scope == "team" else unit_id
    officer_ids = await repo.get_active_officer_ids(
        scope=scope,
        unit_id=target_unit_id,
    )
    officer_count = len(officer_ids)
    
    if officer_count == 0:
        return _empty_aggregated_stats(scope, filter_days)
    
    log.info(
        "Aggregating dashboard for scope",
        scope=scope,
        officer_count=officer_count,
        unit_id=target_unit_id,
        date_range=f"{filter_start} to {filter_end}",
    )
    
    # ==========================================================================
    # Aggregated KPIs using Repository (was 5 separate queries)
    # ==========================================================================
    kpi_data = await repo.get_aggregated_kpis(officer_ids, filter_start, filter_end)
    
    total_consultations = kpi_data["total_consultations"]
    today_consultations = kpi_data["today_consultations"]
    total_active_leads = kpi_data["active_leads"]
    converted_count = kpi_data["converted_count"]
    total_leads = kpi_data["total_leads"] or 1
    
    avg_consultations_per_day = round(total_consultations / filter_days, 1) if filter_days > 0 else 0
    conversion_rate = round((converted_count / total_leads) * 100, 1)
    
    # ==========================================================================
    # Aggregated Funnel using Repository (was N+1 loop)
    # ==========================================================================
    sales_funnel = await repo.get_aggregated_funnel(officer_ids)
    
    # ==========================================================================
    # Team Overview using Repository (was N+1 loop)
    # ==========================================================================
    team_overview = await repo.get_team_overview(officer_ids, filter_start, filter_end, limit=10)
    
    # ==========================================================================
    # Build response
    # ==========================================================================
    return {
        "kpis": {
            "consultations_today": today_consultations,
            "consultations_target": officer_count * 10,  # Aggregate target
            "consultations_trend": {
                "value": avg_consultations_per_day,
                "direction": "neutral",
                "comparison": f"TB/ngày trong {filter_days} ngày",
            },
            "active_leads": total_active_leads,
            "active_leads_trend": {
                "value": 0,
                "direction": "neutral",
                "comparison": f"{officer_count} officers",
            },
            "conversion_rate": conversion_rate,
            "conversion_rate_trend": {
                "value": 0,
                "direction": "neutral",
                "comparison": f"trong {filter_days} ngày",
            },
            "avg_response_time": 0,  # TODO: Calculate aggregate
            "avg_response_time_trend": {
                "value": 0,
                "direction": "neutral",
                "comparison": "",
            },
        },
        # Must match WorkloadStats schema
        "status_overview": {
            "current_workload": total_active_leads,
            "max_capacity": officer_count * 30,  # Aggregate capacity
            "utilization": round((total_active_leads / (officer_count * 30)) * 100, 1) if officer_count > 0 else 0,
            "availability_status": "available",
        },
        "priority_actions": [],  # Not applicable for aggregated view
        "performance_trends": [],  # TODO: Add aggregated trends
        "sales_funnel": sales_funnel,
        # Must match ActionableLists schema
        "actionable_lists": {
            "high_score": [],
            "stale": [],
            "upcoming": [],
        },
        "team_overview": team_overview,  # Added for manager/admin view
    }


def _empty_aggregated_stats(scope: str, filter_days: int) -> Dict[str, Any]:
    """Return empty stats when no officers found in the selected unit/scope."""
    return {
        "kpis": {
            "consultations_today": 0,
            "consultations_target": 0,
            "consultations_trend": {"value": 0, "direction": "neutral", "comparison": ""},
            "active_leads": 0,
            "active_leads_trend": {"value": 0, "direction": "neutral", "comparison": ""},
            "conversion_rate": 0,
            "conversion_rate_trend": {"value": 0, "direction": "neutral", "comparison": ""},
            "avg_response_time": 0,
            "avg_response_time_trend": {"value": 0, "direction": "neutral", "comparison": ""},
        },
        # Must match WorkloadStats schema
        "status_overview": {
            "current_workload": 0,
            "max_capacity": 0,
            "utilization": 0,
            "availability_status": "available",
        },
        "priority_actions": [],
        "performance_trends": [],
        "sales_funnel": [],
        # Must match ActionableLists schema
        "actionable_lists": {
            "high_score": [],
            "stale": [],
            "upcoming": [],
        },
        # Phase 6: Annual progress (null when no officers)
        "annual_progress": None,
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
    
    # REFACTORED: Use Repository for leads query
    repo = OfficerRepository(db)
    leads = await repo.get_priority_leads_for_actions(officer_id, limit=20)
    
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
            "phone": lead.phone,  # For Zalo/Phone quick actions
            "last_contact_at": last_contact,  # For display
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
    db: AsyncSession,
    officer_id: int,
    limit: int = 5,
    start_date: date = None,
    end_date: date = None,
    scope: str = None,
    unit_id: int = None,
    requesting_user: models.User = None,
) -> Dict[str, Any]:
    """
    Get weekly leaderboard for gamification.

    REFACTORED: Uses OfficerRepository.get_all_weekly_rankings.
    - Reduced from 2 queries to 1 batch query.

    Shows top officers by consultations this week.
    Includes current officer's rank even if not in top N.
    PHASE 6: Now includes rank change vs previous week.

    Args:
        officer_id: Current user's ID (for marking "you" in leaderboard)
        limit: Number of top entries to show
        start_date: Optional custom start date (defaults to this week's Monday)
        end_date: Optional custom end date (defaults to today)
        scope: "personal" | "team" | "organization"
        unit_id: Filter by specific unit (for organization scope)
        requesting_user: The user making the request (for team scope)
    """
    repo = OfficerRepository(db)
    today = datetime.now(timezone.utc).date()

    # Use provided dates or default to current week
    if start_date and end_date:
        period_start = start_date
        period_end = end_date
    else:
        period_start = today - timedelta(days=today.weekday())  # Monday
        period_end = today

    # Calculate previous period for rank comparison
    period_length = (period_end - period_start).days + 1
    prev_period_end = period_start - timedelta(days=1)
    prev_period_start = prev_period_end - timedelta(days=period_length - 1)

    # Determine unit filter based on scope
    unit_ids = None
    if scope == "team" and requesting_user and requesting_user.unit_id:
        # Team scope: filter by requesting user's unit
        org_repo = OrganizationRepository(db)
        unit_ids = await org_repo.get_descendant_unit_ids(requesting_user.unit_id)
    elif scope == "organization" and unit_id:
        # Organization scope with specific unit: filter by that unit and descendants
        org_repo = OrganizationRepository(db)
        unit_ids = await org_repo.get_descendant_unit_ids(unit_id)
    # For "personal" scope or no scope: show all officers (no filter)

    # Get all officers' stats for THIS period using Repository
    all_officers = await repo.get_all_weekly_rankings(period_start, period_end, unit_ids)

    # Get PREVIOUS period ranks using Repository
    prev_officers = await repo.get_all_weekly_rankings(prev_period_start, prev_period_end, unit_ids)
    
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
            "consultations": officer.consultations or 0,
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
        user = await repo.get_officer_with_capacity(officer_id)
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
        "week_start": period_start.isoformat(),
        "week_end": period_end.isoformat(),
        "total_officers": len(all_officers) + (1 if current_user_rank is None else 0),
        "current_user_rank": current_user_rank or (len(all_officers) + 1),
        "leaderboard": leaderboard,
    }


async def get_team_stats(
    db: AsyncSession,
    officer_id: int,
    days: int = 30,
    start_date: date = None,
    end_date: date = None
) -> Dict[str, Any]:
    """
    Get team average statistics for performance comparison.
    
    REFACTORED: Uses OfficerRepository methods.
    - Reduced from 3 queries to 2 repository calls.
    
    Returns:
        - team_avg_consultations: Average daily consultations across all officers
        - team_avg_conversions: Average daily conversions across all officers
        - officer_rank_percentile: Current officer's rank percentile
    """
    repo = OfficerRepository(db)
    today = datetime.now(timezone.utc).date()
    
    # Determine date range
    if start_date and end_date:
        calc_start = start_date
        calc_end = end_date
        # Recalculate days for rank logic if needed or just trust the range
        calc_days = (end_date - start_date).days + 1
        if calc_days < 1: calc_days = 1
    else:
        calc_start = today - timedelta(days=days - 1)
        calc_end = today
        calc_days = days
    
    # Get all active officers using Repository
    active_officers = await repo.get_active_officer_ids(scope="organization", unit_id=None)
    
    if len(active_officers) == 0:
        return {
            "team_avg_consultations": 0,
            "team_avg_conversions": 0,
            "officer_rank_percentile": 0,
            "total_officers": 0,
        }
    
    # Get team averages using Repository
    team_data = await repo.get_team_averages(unit_id=None, start_date=calc_start, end_date=calc_end)
    
    # Get current officer's KPI for rank calculation
    officer_kpi = await repo.get_kpi_stats(officer_id, calc_start, today)
    current_officer_count = officer_kpi["consultations_in_range"]
    
    # Calculate approximate rank percentile
    # Using team average as reference point
    team_avg = team_data["team_avg_consultations"]
    if team_avg > 0:
        # Rough percentile: if above average, higher percentile
        daily_avg = current_officer_count / calc_days if calc_days > 0 else 0
        if daily_avg >= team_avg:
            rank_percentile = min(90, 50 + int((daily_avg / team_avg - 1) * 50))
        else:
            rank_percentile = max(10, int((daily_avg / team_avg) * 50))
    else:
        rank_percentile = 50
    
    return {
        "team_avg_consultations": team_avg,
        "team_avg_conversions": team_data["team_avg_conversions"],
        "officer_rank_percentile": rank_percentile,
        "total_officers": team_data["total_officers"],
        "period_days": calc_days,
    }


async def get_upcoming_activities(
    db: AsyncSession,
    officer_id: int,
    month: int,
    year: int
) -> Dict[str, Any]:
    """
    Lấy các hoạt động sắp tới (leads có next_activity_at) cho officer.
    
    REFACTORED: Uses OfficerRepository.get_upcoming_activities.
    
    Trả về danh sách activities và các ngày có activities.
    
    Args:
        db: Database session
        officer_id: Officer user ID
        month: Month (1-12)
        year: Year (e.g., 2025)
        
    Returns:
        Dict with activities list and dates with activities
    """
    repo = OfficerRepository(db)
    
    # Tính start/end của tháng
    start_of_month = datetime(year, month, 1, tzinfo=timezone.utc)
    if month == 12:
        end_of_month = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end_of_month = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    
    # REFACTORED: Use Repository
    leads = await repo.get_upcoming_activities(officer_id, start_of_month, end_of_month)
    
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