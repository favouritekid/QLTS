# app/services/insights_service.py
from datetime import datetime, timezone
from typing import List

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from .. import models, schemas
from ..config import settings
from ..repositories import InsightsRepository

log = structlog.get_logger(__name__)


async def _calculate_engagement_score(db: AsyncSession, lead_id: int) -> int:
    """
    Tính điểm tương tác.
    
    REFACTORED: Uses InsightsRepository for data access.
    """
    repo = InsightsRepository(db)
    points_config = settings.LEAD_SCORING_ENGAGEMENT_POINTS
    now = datetime.now(timezone.utc)
    
    # Get aggregated data from repository
    data = await repo.get_engagement_score_data(lead_id)
    
    if data is None:
        return 0
    
    # Calculate score
    score = 0
    score += data.total_count * points_config["consultation_count_multiplier"]
    score += data.total_status_score
    score += data.total_method_score
    score += data.total_duration_score
    
    # Inactivity penalty
    if data.last_consultation_date:
        last_date = data.last_consultation_date
        if last_date.tzinfo is None:
            last_date = last_date.replace(tzinfo=timezone.utc)
        
        days_since_last_contact = (now - last_date).days
        if days_since_last_contact > 3:
            penalty = abs(points_config["inactivity_penalty_per_day"])
            score -= (days_since_last_contact - 3) * penalty
    
    return max(0, min(score, points_config["max_score"]))


def _calculate_fit_score(lead: models.Lead) -> int:
    """
    Fit Score = lead_score + Officer Rating bonus

    Công thức minh bạch cho Officers:
    - Base: lead_score (0-100) - đã tính từ education, GPA, source, location
    - Bonus: officer_rating × 4 (1-5 stars → +4 to +20 điểm)

    Ví dụ:
    - lead_score=50, officer_rating=5 → 50 + 20 = 70
    - lead_score=60, officer_rating=None → 60
    - lead_score=90, officer_rating=3 → min(90+12, 100) = 100

    Max: 100
    """
    base_score = lead.lead_score or 0

    officer_bonus = 0
    if lead.officer_rating:
        try:
            officer_bonus = int(lead.officer_rating) * 4  # 1-5 → +4 to +20
        except (ValueError, TypeError):
            officer_bonus = 0

    return min(base_score + officer_bonus, 100)


def _get_urgency_score(lead: models.Lead) -> int:
    """
    Urgency Score = cached_urgency_score từ Lead model

    Công thức minh bạch cho Officers (đã tính trong lead_cache_service):
    - Task quá hạn (is_overdue): +30
    - Hoạt động tiếp theo trong 24h: +20
    - Giai đoạn pipeline: stage_order × 5
    - Ngày không hoạt động: +2/ngày (max +20)

    Sử dụng cached value để đảm bảo đồng bộ với Lead model.
    Max: 100
    """
    return lead.cached_urgency_score or 0


async def get_lead_insights(
    db: AsyncSession,
    lead: models.Lead,
    timeline: List[dict],
) -> schemas.LeadInsights:
    """
    Lấy các chỉ số insight 360 độ của một Lead.
    ✅ FIXED: Không refresh 'consultations', thay vào đó gọi
    hàm _calculate_engagement_score đã tối ưu.
    """
    log.debug("Calculating insights for lead", lead_id=lead.id)

    # === ⭐️ THAY ĐỔI QUAN TRỌNG Ở ĐÂY ⭐️ ===
    try:
        # BỎ "consultations" khỏi danh sách refresh
        await db.refresh(lead, ["assignment_logs", "pipeline_stage"])
        log.debug(
            "Lead object refreshed (minimal) before insight calculation",
            lead_id=lead.id,
        )
    except Exception as e:
        log.error(
            "Failed to refresh lead object before calculating insights",
            lead_id=lead.id,
            error=str(e),
            exc_info=True,
        )
    # === KẾT THÚC THAY ĐỔI ===

    # Tính toán điểm số

    # 1. Gọi hàm async mới (chạy song song)
    engagement_score_task = _calculate_engagement_score(db, lead.id)

    # 2. Các hàm sync (không cần timeline cho urgency nữa - dùng cached)
    fit_score = _calculate_fit_score(lead)
    urgency_score = _get_urgency_score(lead)

    # 3. Lấy kết quả
    engagement_score = await engagement_score_task

    # (Logic còn lại giữ nguyên)
    weights = settings.LEAD_SCORING_WEIGHTS
    overall_score = (
        (engagement_score * weights["engagement"])
        + (fit_score * weights["fit"])
        + (urgency_score * weights["urgency"])
    )

    if lead.officer_rating:
        try:
            rating_contribution = (
                int(lead.officer_rating) * weights["officer_rating_multiplier"]
            ) * weights["officer_rating_weight"]
            overall_score += rating_contribution
        except (ValueError, TypeError):
            log.warning(
                "Invalid officer_rating during insight calculation",
                lead_id=lead.id,
                rating=lead.officer_rating,
            )

    overall_score_final = int(min(max(overall_score, 0), 100))

    return schemas.LeadInsights(
        engagement_score=int(engagement_score),
        fit_score=int(fit_score),
        urgency_score=int(urgency_score),
        overall_score=overall_score_final,
        officer_rating=lead.officer_rating,
        officer_summary=lead.officer_summary,
    )
