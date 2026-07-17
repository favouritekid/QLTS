# app/repositories/insights_repository.py
"""
InsightsRepository - Data access for lead insights calculations

Provides optimized queries for:
- Engagement score aggregation (consultation stats)
"""

from datetime import datetime, timezone
from typing import Optional, NamedTuple

from sqlalchemy import select, func, case
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.repositories.base import BaseRepository
from app.config import settings


class EngagementScoreData(NamedTuple):
    """Raw data for engagement score calculation."""
    total_count: int
    total_status_score: int
    total_method_score: int
    total_duration_score: int
    last_consultation_date: Optional[datetime]


class InsightsRepository(BaseRepository[models.Lead]):
    """
    Repository for lead insights data access.
    """
    
    def __init__(self, db: AsyncSession):
        super().__init__(db, models.Lead)
    
    async def get_engagement_score_data(
        self, 
        lead_id: int
    ) -> Optional[EngagementScoreData]:
        """
        Get aggregated consultation data for engagement score calculation.
        
        Single query with conditional aggregations instead of multiple queries.
        
        Returns:
            EngagementScoreData or None if no consultations
        """
        now = datetime.now(timezone.utc)
        points_config = settings.LEAD_SCORING_ENGAGEMENT_POINTS
        
        # Status score cases
        status_score_case = case(
            (
                models.Consultation.consultation_status_id == "sts04",
                points_config["outcome"].get("successful", 10),
            ),
            (
                models.Consultation.consultation_status_id.in_(["sts02", "sts03"]),
                points_config["outcome"].get("follow-up", 5),
            ),
            (
                models.Consultation.consultation_status_id == "sts05",
                points_config["outcome"].get("failed", -5),
            ),
            else_=0,
        )
        
        # Method score cases
        method_score_case = case(
            (models.Consultation.method == "meeting", points_config["method"].get("meeting", 15)),
            (models.Consultation.method == "call", points_config["method"].get("call", 5)),
            (models.Consultation.method == "email", points_config["method"].get("email", 2)),
            else_=0,
        )
        
        # Duration score
        duration_score_calc = func.coalesce(
            (models.Consultation.duration_minutes // 10) * points_config["duration_bonus_per_10_min"],
            0
        )
        
        # Single aggregation query
        stmt = select(
            func.count(models.Consultation.id).label("total_count"),
            func.sum(status_score_case).label("total_status_score"),
            func.sum(method_score_case).label("total_method_score"),
            func.sum(duration_score_calc).label("total_duration_score"),
            func.max(models.Consultation.consultation_date).label("last_consultation_date"),
        ).where(
            models.Consultation.lead_id == lead_id,
            models.Consultation.consultation_date <= now,
            models.Consultation.deleted_at.is_(None),  # Exclude soft-deleted consultations
            # B7b: loại cuộc do hệ thống tạo khỏi engagement (count + recency).
            # Recency ở đây feed insights_service, KHÔNG phải cache SLA nên lọc
            # cả WHERE an toàn. Lead chỉ có cuộc system → total_count=0 → trả None.
            models.Consultation.method.is_distinct_from("system"),
        )
        
        result = await self.db.execute(stmt)
        row = result.one_or_none()
        
        if not row or row.total_count == 0:
            return None
        
        return EngagementScoreData(
            total_count=row.total_count or 0,
            total_status_score=row.total_status_score or 0,
            total_method_score=row.total_method_score or 0,
            total_duration_score=row.total_duration_score or 0,
            last_consultation_date=row.last_consultation_date,
        )
    
    async def get_filtered(self, skip: int = 0, limit: int = 100, **filters):
        """Not used for insights - required by base class."""
        return 0, []
