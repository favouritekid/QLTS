# app/repositories/officer_repository.py
"""
OfficerRepository - Optimized data access for Officer Dashboard

Key optimizations:
- Batch queries with GROUP BY instead of N+1 loops
- CTEs for related aggregations
- Conditional aggregations for multi-stat queries

Created: 2024-12-18
"""

import structlog
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select, func, or_, and_, case, literal_column
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload, joinedload

from app import models
from app.core.constants import UserRole
from app.repositories.base import BaseRepository

log = structlog.get_logger(__name__)


# =============================================================================
# TYPE DEFINITIONS
# =============================================================================

class FunnelStageData:
    """Data for a single funnel stage."""
    def __init__(
        self,
        stage_id: str,
        stage_name: str,
        stage_order: int,
        is_final_stage: bool,
        lead_count: int = 0,
        positive_count: int = 0,
        negative_count: int = 0,
        neutral_count: int = 0,
    ):
        self.stage_id = stage_id
        self.stage_name = stage_name
        self.stage_order = stage_order
        self.is_final_stage = is_final_stage
        self.lead_count = lead_count
        self.positive_count = positive_count
        self.negative_count = negative_count
        self.neutral_count = neutral_count


class TrendPoint:
    """Data for a single day in performance trends."""
    def __init__(self, date: str, assigned: int = 0, consultations: int = 0, converted: int = 0, enrolled: int = 0, lost: int = 0):
        self.date = date
        self.assigned = assigned
        self.consultations = consultations
        self.converted = converted  # Backward compat: enrolled + lost
        self.enrolled = enrolled
        self.lost = lost


# =============================================================================
# OFFICER REPOSITORY
# =============================================================================

