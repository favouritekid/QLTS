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
    def __init__(self, date: str, assigned: int = 0, consultations: int = 0, converted: int = 0):
        self.date = date
        self.assigned = assigned
        self.consultations = consultations
        self.converted = converted


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

        SPEC: LOSS_REASON_UX_SPEC.md / FUNNEL_FEASIBILITY_ANALYSIS.md Phase 2

        Returns:
            Dict[stage_id, [
                {"reason_code": "PRICE_HIGH", "count": 10, "percentage": 25.0},
                {"reason_code": "NO_CONTACT", "count": 8, "percentage": 20.0},
                ...
            ]]
        """
        # Build conditions
        conditions = [
            models.LeadStatusHistory.loss_reason_code.isnot(None),
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

        # Query: aggregate loss_reason_code by pipeline_stage_id
        query = (
            select(
                models.LeadStatusHistory.new_pipeline_stage_id.label("stage_id"),
                models.LeadStatusHistory.loss_reason_code,
                func.count().label("count"),
            )
            .join(models.Lead, models.LeadStatusHistory.lead_id == models.Lead.id)
            .where(*conditions)
            .group_by(
                models.LeadStatusHistory.new_pipeline_stage_id,
                models.LeadStatusHistory.loss_reason_code,
            )
            .order_by(
                models.LeadStatusHistory.new_pipeline_stage_id,
                func.count().desc(),
            )
        )

        result = await self.db.execute(query)
        rows = result.fetchall()

        # Build stage -> loss breakdown dict
        stage_breakdown: Dict[str, List[Dict[str, Any]]] = {}
        stage_totals: Dict[str, int] = {}

        # First pass: calculate totals per stage
        for row in rows:
            stage_id = row.stage_id
            if stage_id:
                stage_totals[stage_id] = stage_totals.get(stage_id, 0) + row.count

        # Second pass: build breakdown with percentages
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
    ) -> Dict[str, Dict[str, int]]:
        """
        Get transition counts between stages for conversion rate calculation.

        Returns:
            Dict[from_stage_id, Dict[to_stage_id, count]]
        """
        since_date = datetime.now(timezone.utc) - timedelta(days=days)
        
        query = (
            select(
                models.LeadStatusHistory.old_pipeline_stage_id,
                models.LeadStatusHistory.new_pipeline_stage_id,
                func.count().label("transition_count")
            )
            .join(models.Lead, models.LeadStatusHistory.lead_id == models.Lead.id)
            .where(
                models.LeadStatusHistory.changed_by_user_id == officer_id,
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
        
        # Query 3: Conversions per day (based on status history)
        converted_query = (
            select(
                func.date(models.LeadStatusHistory.changed_at).label("day"),
                func.count(func.distinct(models.LeadStatusHistory.lead_id)).label("count")
            )
            .join(models.Lead, models.LeadStatusHistory.lead_id == models.Lead.id)
            .join(models.PipelineStage, 
                  models.LeadStatusHistory.new_pipeline_stage_id == models.PipelineStage.id)
            .where(
                models.LeadStatusHistory.changed_by_user_id == officer_id,
                func.date(models.LeadStatusHistory.changed_at) >= start_date,
                func.date(models.LeadStatusHistory.changed_at) <= end_date,
                models.PipelineStage.is_final_stage == True,
                models.Lead.deleted_at.is_(None)
            )
            .group_by(func.date(models.LeadStatusHistory.changed_at))
        )
        converted_result = await self.db.execute(converted_query)
        for row in converted_result.fetchall():
            date_str = str(row.day)
            if date_str in trends:
                trends[date_str].converted = row.count
        
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
        today = datetime.now(timezone.utc).date()
        
        # Query 1: Consultations (range + today in one query with conditional)
        consult_query = (
            select(
                func.count(models.Consultation.id).label("range_count"),
                func.count(
                    case((func.date(models.Consultation.consultation_date) == today, 1))
                ).label("today_count"),
            )
            .join(models.Lead, models.Consultation.lead_id == models.Lead.id)
            .where(
                models.Consultation.officer_id == officer_id,
                func.date(models.Consultation.consultation_date) >= start_date,
                func.date(models.Consultation.consultation_date) <= end_date,
                models.Lead.deleted_at.is_(None),
                models.Consultation.deleted_at.is_(None),  # Exclude soft-deleted consultations
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
                                models.ConsultationStatus.is_final_status == False,
                                models.ConsultationStatus.is_final_status.is_(None)
                            )
                        ), 1
                    ))
                ).label("active"),
                func.count(
                    case((
                        and_(
                            models.ConsultationStatus.is_final_status == True,
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
        
        return {
            "consultations_in_range": consultations_in_range,
            "consultations_today": consultations_today,
            "active_leads": lead_row.active or 0,
            "converted_count": lead_row.converted or 0,
            "total_leads": lead_row.total or 0,
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
                    models.ConsultationStatus.is_final_status == False,
                    models.ConsultationStatus.is_final_status.is_(None)
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
                    models.ConsultationStatus.is_final_status == False,
                    models.ConsultationStatus.is_final_status.is_(None)
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
                    models.ConsultationStatus.is_final_status == False,
                    models.ConsultationStatus.is_final_status.is_(None)
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
                models.User.role == "officer",
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
    ) -> Dict[str, float]:
        """
        Get team average consultations and conversions.
        
        Args:
            unit_id: Filter by unit (None = all officers)
            start_date: Start date for calculation
            end_date: End date for calculation
        """
        # Calculate number of days for averaging
        days = (end_date - start_date).days + 1
        if days < 1: days = 1
        
        # Build conditions for officers
        conditions = [
            models.User.role == "officer",
            models.User.status == "active",
        ]
        if unit_id:
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
        
        if unit_id:
            consult_conditions.append(
                models.Consultation.officer_id.in_(
                    select(models.User.id).where(*conditions)
                )
            )
        else:
             # FIX: Ensure we only count consults from officers matching the "conditions" (Active Officers)
             # This aligns the numerator (consults by active officers) with the denominator (count of active officers)
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
            "team_avg_conversions": 0.0,  # Placeholder
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
            .where(models.User.role == "officer")
            .offset(skip)
            .limit(limit)
        )
        result = await self.db.execute(query)
        officers = list(result.scalars().all())
        
        count_query = (
            select(func.count(models.User.id))
            .where(models.User.role == "officer")
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
            scope: "team" or "organization"
            unit_id: Filter by unit ID (required for team scope)

        Returns:
            List of officer user IDs
        """
        conditions = [
            models.User.role == "officer",
            models.User.status == "active",
        ]
        
        if unit_id:
            conditions.append(models.User.unit_id == unit_id)
        
        query = select(models.User.id).where(*conditions)
        result = await self.db.execute(query)
        return [row[0] for row in result.fetchall()]

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
        today = datetime.now(timezone.utc).date()
        
        # Query 1: Consultations (batch, exclude soft-deleted)
        consult_query = (
            select(
                func.count(models.Consultation.id).label("range_count"),
                func.count(
                    case((func.date(models.Consultation.consultation_date) == today, 1))
                ).label("today_count"),
            )
            .join(models.Lead, models.Consultation.lead_id == models.Lead.id)
            .where(
                models.Consultation.officer_id.in_(officer_ids),
                func.date(models.Consultation.consultation_date) >= start_date,
                func.date(models.Consultation.consultation_date) <= end_date,
                models.Lead.deleted_at.is_(None),
                models.Consultation.deleted_at.is_(None),  # Exclude soft-deleted consultations
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
                            models.ConsultationStatus.is_final_status == False,
                            models.ConsultationStatus.is_final_status.is_(None)
                        ), 1
                    ))
                ).label("active"),
                func.count(
                    case((
                        and_(
                            models.ConsultationStatus.is_final_status == True,
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
        
        return {
            "total_consultations": consult_row.range_count or 0,
            "today_consultations": consult_row.today_count or 0,
            "active_leads": lead_row.active or 0,
            "converted_count": lead_row.converted or 0,
            "total_leads": lead_row.total or 0,
        }

    async def get_aggregated_funnel(
        self,
        officer_ids: List[int],
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
            .group_by(models.Lead.pipeline_stage_id)
        )
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
                models.User.role == "officer",
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
