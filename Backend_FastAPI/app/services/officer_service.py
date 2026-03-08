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
    transition_rates = await repo.get_stage_transition_rates(officer_id, days=30)

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
                "action_url": f"/leads?stage={stage['stage_id']}&outcome=negative",
                "_severity": severity * 50,  # High weight for revenue
            })

    # 4. Top Loss Reasons
    if aggregated_loss_breakdown:
        for reason in aggregated_loss_breakdown[:2]:  # Top 2 reasons
            if reason.get("percentage", 0) >= cfg["loss_reason_threshold_pct"]:
                reason_code = reason["reason_code"]
                count = reason["count"]
                pct = reason["percentage"]

                # Map reason codes to actionable labels
                reason_actions = {
                    "PRICE_HIGH": ("học phí cao", "Xem xét chính sách học bổng/ưu đãi"),
                    "LOCATION_FAR": ("xa nhà", "Hỗ trợ thông tin ký túc xá/di chuyển"),
                    "CHOSE_COMPETITOR": ("chọn trường khác", "Phân tích USP và cải thiện pitch"),
                    "NO_CONTACT": ("không liên lạc được", "Cải thiện quy trình follow-up"),
                    "TIMING_BAD": ("chưa sẵn sàng", "Nurture leads chưa ready"),
                }

                reason_label, action_hint = reason_actions.get(
                    reason_code,
                    (reason_code.lower().replace("_", " "), "Phân tích và có chiến lược xử lý")
                )

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
                    "action_url": f"/leads?outcome=negative&loss_reason={reason_code}",
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
    
    new_lead_conversion_rate = round((converted_in_range / total_in_range) * 100, 1)

    # Compare with previous period of same length
    prev_filter_end = filter_start - timedelta(days=1)
    prev_filter_start = prev_filter_end - timedelta(days=filter_days - 1)

    # Get previous period KPIs using Repository
    prev_kpi_data = await repo.get_kpi_stats(officer_id, prev_filter_start, prev_filter_end)
    converted_prev = prev_kpi_data["converted_count"]
    total_prev = prev_kpi_data["total_leads"] or 1
    prev_rate = (converted_prev / total_prev) * 100

    conversion_diff = new_lead_conversion_rate - prev_rate
    new_lead_conversion_trend = {
        "value": abs(round(conversion_diff, 1)),
        "direction": "up" if conversion_diff > 0 else "down" if conversion_diff < 0 else "neutral",
        "comparison": f"vs {filter_days} ngày trước"
    }

    # === Activity-based Win Rate ===
    win_rate_data = await repo.get_win_rate_stats(officer_id, filter_start, filter_end)
    prev_win_rate_data = await repo.get_win_rate_stats(officer_id, prev_filter_start, prev_filter_end)
    win_rate_diff = win_rate_data["win_rate"] - prev_win_rate_data["win_rate"]
    win_rate_trend = {
        "value": abs(round(win_rate_diff, 1)),
        "direction": "up" if win_rate_diff > 0 else "down" if win_rate_diff < 0 else "neutral",
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

    # === 5. SLA COMPLIANCE RATE ===
    sla_hours = await kpi_service.get_kpi_target(
        db, "response_time_hours", officer_id, user.unit_id, "daily"
    )
    sla_stats = await repo.get_sla_compliance_stats(officer_id, filter_start, filter_end, sla_hours)
    prev_sla_stats = await repo.get_sla_compliance_stats(officer_id, prev_filter_start, prev_filter_end, sla_hours)
    sla_diff = sla_stats["rate"] - prev_sla_stats["rate"]
    sla_compliance_trend = {
        "value": abs(round(sla_diff, 1)),
        "direction": "up" if sla_diff > 0 else "down" if sla_diff < 0 else "neutral",
        "comparison": f"vs {filter_days} ngày trước",
    }

    # === 6. CONSULTATION EFFECTIVENESS ===
    effectiveness_stats = await repo.get_consultation_effectiveness_stats(officer_id, filter_start, filter_end)
    prev_effectiveness_stats = await repo.get_consultation_effectiveness_stats(officer_id, prev_filter_start, prev_filter_end)
    eff_diff = effectiveness_stats["effectiveness"] - prev_effectiveness_stats["effectiveness"]
    effectiveness_trend = {
        "value": abs(round(eff_diff, 1)),
        "direction": "up" if eff_diff > 0 else "down" if eff_diff < 0 else "neutral",
        "comparison": f"vs {filter_days} ngày trước",
    }

    # === 7. PRIORITY ACTIONS ===
    priority_actions = await _calculate_priority_actions(db, officer_id)

    # === 8. PERFORMANCE TRENDS (within date range) - OPTIMIZED ===
    # Use batch query instead of N+1 day loop (repo already initialized in section 4)
    trends_data = await repo.get_performance_trends_batch(officer_id, filter_start, filter_end)
    performance_trends = [
        {"date": tp.date, "assigned": tp.assigned, "consultations": tp.consultations, "converted": tp.converted}
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

    # === 10. ANNUAL PROGRESS (Phase 6: Rolling Targets) ===
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
            "win_rate": win_rate_data["win_rate"],
            "win_rate_trend": win_rate_trend,
            "new_lead_conversion_rate": new_lead_conversion_rate,
            "new_lead_conversion_rate_trend": new_lead_conversion_trend,
            "avg_response_time": avg_response_time,
            "avg_response_time_trend": avg_response_trend,
            "sla_compliance_rate": sla_stats["rate"],
            "sla_compliance_rate_trend": sla_compliance_trend,
            "consultation_effectiveness": effectiveness_stats["effectiveness"],
            "consultation_effectiveness_trend": effectiveness_trend,
        },
        "status_overview": base_stats["status_overview"],
        "priority_actions": priority_actions,
        "performance_trends": performance_trends,
        "sales_funnel": sales_funnel,
        "funnel_suggestions": funnel_suggestions,  # Phase 2: AI-powered suggestions
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
    new_lead_conversion_rate = round((converted_count / total_leads) * 100, 1)

    # Aggregated Win Rate
    win_rate_data = await repo.get_aggregated_win_rate_stats(officer_ids, filter_start, filter_end)

    # Aggregated SLA Compliance
    sla_hours = await kpi_service.get_kpi_target(db, "response_time_hours")
    agg_sla_stats = await repo.get_aggregated_sla_compliance_stats(officer_ids, filter_start, filter_end, sla_hours)

    # Aggregated Consultation Effectiveness
    agg_effectiveness_stats = await repo.get_aggregated_consultation_effectiveness_stats(officer_ids, filter_start, filter_end)

    # ==========================================================================
    # Aggregated Funnel using Repository (was N+1 loop)
    # ==========================================================================
    sales_funnel = await repo.get_aggregated_funnel(officer_ids)

    # ==========================================================================
    # Phase 2: Fetch metrics for aggregated funnel (loss_breakdown, velocity, lost_revenue)
    # Use unit_ids for filtering (more efficient than officer_ids for these queries)
    # ==========================================================================
    unit_ids_for_metrics = [target_unit_id] if target_unit_id else None

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

    # Phase 2: Generate funnel suggestions based on aggregated metrics
    funnel_suggestions = generate_funnel_suggestions(sales_funnel)
    
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
            "win_rate": win_rate_data["win_rate"],
            "win_rate_trend": {
                "value": 0,
                "direction": "neutral",
                "comparison": f"trong {filter_days} ngày",
            },
            "new_lead_conversion_rate": new_lead_conversion_rate,
            "new_lead_conversion_rate_trend": {
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
            "sla_compliance_rate": agg_sla_stats["rate"],
            "sla_compliance_rate_trend": {
                "value": 0,
                "direction": "neutral",
                "comparison": f"trong {filter_days} ngày",
            },
            "consultation_effectiveness": agg_effectiveness_stats["effectiveness"],
            "consultation_effectiveness_trend": {
                "value": 0,
                "direction": "neutral",
                "comparison": f"trong {filter_days} ngày",
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
        "funnel_suggestions": funnel_suggestions,  # Phase 2: AI-powered suggestions
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
            "win_rate": 0,
            "win_rate_trend": {"value": 0, "direction": "neutral", "comparison": ""},
            "new_lead_conversion_rate": 0,
            "new_lead_conversion_rate_trend": {"value": 0, "direction": "neutral", "comparison": ""},
            "avg_response_time": 0,
            "avg_response_time_trend": {"value": 0, "direction": "neutral", "comparison": ""},
            "sla_compliance_rate": 0,
            "sla_compliance_rate_trend": {"value": 0, "direction": "neutral", "comparison": ""},
            "consultation_effectiveness": 0,
            "consultation_effectiveness_trend": {"value": 0, "direction": "neutral", "comparison": ""},
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
        "funnel_suggestions": [],  # Phase 2: Empty suggestions
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