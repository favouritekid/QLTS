# app/repositories/lead_repository.py
"""
✅ PHASE 2 - WEEK 1: Lead Repository

Lead-specific data access layer.
Handles all Lead CRUD operations and complex queries.

Benefits:
- Centralized lead query logic
- Optimized eager loading strategies
- Testable with repository mocks
- Separates SQL from business logic
"""

from datetime import datetime, timezone
from typing import List, Optional, Tuple

from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app import models
from app.repositories.base import BaseRepository


class LeadRepository(BaseRepository[models.Lead]):
    """Repository for Lead model operations."""

    def __init__(self, db: AsyncSession):
        """
        Initialize Lead repository.

        Args:
            db: SQLAlchemy async session
        """
        super().__init__(db, models.Lead)

    async def get_filtered(
        self,
        skip: int = 0,
        limit: int = 10,
        status: Optional[str] = None,
        assigned_officer_id: Optional[int] = None,
        unit_id: Optional[int] = None,
        offering_id: Optional[int] = None,
        source: Optional[str] = None,
        search: Optional[str] = None,
        sort_by: str = "created_at",
        order: str = "desc",
        # === PIPELINE STAGE FILTER ===
        pipeline_stage_id: Optional[str] = None,
        # === DATE RANGE FILTER ===
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        date_field: str = "created_at",
    ) -> Tuple[int, List[models.Lead]]:
        """
        Get filtered list of leads with pagination and eager loading.

        Implements Quick Disposition bubble-up logic:
        - Overdue activities (next_activity_at <= now) appear first
        - Today's activities appear second
        - Future/no activities appear last

        Args:
            skip: Number of records to skip
            limit: Maximum number of records to return
            status: Comma-separated status filter
            assigned_officer_id: Filter by assigned officer
            unit_id: Filter by organization unit
            offering_id: Filter by program offering
            source: Comma-separated source filter
            search: Search term for name/email/phone
            sort_by: Column to sort by (default: created_at)
            order: Sort order (asc/desc)

        Returns:
            Tuple of (total_count, lead_list)
        """
        # Build base queries
        base_query = select(models.Lead)
        count_query = select(func.count(models.Lead.id))

        # Apply filters
        filters = []

        # Always filter out soft-deleted leads
        filters.append(models.Lead.deleted_at.is_(None))

        if status:
            statuses = [s.strip() for s in status.split(",") if s.strip()]
            if statuses:
                filters.append(models.Lead.status.in_(statuses))

        if assigned_officer_id is not None:
            filters.append(models.Lead.assigned_officer_id == assigned_officer_id)

        if unit_id is not None:
            filters.append(models.Lead.unit_id == unit_id)

        if offering_id is not None:
            filters.append(models.Lead.offering_id == offering_id)

        if source:
            sources = [s.strip() for s in source.split(",") if s.strip()]
            if sources:
                filters.append(models.Lead.source.in_(sources))

        # Apply search
        if search:
            search_term = f"%{search.strip()}%"
            search_conditions = or_(
                models.Lead.full_name.ilike(search_term),
                models.Lead.email.ilike(search_term),
                models.Lead.phone.ilike(search_term),
            )
            filters.append(search_conditions)

        # === PIPELINE STAGE FILTER ===
        if pipeline_stage_id:
            filters.append(models.Lead.pipeline_stage_id == pipeline_stage_id)

        # === DATE RANGE FILTER ===
        # Filter by date_from and/or date_to on specified date_field (created_at or updated_at)
        if date_from or date_to:
            # Validate date_field - only allow created_at or updated_at
            if date_field not in ("created_at", "updated_at"):
                date_field = "created_at"  # Default fallback
            
            date_column = getattr(models.Lead, date_field)
            
            if date_from:
                filters.append(date_column >= date_from)
            if date_to:
                filters.append(date_column <= date_to)

        # Apply filters to both queries
        if filters:
            base_query = base_query.where(*filters)
            count_query = count_query.where(*filters)

        # Execute count query
        total_count_result = await self.db.execute(count_query)
        total_count = total_count_result.scalar_one_or_none() or 0

        if total_count == 0:
            return 0, []

        # Apply sorting with bubble-up logic
        now = datetime.now(timezone.utc)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = now.replace(hour=23, minute=59, second=59, microsecond=999999)

        # Priority weight:
        # 0 = Overdue (most urgent)
        # 1 = Today
        # 2 = Future or NULL
        activity_priority = case(
            (models.Lead.next_activity_at <= now, 0),
            (models.Lead.next_activity_at.between(today_start, today_end), 1),
            else_=2
        )

        sort_column = getattr(models.Lead, sort_by, models.Lead.created_at)

        if order.lower() == "desc":
            leads_query = base_query.order_by(
                activity_priority.asc(),
                models.Lead.next_activity_at.asc().nullslast(),
                sort_column.desc()
            )
        else:
            leads_query = base_query.order_by(
                activity_priority.asc(),
                models.Lead.next_activity_at.asc().nullslast(),
                sort_column.asc()
            )

        # ✅ Apply eager loading with ALL relationships required by schema
        leads_query = (
            leads_query.options(
                selectinload(models.Lead.offering).options(
                    selectinload(models.ProgramOffering.program)
                ),
                selectinload(models.Lead.assigned_officer),
                selectinload(models.Lead.unit),
                selectinload(models.Lead.consultation_status),
                selectinload(models.Lead.pipeline_stage),
                # ✅ FIX: Add missing eager load for application to prevent MissingGreenlet error
                selectinload(models.Lead.application),
            )
            .offset(skip)
            .limit(limit)
        )

        # Execute query
        result = await self.db.execute(leads_query)
        leads = list(result.scalars().all())

        return total_count, leads

    async def get_by_phone(self, phone: str) -> Optional[models.Lead]:
        """
        Get lead by phone number (primary or secondary).

        Args:
            phone: Phone number to search

        Returns:
            Lead instance or None
        """
        result = await self.db.execute(
            select(models.Lead)
            .where(
                or_(
                    models.Lead.phone == phone,
                    models.Lead.phone2 == phone
                )
            )
            .where(models.Lead.deleted_at.is_(None))
        )
        return result.scalars().first()

    async def get_by_email(self, email: str) -> Optional[models.Lead]:
        """
        Get lead by email address.

        Args:
            email: Email to search

        Returns:
            Lead instance or None
        """
        result = await self.db.execute(
            select(models.Lead)
            .where(models.Lead.email == email)
            .where(models.Lead.deleted_at.is_(None))
        )
        return result.scalars().first()

    async def update_next_activity(
        self,
        lead_id: int
    ) -> None:
        """
        Update lead's next_activity_at field.

        Finds earliest scheduled consultation that:
        - Hasn't sent reminder yet
        - Is in the future
        - Belongs to this lead

        Args:
            lead_id: Lead ID to update
        """
        from sqlalchemy import and_

        lead = await self.db.get(models.Lead, lead_id)
        if not lead:
            return

        now = datetime.now(timezone.utc)

        result = await self.db.execute(
            select(func.min(models.Consultation.scheduled_at))
            .where(
                and_(
                    models.Consultation.lead_id == lead_id,
                    models.Consultation.scheduled_at.isnot(None),
                    models.Consultation.scheduled_at >= now,
                    models.Consultation.reminder_sent == False,
                )
            )
        )
        earliest_scheduled = result.scalar_one_or_none()

        lead.next_activity_at = earliest_scheduled
        await self.db.flush()

    async def get_stale_leads(
        self,
        officer_id: int,
        days_threshold: int = 7,
        limit: int = 10
    ) -> List[models.Lead]:
        """
        Get stale leads for an officer.

        Stale = no activity for X days.

        Args:
            officer_id: Officer ID
            days_threshold: Number of days to consider stale
            limit: Maximum results

        Returns:
            List of stale leads
        """
        from datetime import timedelta

        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_threshold)

        result = await self.db.execute(
            select(models.Lead)
            .where(models.Lead.assigned_officer_id == officer_id)
            .where(models.Lead.updated_at < cutoff_date)
            .where(models.Lead.deleted_at.is_(None))
            .order_by(models.Lead.updated_at.asc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_high_score_leads(
        self,
        officer_id: Optional[int] = None,
        min_score: int = 70,
        limit: int = 10
    ) -> List[models.Lead]:
        """
        Get high-scoring leads.

        Args:
            officer_id: Filter by officer (optional)
            min_score: Minimum lead score
            limit: Maximum results

        Returns:
            List of high-score leads
        """
        query = (
            select(models.Lead)
            .where(models.Lead.lead_score >= min_score)
            .where(models.Lead.deleted_at.is_(None))
            .order_by(models.Lead.lead_score.desc())
            .limit(limit)
        )

        if officer_id is not None:
            query = query.where(models.Lead.assigned_officer_id == officer_id)

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def count_by_status(
        self,
        unit_id: Optional[int] = None,
        officer_id: Optional[int] = None
    ) -> dict:
        """
        Count leads grouped by status.

        Args:
            unit_id: Filter by unit (optional)
            officer_id: Filter by officer (optional)

        Returns:
            Dict mapping status to count
        """
        query = (
            select(
                models.Lead.status,
                func.count(models.Lead.id).label("count")
            )
            .where(models.Lead.deleted_at.is_(None))
            .group_by(models.Lead.status)
        )

        if unit_id is not None:
            query = query.where(models.Lead.unit_id == unit_id)

        if officer_id is not None:
            query = query.where(models.Lead.assigned_officer_id == officer_id)

        result = await self.db.execute(query)
        return {row.status: row.count for row in result}
