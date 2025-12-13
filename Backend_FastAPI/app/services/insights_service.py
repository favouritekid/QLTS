# app/services/insights_service.py
from datetime import datetime, timezone
from typing import List

import structlog
from sqlalchemy import select  # <-- THÊM select
from sqlalchemy import case, func
from sqlalchemy.ext.asyncio import AsyncSession

from .. import models, schemas
from ..config import settings

log = structlog.get_logger(__name__)


async def _calculate_engagement_score(db: AsyncSession, lead_id: int) -> int:
    """
    Tính điểm tương tác.
    ✅ FIXED: Sử dụng consultation_status_id thay vì outcome (không tồn tại trong model).
    """
    score = 0
    points_config = settings.LEAD_SCORING_ENGAGEMENT_POINTS
    now = datetime.now(timezone.utc)

    # Định nghĩa các trường hợp (case) cho điểm dựa trên consultation_status_id
    # Status IDs: sts01=Lên lịch, sts02=Đã liên hệ, sts03=Cần theo dõi, sts04=Thành công, sts05=Thất bại
    status_score_case = case(
        (
            models.Consultation.consultation_status_id == "sts04",  # Thành công
            points_config["outcome"].get("successful", 10),
        ),
        (
            models.Consultation.consultation_status_id.in_(["sts02", "sts03"]),  # Đã liên hệ / Cần theo dõi
            points_config["outcome"].get("follow-up", 5),
        ),
        (
            models.Consultation.consultation_status_id == "sts05",  # Thất bại
            points_config["outcome"].get("failed", -5),
        ),
        else_=0,
    )

    method_score_case = case(
        (models.Consultation.method == "meeting", points_config["method"].get("meeting", 15)),
        (models.Consultation.method == "call", points_config["method"].get("call", 5)),
        (models.Consultation.method == "email", points_config["method"].get("email", 2)),
        else_=0,
    )

    # Handle NULL duration_minutes with COALESCE
    duration_score_calc = func.coalesce(
        (models.Consultation.duration_minutes // 10) * points_config["duration_bonus_per_10_min"],
        0
    )

    # Truy vấn tổng hợp
    stmt = select(
        func.count(models.Consultation.id).label("total_count"),
        func.sum(status_score_case).label("total_status_score"),
        func.sum(method_score_case).label("total_method_score"),
        func.sum(duration_score_calc).label("total_duration_score"),
        func.max(models.Consultation.consultation_date).label("last_consultation_date"),
    ).where(
        models.Consultation.lead_id == lead_id,
        models.Consultation.consultation_date <= now,
    )

    # Thực thi truy vấn (chỉ trả về 1 hàng)
    result = await db.execute(stmt)
    agg_data = result.one_or_none()

    if not agg_data or agg_data.total_count == 0:
        return 0

    # Logic tính toán
    score += agg_data.total_count * points_config["consultation_count_multiplier"]
    score += agg_data.total_status_score or 0
    score += agg_data.total_method_score or 0
    score += agg_data.total_duration_score or 0

    # Tính phạt dựa trên ngày không liên hệ
    last_consultation_date = agg_data.last_consultation_date
    if last_consultation_date:
        if last_consultation_date.tzinfo is None:
            last_consultation_date = last_consultation_date.replace(tzinfo=timezone.utc)

        days_since_last_contact = (now - last_consultation_date).days
        if days_since_last_contact > 3:
            penalty = abs(points_config["inactivity_penalty_per_day"])
            score -= (days_since_last_contact - 3) * penalty

    return max(0, min(score, points_config["max_score"]))


def _calculate_fit_score(lead: models.Lead) -> int:
    # ... (Hàm này giữ nguyên, không thay đổi) ...
    score = 0
    points_config = settings.LEAD_SCORING_FIT_POINTS
    score += points_config["source"].get(lead.source, 0)
    if lead.gpa:
        for threshold, points in sorted(
            points_config["gpa_thresholds"].items(), reverse=True
        ):
            if lead.gpa >= threshold:
                score += points
                break
    if lead.education_level:
        score += points_config["education_level"].get(lead.education_level, 0)
    if lead.location:
        score += points_config["location"].get(lead.location, 0)
    return max(0, min(score, points_config["max_score"]))


def _calculate_urgency_score(lead: models.Lead, timeline: List[dict]) -> int:
    # ... (Hàm này giữ nguyên, không thay đổi) ...
    score = 0
    points_config = settings.LEAD_SCORING_URGENCY_POINTS
    if hasattr(lead, "pipeline_stage") and lead.pipeline_stage:
        score += lead.pipeline_stage.order * points_config["stage_order_multiplier"]
    else:
        initial_stage_order = 1
        score += initial_stage_order * points_config["stage_order_multiplier"]

    stage_changes = []
    sorted_timeline = sorted(timeline, key=lambda x: x["timestamp"])

    for item in sorted_timeline:
        consultation_status = None
        if item["type"] == "consultation":
            if hasattr(item["data"], "consultation_status"):
                consultation_status = item["data"].consultation_status

        if consultation_status:
            stage_id = consultation_status.stage_id
            if not stage_changes or stage_changes[-1]["stage_id"] != stage_id:
                stage_changes.append(
                    {"stage_id": stage_id, "timestamp": item["timestamp"]}
                )

    for i in range(1, len(stage_changes)):
        ts_i = stage_changes[i]["timestamp"]
        ts_prev = stage_changes[i - 1]["timestamp"]
        if ts_i.tzinfo is None:
            ts_i = ts_i.replace(tzinfo=timezone.utc)
        if ts_prev.tzinfo is None:
            ts_prev = ts_prev.replace(tzinfo=timezone.utc)

        time_diff_days = (ts_i - ts_prev).days
        if time_diff_days <= 3:
            score += points_config["fast_conversion_bonus"]
        elif time_diff_days > 14:
            score -= abs(points_config["slow_conversion_penalty"])

    return max(0, min(score, points_config["max_score"]))


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

    # 2. Các hàm sync cũ (vẫn cần 'lead' object)
    fit_score = _calculate_fit_score(lead)
    urgency_score = _calculate_urgency_score(lead, timeline)

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
