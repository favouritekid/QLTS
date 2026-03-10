# app/services/recommendation_engine.py
"""
Recommendation Engine - Phase 7

Generates actionable recommendations based on KPI performance analysis.
Rules-based engine that analyzes:
1. KPI gaps (actual vs target)
2. Trends (improving, declining, stagnant)
3. Historical patterns
4. Industry benchmarks

Returns structured recommendations with priority, action items, and expected impact.
"""
import structlog
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.services import kpi_service

log = structlog.get_logger(__name__)


# =============================================================================
# RECOMMENDATION RULES
# =============================================================================

class RecommendationType:
    """Types of recommendations."""
    INCREASE_ACTIVITY = "increase_activity"
    IMPROVE_CONVERSION = "improve_conversion"
    REDUCE_RESPONSE_TIME = "reduce_response_time"
    FOCUS_HOT_LEADS = "focus_hot_leads"
    CLEAR_STALE_LEADS = "clear_stale_leads"
    BALANCE_WORKLOAD = "balance_workload"
    CELEBRATE_SUCCESS = "celebrate_success"
    MAINTAIN_MOMENTUM = "maintain_momentum"


class RecommendationPriority:
    """Priority levels for recommendations."""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


# Default thresholds (fallback when no config exists)
DEFAULT_THRESHOLDS = {
    "consultations_gap_critical": 0.5,   # < 50% of target
    "consultations_gap_warning": 0.8,    # < 80% of target
    "conversion_rate_low": 10,           # < 10%
    "conversion_rate_good": 20,          # >= 20%
    "response_time_critical": 4,         # > 4 hours
    "response_time_warning": 2,          # > 2 hours
    "hot_leads_untouched": 3,            # > 3 hot leads without recent activity
    "stale_leads_threshold": 5,          # > 5 stale leads
}

# Valid threshold keys (for validation in P3-2)
VALID_THRESHOLD_KEYS = frozenset(DEFAULT_THRESHOLDS.keys())

# KpiConfig kpi_code prefix for threshold storage
THRESHOLD_KPI_PREFIX = "threshold_"


async def get_recommendation_thresholds(
    db: AsyncSession,
    officer_id: Optional[int] = None,
    unit_id: Optional[int] = None,
) -> Dict[str, float]:
    """
    Get recommendation thresholds with config-driven resolution (Phase P3-1).

    Priority: officer config -> unit config -> global config -> DEFAULT_THRESHOLDS.
    Each threshold key is resolved independently (partial override allowed).

    Reads from KpiConfig with kpi_code = "threshold_{key}", period_type = "threshold".
    """
    thresholds = dict(DEFAULT_THRESHOLDS)
    resolved_source: Dict[str, str] = {}

    try:
        for key in DEFAULT_THRESHOLDS:
            kpi_code = f"{THRESHOLD_KPI_PREFIX}{key}"
            target = await kpi_service.get_kpi_target(
                db, kpi_code=kpi_code,
                officer_id=officer_id, unit_id=unit_id,
                period_type="threshold",
            )
            # get_kpi_target returns 0 when no config exists (default=0 for unknown codes)
            # We only override if a non-zero config was found
            if target != 0:
                thresholds[key] = target
                resolved_source[key] = "config"
            else:
                resolved_source[key] = "default"
    except Exception as e:
        log.warning("Failed to load threshold config, using defaults", error=str(e))
        resolved_source = {k: "default_fallback" for k in DEFAULT_THRESHOLDS}

    log.debug(
        "Thresholds resolved",
        officer_id=officer_id, unit_id=unit_id,
        sources=resolved_source,
    )
    return thresholds


# =============================================================================
# RECOMMENDATION GENERATION
# =============================================================================