class OfficerRepository(BaseRepository[models.User]):
    """
    Repository for officer-related data access.
    
    Provides optimized queries for dashboard statistics,
    using batch queries and CTEs to minimize database round-trips.
    """
    
    def __init__(self, db: AsyncSession):
        super().__init__(db, models.User)
    
    # =========================================================================
    # CORE: Workload & Capacity
    # =========================================================================
    
    async def get_officer_with_capacity(self, officer_id: int) -> Optional[models.User]:
        """Get officer with capacity info."""
        return await self.db.get(models.User, officer_id)
    
    async def get_workload_count(self, officer_id: int) -> int:
        """
        Count active leads (non-final stage) for an officer.
        
        Optimized: Single COUNT query with LEFT JOIN.
        """
        query = (
            select(func.count(models.Lead.id))
            .join(
                models.PipelineStage,
                models.Lead.pipeline_stage_id == models.PipelineStage.id,
                isouter=True,
            )
            .where(
                models.Lead.assigned_officer_id == officer_id,
                models.Lead.deleted_at.is_(None),
                or_(
                    models.PipelineStage.is_final_stage == False,
                    models.PipelineStage.is_final_stage.is_(None),
                ),
            )
        )
        result = await self.db.execute(query)
        return result.scalar() or 0
    
    # =========================================================================
    # OPTIMIZED: Sales Funnel (was 14 queries → 2)
    # =========================================================================
    
    async def get_all_pipeline_stages(self) -> List[models.PipelineStage]:
        """Get all pipeline stages ordered."""
        query = select(models.PipelineStage).order_by(models.PipelineStage.order.asc())
        result = await self.db.execute(query)
        return list(result.scalars().all())
    
    async def get_funnel_stage_counts_batch(
        self,
        officer_id: int,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> Dict[str, Dict[str, Any]]:
        """
        Get lead counts and outcome breakdown for ALL stages in ONE query.

        OPTIMIZATION: Replaces N+1 loop with single GROUP BY query.
        Before: 14 queries (7 stages × 2 queries each)
        After: 1 query

        SPEC COMPLIANCE (2026-02-04):
        - Filter: counts_for_funnel = TRUE (exclude activity logs)
        - Filter: stage_id IS NOT NULL (exclude universal statuses)
        - Early Exit: Counts FINAL leads at non-final stages

        Returns:
            Dict[stage_id, {count, positive, negative, neutral, early_exit_count}]
        """
        # Base conditions
        conditions = [
            models.Lead.assigned_officer_id == officer_id,
            models.Lead.deleted_at.is_(None),
            # SPEC: Exclude universal statuses (stage_id = NULL)
            models.Lead.pipeline_stage_id.isnot(None),
        ]

        # Optional date filter
        if start_date and end_date:
            conditions.extend([
                func.date(models.Lead.created_at) >= start_date,
                func.date(models.Lead.created_at) <= end_date,
            ])

        # Single query with conditional aggregations
        # SPEC: Only count leads with counts_for_funnel = TRUE
        query = (
            select(
                models.Lead.pipeline_stage_id,
                func.count(models.Lead.id).label("total_count"),
                # Conditional counts for outcome breakdown
                func.count(
                    case(
                        (models.ConsultationStatus.outcome_type == "positive", 1),
                    )
                ).label("positive_count"),
                func.count(
                    case(
                        (models.ConsultationStatus.outcome_type == "negative", 1),
                    )
                ).label("negative_count"),
                func.count(
                    case(
                        (models.ConsultationStatus.outcome_type == "neutral", 1),
                    )
                ).label("neutral_count"),
                # SPEC: Early Exit = FINAL leads at this stage (outcome=negative, is_final=TRUE)
                func.count(
                    case(
                        (and_(
                            models.ConsultationStatus.is_final == True,
                            models.ConsultationStatus.outcome_type == "negative",
                        ), 1),
                    )
                ).label("early_exit_count"),
            )
            .join(
                models.ConsultationStatus,
                models.Lead.consultation_status_id == models.ConsultationStatus.id
            )
            .where(
                *conditions,
                # SPEC: counts_for_funnel = TRUE (only funnel-relevant statuses)
                models.ConsultationStatus.counts_for_funnel == True,
            )
            .group_by(models.Lead.pipeline_stage_id)
        )

        result = await self.db.execute(query)

        # Build result dict
        stage_data = {}
        for row in result.fetchall():
            stage_id = row.pipeline_stage_id
            if stage_id:
                stage_data[stage_id] = {
                    "count": row.total_count or 0,
                    "positive": row.positive_count or 0,
                    "negative": row.negative_count or 0,
                    "neutral": row.neutral_count or 0,
                    "early_exit_count": row.early_exit_count or 0,
                }

        return stage_data

    async def get_loss_reason_breakdown_by_stage(
        self,
        officer_id: Optional[int] = None,
        unit_ids: Optional[List[int]] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Get loss reason breakdown aggregated by pipeline stage.

        Source: Consultation table (loss_reason now stored directly on consultation).
        Deduped by (lead_id, stage_id) — latest consultation per lead/stage wins.

        Returns:
            Dict[stage_id, [
                {"reason_code": "PRICE_HIGH", "count": 10, "percentage": 25.0},
                ...
            ]]
        """
        from sqlalchemy.orm import aliased

        # Subquery: latest consultation with loss_reason per (lead_id, stage_id)
        # Using consultation_status -> stage_id for stage grouping.
        # row_number() avoids duplicate matches when multiple consultations share the same timestamp.
        ConsultationStatus = aliased(models.ConsultationStatus)

        conditions = [
            models.Consultation.loss_reason_code.isnot(None),
            models.Consultation.deleted_at.is_(None),
            models.Lead.deleted_at.is_(None),
        ]

        if officer_id:
            conditions.append(models.Lead.assigned_officer_id == officer_id)
        elif unit_ids:
            conditions.append(models.Lead.unit_id.in_(unit_ids))

        if start_date:
            conditions.append(func.date(models.Consultation.consultation_date) >= start_date)
        if end_date:
            conditions.append(func.date(models.Consultation.consultation_date) <= end_date)

        ranked_subq = (
            select(
                models.Consultation.id.label("consultation_id"),
                models.Consultation.lead_id,
                ConsultationStatus.stage_id,
                models.Consultation.loss_reason_code.label("loss_reason_code"),
                func.row_number().over(
                    partition_by=(models.Consultation.lead_id, ConsultationStatus.stage_id),
                    order_by=(
                        models.Consultation.consultation_date.desc(),
                        models.Consultation.id.desc(),
                    ),
                ).label("row_num"),
            )
            .join(models.Lead, models.Consultation.lead_id == models.Lead.id)
            .join(ConsultationStatus, models.Consultation.consultation_status_id == ConsultationStatus.id)
            .where(*conditions)
            .subquery()
        )

        query = (
            select(
                ranked_subq.c.stage_id,
                ranked_subq.c.loss_reason_code,
                func.count().label("count"),
            )
            .where(ranked_subq.c.row_num == 1)
            .group_by(ranked_subq.c.stage_id, ranked_subq.c.loss_reason_code)
            .order_by(ranked_subq.c.stage_id, func.count().desc())
        )

        result = await self.db.execute(query)
        rows = result.fetchall()

        # Build stage -> loss breakdown dict
        stage_breakdown: Dict[str, List[Dict[str, Any]]] = {}
        stage_totals: Dict[str, int] = {}

        for row in rows:
            stage_id = row.stage_id
            if stage_id:
                stage_totals[stage_id] = stage_totals.get(stage_id, 0) + row.count

        for row in rows:
            stage_id = row.stage_id
            if stage_id:
                if stage_id not in stage_breakdown:
                    stage_breakdown[stage_id] = []

                total = stage_totals.get(stage_id, 1)
                percentage = round((row.count / total) * 100, 1) if total > 0 else 0.0

                stage_breakdown[stage_id].append({
                    "reason_code": row.loss_reason_code,
                    "count": row.count,
                    "percentage": percentage,
                })

        return stage_breakdown

    async def get_stage_velocity_stats(
        self,
        officer_id: Optional[int] = None,
        unit_ids: Optional[List[int]] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> Dict[str, Dict[str, Any]]:
        """
        Calculate average time spent in each pipeline stage.

        SPEC: FUNNEL_FEASIBILITY_ANALYSIS.md - Velocity / Time in Stage

        Uses LeadStatusHistory to calculate time between stage transitions.
        For each stage, calculates:
        - avg_days: Average days spent in stage before moving to next
        - median_days: Median days (approximated)
        - min_days: Minimum days
        - max_days: Maximum days
        - sample_size: Number of transitions measured

        Returns:
            Dict[stage_id, {
                "avg_days": 2.5,
                "min_days": 0.5,
                "max_days": 7.0,
                "sample_size": 45
            }]
        """
        # Build base conditions
        conditions = [
            models.LeadStatusHistory.old_pipeline_stage_id.isnot(None),
            models.LeadStatusHistory.new_pipeline_stage_id.isnot(None),
            models.LeadStatusHistory.old_pipeline_stage_id != models.LeadStatusHistory.new_pipeline_stage_id,
            models.Lead.deleted_at.is_(None),
        ]

        # Filter by officer or units
        if officer_id:
            conditions.append(models.Lead.assigned_officer_id == officer_id)
        elif unit_ids:
            conditions.append(models.Lead.unit_id.in_(unit_ids))

        # Optional date filter
        if start_date:
            conditions.append(func.date(models.LeadStatusHistory.changed_at) >= start_date)
        if end_date:
            conditions.append(func.date(models.LeadStatusHistory.changed_at) <= end_date)

        # Subquery: Get each transition with time to next transition
        # Using a self-join approach to find "next transition" for each lead
        # This calculates time_in_stage = next_changed_at - changed_at

        # Step 1: Get all stage transitions with their timestamps
        history_alias = models.LeadStatusHistory.__table__.alias("h2")

        # Query to get stage durations by finding the next transition for each entry
        # We use a correlated subquery to find the minimum changed_at that is > current changed_at
        next_change_subq = (
            select(func.min(history_alias.c.changed_at))
            .where(
                history_alias.c.lead_id == models.LeadStatusHistory.lead_id,
                history_alias.c.changed_at > models.LeadStatusHistory.changed_at,
            )
            .correlate(models.LeadStatusHistory)
            .scalar_subquery()
        )

        # Main query: Calculate duration in days for each transition
        # duration = (next_changed_at - changed_at) in days
        duration_expr = func.extract(
            'epoch',
            next_change_subq - models.LeadStatusHistory.changed_at
        ) / 86400.0  # Convert seconds to days

        query = (
            select(
                models.LeadStatusHistory.old_pipeline_stage_id.label("stage_id"),
                func.avg(duration_expr).label("avg_days"),
                func.min(duration_expr).label("min_days"),
                func.max(duration_expr).label("max_days"),
                func.count().label("sample_size"),
            )
            .join(models.Lead, models.LeadStatusHistory.lead_id == models.Lead.id)
            .where(
                *conditions,
                next_change_subq.isnot(None),  # Only count transitions that have a "next" transition
            )
            .group_by(models.LeadStatusHistory.old_pipeline_stage_id)
        )

        result = await self.db.execute(query)
        rows = result.fetchall()

        # Build result dict
        velocity_stats: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            stage_id = row.stage_id
            if stage_id:
                avg_days = float(row.avg_days) if row.avg_days else 0.0
                min_days = float(row.min_days) if row.min_days else 0.0
                max_days = float(row.max_days) if row.max_days else 0.0

                velocity_stats[stage_id] = {
                    "avg_days": round(avg_days, 2),
                    "min_days": round(min_days, 2),
                    "max_days": round(max_days, 2),
                    "sample_size": row.sample_size or 0,
                }

        return velocity_stats

    async def get_estimated_lost_revenue_by_stage(
        self,
        officer_id: Optional[int] = None,
        unit_ids: Optional[List[int]] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        academic_year: Optional[int] = None,
    ) -> Dict[str, Dict[str, Any]]:
        """
        Calculate estimated lost revenue per pipeline stage.

        SPEC: FUNNEL_FEASIBILITY_ANALYSIS.md - Estimated Lost Revenue

        For each stage, calculates revenue from leads that dropped out (negative outcome).
        Uses tuition_fee_per_year from OfferingAcademicInfo based on Lead's offering_id.

        Formula: lost_revenue = COUNT(lost_leads) * AVG(tuition_fee_per_year)

        Args:
            officer_id: Filter by specific officer
            unit_ids: Filter by unit IDs (if officer_id not provided)
            start_date: Filter leads created after this date
            end_date: Filter leads created before this date
            academic_year: Specific academic year for tuition lookup (default: current year)

        Returns:
            Dict[stage_id, {
                "lost_leads_count": 10,
                "avg_tuition": 15000000.0,
                "total_lost_revenue": 150000000.0,
                "leads_with_tuition": 8  # leads that have offering with tuition data
            }]
        """
        from datetime import datetime as dt

        # Default to current academic year if not specified
        if academic_year is None:
            academic_year = dt.now().year

        # Build base conditions
        conditions = [
            models.Lead.deleted_at.is_(None),
            models.Lead.pipeline_stage_id.isnot(None),
            # Filter for negative outcomes (lost leads)
            models.ConsultationStatus.outcome_type == "negative",
            models.ConsultationStatus.is_final == True,
        ]

        # Filter by officer or units
        if officer_id:
            conditions.append(models.Lead.assigned_officer_id == officer_id)
        elif unit_ids:
            conditions.append(models.Lead.unit_id.in_(unit_ids))

        # Optional date filter
        if start_date:
            conditions.append(func.date(models.Lead.created_at) >= start_date)
        if end_date:
            conditions.append(func.date(models.Lead.created_at) <= end_date)

        # Query: Group lost leads by stage with tuition info
        # JOIN: Lead -> ProgramOffering -> OfferingAcademicInfo
        query = (
            select(
                models.Lead.pipeline_stage_id.label("stage_id"),
                func.count(models.Lead.id).label("lost_leads_count"),
                func.avg(models.OfferingAcademicInfo.tuition_fee_per_year).label("avg_tuition"),
                func.sum(models.OfferingAcademicInfo.tuition_fee_per_year).label("total_lost_revenue"),
                func.count(models.OfferingAcademicInfo.tuition_fee_per_year).label("leads_with_tuition"),
            )
            .join(
                models.ConsultationStatus,
                models.Lead.consultation_status_id == models.ConsultationStatus.id
            )
            .outerjoin(
                models.ProgramOffering,
                models.Lead.offering_id == models.ProgramOffering.id
            )
            .outerjoin(
                models.OfferingAcademicInfo,
                and_(
                    models.OfferingAcademicInfo.offering_id == models.ProgramOffering.id,
                    models.OfferingAcademicInfo.academic_year == academic_year,
                    models.OfferingAcademicInfo.is_published == True,
                    models.OfferingAcademicInfo.is_deleted == False,
                )
            )
            .where(*conditions)
            .group_by(models.Lead.pipeline_stage_id)
        )

        result = await self.db.execute(query)
        rows = result.fetchall()

        # Build result dict
        revenue_stats: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            stage_id = row.stage_id
            if stage_id:
                avg_tuition = float(row.avg_tuition) if row.avg_tuition else 0.0
                total_revenue = float(row.total_lost_revenue) if row.total_lost_revenue else 0.0

                revenue_stats[stage_id] = {
                    "lost_leads_count": row.lost_leads_count or 0,
                    "avg_tuition": round(avg_tuition, 0),
                    "total_lost_revenue": round(total_revenue, 0),
                    "leads_with_tuition": row.leads_with_tuition or 0,
                }

        return revenue_stats

    async def get_stage_transition_rates(
        self,
        officer_id: int,
        days: int = 30,
        start_date: date = None,
        end_date: date = None,
    ) -> Dict[str, Dict[str, int]]:
        """
        Get transition counts between stages for conversion rate calculation.

        Returns:
            Dict[from_stage_id, Dict[to_stage_id, count]]
        """
        if start_date and end_date:
            since_date = datetime(start_date.year, start_date.month, start_date.day, tzinfo=timezone.utc)
            until_date = datetime(end_date.year, end_date.month, end_date.day, 23, 59, 59, tzinfo=timezone.utc)
        else:
            since_date = datetime.now(timezone.utc) - timedelta(days=days)
            until_date = None

        query = (
            select(
                models.LeadStatusHistory.old_pipeline_stage_id,
                models.LeadStatusHistory.new_pipeline_stage_id,
                func.count().label("transition_count")
            )
            .join(models.Lead, models.LeadStatusHistory.lead_id == models.Lead.id)
            .where(
                models.Lead.assigned_officer_id == officer_id,
                models.LeadStatusHistory.changed_at >= since_date,
                models.LeadStatusHistory.old_pipeline_stage_id.isnot(None),
                models.LeadStatusHistory.new_pipeline_stage_id.isnot(None),
                models.LeadStatusHistory.old_pipeline_stage_id != models.LeadStatusHistory.new_pipeline_stage_id,
                models.Lead.deleted_at.is_(None)
            )
            .group_by(
                models.LeadStatusHistory.old_pipeline_stage_id,
                models.LeadStatusHistory.new_pipeline_stage_id
            )
        )

        if until_date:
            query = query.where(models.LeadStatusHistory.changed_at <= until_date)

        result = await self.db.execute(query)
        
        transition_map: Dict[str, Dict[str, int]] = {}
        for row in result.fetchall():
            from_stage = row.old_pipeline_stage_id
            to_stage = row.new_pipeline_stage_id
            count = row.transition_count
            
            if from_stage not in transition_map:
                transition_map[from_stage] = {}
            transition_map[from_stage][to_stage] = count
        
        return transition_map
    
    # =========================================================================
    # OPTIMIZED: Performance Trends (was 21 queries → 1)
    # =========================================================================
    
    async def get_performance_trends_batch(
        self,
        officer_id: int,
        start_date: date,
        end_date: date,
    ) -> Dict[str, TrendPoint]:
        """
        Get performance trends (assigned, consultations, converted) per day.
        
        OPTIMIZATION: Single query with UNION ALL instead of 3 queries × N days.
        Before: 21 queries (7 days × 3 metrics)
        After: 3 queries (one per metric type, grouped by date)
        
        Returns:
            Dict[date_str, TrendPoint]
        """
        trends: Dict[str, TrendPoint] = {}
        
        # Initialize all days with zero values
        current = start_date
        while current <= end_date:
            date_str = current.isoformat()
            trends[date_str] = TrendPoint(date=date_str)
            current += timedelta(days=1)
        
        # Query 1: Assignments per day
        assigned_query = (
            select(
                func.date(models.AssignmentLog.timestamp).label("day"),
                func.count(func.distinct(models.AssignmentLog.lead_id)).label("count")
            )
            .join(models.Lead, models.AssignmentLog.lead_id == models.Lead.id)
            .where(
                models.AssignmentLog.officer_id == officer_id,
                func.date(models.AssignmentLog.timestamp) >= start_date,
                func.date(models.AssignmentLog.timestamp) <= end_date,
                models.Lead.deleted_at.is_(None)
            )
            .group_by(func.date(models.AssignmentLog.timestamp))
        )
        assigned_result = await self.db.execute(assigned_query)
        for row in assigned_result.fetchall():
            date_str = str(row.day)
            if date_str in trends:
                trends[date_str].assigned = row.count
        
        # Query 2: Consultations per day (exclude soft-deleted)
        consult_query = (
            select(
                func.date(models.Consultation.consultation_date).label("day"),
                func.count(func.distinct(models.Consultation.lead_id)).label("count")
            )
            .join(models.Lead, models.Consultation.lead_id == models.Lead.id)
            .where(
                models.Consultation.officer_id == officer_id,
                func.date(models.Consultation.consultation_date) >= start_date,
                func.date(models.Consultation.consultation_date) <= end_date,
                models.Lead.deleted_at.is_(None),
                models.Consultation.deleted_at.is_(None),  # Exclude soft-deleted consultations
            )
            .group_by(func.date(models.Consultation.consultation_date))
        )
        consult_result = await self.db.execute(consult_query)
        for row in consult_result.fetchall():
            date_str = str(row.day)
            if date_str in trends:
                trends[date_str].consultations = row.count
        
        # Query 3: Final outcomes per day — split enrolled (positive) vs lost (negative)
        outcomes_query = (
            select(
                func.date(models.LeadStatusHistory.changed_at).label("day"),
                func.count(func.distinct(case(
                    (models.ConsultationStatus.outcome_type == "positive", models.LeadStatusHistory.lead_id),
                ))).label("enrolled_count"),
                func.count(func.distinct(case(
                    (models.ConsultationStatus.outcome_type == "negative", models.LeadStatusHistory.lead_id),
                ))).label("lost_count"),
            )
            .join(models.Lead, models.LeadStatusHistory.lead_id == models.Lead.id)
            .join(models.ConsultationStatus,
                  models.LeadStatusHistory.new_consultation_status_id == models.ConsultationStatus.id)
            .where(
                models.Lead.assigned_officer_id == officer_id,
                func.date(models.LeadStatusHistory.changed_at) >= start_date,
                func.date(models.LeadStatusHistory.changed_at) <= end_date,
                models.ConsultationStatus.is_final == True,
                models.Lead.deleted_at.is_(None),
            )
            .group_by(func.date(models.LeadStatusHistory.changed_at))
        )
        outcomes_result = await self.db.execute(outcomes_query)
        for row in outcomes_result.fetchall():
            date_str = str(row.day)
            if date_str in trends:
                trends[date_str].enrolled = row.enrolled_count or 0
                trends[date_str].lost = row.lost_count or 0
                trends[date_str].converted = (row.enrolled_count or 0) + (row.lost_count or 0)

        return trends

    async def get_performance_trends_batch_multi(
        self,
        officer_ids: List[int],
        start_date: date,
        end_date: date,
    ) -> Dict[str, "TrendPoint"]:
        """
        Get aggregated performance trends across multiple officers.

        Same structure as get_performance_trends_batch but filters by
        officer_ids list instead of single officer_id.
        Counts unique leads per day (deduped across officers).
        """
        trends: Dict[str, TrendPoint] = {}

        current = start_date
        while current <= end_date:
            date_str = current.isoformat()
            trends[date_str] = TrendPoint(date=date_str)
            current += timedelta(days=1)

        if not officer_ids:
            return trends

        # Query 1: Assignments per day
        assigned_query = (
            select(
                func.date(models.AssignmentLog.timestamp).label("day"),
                func.count(func.distinct(models.AssignmentLog.lead_id)).label("count"),
            )
            .join(models.Lead, models.AssignmentLog.lead_id == models.Lead.id)
            .where(
                models.AssignmentLog.officer_id.in_(officer_ids),
                func.date(models.AssignmentLog.timestamp) >= start_date,
                func.date(models.AssignmentLog.timestamp) <= end_date,
                models.Lead.deleted_at.is_(None),
            )
            .group_by(func.date(models.AssignmentLog.timestamp))
        )
        assigned_result = await self.db.execute(assigned_query)
        for row in assigned_result.fetchall():
            date_str = str(row.day)
            if date_str in trends:
                trends[date_str].assigned = row.count

        # Query 2: Consultations per day
        consult_query = (
            select(
                func.date(models.Consultation.consultation_date).label("day"),
                func.count(func.distinct(models.Consultation.lead_id)).label("count"),
            )
            .join(models.Lead, models.Consultation.lead_id == models.Lead.id)
            .where(
                models.Consultation.officer_id.in_(officer_ids),
                func.date(models.Consultation.consultation_date) >= start_date,
                func.date(models.Consultation.consultation_date) <= end_date,
                models.Lead.deleted_at.is_(None),
                models.Consultation.deleted_at.is_(None),
            )
            .group_by(func.date(models.Consultation.consultation_date))
        )
        consult_result = await self.db.execute(consult_query)
        for row in consult_result.fetchall():
            date_str = str(row.day)
            if date_str in trends:
                trends[date_str].consultations = row.count

        # Query 3: Final outcomes per day — split enrolled (positive) vs lost (negative)
        outcomes_query = (
            select(
                func.date(models.LeadStatusHistory.changed_at).label("day"),
                func.count(func.distinct(case(
                    (models.ConsultationStatus.outcome_type == "positive", models.LeadStatusHistory.lead_id),
                ))).label("enrolled_count"),
                func.count(func.distinct(case(
                    (models.ConsultationStatus.outcome_type == "negative", models.LeadStatusHistory.lead_id),
                ))).label("lost_count"),
            )
            .join(models.Lead, models.LeadStatusHistory.lead_id == models.Lead.id)
            .join(models.ConsultationStatus,
                  models.LeadStatusHistory.new_consultation_status_id == models.ConsultationStatus.id)
            .where(
                models.Lead.assigned_officer_id.in_(officer_ids),
                func.date(models.LeadStatusHistory.changed_at) >= start_date,
                func.date(models.LeadStatusHistory.changed_at) <= end_date,
                models.ConsultationStatus.is_final == True,
                models.Lead.deleted_at.is_(None),
            )
            .group_by(func.date(models.LeadStatusHistory.changed_at))
        )
        outcomes_result = await self.db.execute(outcomes_query)
        for row in outcomes_result.fetchall():
            date_str = str(row.day)
            if date_str in trends:
                trends[date_str].enrolled = row.enrolled_count or 0
                trends[date_str].lost = row.lost_count or 0
                trends[date_str].converted = (row.enrolled_count or 0) + (row.lost_count or 0)

        return trends

    # =========================================================================
    # OPTIMIZED: KPI Stats (was 5 queries → 1 CTE-like approach)
    # =========================================================================
    
    async def get_kpi_stats(
        self,
        officer_id: int,
        start_date: date,
        end_date: date,
    ) -> Dict[str, Any]:
        """
        Get KPI statistics in minimal queries.
        
        Returns dict with:
        - consultations_in_range
        - consultations_today
        - active_leads
        - converted_count
        - total_leads
        """
        # P1 fix: use Asia/Ho_Chi_Minh for today boundary (spec §15.3)
        from zoneinfo import ZoneInfo
        VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
        now_vn = datetime.now(VN_TZ)
        today_start = now_vn.replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + timedelta(days=1)

        # Query 1: Consultations (range + today in one query with conditional)
        # D5: filter method IS DISTINCT FROM 'system' (NULL-safe)
        # today_count uses VN timezone range [day_start, day_end) instead of DATE()
        consult_query = (
            select(
                func.count(models.Consultation.id).label("range_count"),
                func.count(
                    case((and_(
                        models.Consultation.consultation_date >= today_start,
                        models.Consultation.consultation_date < today_end,
                    ), 1))
                ).label("today_count"),
            )
            .join(models.Lead, models.Consultation.lead_id == models.Lead.id)
            .where(
                models.Consultation.officer_id == officer_id,
                func.date(models.Consultation.consultation_date) >= start_date,
                func.date(models.Consultation.consultation_date) <= end_date,
                models.Lead.deleted_at.is_(None),
                models.Consultation.deleted_at.is_(None),
                models.Consultation.method.is_distinct_from("system"),
            )
        )
        consult_result = await self.db.execute(consult_query)
        consult_row = consult_result.fetchone()
        consultations_in_range = consult_row.range_count or 0
        consultations_today = consult_row.today_count or 0
        
        # Query 2: Lead stats (active + converted + total in one query)
        lead_query = (
            select(
                func.count(models.Lead.id).label("total"),
                func.count(
                    case((
                        and_(
                            or_(
                                models.ConsultationStatus.is_final == False,
                                models.ConsultationStatus.is_final.is_(None)
                            )
                        ), 1
                    ))
                ).label("active"),
                func.count(
                    case((
                        and_(
                            models.ConsultationStatus.is_final == True,
                            models.ConsultationStatus.outcome_type == "positive"
                        ), 1
                    ))
                ).label("converted"),
            )
            .outerjoin(
                models.ConsultationStatus,
                models.Lead.consultation_status_id == models.ConsultationStatus.id
            )
            .where(
                models.Lead.assigned_officer_id == officer_id,
                func.date(models.Lead.created_at) >= start_date,
                func.date(models.Lead.created_at) <= end_date,
                models.Lead.deleted_at.is_(None)
            )
        )
        lead_result = await self.db.execute(lead_query)
        lead_row = lead_result.fetchone()

        # Query 3: Realtime active leads (no date range — snapshot workload)
        realtime_active_query = (
            select(func.count(models.Lead.id))
            .outerjoin(
                models.ConsultationStatus,
                models.Lead.consultation_status_id == models.ConsultationStatus.id
            )
            .where(
                models.Lead.assigned_officer_id == officer_id,
                models.Lead.deleted_at.is_(None),
                or_(
                    models.ConsultationStatus.is_final == False,
                    models.ConsultationStatus.is_final.is_(None),
                ),
            )
        )
        realtime_result = await self.db.execute(realtime_active_query)
        active_leads_realtime = realtime_result.scalar() or 0

        return {
            "consultations_in_range": consultations_in_range,
            "consultations_today": consultations_today,
            "active_leads": active_leads_realtime,
            "active_leads_in_period": lead_row.active or 0,
            "converted_count": lead_row.converted or 0,
            "total_leads": lead_row.total or 0,
        }
    
    # =========================================================================
    # Activity-based Win Rate (from LeadStatusHistory)
    # =========================================================================

    async def get_win_rate_stats(
        self,
        officer_id: int,
        start_date: date,
        end_date: date,
    ) -> Dict[str, Any]:
        """
        Activity-based Win Rate: last transition per lead in date range.

        Uses DISTINCT ON(lead_id) + ORDER BY changed_at DESC to get exactly
        one row per lead (the most recent transition in the period).
        Only counts Win/Lost if that latest transition is to a final status.

        Edge cases handled:
        - Lead reopened (final→non-final): not counted
        - Lead transitions negative→positive in period: only latest counts
        """
        latest_transitions = (
            select(
                models.LeadStatusHistory.lead_id,
                models.ConsultationStatus.outcome_type,
                models.ConsultationStatus.is_final,
            )
            .distinct(models.LeadStatusHistory.lead_id)
            .join(
                models.ConsultationStatus,
                models.LeadStatusHistory.new_consultation_status_id == models.ConsultationStatus.id,
            )
            .join(
                models.Lead,
                models.LeadStatusHistory.lead_id == models.Lead.id,
            )
            .where(
                models.Lead.assigned_officer_id == officer_id,
                func.date(models.LeadStatusHistory.changed_at) >= start_date,
                func.date(models.LeadStatusHistory.changed_at) <= end_date,
                models.Lead.deleted_at.is_(None),
                models.LeadStatusHistory.new_consultation_status_id.isnot(None),
            )
            .order_by(
                models.LeadStatusHistory.lead_id,
                models.LeadStatusHistory.changed_at.desc(),
            )
        )

        result = await self.db.execute(latest_transitions)
        rows = result.fetchall()

        won = sum(1 for r in rows if r.is_final and r.outcome_type == "positive")
        lost = sum(1 for r in rows if r.is_final and r.outcome_type == "negative")
        total_closed = won + lost

        return {
            "won": won,
            "lost": lost,
            "total_closed": total_closed,
            "win_rate": round((won / total_closed) * 100, 1) if total_closed > 0 else 0.0,
        }

    async def get_aggregated_win_rate_stats(
        self,
        officer_ids: List[int],
        start_date: date,
        end_date: date,
    ) -> Dict[str, Any]:
        """
        Aggregated Win Rate for multiple officers.
        Same DISTINCT ON logic as get_win_rate_stats but filters by officer_ids list.
        """
        if not officer_ids:
            return {"won": 0, "lost": 0, "total_closed": 0, "win_rate": 0.0}

        latest_transitions = (
            select(
                models.LeadStatusHistory.lead_id,
                models.ConsultationStatus.outcome_type,
                models.ConsultationStatus.is_final,
            )
            .distinct(models.LeadStatusHistory.lead_id)
            .join(
                models.ConsultationStatus,
                models.LeadStatusHistory.new_consultation_status_id == models.ConsultationStatus.id,
            )
            .join(
                models.Lead,
                models.LeadStatusHistory.lead_id == models.Lead.id,
            )
            .where(
                models.Lead.assigned_officer_id.in_(officer_ids),
                func.date(models.LeadStatusHistory.changed_at) >= start_date,
                func.date(models.LeadStatusHistory.changed_at) <= end_date,
                models.Lead.deleted_at.is_(None),
                models.LeadStatusHistory.new_consultation_status_id.isnot(None),
            )
            .order_by(
                models.LeadStatusHistory.lead_id,
                models.LeadStatusHistory.changed_at.desc(),
            )
        )

        result = await self.db.execute(latest_transitions)
        rows = result.fetchall()

        won = sum(1 for r in rows if r.is_final and r.outcome_type == "positive")
        lost = sum(1 for r in rows if r.is_final and r.outcome_type == "negative")
        total_closed = won + lost

        return {
            "won": won,
            "lost": lost,
            "total_closed": total_closed,
            "win_rate": round((won / total_closed) * 100, 1) if total_closed > 0 else 0.0,
        }

    # =========================================================================
    # Actionable Leads
    # =========================================================================

    async def get_high_score_leads(
        self,
        officer_id: int,
        limit: int = 5,
    ) -> List[models.Lead]:
        """Get top leads by score that are not in final status."""
        query = (
            select(models.Lead)
            .options(selectinload(models.Lead.pipeline_stage))
            .outerjoin(
                models.ConsultationStatus,
                models.Lead.consultation_status_id == models.ConsultationStatus.id
            )
            .where(
                models.Lead.assigned_officer_id == officer_id,
                models.Lead.deleted_at.is_(None),
                or_(
                    models.ConsultationStatus.is_final == False,
                    models.ConsultationStatus.is_final.is_(None)
                )
            )
            .order_by(models.Lead.lead_score.desc().nulls_last())
            .limit(limit)
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())
    
    async def get_stale_leads(
        self,
        officer_id: int,
        stale_days: int = 3,
        limit: int = 5,
    ) -> List[models.Lead]:
        """Get leads not updated in N days (stale leads)."""
        stale_threshold = datetime.now(timezone.utc) - timedelta(days=stale_days)
        
        query = (
            select(models.Lead)
            .options(selectinload(models.Lead.pipeline_stage))
            .outerjoin(
                models.ConsultationStatus,
                models.Lead.consultation_status_id == models.ConsultationStatus.id
            )
            .where(
                models.Lead.assigned_officer_id == officer_id,
                models.Lead.deleted_at.is_(None),
                models.Lead.updated_at < stale_threshold,
                or_(
                    models.ConsultationStatus.is_final == False,
                    models.ConsultationStatus.is_final.is_(None)
                )
            )
            .order_by(models.Lead.updated_at.asc())
            .limit(limit)
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())
    
    async def get_priority_leads_for_actions(
        self,
        officer_id: int,
        limit: int = 10,
    ) -> List[models.Lead]:
        """
        Get leads for priority action calculation.
        
        Includes: hot leads, overdue, needs follow-up.
        """
        query = (
            select(models.Lead)
            .options(
                selectinload(models.Lead.pipeline_stage),
                selectinload(models.Lead.consultation_status),
            )
            .outerjoin(
                models.ConsultationStatus,
                models.Lead.consultation_status_id == models.ConsultationStatus.id
            )
            .where(
                models.Lead.assigned_officer_id == officer_id,
                models.Lead.deleted_at.is_(None),
                or_(
                    models.ConsultationStatus.is_final == False,
                    models.ConsultationStatus.is_final.is_(None)
                )
            )
            .order_by(
                models.Lead.lead_score.desc().nulls_last(),
                models.Lead.updated_at.asc()
            )
            .limit(limit * 2)  # Get more to allow filtering
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_upcoming_activities(
        self,
        officer_id: int,
        start_of_month: datetime,
        end_of_month: datetime,
    ) -> List[models.Lead]:
        """
        Get leads with next_activity_at within the given date range.
        
        Used for calendar/activity planning views.
        """
        query = (
            select(models.Lead)
            .where(
                models.Lead.assigned_officer_id == officer_id,
                models.Lead.next_activity_at.isnot(None),
                models.Lead.next_activity_at >= start_of_month,
                models.Lead.next_activity_at < end_of_month,
                models.Lead.deleted_at.is_(None),
            )
            .order_by(models.Lead.next_activity_at.asc())
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_upcoming_activities_multi(
        self,
        officer_ids: List[int],
        start_of_month: datetime,
        end_of_month: datetime,
    ) -> List[models.Lead]:
        """Get leads with next_activity_at for multiple officers (team/org scope)."""
        if not officer_ids:
            return []
        query = (
            select(models.Lead)
            .where(
                models.Lead.assigned_officer_id.in_(officer_ids),
                models.Lead.next_activity_at.isnot(None),
                models.Lead.next_activity_at >= start_of_month,
                models.Lead.next_activity_at < end_of_month,
                models.Lead.deleted_at.is_(None),
            )
            .order_by(models.Lead.next_activity_at.asc())
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())

    # =========================================================================
    # Leaderboard
    # =========================================================================
    
    async def get_weekly_consultation_rankings(
        self,
        week_start: date,
        week_end: date,
        limit: int = 10,
    ) -> List[Tuple[int, str, str, int]]:
        """
        Get top officers by consultation count for a week.
        
        Returns list of (user_id, username, full_name, consultation_count)
        """
        query = (
            select(
                models.User.id,
                models.User.username,
                models.User.full_name,
                func.count(models.Consultation.id).label("count")
            )
            .join(models.Consultation, models.Consultation.officer_id == models.User.id)
            .where(
                models.User.role == UserRole.OFFICER,
                models.User.status == "active",
                func.date(models.Consultation.consultation_date) >= week_start,
                func.date(models.Consultation.consultation_date) <= week_end,
                models.Consultation.deleted_at.is_(None),  # Exclude soft-deleted
            )
            .group_by(models.User.id, models.User.username, models.User.full_name)
            .order_by(func.count(models.Consultation.id).desc())
            .limit(limit)
        )
        result = await self.db.execute(query)
        return result.fetchall()
    
    async def get_officer_rank(
        self,
        officer_id: int,
        week_start: date,
        week_end: date,
    ) -> int:
        """Get officer's rank based on consultation count."""
        # Subquery to count consultations per officer (exclude soft-deleted)
        subq = (
            select(
                models.Consultation.officer_id,
                func.count(models.Consultation.id).label("count")
            )
            .where(
                func.date(models.Consultation.consultation_date) >= week_start,
                func.date(models.Consultation.consultation_date) <= week_end,
                models.Consultation.deleted_at.is_(None),  # Exclude soft-deleted
            )
            .group_by(models.Consultation.officer_id)
        ).subquery()

        # Count how many have more consultations (exclude soft-deleted)
        my_count_query = (
            select(func.count(models.Consultation.id))
            .where(
                models.Consultation.officer_id == officer_id,
                func.date(models.Consultation.consultation_date) >= week_start,
                func.date(models.Consultation.consultation_date) <= week_end,
                models.Consultation.deleted_at.is_(None),  # Exclude soft-deleted
            )
        )
        my_count = (await self.db.execute(my_count_query)).scalar() or 0
        
        higher_query = (
            select(func.count())
            .select_from(subq)
            .where(subq.c.count > my_count)
        )
        higher_count = (await self.db.execute(higher_query)).scalar() or 0
        
        return higher_count + 1  # Rank is 1-indexed
    
    # =========================================================================
    # Team Stats
    # =========================================================================
    
    async def get_team_averages(
        self,
        unit_id: Optional[int],
        start_date: date,
        end_date: date,
        officer_ids: Optional[List[int]] = None,
    ) -> Dict[str, float]:
        """
        Get team average consultations and conversions.
        
        Args:
            unit_id: Filter by unit (None = all officers)
            start_date: Start date for calculation
            end_date: End date for calculation
            officer_ids: Pre-resolved officer IDs for subtree/aggregated scope
        """
        # Calculate number of days for averaging
        days = (end_date - start_date).days + 1
        if days < 1: days = 1
        
        # Build conditions for officers
        conditions = [
            models.User.role == UserRole.OFFICER,
            models.User.status == "active",
        ]
        if officer_ids is not None:
            if not officer_ids:
                return {
                    "team_avg_consultations": 0.0,
                    "total_officers": 0,
                }
            conditions.append(models.User.id.in_(officer_ids))
        elif unit_id:
            conditions.append(models.User.unit_id == unit_id)
        
        # Count officers
        officer_count_query = select(func.count(models.User.id)).where(*conditions)
        officer_count = (await self.db.execute(officer_count_query)).scalar() or 1
        
        # Total consultations
        # JOIN with Lead to filter soft-deleted leads and consultations
        consult_conditions = [
            func.date(models.Consultation.consultation_date) >= start_date,
            func.date(models.Consultation.consultation_date) <= end_date,
            models.Lead.deleted_at.is_(None),  # Exclude consultations of deleted leads
            models.Consultation.deleted_at.is_(None),  # Exclude soft-deleted consultations
        ]
        
        # Ensure numerator and denominator use the exact same officer set.
        consult_conditions.append(
            models.Consultation.officer_id.in_(
                select(models.User.id).where(*conditions)
            )
        )
        
        consult_query = (
            select(func.count(models.Consultation.id))
            .join(models.Lead, models.Consultation.lead_id == models.Lead.id)
            .where(*consult_conditions)
        )
        total_consultations = (await self.db.execute(consult_query)).scalar() or 0
        
        avg_consultations = total_consultations / officer_count / days if officer_count > 0 else 0
        
        return {
            "team_avg_consultations": round(avg_consultations, 2),
            "total_officers": officer_count,
        }
    
    # =========================================================================
    # Base abstract implementation
    # =========================================================================
    
    async def get_filtered(
        self,
        skip: int = 0,
        limit: int = 100,
        **filters
    ) -> Tuple[int, List[models.User]]:
        """Get filtered officers (delegates to UserRepository for complex queries)."""
        # Simple implementation for officer queries
        query = (
            select(models.User)
            .where(models.User.role == UserRole.OFFICER)
            .offset(skip)
            .limit(limit)
        )
        result = await self.db.execute(query)
        officers = list(result.scalars().all())
        
        count_query = (
            select(func.count(models.User.id))
            .where(models.User.role == UserRole.OFFICER)
        )
        total = (await self.db.execute(count_query)).scalar() or 0
        
        return total, officers

    # =========================================================================
    # Aggregated Dashboard (for Manager/Admin views)
    # =========================================================================

    async def get_active_officer_ids(
        self,
        scope: str = "organization",
        unit_id: Optional[int] = None,
    ) -> List[int]:
        """
        Get list of active officer IDs based on scope.

        Args:
            scope: "unit" or "organization"
            unit_id: Filter by unit ID (required for unit scope)

        Returns:
            List of officer user IDs
        """
        conditions = [
            models.User.role == UserRole.OFFICER,
            models.User.status == "active",
        ]
        
        if unit_id:
            conditions.append(models.User.unit_id == unit_id)
        
        query = select(models.User.id).where(*conditions)
        result = await self.db.execute(query)
        return [row[0] for row in result.fetchall()]

    async def get_officers_total_capacity(self, officer_ids: List[int]) -> int:
        """Sum actual max_capacity for given officers. NULL defaults to 100."""
        if not officer_ids:
            return 0
        result = await self.db.execute(
            select(func.coalesce(func.sum(func.coalesce(models.User.max_capacity, 100)), 0))
            .where(models.User.id.in_(officer_ids))
        )
        return result.scalar() or 0

    async def get_aggregated_kpis(
        self,
        officer_ids: List[int],
        start_date: date,
        end_date: date,
    ) -> Dict[str, Any]:
        """
        Get aggregated KPIs for multiple officers.

        OPTIMIZATION: Single batch query instead of N queries per officer.

        Returns:
            Dict with total_consultations, today_consultations, active_leads,
            converted_count, total_leads
        """
        # Mirror personal-path semantics (get_kpi_stats L828-856):
        # - VN timezone for today boundary
        # - Exclude method='system' (NULL-safe)
        from zoneinfo import ZoneInfo
        VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
        now_vn = datetime.now(VN_TZ)
        today_start = now_vn.replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + timedelta(days=1)

        # Query 1: Consultations (batch, exclude soft-deleted + system)
        consult_query = (
            select(
                func.count(models.Consultation.id).label("range_count"),
                func.count(
                    case((and_(
                        models.Consultation.consultation_date >= today_start,
                        models.Consultation.consultation_date < today_end,
                    ), 1))
                ).label("today_count"),
            )
            .join(models.Lead, models.Consultation.lead_id == models.Lead.id)
            .where(
                models.Consultation.officer_id.in_(officer_ids),
                func.date(models.Consultation.consultation_date) >= start_date,
                func.date(models.Consultation.consultation_date) <= end_date,
                models.Lead.deleted_at.is_(None),
                models.Consultation.deleted_at.is_(None),
                models.Consultation.method.is_distinct_from("system"),
            )
        )
        consult_result = await self.db.execute(consult_query)
        consult_row = consult_result.fetchone()
        
        # Query 2: Lead stats (batch with conditional counts)
        lead_query = (
            select(
                func.count(models.Lead.id).label("total"),
                func.count(
                    case((
                        or_(
                            models.ConsultationStatus.is_final == False,
                            models.ConsultationStatus.is_final.is_(None)
                        ), 1
                    ))
                ).label("active"),
                func.count(
                    case((
                        and_(
                            models.ConsultationStatus.is_final == True,
                            models.ConsultationStatus.outcome_type == "positive"
                        ), 1
                    ))
                ).label("converted"),
            )
            .outerjoin(
                models.ConsultationStatus,
                models.Lead.consultation_status_id == models.ConsultationStatus.id
            )
            .where(
                models.Lead.assigned_officer_id.in_(officer_ids),
                func.date(models.Lead.created_at) >= start_date,
                func.date(models.Lead.created_at) <= end_date,
                models.Lead.deleted_at.is_(None)
            )
        )
        lead_result = await self.db.execute(lead_query)
        lead_row = lead_result.fetchone()

        # Query 3: Realtime active leads (no date range — snapshot workload)
        realtime_active_query = (
            select(func.count(models.Lead.id))
            .outerjoin(
                models.ConsultationStatus,
                models.Lead.consultation_status_id == models.ConsultationStatus.id
            )
            .where(
                models.Lead.assigned_officer_id.in_(officer_ids),
                models.Lead.deleted_at.is_(None),
                or_(
                    models.ConsultationStatus.is_final == False,
                    models.ConsultationStatus.is_final.is_(None),
                ),
            )
        )
        realtime_result = await self.db.execute(realtime_active_query)
        active_leads_realtime = realtime_result.scalar() or 0

        return {
            "total_consultations": consult_row.range_count or 0,
            "today_consultations": consult_row.today_count or 0,
            "active_leads": active_leads_realtime,
            "active_leads_in_period": lead_row.active or 0,
            "converted_count": lead_row.converted or 0,
            "total_leads": lead_row.total or 0,
        }

    async def get_aggregated_funnel(
        self,
        officer_ids: List[int],
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get aggregated sales funnel for multiple officers.

        OPTIMIZATION: Single GROUP BY query instead of N queries per stage.

        SPEC COMPLIANCE (2026-02-04):
        - Filter: counts_for_funnel = TRUE (exclude activity logs)
        - Filter: stage_id IS NOT NULL (exclude universal statuses)
        - Early Exit: Counts FINAL leads (negative) at non-final stages
        - Outcome breakdown: positive/negative/neutral counts

        Returns:
            List of funnel stage dicts with counts, early_exit, and outcome breakdown
        """
        # Get all stages
        stages = await self.get_all_pipeline_stages()
        stage_by_id = {s.id: s for s in stages}

        # SPEC: Batch query with counts_for_funnel filter and outcome breakdown
        count_query = (
            select(
                models.Lead.pipeline_stage_id,
                func.count(models.Lead.id).label("total_count"),
                # Outcome breakdown
                func.count(
                    case(
                        (models.ConsultationStatus.outcome_type == "positive", 1),
                    )
                ).label("positive_count"),
                func.count(
                    case(
                        (models.ConsultationStatus.outcome_type == "negative", 1),
                    )
                ).label("negative_count"),
                func.count(
                    case(
                        (models.ConsultationStatus.outcome_type == "neutral", 1),
                    )
                ).label("neutral_count"),
                # SPEC: Early Exit = FINAL leads with negative outcome
                func.count(
                    case(
                        (and_(
                            models.ConsultationStatus.is_final == True,
                            models.ConsultationStatus.outcome_type == "negative",
                        ), 1),
                    )
                ).label("early_exit_count"),
            )
            .join(
                models.ConsultationStatus,
                models.Lead.consultation_status_id == models.ConsultationStatus.id
            )
            .where(
                models.Lead.assigned_officer_id.in_(officer_ids),
                models.Lead.deleted_at.is_(None),
                # SPEC: Exclude universal statuses (stage_id = NULL)
                models.Lead.pipeline_stage_id.isnot(None),
                # SPEC: counts_for_funnel = TRUE
                models.ConsultationStatus.counts_for_funnel == True,
            )
        )
        # Optional date filter (same pattern as get_funnel_stage_counts_batch)
        if start_date and end_date:
            count_query = count_query.where(
                func.date(models.Lead.created_at) >= start_date,
                func.date(models.Lead.created_at) <= end_date,
            )
        count_query = count_query.group_by(models.Lead.pipeline_stage_id)
        count_result = await self.db.execute(count_query)

        # Build lookup with all metrics
        stage_counts = {}
        for row in count_result.fetchall():
            stage_counts[row.pipeline_stage_id] = {
                "count": row.total_count,
                "positive": row.positive_count,
                "negative": row.negative_count,
                "neutral": row.neutral_count,
                "early_exit_count": row.early_exit_count,
            }

        # SPEC: Calculate Net Conversion Rate
        total_enrolled = 0
        total_lost = 0

        for stage in stages:
            stage_data = stage_counts.get(stage.id, {})
            if stage.is_final_stage:
                total_enrolled += stage_data.get("positive", 0)
                total_lost += stage_data.get("negative", 0)
            else:
                total_lost += stage_data.get("early_exit_count", 0)

        net_conversion_rate = round(
            (total_enrolled / (total_enrolled + total_lost)) * 100, 1
        ) if (total_enrolled + total_lost) > 0 else 0.0

        # Build funnel with all metrics
        funnel = []
        for idx, stage in enumerate(stages):
            stage_data = stage_counts.get(stage.id, {})
            lead_count = stage_data.get("count", 0)
            early_exit_count = stage_data.get("early_exit_count", 0)
            move_forward = lead_count - early_exit_count if not stage.is_final_stage else lead_count

            funnel.append({
                "stage_id": stage.id,
                "stage_name": stage.name,
                "stage_order": stage.order,
                "lead_count": lead_count,
                "is_final_stage": stage.is_final_stage,
                "fill": f"var(--chart-{idx % 5 + 1})",
                "conversion_rate": None,  # TODO: Calculate from transitions
                # SPEC: Early Exit metrics
                "early_exit_count": early_exit_count,
                "move_forward": move_forward,
                "outcome_breakdown": {
                    "positive": stage_data.get("positive", 0),
                    "negative": stage_data.get("negative", 0),
                    "neutral": stage_data.get("neutral", 0),
                },
            })

        return funnel

    async def get_team_overview(
        self,
        officer_ids: List[int],
        start_date: date,
        end_date: date,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Get team overview with top performers.

        OPTIMIZATION: Single JOIN query instead of N+1 loop.

        Returns:
            List of officer dicts with consultation counts
        """
        query = (
            select(
                models.User.id,
                models.User.full_name,
                models.User.username,
                func.count(models.Consultation.id).label("consultations")
            )
            .outerjoin(
                models.Consultation,
                and_(
                    models.Consultation.officer_id == models.User.id,
                    func.date(models.Consultation.consultation_date) >= start_date,
                    func.date(models.Consultation.consultation_date) <= end_date,
                    models.Consultation.deleted_at.is_(None),  # Exclude soft-deleted consultations
                )
            )
            .where(models.User.id.in_(officer_ids))
            .group_by(models.User.id, models.User.full_name, models.User.username)
            .order_by(func.count(models.Consultation.id).desc())
            .limit(limit)
        )
        
        result = await self.db.execute(query)
        
        return [
            {
                "officer_id": row.id,
                "officer_name": row.full_name or row.username,
                "consultations": row.consultations or 0,
            }
            for row in result.fetchall()
        ]

    async def get_all_weekly_rankings(
        self,
        week_start: date,
        week_end: date,
        unit_ids: Optional[List[int]] = None,
    ) -> List[Tuple[int, str, str, int]]:
        """
        Get ALL officers ranked by consultations for the week.

        Args:
            week_start: Start date for the ranking period
            week_end: End date for the ranking period
            unit_ids: Optional list of unit IDs to filter officers (includes children)

        Returns list of (user_id, username, full_name, consultation_count)
        """
        query = (
            select(
                models.User.id,
                models.User.username,
                models.User.full_name,
                func.count(models.Consultation.id).label("consultations")
            )
            .outerjoin(
                models.Consultation,
                and_(
                    models.Consultation.officer_id == models.User.id,
                    func.date(models.Consultation.consultation_date) >= week_start,
                    func.date(models.Consultation.consultation_date) <= week_end,
                    models.Consultation.deleted_at.is_(None),  # Exclude soft-deleted consultations
                )
            )
            .where(
                models.User.role == UserRole.OFFICER,
                models.User.status == "active",
            )
        )

        # Filter by unit IDs if provided
        if unit_ids:
            query = query.where(models.User.unit_id.in_(unit_ids))

        query = query.group_by(
            models.User.id, models.User.username, models.User.full_name
        ).order_by(func.count(models.Consultation.id).desc())

        result = await self.db.execute(query)
        return result.fetchall()

    # =========================================================================
    # Response Time Calculation
    # =========================================================================

    async def get_avg_response_time_hours(
        self,
        officer_id: int,
        start_date: date,
        end_date: date,
    ) -> Optional[float]:
        """
        Calculate average response time in hours for an officer.

        Response time = Time from lead assignment to first consultation.
        Only considers leads that:
        - Were assigned to this officer within the date range
        - Have at least one consultation by this officer
        - Have a valid assigned_at timestamp

        Returns:
            Average response time in hours, or None if no data
        """
        # Subquery to get the first consultation date for each lead by this officer
        first_consult_subq = (
            select(
                models.Consultation.lead_id,
                func.min(models.Consultation.consultation_date).label("first_consultation")
            )
            .where(
                models.Consultation.officer_id == officer_id,
                models.Consultation.deleted_at.is_(None),
            )
            .group_by(models.Consultation.lead_id)
        ).subquery()

        # Main query: Get leads assigned in date range with their first consultation
        # Calculate time difference in hours
        query = (
            select(
                func.avg(
                    func.extract(
                        'epoch',
                        first_consult_subq.c.first_consultation - models.Lead.assigned_at
                    ) / 3600  # Convert seconds to hours
                ).label("avg_hours")
            )
            .join(
                first_consult_subq,
                first_consult_subq.c.lead_id == models.Lead.id
            )
            .where(
                models.Lead.assigned_officer_id == officer_id,
                models.Lead.assigned_at.isnot(None),
                models.Lead.deleted_at.is_(None),
                func.date(models.Lead.assigned_at) >= start_date,
                func.date(models.Lead.assigned_at) <= end_date,
                # Ensure first consultation is after assignment (valid response)
                first_consult_subq.c.first_consultation >= models.Lead.assigned_at,
            )
        )

        result = await self.db.execute(query)
        avg_hours = result.scalar()

        if avg_hours is None:
            return None

        return round(float(avg_hours), 1)

    async def get_avg_response_time_hours_multi(
        self,
        officer_ids: List[int],
        start_date: date,
        end_date: date,
    ) -> Optional[float]:
        """
        Calculate average response time in hours across multiple officers.
        Same logic as get_avg_response_time_hours but uses .in_(officer_ids).
        """
        first_consult_subq = (
            select(
                models.Consultation.lead_id,
                func.min(models.Consultation.consultation_date).label("first_consultation")
            )
            .where(
                models.Consultation.officer_id.in_(officer_ids),
                models.Consultation.deleted_at.is_(None),
            )
            .group_by(models.Consultation.lead_id)
        ).subquery()

        query = (
            select(
                func.avg(
                    func.extract(
                        'epoch',
                        first_consult_subq.c.first_consultation - models.Lead.assigned_at
                    ) / 3600
                ).label("avg_hours")
            )
            .join(
                first_consult_subq,
                first_consult_subq.c.lead_id == models.Lead.id
            )
            .where(
                models.Lead.assigned_officer_id.in_(officer_ids),
                models.Lead.assigned_at.isnot(None),
                models.Lead.deleted_at.is_(None),
                func.date(models.Lead.assigned_at) >= start_date,
                func.date(models.Lead.assigned_at) <= end_date,
                first_consult_subq.c.first_consultation >= models.Lead.assigned_at,
            )
        )

        result = await self.db.execute(query)
        avg_hours = result.scalar()

        if avg_hours is None:
            return None

        return round(float(avg_hours), 1)

    # =========================================================================
    # SLA Compliance Rate
    # =========================================================================

    async def get_sla_compliance_stats(
        self,
        officer_id: int,
        start_date: date,
        end_date: date,
        sla_hours: float,
    ) -> Dict[str, Any]:
        """
        Calculate SLA compliance rate for an officer.

        SLA = (Leads responded within sla_hours / Total eligible leads) × 100

        Eligible leads:
        - Contacted leads assigned in date range (have ≥1 consultation)
        - Uncontacted leads assigned in range whose SLA has expired

        Returns dict with compliant, total, overdue_uncontacted, rate.
        """
        now = datetime.now(timezone.utc)

        # Subquery: first consultation per lead by this officer
        first_consult_subq = (
            select(
                models.Consultation.lead_id,
                func.min(models.Consultation.consultation_date).label("first_consultation"),
            )
            .where(
                models.Consultation.officer_id == officer_id,
                models.Consultation.deleted_at.is_(None),
            )
            .group_by(models.Consultation.lead_id)
        ).subquery()

        # Query 1: Contacted leads — count compliant vs total
        contacted_query = (
            select(
                func.count().label("total_contacted"),
                func.count().filter(
                    func.extract(
                        "epoch",
                        first_consult_subq.c.first_consultation - models.Lead.assigned_at,
                    )
                    <= sla_hours * 3600
                ).label("compliant"),
            )
            .join(
                first_consult_subq,
                first_consult_subq.c.lead_id == models.Lead.id,
            )
            .where(
                models.Lead.assigned_officer_id == officer_id,
                models.Lead.assigned_at.isnot(None),
                models.Lead.deleted_at.is_(None),
                func.date(models.Lead.assigned_at) >= start_date,
                func.date(models.Lead.assigned_at) <= end_date,
                first_consult_subq.c.first_consultation >= models.Lead.assigned_at,
            )
        )

        result1 = await self.db.execute(contacted_query)
        row1 = result1.one()
        total_contacted = row1.total_contacted or 0
        compliant = row1.compliant or 0

        # Query 2: Uncontacted leads whose SLA has expired
        sla_deadline = now - timedelta(hours=sla_hours)
        overdue_query = (
            select(func.count().label("overdue_count"))
            .select_from(models.Lead)
            .outerjoin(
                first_consult_subq,
                first_consult_subq.c.lead_id == models.Lead.id,
            )
            .where(
                models.Lead.assigned_officer_id == officer_id,
                models.Lead.assigned_at.isnot(None),
                models.Lead.deleted_at.is_(None),
                func.date(models.Lead.assigned_at) >= start_date,
                func.date(models.Lead.assigned_at) <= end_date,
                first_consult_subq.c.lead_id.is_(None),  # No consultation
                models.Lead.assigned_at < sla_deadline,  # SLA expired
            )
        )

        result2 = await self.db.execute(overdue_query)
        overdue_uncontacted = result2.scalar() or 0

        total = total_contacted + overdue_uncontacted
        rate = round((compliant / total) * 100, 1) if total > 0 else 0.0

        return {
            "compliant": compliant,
            "total": total,
            "overdue_uncontacted": overdue_uncontacted,
            "rate": rate,
        }

    async def get_aggregated_sla_compliance_stats(
        self,
        officer_ids: List[int],
        start_date: date,
        end_date: date,
        sla_hours: float,
    ) -> Dict[str, Any]:
        """Aggregated SLA compliance for multiple officers."""
        if not officer_ids:
            return {"compliant": 0, "total": 0, "overdue_uncontacted": 0, "rate": 0.0}

        now = datetime.now(timezone.utc)

        first_consult_subq = (
            select(
                models.Consultation.lead_id,
                func.min(models.Consultation.consultation_date).label("first_consultation"),
            )
            .where(
                models.Consultation.officer_id.in_(officer_ids),
                models.Consultation.deleted_at.is_(None),
            )
            .group_by(models.Consultation.lead_id)
        ).subquery()

        contacted_query = (
            select(
                func.count().label("total_contacted"),
                func.count().filter(
                    func.extract(
                        "epoch",
                        first_consult_subq.c.first_consultation - models.Lead.assigned_at,
                    )
                    <= sla_hours * 3600
                ).label("compliant"),
            )
            .join(
                first_consult_subq,
                first_consult_subq.c.lead_id == models.Lead.id,
            )
            .where(
                models.Lead.assigned_officer_id.in_(officer_ids),
                models.Lead.assigned_at.isnot(None),
                models.Lead.deleted_at.is_(None),
                func.date(models.Lead.assigned_at) >= start_date,
                func.date(models.Lead.assigned_at) <= end_date,
                first_consult_subq.c.first_consultation >= models.Lead.assigned_at,
            )
        )

        result1 = await self.db.execute(contacted_query)
        row1 = result1.one()
        total_contacted = row1.total_contacted or 0
        compliant = row1.compliant or 0

        sla_deadline = now - timedelta(hours=sla_hours)
        overdue_query = (
            select(func.count().label("overdue_count"))
            .select_from(models.Lead)
            .outerjoin(
                first_consult_subq,
                first_consult_subq.c.lead_id == models.Lead.id,
            )
            .where(
                models.Lead.assigned_officer_id.in_(officer_ids),
                models.Lead.assigned_at.isnot(None),
                models.Lead.deleted_at.is_(None),
                func.date(models.Lead.assigned_at) >= start_date,
                func.date(models.Lead.assigned_at) <= end_date,
                first_consult_subq.c.lead_id.is_(None),
                models.Lead.assigned_at < sla_deadline,
            )
        )

        result2 = await self.db.execute(overdue_query)
        overdue_uncontacted = result2.scalar() or 0

        total = total_contacted + overdue_uncontacted
        rate = round((compliant / total) * 100, 1) if total > 0 else 0.0

        return {
            "compliant": compliant,
            "total": total,
            "overdue_uncontacted": overdue_uncontacted,
            "rate": rate,
        }

    # =========================================================================
    # Consultation Effectiveness
    # =========================================================================

    async def get_consultation_effectiveness_stats(
        self,
        officer_id: int,
        start_date: date,
        end_date: date,
    ) -> Dict[str, Any]:
        """
        Consultation Effectiveness: % of consulted leads that converted (Won).

        Only counts leads that:
        - Have ≥1 consultation by this officer
        - Have reached a final status (is_final=True)

        Numerator: final + positive (Won)
        Denominator: ALL final outcomes (positive + negative + neutral)

        Returns dict with won_consulted, total_final_consulted, effectiveness.
        """
        # Subquery: leads with at least one consultation by this officer
        consulted_leads_subq = (
            select(models.Consultation.lead_id)
            .where(
                models.Consultation.officer_id == officer_id,
                models.Consultation.deleted_at.is_(None),
            )
            .distinct()
        ).subquery()

        # Latest transition per lead (DISTINCT ON lead_id ORDER BY changed_at DESC)
        latest_transitions = (
            select(
                models.LeadStatusHistory.lead_id,
                models.ConsultationStatus.outcome_type,
                models.ConsultationStatus.is_final,
            )
            .distinct(models.LeadStatusHistory.lead_id)
            .join(
                models.ConsultationStatus,
                models.LeadStatusHistory.new_consultation_status_id == models.ConsultationStatus.id,
            )
            .join(
                models.Lead,
                models.LeadStatusHistory.lead_id == models.Lead.id,
            )
            .join(
                consulted_leads_subq,
                models.LeadStatusHistory.lead_id == consulted_leads_subq.c.lead_id,
            )
            .where(
                models.Lead.assigned_officer_id == officer_id,
                func.date(models.LeadStatusHistory.changed_at) >= start_date,
                func.date(models.LeadStatusHistory.changed_at) <= end_date,
                models.Lead.deleted_at.is_(None),
                models.LeadStatusHistory.new_consultation_status_id.isnot(None),
            )
            .order_by(
                models.LeadStatusHistory.lead_id,
                models.LeadStatusHistory.changed_at.desc(),
            )
        )

        result = await self.db.execute(latest_transitions)
        rows = result.fetchall()

        won_consulted = sum(1 for r in rows if r.is_final and r.outcome_type == "positive")
        total_final_consulted = sum(1 for r in rows if r.is_final)

        effectiveness = (
            round((won_consulted / total_final_consulted) * 100, 1)
            if total_final_consulted > 0
            else 0.0
        )

        return {
            "won_consulted": won_consulted,
            "total_final_consulted": total_final_consulted,
            "effectiveness": effectiveness,
        }

    async def get_aggregated_consultation_effectiveness_stats(
        self,
        officer_ids: List[int],
        start_date: date,
        end_date: date,
    ) -> Dict[str, Any]:
        """Aggregated Consultation Effectiveness for multiple officers."""
        if not officer_ids:
            return {"won_consulted": 0, "total_final_consulted": 0, "effectiveness": 0.0}

        consulted_leads_subq = (
            select(models.Consultation.lead_id)
            .where(
                models.Consultation.officer_id.in_(officer_ids),
                models.Consultation.deleted_at.is_(None),
            )
            .distinct()
        ).subquery()

        latest_transitions = (
            select(
                models.LeadStatusHistory.lead_id,
                models.ConsultationStatus.outcome_type,
                models.ConsultationStatus.is_final,
            )
            .distinct(models.LeadStatusHistory.lead_id)
            .join(
                models.ConsultationStatus,
                models.LeadStatusHistory.new_consultation_status_id == models.ConsultationStatus.id,
            )
            .join(
                models.Lead,
                models.LeadStatusHistory.lead_id == models.Lead.id,
            )
            .join(
                consulted_leads_subq,
                models.LeadStatusHistory.lead_id == consulted_leads_subq.c.lead_id,
            )
            .where(
                models.Lead.assigned_officer_id.in_(officer_ids),
                func.date(models.LeadStatusHistory.changed_at) >= start_date,
                func.date(models.LeadStatusHistory.changed_at) <= end_date,
                models.Lead.deleted_at.is_(None),
                models.LeadStatusHistory.new_consultation_status_id.isnot(None),
            )
            .order_by(
                models.LeadStatusHistory.lead_id,
                models.LeadStatusHistory.changed_at.desc(),
            )
        )

        result = await self.db.execute(latest_transitions)
        rows = result.fetchall()

        won_consulted = sum(1 for r in rows if r.is_final and r.outcome_type == "positive")
        total_final_consulted = sum(1 for r in rows if r.is_final)

        effectiveness = (
            round((won_consulted / total_final_consulted) * 100, 1)
            if total_final_consulted > 0
            else 0.0
        )

        return {
            "won_consulted": won_consulted,
            "total_final_consulted": total_final_consulted,
            "effectiveness": effectiveness,
        }


    # =========================================================================
    # DAILY QUALITY KPIs (Phase D — spec section 15)
    # =========================================================================

    async def count_human_consultations_daily(
        self, officer_id: int, day_start: datetime, day_end: datetime,
    ) -> int:
        """D1/D5: Count human consultations for a day. Excludes method=system (NULL-safe)."""
        r = await self.db.execute(
            select(func.count(models.Consultation.id)).where(
                models.Consultation.officer_id == officer_id,
                models.Consultation.consultation_date >= day_start,
                models.Consultation.consultation_date < day_end,
                models.Consultation.deleted_at.is_(None),
                models.Consultation.method.is_distinct_from("system"),
            )
        )
        return r.scalar_one()

    async def count_verified_consultations_daily(
        self, officer_id: int, day_start: datetime, day_end: datetime,
    ) -> int:
        """D1: Verified consultations - DISTINCT lead_id with quality filters."""
        r = await self.db.execute(
            select(func.count(func.distinct(models.Consultation.lead_id))).where(
                models.Consultation.officer_id == officer_id,
                models.Consultation.consultation_date >= day_start,
                models.Consultation.consultation_date < day_end,
                models.Consultation.deleted_at.is_(None),
                models.Consultation.method.is_distinct_from("system"),
                models.Consultation.consultation_status_id.isnot(None),
                models.Consultation.consultation_status_id.in_(
                    select(models.ConsultationStatus.id).where(
                        models.ConsultationStatus.counts_for_funnel == True,  # noqa: E712
                        models.ConsultationStatus.updates_pipeline == True,  # noqa: E712
                    )
                ),
                models.Consultation.lead_id.in_(
                    select(models.LeadStatusHistory.lead_id).where(
                        models.LeadStatusHistory.changed_at >= day_start,
                        models.LeadStatusHistory.changed_at < day_end,
                    )
                ),
            )
        )
        return r.scalar_one()

    async def get_followup_commitment_stats(
        self, officer_id: int, day_start: datetime, day_end: datetime,
    ) -> Dict[str, int]:
        """D2: Followup commitment - numerator / denominator (V_D non-final)."""
        base = [
            models.Consultation.officer_id == officer_id,
            models.Consultation.consultation_date >= day_start,
            models.Consultation.consultation_date < day_end,
            models.Consultation.deleted_at.is_(None),
            models.Consultation.method.is_distinct_from("system"),
        ]
        nf_status = select(models.ConsultationStatus.id).where(
            models.ConsultationStatus.counts_for_funnel == True,  # noqa: E712
            models.ConsultationStatus.updates_pipeline == True,  # noqa: E712
            models.ConsultationStatus.is_final == False,  # noqa: E712
        )
        hist = select(models.LeadStatusHistory.lead_id).where(
            models.LeadStatusHistory.changed_at >= day_start,
            models.LeadStatusHistory.changed_at < day_end,
        )
        denom = (await self.db.execute(
            select(func.count(func.distinct(models.Consultation.lead_id))).where(
                *base, models.Consultation.consultation_status_id.in_(nf_status),
                models.Consultation.lead_id.in_(hist),
            )
        )).scalar_one()
        numer = (await self.db.execute(
            select(func.count(func.distinct(models.Consultation.lead_id))).where(
                *base, models.Consultation.consultation_status_id.in_(nf_status),
                models.Consultation.lead_id.in_(hist),
                models.Consultation.scheduled_at.isnot(None),
                models.Consultation.scheduled_at > models.Consultation.consultation_date,
            )
        )).scalar_one()
        return {"numerator": numer, "denominator": denom}

    def _verified_lead_subquery(self, officer_id: int, day_start: datetime, day_end: datetime):
        """Shared subquery: verified lead_ids for a day."""
        return (
            select(func.distinct(models.Consultation.lead_id))
            .where(
                models.Consultation.officer_id == officer_id,
                models.Consultation.consultation_date >= day_start,
                models.Consultation.consultation_date < day_end,
                models.Consultation.deleted_at.is_(None),
                models.Consultation.method.is_distinct_from("system"),
                models.Consultation.consultation_status_id.in_(
                    select(models.ConsultationStatus.id).where(
                        models.ConsultationStatus.counts_for_funnel == True,  # noqa: E712
                        models.ConsultationStatus.updates_pipeline == True,  # noqa: E712
                    )
                ),
                models.Consultation.lead_id.in_(
                    select(models.LeadStatusHistory.lead_id).where(
                        models.LeadStatusHistory.changed_at >= day_start,
                        models.LeadStatusHistory.changed_at < day_end,
                    )
                ),
            )
        )

    async def get_progress_rate_d7(
        self, officer_id: int, day_start: datetime, day_end: datetime,
    ) -> Dict[str, Any]:
        """D3: % verified leads progressed within 7 days."""
        v_subq = self._verified_lead_subquery(officer_id, day_start, day_end)
        total_v = (await self.db.execute(select(func.count()).select_from(v_subq.subquery()))).scalar_one()
        if total_v == 0:
            return {"total": 0, "progressed": 0, "rate": None}
        d7_end = day_end + timedelta(days=7)
        old_ps = models.PipelineStage.__table__.alias("old_ps_d7")
        new_ps = models.PipelineStage.__table__.alias("new_ps_d7")
        neg_st = select(models.ConsultationStatus.id).where(models.ConsultationStatus.outcome_type == "negative")
        pos_st = select(models.ConsultationStatus.id).where(models.ConsultationStatus.outcome_type == "positive")
        progressed = (await self.db.execute(
            select(func.count(func.distinct(models.LeadStatusHistory.lead_id)))
            .join(old_ps, models.LeadStatusHistory.old_pipeline_stage_id == old_ps.c.id)
            .join(new_ps, models.LeadStatusHistory.new_pipeline_stage_id == new_ps.c.id)
            .where(
                models.LeadStatusHistory.lead_id.in_(v_subq),
                models.LeadStatusHistory.changed_at > day_end,
                models.LeadStatusHistory.changed_at <= d7_end,
                or_(
                    and_(new_ps.c.order > old_ps.c.order,
                         or_(models.LeadStatusHistory.new_consultation_status_id.is_(None),
                             ~models.LeadStatusHistory.new_consultation_status_id.in_(neg_st))),
                    and_(new_ps.c.is_final_stage == True,  # noqa: E712
                         models.LeadStatusHistory.new_consultation_status_id.in_(pos_st)),
                ),
            )
        )).scalar_one()
        return {"total": total_v, "progressed": progressed,
                "rate": round(progressed / total_v * 100, 1)}

    async def get_rollback_rate_d3(
        self, officer_id: int, day_start: datetime, day_end: datetime,
    ) -> Dict[str, Any]:
        """D3: % verified leads dropped stage within 3 days. Gross rollback."""
        v_subq = self._verified_lead_subquery(officer_id, day_start, day_end)
        total_v = (await self.db.execute(select(func.count()).select_from(v_subq.subquery()))).scalar_one()
        if total_v == 0:
            return {"total": 0, "rolled_back": 0, "rate": None}
        d3_end = day_end + timedelta(days=3)
        old_ps = models.PipelineStage.__table__.alias("old_ps_rb")
        new_ps = models.PipelineStage.__table__.alias("new_ps_rb")
        rolled_back = (await self.db.execute(
            select(func.count(func.distinct(models.LeadStatusHistory.lead_id)))
            .join(old_ps, models.LeadStatusHistory.old_pipeline_stage_id == old_ps.c.id)
            .join(new_ps, models.LeadStatusHistory.new_pipeline_stage_id == new_ps.c.id)
            .where(
                models.LeadStatusHistory.lead_id.in_(v_subq),
                models.LeadStatusHistory.changed_at > day_end,
                models.LeadStatusHistory.changed_at <= d3_end,
                new_ps.c.order < old_ps.c.order,
            )
        )).scalar_one()
        return {"total": total_v, "rolled_back": rolled_back,
                "rate": round(rolled_back / total_v * 100, 1)}
