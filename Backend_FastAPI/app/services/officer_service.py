import logging as _logging

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
from .pipeline_service import LOSS_REASONS

# Build lookup from canonical loss reason source
_LOSS_REASON_LOOKUP = {r["code"]: r for r in LOSS_REASONS}

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
        {"date": tp.date, "assigned": tp.assigned, "consultations": tp.consultations, "converted": tp.converted, "enrolled": tp.enrolled, "lost": tp.lost}
        for tp in trends_data.values()
    ]
    
    # 4. Sales Funnel (batch query - was 14 queries, now 2)
    all_stages = await repo.get_all_pipeline_stages()
    stage_counts = await repo.get_funnel_stage_counts_batch(officer_id)
    transition_rates = await repo.get_stage_transition_rates(officer_id, days=30)

    # Phase 2: Get loss reason breakdown per stage (no date filter for base dashboard)
    loss_breakdown_by_stage = await repo.get_loss_reason_breakdown_by_stage(
        officer_id=officer_id,
    )

    # Phase 2: Get velocity stats (time in stage) per stage
    velocity_by_stage = await repo.get_stage_velocity_stats(
        officer_id=officer_id,
    )

    # Phase 2: Get estimated lost revenue per stage
    lost_revenue_by_stage = await repo.get_estimated_lost_revenue_by_stage(
        officer_id=officer_id,
    )

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

        # Phase 2: Get loss breakdown for this stage (if any)
        stage_loss_breakdown = loss_breakdown_by_stage.get(stage.id, [])

        # Phase 2: Get velocity stats for this stage (if any)
        stage_velocity = velocity_by_stage.get(stage.id, None)

        # Phase 2: Get estimated lost revenue for this stage (if any)
        stage_lost_revenue = lost_revenue_by_stage.get(stage.id, None)

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
            },
            "loss_breakdown": stage_loss_breakdown if stage_loss_breakdown else None,
            "velocity": stage_velocity,  # Phase 2: Time in stage analytics
            "estimated_lost_revenue": stage_lost_revenue,  # Phase 2: Lost revenue analytics
        })

    # Store net_conversion_rate for response (used in enhanced dashboard)
    # Note: This is stored at module level for now, will be added to response later

    # Phase 2: Generate funnel suggestions
    # Aggregate loss breakdown for suggestions
    aggregated_loss = []
    loss_totals: Dict[str, int] = {}
    for stage in sales_funnel:
        for item in (stage.get("loss_breakdown") or []):
            loss_totals[item["reason_code"]] = loss_totals.get(item["reason_code"], 0) + item["count"]

    total_loss_reasons = sum(loss_totals.values()) or 1
    aggregated_loss = [
        {"reason_code": k, "count": v, "percentage": round((v / total_loss_reasons) * 100, 1)}
        for k, v in sorted(loss_totals.items(), key=lambda x: -x[1])
    ]

    funnel_suggestions = generate_funnel_suggestions(
        funnel_stages=sales_funnel,
        aggregated_loss_breakdown=aggregated_loss,
    )

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
        "funnel_suggestions": funnel_suggestions,  # Phase 2: AI-powered suggestions
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

    # ✅ Dispatch notification in savepoint (records flushed with main transaction)
    _notif_cb = None
    try:
        from app.services.notification_dispatcher import rooms_for_user
        _notif_rooms = ["role_admin"]
        if user.unit_id:
            _notif_rooms.append(f"unit_{user.unit_id}")
        _notif_rooms.append(f"user_room_{officer_id}")
        async with db.begin_nested():
            _, _notif_cb = await dispatch(
                db=db,
                event=SystemEvents.OFFICER_AVAILABILITY_CHANGED,
                payload={
                    "officer_id": officer_id,
                    "new_status": availability_status,
                    "old_status": old_status,
                    "username": user.username,
                    "unit_id": user.unit_id,
                    "actor_id": officer_id,
                },
                dedupe_key=f"officer_availability:{officer_id}:{availability_status}",
                rooms=_notif_rooms,
            )
    except Exception as e:
        log.warning(
            "Dispatch failed, business data preserved",
            officer_id=officer_id,
            error=str(e)
        )

    async def _post_commit():
        """Execute after router commits the transaction."""
        if _notif_cb:
            await _notif_cb()

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
    Phase 2: Includes loss_breakdown per stage (LOSS_REASON_UX_SPEC.md)
    """
    repo = OfficerRepository(db)

    # Get all stages and batch counts (optimized)
    all_stages = await repo.get_all_pipeline_stages()
    stage_counts = await repo.get_funnel_stage_counts_batch(
        officer_id, start_date=filter_start, end_date=filter_end
    )
    transition_rates = await repo.get_stage_transition_rates(
        officer_id, start_date=filter_start, end_date=filter_end
    )

    # Phase 2: Get loss reason breakdown per stage
    loss_breakdown_by_stage = await repo.get_loss_reason_breakdown_by_stage(
        officer_id=officer_id,
        start_date=filter_start,
        end_date=filter_end,
    )

    # Phase 2: Get velocity stats (time in stage) per stage
    velocity_by_stage = await repo.get_stage_velocity_stats(
        officer_id=officer_id,
        start_date=filter_start,
        end_date=filter_end,
    )

    # Phase 2: Get estimated lost revenue per stage
    lost_revenue_by_stage = await repo.get_estimated_lost_revenue_by_stage(
        officer_id=officer_id,
        start_date=filter_start,
        end_date=filter_end,
    )

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

        # Phase 2: Get loss breakdown for this stage (if any)
        stage_loss_breakdown = loss_breakdown_by_stage.get(stage.id, [])

        # Phase 2: Get velocity stats for this stage (if any)
        stage_velocity = velocity_by_stage.get(stage.id, None)

        # Phase 2: Get estimated lost revenue for this stage (if any)
        stage_lost_revenue = lost_revenue_by_stage.get(stage.id, None)

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
            },
            "loss_breakdown": stage_loss_breakdown if stage_loss_breakdown else None,
            "velocity": stage_velocity,  # Phase 2: Time in stage analytics
            "estimated_lost_revenue": stage_lost_revenue,  # Phase 2: Lost revenue analytics
        })

    return sales_funnel


# =============================================================================
# PHASE 2: Funnel Suggestions Generator
# =============================================================================

def generate_funnel_suggestions(
    funnel_stages: List[Dict[str, Any]],
    aggregated_loss_breakdown: List[Dict[str, Any]] = None,
    config: Dict[str, Any] = None,
) -> List[Dict[str, Any]]:
    """
    Generate AI-powered suggestions based on funnel metrics.

    SPEC: FUNNEL_FEASIBILITY_ANALYSIS.md - Suggested Actions

    Analyzes funnel data and generates actionable suggestions:
    1. Bottleneck detection (low conversion rate)
    2. Slow stages (high velocity/time in stage)
    3. High revenue loss stages
    4. Top loss reasons to address

    Args:
        funnel_stages: List of funnel stage data (from _get_sales_funnel_in_range)
        aggregated_loss_breakdown: Aggregated loss reasons across all stages
        config: Optional configuration overrides

    Returns:
        List of FunnelSuggestion dicts, sorted by priority
    """
    # Default configuration
    cfg = {
        "bottleneck_threshold": 50,           # Conversion rate below this triggers bottleneck
        "slow_stage_threshold_days": 5,       # Avg days above this triggers slow stage
        "high_loss_threshold_vnd": 100_000_000,  # Lost revenue above this triggers high loss
        "loss_reason_threshold_pct": 20,      # Loss reason above this % triggers suggestion
        "max_suggestions": 5,                 # Maximum suggestions to return
        **(config or {})
    }

    suggestions: List[Dict[str, Any]] = []

    # Filter to non-final stages for analysis
    core_stages = [s for s in funnel_stages if not s.get("is_final_stage", False)]

    # 1. Bottleneck Detection (low conversion rate)
    for stage in core_stages:
        conversion_rate = stage.get("conversion_rate")
        if conversion_rate is not None and conversion_rate < cfg["bottleneck_threshold"]:
            # Calculate severity based on how far below threshold
            severity = cfg["bottleneck_threshold"] - conversion_rate
            priority = "critical" if severity > 30 else "high" if severity > 15 else "medium"

            suggestions.append({
                "id": f"bottleneck_{stage['stage_id']}",
                "type": "bottleneck",
                "priority": priority,
                "stage_id": stage["stage_id"],
                "stage_name": stage["stage_name"],
                "title": f"Điểm nghẽn tại {stage['stage_name']}",
                "description": f"Tỷ lệ chuyển đổi thấp ({conversion_rate:.0f}%), "
                              f"cần review quy trình tư vấn và chất lượng leads đầu vào.",
                "metric_value": conversion_rate,
                "metric_label": f"Conversion: {conversion_rate:.0f}%",
                "action_label": "Xem leads",
                "action_url": f"/leads?stage={stage['stage_id']}",
                "drill_down": {
                    "target": "transitions",
                    "exactness": "exact",
                    "metric_key": "bottleneck",
                    "filters": {"stage_id": str(stage["stage_id"])},
                },
                "_severity": severity,  # For sorting
            })

    # 2. Slow Stage Detection (high velocity)
    for stage in core_stages:
        velocity = stage.get("velocity")
        if velocity and velocity.get("avg_days", 0) > cfg["slow_stage_threshold_days"]:
            avg_days = velocity["avg_days"]
            # Calculate how many times over threshold
            severity = avg_days / cfg["slow_stage_threshold_days"]
            priority = "high" if severity > 2 else "medium"

            suggestions.append({
                "id": f"slow_{stage['stage_id']}",
                "type": "slow_stage",
                "priority": priority,
                "stage_id": stage["stage_id"],
                "stage_name": stage["stage_name"],
                "title": f"Leads chậm tại {stage['stage_name']}",
                "description": f"Leads ở stage này trung bình {avg_days:.1f} ngày "
                              f"(>{cfg['slow_stage_threshold_days']} ngày). "
                              f"Cần follow-up và đẩy nhanh tiến độ.",
                "metric_value": avg_days,
                "metric_label": f"TB: {avg_days:.1f} ngày",
                "action_label": "Xem leads",
                "action_url": f"/leads?stage={stage['stage_id']}",
                "drill_down": {
                    "target": "transitions",
                    "exactness": "exact",
                    "metric_key": "slow_stage",
                    "filters": {"stage_id": str(stage["stage_id"])},
                },
                "_severity": severity * 10,  # For sorting (multiply to compare with conversion)
            })

    # 3. High Revenue Loss Detection
    for stage in core_stages:
        lost_revenue = stage.get("estimated_lost_revenue")
        if lost_revenue and lost_revenue.get("total_lost_revenue", 0) > cfg["high_loss_threshold_vnd"]:
            total_loss = lost_revenue["total_lost_revenue"]
            lost_count = lost_revenue["lost_leads_count"]
            # Calculate severity based on revenue (in millions)
            severity = total_loss / 1_000_000_000  # Billions

            priority = "critical" if total_loss > 500_000_000 else "high" if total_loss > 200_000_000 else "medium"

            # Format for display
            if total_loss >= 1_000_000_000:
                loss_display = f"{total_loss / 1_000_000_000:.1f}B"
            else:
                loss_display = f"{total_loss / 1_000_000:.0f}M"

            suggestions.append({
                "id": f"high_loss_{stage['stage_id']}",
                "type": "high_loss",
                "priority": priority,
                "stage_id": stage["stage_id"],
                "stage_name": stage["stage_name"],
                "title": f"Mất {loss_display} VND tại {stage['stage_name']}",
                "description": f"{lost_count} leads đã lost tại stage này, "
                              f"ước tính mất {loss_display} VND doanh thu. "
                              f"Ưu tiên cải thiện conversion tại đây.",
                "metric_value": total_loss,
                "metric_label": f"Lost: {loss_display} VND",
                "action_label": "Xem leads lost",
                "action_url": f"/leads?stage={stage['stage_id']}&status=rejected,unqualified",
                "drill_down": {
                    "target": "transitions",
                    "exactness": "exact",
                    "metric_key": "high_loss",
                    "filters": {
                        "stage_id": str(stage["stage_id"]),
                        "outcome": "negative",
                        "final_only": True,
                    },
                },
                "_severity": severity * 50,  # High weight for revenue
            })

    # 4. Top Loss Reasons
    if aggregated_loss_breakdown:
        for reason in aggregated_loss_breakdown[:2]:  # Top 2 reasons
            if reason.get("percentage", 0) >= cfg["loss_reason_threshold_pct"]:
                reason_code = reason["reason_code"]
                count = reason["count"]
                pct = reason["percentage"]

                # Map reason codes to actionable labels (from canonical source)
                reason_info = _LOSS_REASON_LOOKUP.get(reason_code)
                if reason_info:
                    reason_label = reason_info["label"].lower()
                    action_hint = reason_info["action_hint"]
                else:
                    reason_label = reason_code.lower().replace("_", " ")
                    action_hint = "Phân tích và có chiến lược xử lý"

                suggestions.append({
                    "id": f"loss_reason_{reason_code}",
                    "type": "loss_reason",
                    "priority": "high" if pct >= 30 else "medium",
                    "stage_id": None,
                    "stage_name": None,
                    "title": f"{pct:.0f}% leads lost vì {reason_label}",
                    "description": f"{count} leads đã lost với lý do '{reason_label}'. {action_hint}",
                    "metric_value": pct,
                    "metric_label": f"{count} leads ({pct:.0f}%)",
                    "action_label": "Xem chi tiết",
                    "action_url": "/leads?status=rejected,unqualified",
                    "drill_down": {
                        "target": "consultations",
                        "exactness": "exact",
                        "metric_key": "loss_reason",
                        "filters": {
                            "loss_reason_code": reason_code,
                            "consultation_kind": "human",
                        },
                    },
                    "_severity": pct,  # For sorting
                })

    # Sort by priority (critical > high > medium > low) then by severity
    priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    suggestions.sort(key=lambda x: (priority_order.get(x["priority"], 99), -x.get("_severity", 0)))

    # Remove internal severity field and limit results
    for s in suggestions:
        s.pop("_severity", None)

    return suggestions[:cfg["max_suggestions"]]


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
    active_leads = kpi_data["active_leads"]  # Realtime snapshot (no date filter)
    active_leads_in_period = kpi_data["active_leads_in_period"]  # Period-scoped
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
        "comparison": f"vs TB/ngày ({filter_days} ngày)"
    }
    
    new_lead_conversion_rate = round((converted_in_range / total_in_range) * 100, 1)

    # Compare with previous period of same length
    prev_filter_end = filter_start - timedelta(days=1)
    prev_filter_start = prev_filter_end - timedelta(days=filter_days - 1)

    # Get previous period KPIs using Repository
    prev_kpi_data = await repo.get_kpi_stats(officer_id, prev_filter_start, prev_filter_end)

    # Active leads trend: compare period-scoped counts between current and previous period
    prev_active_in_period = prev_kpi_data["active_leads_in_period"]
    if prev_active_in_period > 0:
        active_diff_pct = ((active_leads_in_period - prev_active_in_period) / prev_active_in_period) * 100
        active_direction = "up" if active_diff_pct > 0 else "down" if active_diff_pct < 0 else "neutral"
    else:
        active_diff_pct = 0
        active_direction = "neutral"
    active_leads_trend = {
        "value": abs(round(active_diff_pct, 1)),
        "direction": active_direction,
        "comparison": f"vs {filter_days} ngày trước"
    }

    converted_prev = prev_kpi_data["converted_count"]
    total_prev = prev_kpi_data["total_leads"] or 1
    prev_rate = (converted_prev / total_prev) * 100

    conversion_diff = new_lead_conversion_rate - prev_rate
    conv_has_baseline = (prev_kpi_data["total_leads"] or 0) > 0
    new_lead_conversion_trend = {
        "value": abs(round(conversion_diff, 1)) if conv_has_baseline else 0,
        "direction": ("up" if conversion_diff > 0 else "down" if conversion_diff < 0 else "neutral") if conv_has_baseline else "neutral",
        "comparison": f"vs {filter_days} ngày trước" if conv_has_baseline else "Chưa có dữ liệu kỳ trước",
    }

    # === Activity-based Win Rate ===
    win_rate_data = await repo.get_win_rate_stats(officer_id, filter_start, filter_end)
    prev_win_rate_data = await repo.get_win_rate_stats(officer_id, prev_filter_start, prev_filter_end)
    win_rate_diff = win_rate_data["win_rate"] - prev_win_rate_data["win_rate"]
    wr_has_baseline = prev_win_rate_data["total_closed"] > 0
    win_rate_trend = {
        "value": abs(round(win_rate_diff, 1)) if wr_has_baseline else 0,
        "direction": ("up" if win_rate_diff > 0 else "down" if win_rate_diff < 0 else "neutral") if wr_has_baseline else "neutral",
        "comparison": f"vs {filter_days} ngày trước" if wr_has_baseline else "Chưa có dữ liệu kỳ trước",
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

    # Catalog-driven: resolve ALL targets in one call (period_type derived from catalog)
    from app.services.kpi_catalog import METRIC_CATALOG

    all_targets = await kpi_service.get_all_kpi_targets(
        db, officer_id, user.unit_id, effective_date=filter_end,
    )

    def _target_or_none(code: str):
        """Return target only for comparable metrics; None for non-comparable."""
        return all_targets[code] if METRIC_CATALOG[code].comparison.comparable else None

    # === 5. SLA COMPLIANCE RATE ===
    sla_hours = all_targets["response_time_hours"]
    sla_stats = await repo.get_sla_compliance_stats(officer_id, filter_start, filter_end, sla_hours)
    prev_sla_stats = await repo.get_sla_compliance_stats(officer_id, prev_filter_start, prev_filter_end, sla_hours)
    sla_diff = sla_stats["rate"] - prev_sla_stats["rate"]
    # No meaningful trend when previous period had no SLA-eligible leads
    sla_has_baseline = prev_sla_stats["total"] > 0
    sla_compliance_trend = {
        "value": abs(round(sla_diff, 1)) if sla_has_baseline else 0,
        "direction": ("up" if sla_diff > 0 else "down" if sla_diff < 0 else "neutral") if sla_has_baseline else "neutral",
        "comparison": f"vs {filter_days} ngày trước" if sla_has_baseline else "Chưa có dữ liệu kỳ trước",
    }

    # === 6. CONSULTATION EFFECTIVENESS ===
    effectiveness_stats = await repo.get_consultation_effectiveness_stats(officer_id, filter_start, filter_end)
    prev_effectiveness_stats = await repo.get_consultation_effectiveness_stats(officer_id, prev_filter_start, prev_filter_end)
    eff_diff = effectiveness_stats["effectiveness"] - prev_effectiveness_stats["effectiveness"]
    eff_has_baseline = prev_effectiveness_stats["total_final_consulted"] > 0
    effectiveness_trend = {
        "value": abs(round(eff_diff, 1)) if eff_has_baseline else 0,
        "direction": ("up" if eff_diff > 0 else "down" if eff_diff < 0 else "neutral") if eff_has_baseline else "neutral",
        "comparison": f"vs {filter_days} ngày trước" if eff_has_baseline else "Chưa có dữ liệu kỳ trước",
    }

    # === 6b. ENROLLMENTS MONTHLY ===
    from app.repositories.kpi_repository import KpiRepository
    kpi_repo_for_enroll = KpiRepository(db)
    enrollments_monthly = await kpi_repo_for_enroll.count_enrollments_in_period(
        officer_id, filter_start, filter_end,
    )

    # === 7. PRIORITY ACTIONS ===
    priority_actions = await _calculate_priority_actions(db, officer_id)

    # === 8. PERFORMANCE TRENDS (within date range) - OPTIMIZED ===
    # Use batch query instead of N+1 day loop (repo already initialized in section 4)
    trends_data = await repo.get_performance_trends_batch(officer_id, filter_start, filter_end)
    performance_trends = [
        {"date": tp.date, "assigned": tp.assigned, "consultations": tp.consultations, "converted": tp.converted, "enrolled": tp.enrolled, "lost": tp.lost}
        for tp in trends_data.values()
    ]
    
    # === 9. SALES FUNNEL (within date range) ===
    # Get funnel stages with leads created in date range
    sales_funnel = await _get_sales_funnel_in_range(db, officer_id, filter_start, filter_end)

    # Phase 2: Generate funnel suggestions
    # Aggregate loss breakdown for suggestions
    aggregated_loss = []
    loss_totals: Dict[str, int] = {}
    for stage in sales_funnel:
        for item in (stage.get("loss_breakdown") or []):
            loss_totals[item["reason_code"]] = loss_totals.get(item["reason_code"], 0) + item["count"]

    total_loss_reasons = sum(loss_totals.values()) or 1
    aggregated_loss = [
        {"reason_code": k, "count": v, "percentage": round((v / total_loss_reasons) * 100, 1)}
        for k, v in sorted(loss_totals.items(), key=lambda x: -x[1])
    ]

    funnel_suggestions = generate_funnel_suggestions(
        funnel_stages=sales_funnel,
        aggregated_loss_breakdown=aggregated_loss,
    )

    # === 9b. FUNNEL NET CONVERSION TREND (vs previous period) ===
    # Current NCR: derive from sales_funnel data (0 extra queries)
    _ncr_enrolled = sum(
        s["outcome_breakdown"]["positive"]
        for s in sales_funnel if s["is_final_stage"]
    )
    _ncr_lost = sum(
        s["outcome_breakdown"]["negative"]
        for s in sales_funnel if s["is_final_stage"]
    ) + sum(
        s.get("early_exit_count", 0)
        for s in sales_funnel if not s["is_final_stage"]
    )
    current_ncr = round(
        (_ncr_enrolled / (_ncr_enrolled + _ncr_lost)) * 100, 1
    ) if (_ncr_enrolled + _ncr_lost) > 0 else 0.0

    # Previous NCR: reuse stage topology from current funnel (1 extra query)
    _final_ids = {s["stage_id"] for s in sales_funnel if s["is_final_stage"]}
    _non_final_ids = {s["stage_id"] for s in sales_funnel if not s["is_final_stage"]}
    prev_funnel_counts = await repo.get_funnel_stage_counts_batch(
        officer_id, start_date=prev_filter_start, end_date=prev_filter_end
    )
    _prev_enrolled = sum(prev_funnel_counts.get(sid, {}).get("positive", 0) for sid in _final_ids)
    _prev_lost = sum(prev_funnel_counts.get(sid, {}).get("negative", 0) for sid in _final_ids) + \
                 sum(prev_funnel_counts.get(sid, {}).get("early_exit_count", 0) for sid in _non_final_ids)
    prev_ncr = round(
        (_prev_enrolled / (_prev_enrolled + _prev_lost)) * 100, 1
    ) if (_prev_enrolled + _prev_lost) > 0 else 0.0

    ncr_diff = current_ncr - prev_ncr
    ncr_has_baseline = (_prev_enrolled + _prev_lost) > 0
    funnel_net_conversion_trend = {
        "value": abs(round(ncr_diff, 1)) if ncr_has_baseline else 0,
        "direction": ("up" if ncr_diff > 0 else "down" if ncr_diff < 0 else "neutral") if ncr_has_baseline else "neutral",
        "comparison": f"vs {filter_days} ngày trước" if ncr_has_baseline else "Chưa có dữ liệu kỳ trước"
    }

    # === 10. ANNUAL PROGRESS (Phase 6: Rolling Targets) ===
    # Get annual target progress for enrollments KPI
    # Use fiscal year from date filter (filter_end.year)
    annual_progress = await kpi_service.get_annual_target_progress(
        db, officer_id, kpi_code="enrollments_annual",
        fiscal_year=filter_end.year, effective_date=filter_end,
    )

    # === 11. DAILY QUALITY KPIs (Phase D — spec §15) ===
    from zoneinfo import ZoneInfo
    VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
    today_vn = datetime.now(VN_TZ)
    day_start = today_vn.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)

    # D5+D1: Human consultations today (already used above but recounted with system filter)
    h_d = await repo.count_human_consultations_daily(officer_id, day_start, day_end)
    v_d = await repo.count_verified_consultations_daily(officer_id, day_start, day_end)
    quality_rate = round(v_d / h_d * 100, 1) if h_d > 0 else None

    # D2: Followup commitment
    followup = await repo.get_followup_commitment_stats(officer_id, day_start, day_end)
    followup_rate = (
        round(followup["numerator"] / followup["denominator"] * 100, 1)
        if followup["denominator"] > 0 else None
    )

    # D3: Rolling KPIs (use data from 7/3 days ago)
    d7_date = (today_vn - timedelta(days=7)).date()
    d7_start = datetime(d7_date.year, d7_date.month, d7_date.day, tzinfo=VN_TZ)
    d7_end = d7_start + timedelta(days=1)
    progress_d7 = await repo.get_progress_rate_d7(officer_id, d7_start, d7_end)

    d3_date = (today_vn - timedelta(days=3)).date()
    d3_start = datetime(d3_date.year, d3_date.month, d3_date.day, tzinfo=VN_TZ)
    d3_end = d3_start + timedelta(days=1)
    rollback_d3 = await repo.get_rollback_rate_d3(officer_id, d3_start, d3_end)

    # P1: consultations_daily needs is_unit_target flag (special case)
    target_info = await kpi_service.get_kpi_target_source_info(
        db, "consultations_daily", officer_id, user.unit_id,
        effective_date=filter_end,
    )

    # Build enhanced response
    return {
        "kpis": {
            "consultations_today": consultations_today,
            "consultations_target": target_info["value"],
            "is_unit_target": target_info["is_unit_target"],
            "consultations_trend": consultations_trend,
            "active_leads": active_leads,
            "active_leads_in_period": active_leads_in_period,
            "active_leads_trend": active_leads_trend,
            "win_rate": win_rate_data["win_rate"],
            "win_rate_trend": win_rate_trend,
            "new_lead_conversion_rate": new_lead_conversion_rate,
            "new_lead_conversion_rate_trend": new_lead_conversion_trend,
            "avg_response_time": avg_response_time,
            "avg_response_time_trend": avg_response_trend,
            "avg_response_time_target": _target_or_none("response_time_hours"),
            "sla_compliance_rate": sla_stats["rate"],
            "sla_compliance_rate_trend": sla_compliance_trend,
            "consultation_effectiveness": effectiveness_stats["effectiveness"],
            "consultation_effectiveness_trend": effectiveness_trend,
            "consultations_avg_per_day": round(consultations_avg, 1),
            # Catalog-driven targets (comparable flag from METRIC_CATALOG)
            "win_rate_target": _target_or_none("win_rate"),
            "sla_compliance_rate_target": _target_or_none("sla_compliance_rate"),
            "new_lead_conversion_rate_target": _target_or_none("conversion_rate"),
            "consultation_effectiveness_target": _target_or_none("consultation_effectiveness"),
            # All targets for frontend canShowTarget() gating
            "metric_targets": all_targets,
            # Enrollments monthly (leads at final stage in period)
            "enrollments_monthly": enrollments_monthly,
            "enrollments_monthly_target": _target_or_none("enrollments_monthly"),
            # Phase D: Daily Quality KPIs
            "verified_consultations_daily": v_d,
            "quality_rate_daily": quality_rate,
            "followup_commitment_rate": followup_rate,
            "progress_rate_d7": progress_d7["rate"],
            "progress_rate_d7_date": d7_date,
            "rollback_rate_d3": rollback_d3["rate"],
            "rollback_rate_d3_date": d3_date,
        },
        "status_overview": base_stats["status_overview"],
        "priority_actions": priority_actions,
        "performance_trends": performance_trends,
        "sales_funnel": sales_funnel,
        "funnel_net_conversion_trend": funnel_net_conversion_trend,
        "funnel_suggestions": funnel_suggestions,  # Phase 2: AI-powered suggestions
        "actionable_lists": base_stats["actionable_lists"],
        "annual_progress": annual_progress,  # Phase 6: Rolling targets
    }


# =============================================================================
# PHASE 2: Aggregated Dashboard for Manager/Admin
# =============================================================================


def _calc_trend(current: float, previous: float, label: str) -> Dict[str, Any]:
    """Calculate trend direction and percentage change.

    When previous=0 there is no meaningful baseline for comparison,
    so direction is always "neutral" regardless of current value.
    """
    if previous > 0:
        pct = ((current - previous) / previous) * 100
        direction = "up" if pct > 0 else "down" if pct < 0 else "neutral"
    else:
        pct = 0
        direction = "neutral"
    return {"value": abs(round(pct, 1)), "direction": direction, "comparison": label}


async def get_aggregated_dashboard_stats(
    db: AsyncSession,
    ctx,  # DashboardScopeContext — pre-resolved by dependency
    start_date: str = None,
    end_date: str = None,
) -> Dict[str, Any]:
    """
    Get aggregated dashboard stats for multiple officers.

    V12: Receives pre-resolved DashboardScopeContext from dependency.
    No longer resolves descendants or officer IDs internally.
    """
    from datetime import date as date_type

    repo = OfficerRepository(db)

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
    # Read pre-resolved scope from DashboardScopeContext
    # ==========================================================================
    officer_ids = ctx.effective_officer_ids
    descendant_unit_ids = ctx.effective_unit_ids
    officer_count = len(officer_ids)

    if officer_count == 0:
        return _empty_aggregated_stats(ctx.scope_kind, filter_days)

    log.info(
        "Aggregating dashboard for scope",
        scope=ctx.scope_kind,
        officer_count=officer_count,
        unit_root=ctx.effective_unit_root_id,
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
    new_lead_conversion_rate = round((converted_count / total_leads) * 100, 1)

    # Aggregated Win Rate
    win_rate_data = await repo.get_aggregated_win_rate_stats(officer_ids, filter_start, filter_end)

    # Aggregated SLA Compliance — intentionally uses global default (no officer/unit).
    # Aggregate SLA uses a single threshold so all officers are judged by the same standard.
    # Per-officer thresholds would make the aggregate rate an apples-to-oranges comparison.
    sla_hours = await kpi_service.get_kpi_target(
        db, "response_time_hours", effective_date=filter_end,
    )
    agg_sla_stats = await repo.get_aggregated_sla_compliance_stats(officer_ids, filter_start, filter_end, sla_hours)

    # Aggregated Consultation Effectiveness
    agg_effectiveness_stats = await repo.get_aggregated_consultation_effectiveness_stats(officer_ids, filter_start, filter_end)

    # Aggregated Enrollments Monthly (batch query, same semantics as personal)
    from app.repositories.kpi_repository import KpiRepository
    kpi_repo_agg = KpiRepository(db)
    agg_enrollments_monthly = await kpi_repo_agg.count_enrollments_in_period_batch(
        officer_ids, filter_start, filter_end,
    )

    # ==========================================================================
    # Aggregated Funnel using Repository (was N+1 loop)
    # ==========================================================================
    sales_funnel = await repo.get_aggregated_funnel(officer_ids, filter_start, filter_end)

    # ==========================================================================
    # Phase 2: Fetch metrics for aggregated funnel (loss_breakdown, velocity, lost_revenue)
    # Use unit_ids for filtering (more efficient than officer_ids for these queries)
    # ==========================================================================
    unit_ids_for_metrics = descendant_unit_ids if descendant_unit_ids else None

    # Fetch Phase 2 metrics (reusing existing repo methods with unit filter)
    loss_breakdown_by_stage = await repo.get_loss_reason_breakdown_by_stage(
        unit_ids=unit_ids_for_metrics,
        start_date=filter_start,
        end_date=filter_end,
    )
    velocity_by_stage = await repo.get_stage_velocity_stats(
        unit_ids=unit_ids_for_metrics,
        start_date=filter_start,
        end_date=filter_end,
    )
    lost_revenue_by_stage = await repo.get_estimated_lost_revenue_by_stage(
        unit_ids=unit_ids_for_metrics,
        start_date=filter_start,
        end_date=filter_end,
    )

    # Merge Phase 2 metrics into funnel stages
    for stage in sales_funnel:
        stage_id = stage["stage_id"]
        stage["loss_breakdown"] = loss_breakdown_by_stage.get(stage_id, None) or None
        stage["velocity"] = velocity_by_stage.get(stage_id, None)
        stage["estimated_lost_revenue"] = lost_revenue_by_stage.get(stage_id, None)

    # Aggregate loss breakdown across stages for suggestion generator
    loss_totals: Dict[str, int] = {}
    for stage in sales_funnel:
        for item in (stage.get("loss_breakdown") or []):
            loss_totals[item["reason_code"]] = loss_totals.get(item["reason_code"], 0) + item["count"]
    total_loss_reasons = sum(loss_totals.values()) or 1
    aggregated_loss = [
        {"reason_code": k, "count": v, "percentage": round((v / total_loss_reasons) * 100, 1)}
        for k, v in sorted(loss_totals.items(), key=lambda x: -x[1])
    ]

    # Phase 2: Generate funnel suggestions based on aggregated metrics
    funnel_suggestions = generate_funnel_suggestions(
        funnel_stages=sales_funnel,
        aggregated_loss_breakdown=aggregated_loss,
    )
    # Aggregated avg response time
    agg_avg_response_time = await repo.get_avg_response_time_hours_multi(officer_ids, filter_start, filter_end)

    # BUG 14: Calculate previous period for trend comparison
    prev_filter_end = filter_start - timedelta(days=1)
    prev_filter_start = prev_filter_end - timedelta(days=filter_days - 1)
    comparison_label = f"vs {filter_days} ngày trước"

    prev_kpi_data = await repo.get_aggregated_kpis(officer_ids, prev_filter_start, prev_filter_end)
    prev_win_rate_data = await repo.get_aggregated_win_rate_stats(officer_ids, prev_filter_start, prev_filter_end)
    prev_sla_stats = await repo.get_aggregated_sla_compliance_stats(officer_ids, prev_filter_start, prev_filter_end, sla_hours)
    prev_effectiveness_stats = await repo.get_aggregated_consultation_effectiveness_stats(officer_ids, prev_filter_start, prev_filter_end)
    prev_avg_response_time = await repo.get_avg_response_time_hours_multi(officer_ids, prev_filter_start, prev_filter_end)

    # Consultations trend
    prev_consult_avg = prev_kpi_data["total_consultations"] / filter_days if filter_days > 0 else 0
    consultations_trend = _calc_trend(avg_consultations_per_day, prev_consult_avg, comparison_label)

    # Conversion rate trend
    prev_total_leads = prev_kpi_data["total_leads"] or 1
    prev_conversion = round((prev_kpi_data["converted_count"] / prev_total_leads) * 100, 1)
    conversion_trend = _calc_trend(new_lead_conversion_rate, prev_conversion, comparison_label)

    # Win rate trend
    win_rate_trend = _calc_trend(win_rate_data["win_rate"], prev_win_rate_data["win_rate"], comparison_label)

    # Active leads trend (compare period-scoped counts, not realtime)
    curr_active_in_period = kpi_data["active_leads_in_period"]
    prev_active_in_period = prev_kpi_data["active_leads_in_period"]
    active_leads_trend = _calc_trend(float(curr_active_in_period), float(prev_active_in_period), comparison_label)

    # SLA trend
    sla_trend = _calc_trend(agg_sla_stats["rate"], prev_sla_stats["rate"], comparison_label)

    # Effectiveness trend
    eff_trend = _calc_trend(agg_effectiveness_stats["effectiveness"], prev_effectiveness_stats["effectiveness"], comparison_label)

    # Response time trend (lower is better, but we report direction as-is)
    prev_rt = prev_avg_response_time or 0
    curr_rt = agg_avg_response_time or 0
    if prev_rt > 0:
        rt_pct = ((curr_rt - prev_rt) / prev_rt) * 100
        rt_direction = "up" if rt_pct > 0 else "down" if rt_pct < 0 else "neutral"
        response_time_trend = {"value": abs(round(rt_pct, 1)), "direction": rt_direction, "comparison": comparison_label}
    else:
        response_time_trend = {"value": 0, "direction": "neutral", "comparison": "Chưa có dữ liệu"}

    # BUG 12+M2: Sum per-officer targets (respecting inheritance: officer → unit → global)
    from ..repositories import KpiRepository
    kpi_repo = KpiRepository(db)
    fiscal_year = filter_end.year

    total_consultations_target = 0
    for oid in officer_ids:
        # Always resolve each officer's OWN unit_id for correct KPI inheritance.
        # Using target_unit_id (manager's/admin's filter unit) is wrong for child-unit officers.
        oid_unit = await kpi_repo.get_user_unit_id(oid)

        # consultations_daily: resolve via KpiConfig inheritance (period_type from catalog)
        t = await kpi_service.get_kpi_target(
            db, "consultations_daily", oid, oid_unit,
            effective_date=filter_end,
        )
        total_consultations_target += t

    consultations_target = total_consultations_target

    # R1: Delegate annual progress to kpi_service (single calculation path)
    officer_progresses = []
    for oid in officer_ids:
        p = await kpi_service.get_annual_target_progress(
            db, oid, "enrollments_annual",
            fiscal_year=fiscal_year, effective_date=filter_end,
        )
        if p:
            officer_progresses.append(p)

    annual_progress = kpi_service.aggregate_annual_progresses(officer_progresses)

    # BUG 13: Get actual capacity from user records instead of hardcoded
    total_capacity = await repo.get_officers_total_capacity(officer_ids)

    # BUG 21: Funnel net conversion trend
    _agg_ncr_enrolled = sum(
        s["outcome_breakdown"]["positive"] for s in sales_funnel if s["is_final_stage"]
    )
    _agg_ncr_lost = sum(
        s["outcome_breakdown"]["negative"] for s in sales_funnel if s["is_final_stage"]
    ) + sum(
        s.get("early_exit_count", 0) for s in sales_funnel if not s["is_final_stage"]
    )
    current_ncr = round(
        (_agg_ncr_enrolled / (_agg_ncr_enrolled + _agg_ncr_lost)) * 100, 1
    ) if (_agg_ncr_enrolled + _agg_ncr_lost) > 0 else 0.0

    # Previous period NCR
    prev_agg_funnel = await repo.get_aggregated_funnel(officer_ids, prev_filter_start, prev_filter_end)
    _prev_ncr_enrolled = sum(
        s["outcome_breakdown"]["positive"] for s in prev_agg_funnel if s["is_final_stage"]
    )
    _prev_ncr_lost = sum(
        s["outcome_breakdown"]["negative"] for s in prev_agg_funnel if s["is_final_stage"]
    ) + sum(
        s.get("early_exit_count", 0) for s in prev_agg_funnel if not s["is_final_stage"]
    )
    prev_ncr = round(
        (_prev_ncr_enrolled / (_prev_ncr_enrolled + _prev_ncr_lost)) * 100, 1
    ) if (_prev_ncr_enrolled + _prev_ncr_lost) > 0 else 0.0

    ncr_diff = current_ncr - prev_ncr
    agg_ncr_has_baseline = (_prev_ncr_enrolled + _prev_ncr_lost) > 0
    funnel_net_conversion_trend = {
        "value": abs(round(ncr_diff, 1)) if agg_ncr_has_baseline else 0,
        "direction": ("up" if ncr_diff > 0 else "down" if ncr_diff < 0 else "neutral") if agg_ncr_has_baseline else "neutral",
        "comparison": comparison_label if agg_ncr_has_baseline else "Chưa có dữ liệu kỳ trước",
    }

    # ==========================================================================
    # Build response
    # ==========================================================================
    return {
        "kpis": {
            "consultations_today": today_consultations,
            "consultations_target": consultations_target,
            "consultations_trend": consultations_trend,
            "active_leads": kpi_data["active_leads"],
            "active_leads_in_period": kpi_data["active_leads_in_period"],
            "active_leads_trend": active_leads_trend,
            "win_rate": win_rate_data["win_rate"],
            "win_rate_trend": win_rate_trend,
            "new_lead_conversion_rate": new_lead_conversion_rate,
            "new_lead_conversion_rate_trend": conversion_trend,
            "avg_response_time": agg_avg_response_time or 0,
            "avg_response_time_trend": response_time_trend,
            "avg_response_time_target": None,  # Not meaningful for aggregated view
            "sla_compliance_rate": agg_sla_stats["rate"],
            "sla_compliance_rate_trend": sla_trend,
            "consultation_effectiveness": agg_effectiveness_stats["effectiveness"],
            "consultation_effectiveness_trend": eff_trend,
            "consultations_avg_per_day": avg_consultations_per_day,
            # Targets not applicable for aggregated (team/org) view
            "win_rate_target": None,
            "sla_compliance_rate_target": None,
            "new_lead_conversion_rate_target": None,
            "consultation_effectiveness_target": None,
            "metric_targets": None,
            "enrollments_monthly": agg_enrollments_monthly,
            "enrollments_monthly_target": None,
        },
        # Must match WorkloadStats schema
        "status_overview": {
            "current_workload": total_active_leads,
            "max_capacity": total_capacity,
            "utilization": round((total_active_leads / total_capacity) * 100, 1) if total_capacity > 0 else 0,
            "availability_status": "available",
        },
        "priority_actions": [],  # Not applicable for aggregated view
        "performance_trends": [
            {"date": tp.date, "assigned": tp.assigned, "consultations": tp.consultations, "converted": tp.converted, "enrolled": tp.enrolled, "lost": tp.lost}
            for tp in (await repo.get_performance_trends_batch_multi(officer_ids, filter_start, filter_end)).values()
        ],
        "sales_funnel": sales_funnel,
        "funnel_suggestions": funnel_suggestions,  # Phase 2: AI-powered suggestions
        # Must match ActionableLists schema
        "actionable_lists": {
            "high_score": [],
            "stale": [],
            "upcoming": [],
        },
        "annual_progress": annual_progress,
        "funnel_net_conversion_trend": funnel_net_conversion_trend,
    }


def _empty_aggregated_stats(scope: str, filter_days: int) -> Dict[str, Any]:
    """Return empty stats when no officers found in the selected unit/scope."""
    return {
        "kpis": {
            "consultations_today": 0,
            "consultations_target": 0,
            "consultations_trend": {"value": 0, "direction": "neutral", "comparison": ""},
            "active_leads": 0,
            "active_leads_in_period": 0,
            "active_leads_trend": {"value": 0, "direction": "neutral", "comparison": ""},
            "win_rate": 0,
            "win_rate_trend": {"value": 0, "direction": "neutral", "comparison": ""},
            "new_lead_conversion_rate": 0,
            "new_lead_conversion_rate_trend": {"value": 0, "direction": "neutral", "comparison": ""},
            "avg_response_time": 0,
            "avg_response_time_trend": {"value": 0, "direction": "neutral", "comparison": ""},
            "avg_response_time_target": None,
            "sla_compliance_rate": 0,
            "sla_compliance_rate_trend": {"value": 0, "direction": "neutral", "comparison": ""},
            "consultation_effectiveness": 0,
            "consultation_effectiveness_trend": {"value": 0, "direction": "neutral", "comparison": ""},
            "consultations_avg_per_day": 0.0,
            "win_rate_target": None,
            "sla_compliance_rate_target": None,
            "new_lead_conversion_rate_target": None,
            "consultation_effectiveness_target": None,
            "metric_targets": None,
            "enrollments_monthly": 0,
            "enrollments_monthly_target": None,
        },
        # Must match WorkloadStats schema
        "status_overview": {
            "current_workload": 0,
            "max_capacity": 0,
            "utilization": 0,
            "availability_status": "offline",
        },
        "priority_actions": [],
        "performance_trends": [],
        "sales_funnel": [],
        "funnel_suggestions": [],  # Phase 2: Empty suggestions
        # Must match ActionableLists schema
        "actionable_lists": {
            "high_score": [],
            "stale": [],
            "upcoming": [],
        },
        # Phase 6: Annual progress (null when no officers)
        "annual_progress": None,
        "funnel_net_conversion_trend": {"value": 0, "direction": "neutral", "comparison": ""},
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
    ctx,  # DashboardScopeContext
    limit: int = 5,
    start_date: date = None,
    end_date: date = None,
) -> Dict[str, Any]:
    """
    Get weekly leaderboard for gamification.

    V12: Reads unit_ids from ctx.effective_unit_ids instead of resolving descendants.
    officer_id for highlight comes from ctx.requested_officer_id.
    """
    repo = OfficerRepository(db)
    today = datetime.now(timezone.utc).date()

    if start_date and end_date:
        period_start = start_date
        period_end = end_date
    else:
        period_start = today - timedelta(days=today.weekday())
        period_end = today

    period_length = (period_end - period_start).days + 1
    prev_period_end = period_start - timedelta(days=1)
    prev_period_start = prev_period_end - timedelta(days=period_length - 1)

    # V12: Read unit filter from pre-resolved context
    unit_ids = ctx.effective_unit_ids if ctx.effective_unit_ids else None

    all_officers = await repo.get_all_weekly_rankings(period_start, period_end, unit_ids)
    prev_officers = await repo.get_all_weekly_rankings(prev_period_start, prev_period_end, unit_ids)

    prev_ranks = {officer.id: rank for rank, officer in enumerate(prev_officers, 1)}

    # Highlight targets
    officer_id = ctx.requested_officer_id or ctx.requesting_user.id
    requesting_user_id = ctx.requesting_user.id

    leaderboard = []
    current_user_rank = None
    current_user_stats = None

    for rank, officer in enumerate(all_officers, 1):
        prev_rank = prev_ranks.get(officer.id)
        rank_change = (prev_rank - rank) if prev_rank else None

        entry = {
            "rank": rank,
            "user_id": officer.id,
            "username": officer.username,
            "full_name": officer.full_name or officer.username,
            "consultations": officer.consultations or 0,
            "is_current_user": officer.id == requesting_user_id,
            "is_focus_officer": officer.id == officer_id,
            "rank_change": rank_change,
        }

        if officer.id == officer_id:
            current_user_rank = rank
            current_user_stats = entry

        if rank <= limit:
            leaderboard.append(entry)

    if current_user_rank and current_user_rank > limit and current_user_stats:
        leaderboard.append(current_user_stats)

    # If drill-down target has no consultations, add with 0 (officers only)
    if current_user_rank is None and ctx.requesting_user.role == "officer":
        user = await repo.get_officer_with_capacity(officer_id)
        if user:
            prev_rank = prev_ranks.get(officer_id)
            leaderboard.append({
                "rank": len(all_officers) + 1,
                "user_id": officer_id,
                "username": user.username,
                "full_name": user.full_name or user.username,
                "consultations": 0,
                "is_current_user": officer_id == requesting_user_id,
                "is_focus_officer": True,
                "rank_change": (prev_rank - (len(all_officers) + 1)) if prev_rank else None,
            })
            current_user_rank = len(all_officers) + 1

    added_zero_officer = (
        current_user_rank is not None
        and current_user_rank == len(all_officers) + 1
    )
    total = len(all_officers) + (1 if added_zero_officer else 0)

    return {
        "week_start": period_start.isoformat(),
        "week_end": period_end.isoformat(),
        "total_officers": total,
        "current_user_rank": current_user_rank,
        "leaderboard": leaderboard,
    }


async def get_team_stats(
    db: AsyncSession,
    ctx,  # DashboardScopeContext
    days: int = 30,
    start_date: date = None,
    end_date: date = None,
) -> Dict[str, Any]:
    """
    Get team average statistics for performance comparison.

    V12: Reads unit_id from ctx. officer_id for rank from ctx.requested_officer_id.
    """
    repo = OfficerRepository(db)
    today = datetime.now(timezone.utc).date()

    if start_date and end_date:
        calc_start = start_date
        calc_end = end_date
        calc_days = (end_date - start_date).days + 1
        if calc_days < 1:
            calc_days = 1
    else:
        calc_start = today - timedelta(days=days - 1)
        calc_end = today
        calc_days = days

    unit_id = ctx.effective_unit_root_id
    officer_id = ctx.requested_officer_id or ctx.requesting_user.id
    active_officers = ctx.effective_officer_ids

    if len(active_officers) == 0:
        return {
            "team_avg_consultations": 0,
            "team_avg_conversions": 0,
            "officer_rank_percentile": 0,
            "total_officers": 0,
        }

    team_data = await repo.get_team_averages(
        unit_id=unit_id,
        start_date=calc_start,
        end_date=calc_end,
        officer_ids=active_officers,
    )

    officer_kpi = await repo.get_kpi_stats(officer_id, calc_start, calc_end)
    current_officer_count = officer_kpi["consultations_in_range"]

    team_avg = team_data["team_avg_consultations"]
    if team_avg > 0:
        daily_avg = current_officer_count / calc_days if calc_days > 0 else 0
        if daily_avg >= team_avg:
            rank_percentile = min(90, 50 + int((daily_avg / team_avg - 1) * 50))
        else:
            rank_percentile = max(10, int((daily_avg / team_avg) * 50))
    else:
        rank_percentile = 50

    return {
        "team_avg_consultations": team_avg,
        "officer_rank_percentile": rank_percentile,
        "total_officers": team_data["total_officers"],
        "period_days": calc_days,
    }


async def get_upcoming_activities(
    db: AsyncSession,
    ctx,  # DashboardScopeContext
    month: int,
    year: int,
) -> Dict[str, Any]:
    """
    Lấy các hoạt động sắp tới (leads có next_activity_at).

    V12: Reads scope from ctx. Single officer → personal path, multi → aggregated.
    """
    repo = OfficerRepository(db)

    start_of_month = datetime(year, month, 1, tzinfo=timezone.utc)
    if month == 12:
        end_of_month = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end_of_month = datetime(year, month + 1, 1, tzinfo=timezone.utc)

    if len(ctx.effective_officer_ids) == 1:
        leads = await repo.get_upcoming_activities(ctx.effective_officer_ids[0], start_of_month, end_of_month)
    else:
        leads = await repo.get_upcoming_activities_multi(ctx.effective_officer_ids, start_of_month, end_of_month)
    
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


# =============================================================================
# GAP 2: Monthly KPI Plan Breakdown (Officer self-tracking)
# =============================================================================

async def get_officer_kpi_plan(
    db: AsyncSession,
    officer_id: int,
    fiscal_year: int,
) -> Dict[str, Any] | None:
    """
    Return monthly KPI plan breakdown for an officer.

    Resolution order:
    1. Officer's own active plan for fiscal_year
    2. Fallback: unit plan (officer_id IS NULL) for the officer's unit

    Monthly actuals come from KpiPlanMonth.actual_enrollments (source of truth).
    Returns None if no plan exists at either level (NOT raise 404).
    """
    from app.repositories.kpi_planning_repository import KpiPlanningRepository
    from app.utils.exceptions import ResourceNotFoundError

    # Get officer's unit_id
    repo = OfficerRepository(db)
    user = await repo.get_officer_with_capacity(officer_id)
    if not user:
        raise ResourceNotFoundError("Officer not found")

    planning_repo = KpiPlanningRepository(db)

    # 1. Try officer-specific plan
    source = "officer"
    plan = await planning_repo.get_active_plan_by_scope(
        unit_id=user.unit_id,
        fiscal_year=fiscal_year,
        officer_id=officer_id,
        with_months=True,
    )

    # 2. Fallback to unit plan
    if plan is None:
        source = "unit"
        plan = await planning_repo.get_active_plan_by_scope(
            unit_id=user.unit_id,
            fiscal_year=fiscal_year,
            officer_id=None,
            with_months=True,
        )

    if plan is None:
        return None  # No plan exists — caller (router) returns null/204

    # Build monthly summaries from plan.months
    months_by_num = {m.month: m for m in plan.months}
    month_summaries = []
    achieved_ytd = 0

    for month_num in range(1, 13):
        pm = months_by_num.get(month_num)
        if pm is None:
            month_summaries.append({
                "month": month_num,
                "enrollment_target": 0,
                "enrollment_actual": None,
                "working_days": 0,
                "consultations_daily": None,
                "consultations_actual_avg": None,
                "consultations_monthly_total": None,
                "conversion_rate": None,
                "win_rate": None,
            })
            continue

        actual_enroll = int(pm.actual_enrollments) if pm.actual_enrollments is not None else None
        if actual_enroll is not None:
            achieved_ytd += actual_enroll

        consult_daily = int(pm.consultations_daily) if pm.consultations_daily is not None else None
        consult_actual_avg = float(pm.actual_consultations_avg) if pm.actual_consultations_avg is not None else None
        working_days = int(pm.working_days) if pm.working_days is not None else 0
        consult_monthly = (consult_daily * working_days) if consult_daily is not None else None

        month_summaries.append({
            "month": month_num,
            "enrollment_target": int(pm.enrollment_target),
            "enrollment_actual": actual_enroll,
            "working_days": working_days,
            "consultations_daily": consult_daily,
            "consultations_actual_avg": consult_actual_avg,
            "consultations_monthly_total": consult_monthly,  # plan-derived: daily * working_days
            "conversion_rate": float(pm.conversion_rate) if pm.conversion_rate is not None else None,
            "conversion_rate_actual": float(pm.actual_conversion_rate) if pm.actual_conversion_rate is not None else None,
            "win_rate": float(pm.win_rate) if pm.win_rate is not None else None,
            "win_rate_actual": float(pm.actual_win_rate) if pm.actual_win_rate is not None else None,
        })

    annual_target = int(plan.annual_enrollment_target)
    progress_pct = (achieved_ytd / annual_target * 100) if annual_target > 0 else 0.0

    return {
        "fiscal_year": fiscal_year,
        "annual_target": annual_target,
        "achieved_ytd": achieved_ytd,
        "progress_pct": round(progress_pct, 1),
        "months": month_summaries,
        "source": source,
    }


# =============================================================================
# Distribution Panel ("Điểm bận") — giải trình phân phối lead của đơn vị
# =============================================================================
# ⚠️ MỌI con số tải ở đây đến TRỰC TIẾP từ
# ``assignment_service.compute_unit_officer_loads`` — đúng hàm engine chia lead
# dùng để chọn người. Service này CHỈ diễn giải (nhãn/câu chữ), TUYỆT ĐỐI không
# tự tính lại workload/dist_load/eff_util (sẽ lệch khi engine đổi công thức).

# Logger riêng cho đường ĐỌC. Dùng chung logger của assignment_service sẽ khiến
# log của dashboard trông y hệt log của một quyết định phân công thật.
_panel_log = _logging.getLogger("app.services.officer_distribution_panel")


def classify_archetype(load: Dict[str, Any], finance_on: bool) -> Dict[str, str]:
    """Nhãn kiểu officer, suy ra từ tỉ lệ các đòn bẩy tải. Hàm THUẦN."""
    officer = load["officer"]
    workload = load["workload"]
    capacity = load["capacity"]
    fill = workload / capacity if capacity else 0.0

    if (officer.availability_status or "offline") != "available":
        return {"key": "paused", "label": "Đang tắt nhận lead"}
    if load["at_capacity"] or load["overloaded"]:
        return {"key": "overloaded", "label": "Quá tải"}
    if fill < 0.30:
        return {"key": "available", "label": "Còn nhiều chỗ trống"}
    if workload > 0 and load["self_cnt"] / workload >= 0.50:
        return {"key": "self_driven", "label": "Tự tìm khách là chính"}
    if finance_on and workload > 0 and load["tuition_hold"] / workload >= 0.50:
        return {"key": "tuition_heavy", "label": "Chủ yếu chờ học phí"}
    return {"key": "balanced", "label": "Cân bằng"}


def build_diagnosis(
    load: Dict[str, Any], archetype_key: str, *, fill_pct: float
) -> str:
    """Câu chẩn đoán 1 dòng, điền số thật. Hàm THUẦN (dùng nhãn đã chốt).

    ⚠️ NGÔI THỨ BA: chuỗi này render trên MỌI dòng, kể cả dòng đồng nghiệp —
    tuyệt đối không xưng "bạn" (chỉ ``build_boost`` mới được, vì nó chỉ gắn cho
    chính người xem).
    ⚠️ ``fill_pct`` nhận từ caller, KHÔNG tự tính lại: dùng ``round()`` không
    ndigits sẽ ra banker's rounding (round(80.5) == 80) và mâu thuẫn với
    ``fill_pct`` in ngay cạnh trong cùng tooltip.
    """
    workload = load["workload"]
    capacity = load["capacity"]
    dist = load["dist_load"]
    self_cnt = load["self_cnt"]
    tuition = load["tuition_hold"]
    deducted = workload - dist

    if archetype_key == "paused":
        return (
            f"Đang tắt sẵn sàng nên hệ thống không chia lead mới; "
            f"vẫn giữ {workload} lead."
        )
    if archetype_key == "overloaded":
        return (
            f"Đang giữ {workload}/{capacity} lead ({fill_pct}% khả năng nhận) — "
            f"chạm ngưỡng tạm dừng nên hệ thống ưu tiên người khác."
        )
    if archetype_key == "available":
        return (
            f"Mới dùng {workload}/{capacity} khả năng nhận — "
            f"hệ thống thấy còn rất rảnh nên ưu tiên chia thêm."
        )
    if archetype_key == "self_driven":
        return (
            f"{self_cnt}/{workload} lead là tự tìm nên không bị tính; "
            f"hệ thống chỉ tính {dist} lead."
        )
    if archetype_key == "tuition_heavy":
        return (
            f"{tuition}/{workload} lead đã đóng tiền nên không bị tính; "
            f"hệ thống chỉ tính {dist} lead."
        )
    if deducted > 0:
        return (
            f"Giữ {workload} lead, được trừ {deducted} (tự tìm + đã đóng tiền) "
            f"nên hệ thống tính {dist}."
        )
    return (
        f"Gần như toàn bộ {workload} lead là do hệ thống chia — "
        f"không có phần được trừ."
    )


def build_boost(load: Dict[str, Any], archetype_key: str) -> str:
    """Lời khuyên hành động. 🔒 Chỉ gắn cho CHÍNH người đang xem (caller gate).

    Bám đúng cơ chế engine: chỉ ``dist_load`` (lead hệ thống tính) mới kéo điểm
    bận xuống. Lead tự tìm / hồ sơ đã đóng tiền ĐÃ được trừ sẵn nên xử lý chúng
    KHÔNG làm được chia thêm — tuyệt đối không khuyên sai điều này.
    """
    workload = load["workload"]
    capacity = load["capacity"]
    dist = load["dist_load"]
    self_cnt = load["self_cnt"]
    tuition = load["tuition_hold"]

    if archetype_key == "paused":
        return (
            "Bạn đang tắt sẵn sàng nên hệ thống bỏ qua khi chia. "
            "Bật lại khi muốn nhận tiếp."
        )
    if archetype_key == "overloaded":
        return (
            f"Bạn đang giữ {workload}/{capacity} lead nên hệ thống tạm giảm chia. "
            f"Chốt bớt lead đang mở để hạ điểm bận."
        )
    if dist == 0:
        return "Hệ thống đang thấy bạn hoàn toàn rảnh — bạn được ưu tiên chia trước."
    deducted = workload - dist
    if deducted > dist:
        # ⚠️ KHÔNG viết "{self} tự tìm và {tuition} đã đóng tiền" như một phép
        # cộng: phần giao (lead vừa tự tìm vừa đã đóng tiền) chỉ được trừ MỘT
        # lần, nên self + tuition > deducted. Nêu tổng thật, rồi mới tách chi tiết.
        overlap = load.get("overlap", 0)
        detail = f"{self_cnt} lead tự tìm và {tuition} hồ sơ đã đóng tiền"
        if overlap:
            detail += f" (trong đó {overlap} lead thuộc cả hai)"
        return (
            f"Điểm bận thấp của bạn nhờ {deducted} lead không bị tính — gồm "
            f"{detail}. Phần bạn chủ động giảm được là {dist} lead hệ thống "
            f"đang tính."
        )
    return (
        f"Muốn được chia thêm: giảm {dist} lead hệ thống đang tính bằng cách "
        f"chốt bớt lead đang mở — điểm bận sẽ hạ xuống."
    )


def _map_load_to_entry(
    load: Dict[str, Any],
    *,
    rank: int,
    unit_id,
    unit_name,
    requesting_user_id: int,
    finance_on: bool,
    scoring_mode,
) -> Dict[str, Any]:
    """Đổi 1 OfficerLoad của engine thành 1 dòng bảng (KHÔNG tính lại số nào)."""
    officer = load["officer"]
    workload = load["workload"]
    capacity = load["capacity"]
    dist = load["dist_load"]
    tuition = load["tuition_hold"]
    archetype = classify_archetype(load, finance_on)
    is_me = officer.id == requesting_user_id
    fill_pct = round(workload / capacity * 100, 1) if capacity else 0.0

    return {
        "rank": rank,
        "user_id": officer.id,
        # ⚠️ KHÔNG trả `username`: đây là endpoint duy nhất lộ cả roster đơn vị,
        # FE chỉ render `full_name`, nên đưa login-id của đồng nghiệp lên wire là
        # bề mặt PII không đổi lấy gì.
        "full_name": officer.full_name or f"NV #{officer.id}",
        "unit_id": unit_id,
        "unit_name": unit_name,
        # Chế độ chấm điểm là PER-UNIT ⇒ gắn vào từng dòng mới chính xác.
        "scoring_mode": scoring_mode,
        "workload": workload,
        "max_capacity": capacity,
        "weight": load["weight"],
        "self_sourced": load["self_cnt"],
        "tuition_hold": tuition,
        # Phần GIAO self ∩ tuition. BẮT BUỘC có trên wire: thiếu nó thì
        # self_sourced + tuition_hold ≠ deducted và mọi UI hiển thị chung sẽ
        # trình bày một phép cộng không đúng tổng của chính nó.
        "overlap": load.get("overlap", 0),
        "dist_load": dist,
        "deducted": workload - dist,
        "real_util_pct": round(load["real_util"] * 100, 1),
        "fill_pct": fill_pct,
        "eff_util_pct": round(load["eff_util"] * 100, 1),
        "score": round(load["score"], 4),
        "overload_gate_pct": (
            round((workload - tuition) / capacity * 100, 1) if capacity else 0.0
        ),
        "overloaded": load["overloaded"],
        "at_capacity": load["at_capacity"],
        "eligible_for_assignment": load["eligible_for_assignment"],
        "availability_status": officer.availability_status or "offline",
        "archetype": archetype,
        "diagnosis": build_diagnosis(load, archetype["key"], fill_pct=fill_pct),
        # 🔒 Lời khuyên CHỈ hiện trên dòng của chính người đang xem.
        "boost": build_boost(load, archetype["key"]) if is_me else None,
        "is_current_user": is_me,
    }


async def get_officer_distribution_panel(db: AsyncSession, ctx) -> Dict[str, Any]:
    """Bảng "điểm bận" — giải trình engine chia lead cho từng officer.

    Chấm điểm THEO TỪNG ĐƠN VỊ (giống engine, vì pool fairness là per-unit).
    Officer offline/busy vẫn được tính metric để hiển thị nhưng KHÔNG vào pool
    chấm điểm ⇒ điểm của người eligible y hệt con số engine dùng.
    """
    from . import assignment_service

    repo = OfficerRepository(db)
    flags = assignment_service.read_assignment_flags()
    flags_snapshot = {
        "member_weighted": flags.member_on,
        "fairness_weighted": flags.fairness_on,
        "exclude_self_sourced": flags.exclude_active,
        "finance_discount": flags.finance_on,
    }

    officers = await repo.get_officers_by_ids(ctx.effective_officer_ids)
    if not officers:
        return {
            "unit_id": ctx.effective_unit_root_id,
            "total_officers": 0,
            "scoring_mode": None,
            "flags_snapshot": flags_snapshot,
            "entries": [],
        }

    by_unit: Dict[Any, List[Any]] = {}
    for officer in officers:
        by_unit.setdefault(officer.unit_id, []).append(officer)

    # Tên đơn vị lấy từ quan hệ đã eager-load (`selectinload(User.unit)` trong
    # repo) — KHÔNG query rời trong service (giữ đúng Repository pattern và bớt
    # một round-trip).
    unit_name_map: Dict[int, str] = {
        o.unit_id: o.unit.name
        for o in officers
        if o.unit_id is not None and o.unit is not None
    }

    requesting_user_id = ctx.requesting_user.id
    entries: List[Dict[str, Any]] = []
    modes_seen = set()

    for unit_id, unit_officers in by_unit.items():
        # Pool CHẤM ĐIỂM = đúng tập engine sẽ xét (đang sẵn sàng). Người còn lại
        # vẫn có metric hiển thị nhưng đứng ngoài luồng chia.
        eligible_ids = {
            o.id for o in unit_officers if o.availability_status == "available"
        }
        res = await assignment_service.compute_unit_officer_loads(
            db,
            unit_officers,
            include_at_capacity=True,
            eligible_officer_ids=eligible_ids,
            lead_unit_id=unit_id,
            flags=flags,
            # ⚠️ Logger RIÊNG: nếu để mặc định, mỗi lần poll dashboard sẽ ghi
            # "Using <mode> scoring" ở mức INFO vào logger của assignment_service
            # — trước đây một dòng như thế nghĩa là ĐÚNG MỘT lead vừa được gán,
            # nên mọi audit đếm quyết định phân công theo log sẽ bị thổi phồng.
            log=_panel_log,
        )
        modes_seen.add(res.scoring)
        # res.loads đã sort: nhóm eligible (thứ tự ưu tiên nhận của engine) trước.
        for rank, load in enumerate(res.loads, 1):
            entries.append(
                _map_load_to_entry(
                    load,
                    rank=rank,
                    unit_id=unit_id,
                    unit_name=unit_name_map.get(unit_id),
                    requesting_user_id=requesting_user_id,
                    finance_on=flags.finance_on,
                    scoring_mode=res.scoring,
                )
            )

    # ⚠️ Chế độ chấm điểm là PER-UNIT (ngưỡng history fairness tính riêng từng
    # đơn vị). Manager/admin có thể trải NHIỀU đơn vị ⇒ giá trị top-level chỉ có
    # nghĩa khi mọi đơn vị cùng mode; khác nhau ⇒ "mixed" (đọc mode chính xác ở
    # ``entries[].scoring_mode``). Không bao giờ lấy mode của unit đầu tiên làm
    # đại diện — sẽ giải thích SAI cho phần entries còn lại.
    real_modes = {m for m in modes_seen if m is not None}
    if len(real_modes) == 1:
        panel_mode = next(iter(real_modes))
    elif len(real_modes) > 1:
        panel_mode = "mixed"
    else:
        panel_mode = None

    return {
        "unit_id": ctx.effective_unit_root_id,
        "total_officers": len(entries),
        "scoring_mode": panel_mode,
        "flags_snapshot": flags_snapshot,
        "entries": entries,
    }