async def generate_recommendations(
    db: AsyncSession,
    officer_id: int,
    kpis: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """
    Generate actionable recommendations based on KPI data.

    P3-1: Uses config-driven thresholds (officer -> unit -> global -> default).

    Args:
        db: Database session
        officer_id: Officer ID to generate recommendations for
        kpis: Current KPI data from dashboard

    Returns:
        List of recommendation objects with priority, action, and impact
    """
    from app.repositories import LeadRepository, UserRepository

    recommendations = []

    # Get user info via repository
    user_repo = UserRepository(db)
    user = await user_repo.get_by_id(officer_id)
    if not user:
        return recommendations

    # P3-1: Resolve thresholds from config (officer -> unit -> global -> default)
    t = await get_recommendation_thresholds(db, officer_id=officer_id, unit_id=user.unit_id)

    # Rule 1: Consultations below target
    consultations_today = kpis.get("consultations_today", 0)
    consultations_target = kpis.get("consultations_target", 10)

    if consultations_target > 0:
        ratio = consultations_today / consultations_target

        if ratio < t["consultations_gap_critical"]:
            recommendations.append({
                "type": RecommendationType.INCREASE_ACTIVITY,
                "priority": RecommendationPriority.CRITICAL,
                "title": "Tăng cường hoạt động tư vấn",
                "message": f"Bạn mới hoàn thành {consultations_today}/{consultations_target} buổi tư vấn. "
                          f"Hãy liên hệ ngay với các lead có điểm cao nhất.",
                "action": "Xem lead nóng",
                "action_link": "/leads?filter=hot",
                "expected_impact": f"Đạt chỉ tiêu {consultations_target} tư vấn/ngày",
            })
        elif ratio < t["consultations_gap_warning"]:
            recommendations.append({
                "type": RecommendationType.INCREASE_ACTIVITY,
                "priority": RecommendationPriority.HIGH,
                "title": "Gần đạt chỉ tiêu",
                "message": f"Còn {consultations_target - consultations_today} tư vấn nữa để đạt chỉ tiêu. "
                          f"Tập trung vào lead có khả năng chuyển đổi cao.",
                "action": "Xem danh sách lead ưu tiên",
                "action_link": "/leads?sort=lead_score&order=desc",
                "expected_impact": "Đạt 100% chỉ tiêu ngày",
            })
    
    # Rule 2: Low conversion rate
    conversion_rate = kpis.get("new_lead_conversion_rate", 0)
    
    if conversion_rate < t["conversion_rate_low"]:
        recommendations.append({
            "type": RecommendationType.IMPROVE_CONVERSION,
            "priority": RecommendationPriority.HIGH,
            "title": "Cải thiện tỷ lệ chuyển đổi",
            "message": f"Tỷ lệ chuyển đổi hiện tại là {conversion_rate}%, thấp hơn mục tiêu. "
                      f"Xem lại quy trình tư vấn và nghiên cứu các case thành công.",
            "action": "Xem lead đã chuyển đổi",
            "action_link": "/leads?filter=converted",
            "expected_impact": f"Tăng tỷ lệ chuyển đổi lên {t['conversion_rate_good']}%",
        })
    
    # Rule 3: Slow response time
    avg_response_time = kpis.get("avg_response_time", 0)
    
    if avg_response_time > t["response_time_critical"]:
        recommendations.append({
            "type": RecommendationType.REDUCE_RESPONSE_TIME,
            "priority": RecommendationPriority.CRITICAL,
            "title": "Giảm thời gian phản hồi",
            "message": f"Thời gian phản hồi trung bình là {avg_response_time}h, quá lâu. "
                      f"Lead mới cần được liên hệ trong vòng 2 giờ.",
            "action": "Xem lead mới",
            "action_link": "/leads?filter=new",
            "expected_impact": "Tăng tỷ lệ tiếp cận thành công 30%",
        })
    elif avg_response_time > t["response_time_warning"]:
        recommendations.append({
            "type": RecommendationType.REDUCE_RESPONSE_TIME,
            "priority": RecommendationPriority.MEDIUM,
            "title": "Cải thiện thời gian phản hồi",
            "message": f"Thời gian phản hồi {avg_response_time}h có thể tốt hơn. "
                      f"Mục tiêu là dưới 2 giờ.",
            "action": "Xem lead chưa liên hệ",
            "action_link": "/leads?filter=no_contact",
            "expected_impact": "Cải thiện trải nghiệm khách hàng",
        })
    
    # Rule 4: Hot leads need attention (via repository)
    lead_repo = LeadRepository(db)
    hot_leads_count = await lead_repo.count_hot_leads_needing_attention(officer_id)
    
    if hot_leads_count > t["hot_leads_untouched"]:
        recommendations.append({
            "type": RecommendationType.FOCUS_HOT_LEADS,
            "priority": RecommendationPriority.CRITICAL,
            "title": "Lead nóng cần chú ý",
            "message": f"Có {hot_leads_count} lead nóng chưa được liên hệ trong 3 ngày qua. "
                      f"Đây là cơ hội chuyển đổi cao nhất!",
            "action": "Xem lead nóng",
            "action_link": "/leads?filter=hot&sort=last_contact",
            "expected_impact": f"Tăng {hot_leads_count * 2} enrollments tiềm năng",
        })
    
    # Rule 5: Too many stale leads (via repository)
    stale_leads_count = await lead_repo.count_stale_leads(officer_id)
    
    if stale_leads_count > t["stale_leads_threshold"]:
        recommendations.append({
            "type": RecommendationType.CLEAR_STALE_LEADS,
            "priority": RecommendationPriority.MEDIUM,
            "title": "Dọn dẹp lead cũ",
            "message": f"Có {stale_leads_count} lead không hoạt động hơn 14 ngày. "
                      f"Xem xét liên hệ lại hoặc chuyển trạng thái để tập trung vào lead tiềm năng.",
            "action": "Xem lead cũ",
            "action_link": "/leads?filter=stale",
            "expected_impact": "Workload gọn gàng, tập trung hơn",
        })
    
    # Rule 6: Success celebration (positive reinforcement)
    if consultations_target > 0 and consultations_today >= consultations_target:
        recommendations.append({
            "type": RecommendationType.CELEBRATE_SUCCESS,
            "priority": RecommendationPriority.LOW,
            "title": "🎉 Hoàn thành chỉ tiêu!",
            "message": f"Tuyệt vời! Bạn đã hoàn thành {consultations_today}/{consultations_target} tư vấn. "
                      f"Tiếp tục duy trì phong độ!",
            "action": None,
            "action_link": None,
            "expected_impact": "Duy trì hiệu suất cao",
        })
    
    # Rule 7: Conversion rate excellent
    if conversion_rate >= t["conversion_rate_good"]:
        recommendations.append({
            "type": RecommendationType.MAINTAIN_MOMENTUM,
            "priority": RecommendationPriority.LOW,
            "title": "✨ Tỷ lệ chuyển đổi xuất sắc",
            "message": f"Tỷ lệ chuyển đổi {conversion_rate}% rất tốt! "
                      f"Chia sẻ kinh nghiệm với đồng nghiệp.",
            "action": None,
            "action_link": None,
            "expected_impact": "Lan tỏa best practices",
        })
    
    # Sort by priority
    priority_order = {
        RecommendationPriority.CRITICAL: 0,
        RecommendationPriority.HIGH: 1,
        RecommendationPriority.MEDIUM: 2,
        RecommendationPriority.LOW: 3,
    }
    recommendations.sort(key=lambda r: priority_order.get(r["priority"], 99))
    
    log.info(
        "Generated recommendations",
        officer_id=officer_id,
        count=len(recommendations),
    )
    
    return recommendations

# =============================================================================
# ✅ DEPRECATED: Helper functions moved to LeadRepository
# - count_hot_leads_needing_attention() -> LeadRepository.count_hot_leads_needing_attention()
# - count_stale_leads() -> LeadRepository.count_stale_leads()
# =============================================================================


# =============================================================================
# API INTEGRATION
# =============================================================================

async def get_officer_recommendations(
    db: AsyncSession,
    officer_id: int,
    limit: int = 5,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Get recommendations for an officer, intended for dashboard display.

    Args:
        db: Database session
        officer_id: Officer ID
        limit: Maximum recommendations to return
        start_date: Optional start date (YYYY-MM-DD)
        end_date: Optional end date (YYYY-MM-DD)

    Returns:
        List of recommendation objects
    """
    # First, get current KPIs (with date range if provided)
    from app.services.officer_service import get_enhanced_dashboard_stats

    try:
        stats = await get_enhanced_dashboard_stats(
            db, officer_id,
            start_date=start_date,
            end_date=end_date,
        )
        kpis = stats.get("kpis", {})
    except Exception as e:
        log.warning(f"Could not fetch KPIs for recommendations: {e}")
        kpis = {}

    recommendations = await generate_recommendations(db, officer_id, kpis)

    return recommendations[:limit]
