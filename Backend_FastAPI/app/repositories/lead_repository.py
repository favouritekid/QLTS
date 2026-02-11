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

import unicodedata
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

    # =========================================================================
    # DETAIL VIEW METHODS (get_by_id with eager loading)
    # =========================================================================

    async def get_by_id_full(
        self,
        lead_id: int,
        include_deleted: bool = False
    ) -> Optional[models.Lead]:
        """
        Get lead with ALL relationships for Detail/Timeline/Insights view.
        
        This is the "deep" loading strategy that includes:
        - All direct relationships (offering, unit, officer, etc.)
        - Nested relationships (unit.parent, unit.children, unit.major_programs)
        - Collection relationships (consultations, assignment_logs)
        - Nested collection relationships (consultations.officer, consultations.status)
        
        Use this for:
        - Lead Detail Page
        - Timeline View
        - Insights Dashboard
        
        Args:
            lead_id: Lead ID to fetch
            include_deleted: If True, include soft-deleted leads
            
        Returns:
            Lead with all relations loaded, or None if not found
        """
        from sqlalchemy.orm import joinedload
        
        query = (
            select(self.model)
            .options(
                # Direct 1-1 relationships
                selectinload(models.Lead.offering).options(
                    selectinload(models.ProgramOffering.program),
                    selectinload(models.ProgramOffering.academic_info_history),
                ),
                selectinload(models.Lead.unit).options(
                    selectinload(models.OrganizationUnit.parent),
                    selectinload(models.OrganizationUnit.children),
                    selectinload(models.OrganizationUnit.major_programs),
                ),
                selectinload(models.Lead.assigned_officer),
                selectinload(models.Lead.pipeline_stage),
                selectinload(models.Lead.consultation_status).selectinload(models.ConsultationStatus.stage),
                selectinload(models.Lead.application).options(
                    selectinload(models.Application.officer)
                ),
                # NEW: AdmissionProfile for admission module
                selectinload(models.Lead.admission_profile),
                # Collection relationships for timeline/insights
                # ✅ FIX: Filter out soft-deleted consultations
                selectinload(
                    models.Lead.consultations.and_(
                        models.Consultation.deleted_at.is_(None)
                    )
                ).options(
                    joinedload(models.Consultation.officer),
                    joinedload(models.Consultation.consultation_status).joinedload(models.ConsultationStatus.stage),
                ),
                selectinload(models.Lead.assignment_logs).options(
                    joinedload(models.AssignmentLog.officer)
                ),
            )
            .where(self.model.id == lead_id)
        )
        
        if not include_deleted:
            query = query.where(self.model.deleted_at.is_(None))
        
        result = await self.db.execute(query)
        return result.scalars().first()

    async def get_by_id_shallow(
        self,
        lead_id: int,
        include_deleted: bool = False
    ) -> Optional[models.Lead]:
        """
        Get lead with minimal relationships for quick operations.
        
        This is the "shallow" loading strategy that includes only:
        - Direct 1-1 relationships needed for display
        - NO collection relationships (consultations, logs)
        
        Use this for:
        - Quick lead lookup before update
        - List item display
        - Permission checks
        
        Args:
            lead_id: Lead ID to fetch
            include_deleted: If True, include soft-deleted leads
            
        Returns:
            Lead with minimal relations loaded, or None if not found
        """
        query = (
            select(self.model)
            .options(
                selectinload(models.Lead.offering).options(
                    selectinload(models.ProgramOffering.program),
                    selectinload(models.ProgramOffering.academic_info_history),
                ),
                selectinload(models.Lead.unit),
                selectinload(models.Lead.assigned_officer),
                selectinload(models.Lead.pipeline_stage),
                selectinload(models.Lead.consultation_status).selectinload(models.ConsultationStatus.stage),
                selectinload(models.Lead.application).options(
                    selectinload(models.Application.officer)
                ),
                # NEW: AdmissionProfile for admission module
                selectinload(models.Lead.admission_profile),
            )
            .where(self.model.id == lead_id)
        )
        
        if not include_deleted:
            query = query.where(self.model.deleted_at.is_(None))
        
        result = await self.db.execute(query)
        return result.scalars().first()

    async def get_filtered(
        self,
        skip: int = 0,
        limit: int = 10,
        status: Optional[str] = None,
        assigned_officer_id: Optional[str] = None,  # Comma-separated IDs for multi-select
        unit_id: Optional[int] = None,
        offering_id: Optional[str] = None,  # Comma-separated IDs for multi-select
        source: Optional[str] = None,
        search: Optional[str] = None,
        sort_by: str = "created_at",
        order: str = "desc",
        # === PIPELINE STAGE FILTER ===
        pipeline_stage_id: Optional[str] = None,  # Comma-separated IDs for multi-select
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

        Multi-select filters:
        - status, source, offering_id, pipeline_stage_id, assigned_officer_id accept comma-separated values

        Args:
            skip: Number of records to skip
            limit: Maximum number of records to return
            status: Comma-separated status filter
            assigned_officer_id: Comma-separated officer IDs (e.g. "1,2,3")
            unit_id: Filter by organization unit
            offering_id: Comma-separated offering IDs (e.g. "1,2,3")
            source: Comma-separated source filter
            search: Search term for name/email/phone
            sort_by: Column to sort by (default: created_at)
            order: Sort order (asc/desc)
            pipeline_stage_id: Comma-separated stage IDs (e.g. "stg01,stg02")

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

        # Multi-select: assigned_officer_id
        if assigned_officer_id:
            officer_ids = [int(s.strip()) for s in assigned_officer_id.split(",") if s.strip().isdigit()]
            if officer_ids:
                if len(officer_ids) == 1:
                    filters.append(models.Lead.assigned_officer_id == officer_ids[0])
                else:
                    filters.append(models.Lead.assigned_officer_id.in_(officer_ids))

        if unit_id is not None:
            filters.append(models.Lead.unit_id == unit_id)

        # Multi-select: offering_id
        if offering_id:
            offer_ids = [int(s.strip()) for s in offering_id.split(",") if s.strip().isdigit()]
            if offer_ids:
                if len(offer_ids) == 1:
                    filters.append(models.Lead.offering_id == offer_ids[0])
                else:
                    filters.append(models.Lead.offering_id.in_(offer_ids))

        if source:
            sources = [s.strip() for s in source.split(",") if s.strip()]
            if sources:
                filters.append(models.Lead.source.in_(sources))

        # Apply search
        # ✅ FIX: Normalize Unicode to NFC format for Vietnamese diacritics
        # Windows/browsers may send NFD (decomposed) but DB stores NFC (composed)
        # Example: "Hùng" NFD = "Hu" + combining accent vs NFC = single char "ù"
        if search:
            normalized_search = unicodedata.normalize('NFC', search.strip())
            search_term = f"%{normalized_search}%"
            search_conditions = or_(
                models.Lead.full_name.ilike(search_term),
                models.Lead.email.ilike(search_term),
                models.Lead.phone.ilike(search_term),
            )
            filters.append(search_conditions)

        # Multi-select: pipeline_stage_id
        if pipeline_stage_id:
            stage_ids = [s.strip() for s in pipeline_stage_id.split(",") if s.strip()]
            if stage_ids:
                if len(stage_ids) == 1:
                    filters.append(models.Lead.pipeline_stage_id == stage_ids[0])
                else:
                    filters.append(models.Lead.pipeline_stage_id.in_(stage_ids))

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

        # Apply sorting
        sort_column = getattr(models.Lead, sort_by, models.Lead.created_at)

        # Only apply activity bubble-up when sorting by urgency-related columns.
        # For other columns (e.g. created_at), use simple sort so that new leads
        # appear at the top when sorted by newest first.
        use_bubble_up = sort_by in ("cached_urgency_score", "next_activity_at")

        if use_bubble_up:
            now = datetime.now(timezone.utc)
            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            today_end = now.replace(hour=23, minute=59, second=59, microsecond=999999)

            activity_priority = case(
                (models.Lead.next_activity_at <= now, 0),  # Overdue
                (models.Lead.next_activity_at.between(today_start, today_end), 1),  # Today
                else_=2  # Future or NULL
            )

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
        else:
            if order.lower() == "desc":
                leads_query = base_query.order_by(sort_column.desc())
            else:
                leads_query = base_query.order_by(sort_column.asc())

        # ✅ Apply eager loading with ALL relationships required by schema
        leads_query = (
            leads_query.options(
                selectinload(models.Lead.offering).options(
                    selectinload(models.ProgramOffering.program),
                    selectinload(models.ProgramOffering.academic_info_history),
                ),
                selectinload(models.Lead.assigned_officer),
                selectinload(models.Lead.unit),
                selectinload(models.Lead.consultation_status).selectinload(models.ConsultationStatus.stage),
                selectinload(models.Lead.pipeline_stage),
                # ✅ FIX: Add missing eager load for application to prevent MissingGreenlet error
                selectinload(models.Lead.application),
                # NEW: AdmissionProfile for admission module
                selectinload(models.Lead.admission_profile),
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
        Get lead by email address (case-insensitive).

        Args:
            email: Email to search

        Returns:
            Lead instance or None
        """
        result = await self.db.execute(
            select(models.Lead)
            .where(func.lower(models.Lead.email) == email.lower())
            .where(models.Lead.deleted_at.is_(None))
        )
        return result.scalars().first()

    async def update_next_activity(
        self,
        lead_id: int
    ) -> None:
        """
        Update lead's next_activity_at field.

        ✅ FIXED: Finds earliest PENDING consultation regardless of time.
        Task quá hạn vẫn là next activity (nhưng overdue).
        
        Logic mới:
        - Tìm consultation có scheduled_at AND status chưa hoàn thành
        - KHÔNG filter theo time (>= now)
        - KHÔNG dùng reminder_sent

        Args:
            lead_id: Lead ID to update
        """
        from sqlalchemy import and_

        lead = await self.db.get(models.Lead, lead_id)
        if not lead:
            return

        # Các status được coi là "pending" (chưa hoàn thành)
        PENDING_STATUS_IDS = ["sts01", "sts03"]  # Lên lịch, Cần theo dõi

        result = await self.db.execute(
            select(func.min(models.Consultation.scheduled_at))
            .where(
                and_(
                    models.Consultation.lead_id == lead_id,
                    models.Consultation.scheduled_at.isnot(None),
                    models.Consultation.consultation_status_id.in_(PENDING_STATUS_IDS),
                    models.Consultation.deleted_at.is_(None),  # Exclude soft-deleted
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

    # =========================================================================
    # LEAD INSIGHTS CACHE: Aggregation methods for cache update
    # =========================================================================

    async def get_consultation_aggregates(
        self,
        lead_id: int
    ) -> dict:
        """
        Get consultation aggregates for cache update.
        
        ✅ ARCHITECTURE COMPLIANT: Repository handles all queries.
        Called by LeadCacheService to update cached fields.
        
        Args:
            lead_id: Lead ID
            
        Returns:
            Dict with: last_consultation_at, consultation_count, 
                       pending_next_activity (earliest pending task)
        """
        # Query 1: Get consultation stats (exclude soft-deleted)
        stats_query = select(
            func.max(models.Consultation.consultation_date).label("last_consultation_at"),
            func.count(models.Consultation.id).label("consultation_count"),
        ).where(
            models.Consultation.lead_id == lead_id,
            models.Consultation.deleted_at.is_(None),  # Exclude soft-deleted
        )

        stats_result = await self.db.execute(stats_query)
        stats = stats_result.one()

        # Query 2: Get scheduled_at from the LATEST consultation only
        # ✅ FIX: Return scheduled_at regardless of past/future
        # If there's a newer consultation without scheduled_at, it means the follow-up was done
        # LeadCacheService will determine if it's overdue (past) or pending (future)

        # Subquery: Get the latest consultation for this lead
        latest_consult_subq = (
            select(models.Consultation.id)
            .where(
                models.Consultation.lead_id == lead_id,
                models.Consultation.deleted_at.is_(None),
            )
            .order_by(models.Consultation.consultation_date.desc())
            .limit(1)
            .scalar_subquery()
        )

        # Get scheduled_at from the latest consultation (if it exists)
        # Don't filter by time - let LeadCacheService handle past/future logic
        pending_query = select(
            models.Consultation.scheduled_at
        ).where(
            models.Consultation.id == latest_consult_subq,
            models.Consultation.scheduled_at.isnot(None),
        )

        pending_result = await self.db.execute(pending_query)
        pending_next_activity = pending_result.scalar_one_or_none()
        
        return {
            "last_consultation_at": stats.last_consultation_at,
            "consultation_count": stats.consultation_count or 0,
            "pending_next_activity": pending_next_activity,
        }

    # =========================================================================
    # SPRINT 5: Additional Methods for lead_service Migration
    # =========================================================================

    async def get_scoring_config_by_unit(
        self,
        unit_id: int
    ) -> Optional[models.LeadScoringConfig]:
        """
        Get lead scoring config for a unit.
        
        ✅ SPRINT 5: Added for lead_service migration.
        
        Args:
            unit_id: Organization unit ID
            
        Returns:
            LeadScoringConfig or None
        """
        query = select(models.LeadScoringConfig).where(
            models.LeadScoringConfig.unit_id == unit_id
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def get_last_status_history_entry(
        self,
        lead_id: int
    ) -> Optional[models.LeadStatusHistory]:
        """
        Get the most recent status history entry for a lead.
        
        ✅ SPRINT 5: Added for lead_service revert_lead_status migration.
        
        Args:
            lead_id: Lead ID
            
        Returns:
            Most recent LeadStatusHistory or None
        """
        query = (
            select(models.LeadStatusHistory)
            .where(models.LeadStatusHistory.lead_id == lead_id)
            .order_by(
                models.LeadStatusHistory.changed_at.desc(),
                models.LeadStatusHistory.id.desc(),
            )
            .limit(1)
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def unassign_leads_from_officers(self, officer_ids: List[int]) -> int:
        """
        Unassign leads from a list of officers (set assigned_officer_id = NULL).
        
        ✅ SPRINT 7: Added for user_service bulk delete migration.
        
        Args:
            officer_ids: List of officer IDs to unassign leads from
            
        Returns:
            Number of rows updated
        """
        stmt = (
            models.Lead.__table__.update()
            .where(models.Lead.assigned_officer_id.in_(officer_ids))
            .values(assigned_officer_id=None)
        )
        result = await self.db.execute(stmt)
        return result.rowcount

    async def check_phone_conflict(
        self,
        phone: Optional[str],
        phone2: Optional[str],
        exclude_id: Optional[int] = None
    ) -> Optional[models.Lead]:
        """
        Check if any OTHER lead uses these phone numbers (Global check).
        
        Checks if:
        - lead.phone == new_phone OR
        - lead.phone == new_phone2 OR
        - lead.phone2 == new_phone OR
        - lead.phone2 == new_phone2
        
        Args:
            phone: Primary phone to check
            phone2: Secondary phone to check
            exclude_id: Lead ID to exclude from check (for updates)
            
        Returns:
            Conflicting Lead (with assigned_officer loaded) or None
        """
        # Skip if no phones provided
        if not phone and not phone2:
            return None
            
        conditions = []
        if phone:
            conditions.append(models.Lead.phone == phone)
            conditions.append(models.Lead.phone2 == phone)
        if phone2:
            conditions.append(models.Lead.phone == phone2)
            conditions.append(models.Lead.phone2 == phone2)
            
        if not conditions:
            return None
            
        query = (
            select(models.Lead)
            .options(
                selectinload(models.Lead.assigned_officer),
                selectinload(models.Lead.unit)  # ✅ FIX MissingGreenlet: Eager load unit for error message
            )
            .where(
                or_(*conditions),
                models.Lead.deleted_at.is_(None)
            )
        )
        
        if exclude_id is not None:
            query = query.where(models.Lead.id != exclude_id)
            
        result = await self.db.execute(query)
        return result.scalars().first()

    async def check_batch_phone_conflict(self, phones: list[str]) -> set[str]:
        """
        Check which phones in the provided list already exist in DB.
        Checks both phone and phone2 columns.
        
        Args:
            phones: List of phone numbers to check
            
        Returns:
            Set of phone numbers that already exist
        """
        if not phones:
            return set()
            
        # Filter out empty strings and duplicates from input
        valid_phones = {p for p in phones if p}
        if not valid_phones:
            return set()
            
        query = (
            select(models.Lead.phone, models.Lead.phone2)
            .where(
                models.Lead.deleted_at.is_(None),
                or_(
                    models.Lead.phone.in_(valid_phones),
                    models.Lead.phone2.in_(valid_phones)
                )
            )
        )
        
        result = await self.db.execute(query)
        rows = result.all()
        
        existing_phones = set()
        for row in rows:
            p1, p2 = row
            if p1 in valid_phones:
                existing_phones.add(p1)
            if p2 in valid_phones:
                existing_phones.add(p2)
                
        return existing_phones

    async def check_email_conflict(
        self,
        email: str,
        unit_id: int,
        exclude_id: Optional[int] = None
    ) -> Optional[models.Lead]:
        """
        Check if email exists in the same unit.
        
        Args:
            email: Email to check
            unit_id: Organization Unit ID
            exclude_id: Lead ID to exclude (for updates)
            
        Returns:
            Conflicting Lead or None
        """
        query = (
            select(models.Lead)
            .options(selectinload(models.Lead.assigned_officer))
            .where(
                func.lower(models.Lead.email) == email.lower(),
                models.Lead.unit_id == unit_id,
                models.Lead.deleted_at.is_(None)
            )
        )
        
        if exclude_id is not None:
            query = query.where(models.Lead.id != exclude_id)
            
        result = await self.db.execute(query)
        return result.scalars().first()

    async def check_batch_email_conflict(self, emails: list[str]) -> set[str]:
        """
        Check which emails in the provided list already exist in DB (Global check for now).
        Note: If uniqueness is enforced per-unit, this might need unit_id context.
        However, for bulk import, usually we want to know if it exists globally or we accept 
        unit_id in the file. 
        Current logic in service was: `existing_emails_in_db` (Global stream).
        
        Args:
            emails: List of emails to check
            
        Returns:
            Set of emails that already exist
        """
        if not emails:
            return set()
            
        valid_emails = {e.lower() for e in emails if e}
        if not valid_emails:
            return set()
            
        query = (
            select(models.Lead.email)
            .where(
                models.Lead.deleted_at.is_(None),
                func.lower(models.Lead.email).in_(valid_emails)
            )
        )
        
        result = await self.db.execute(query)
        # Return lowercased emails for comparison
        return {row[0].lower() for row in result.all() if row[0]}

    async def bulk_insert_leads(self, leads_data: list[dict]) -> list[int]:
        """
        Bulk insert leads and return their IDs.
        
        Args:
            leads_data: List of dictionaries matching Lead model fields
            
        Returns:
            List of created Lead IDs
        """
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        
        if not leads_data:
            return []
            
        stmt = pg_insert(models.Lead).values(leads_data).returning(models.Lead.id)
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def bulk_update_pipeline_stage(
        self,
        lead_ids: List[int],
        pipeline_stage_id: str
    ) -> int:
        """
        Bulk update pipeline_stage_id for multiple leads.
        
        ✅ PHASE 8: Replaces db.get() in router bulk_update_stage.
        Uses UPDATE ... WHERE id IN (...) for efficiency.
        
        Args:
            lead_ids: List of Lead IDs to update
            pipeline_stage_id: New pipeline stage ID
            
        Returns:
            Number of leads updated
        """
        from sqlalchemy import update
        
        if not lead_ids:
            return 0
            
        stmt = (
            update(models.Lead)
            .where(
                models.Lead.id.in_(lead_ids),
                models.Lead.deleted_at.is_(None)
            )
            .values(pipeline_stage_id=pipeline_stage_id)
        )
        result = await self.db.execute(stmt)
        return result.rowcount

    # =========================================================================
    # CONSULTATION METHODS (for response serialization)
    # =========================================================================

    async def get_consultation_with_status_stage(
        self,
        consultation_id: int
    ) -> Optional[models.Consultation]:
        """
        Get consultation with eager loaded relationships for API response.
        
        Loads:
        - officer: User who created the consultation
        - consultation_status.stage: Nested stage for ConsultationStatus schema
        
        ✅ Architecture compliant: Service calls Repository for all queries.
        
        Args:
            consultation_id: Consultation ID
            
        Returns:
            Consultation with relationships loaded, or None if not found
        """
        query = (
            select(models.Consultation)
            .options(
                selectinload(models.Consultation.officer),
                selectinload(models.Consultation.consultation_status).selectinload(models.ConsultationStatus.stage),
            )
            .where(models.Consultation.id == consultation_id)
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def get_latest_consultation(
        self,
        lead_id: int
    ) -> Optional[models.Consultation]:
        """
        Get the most recent consultation for a lead.

        Args:
            lead_id: Lead ID

        Returns:
            Most recent Consultation or None (excludes soft-deleted)
        """
        query = (
            select(models.Consultation)
            .where(
                models.Consultation.lead_id == lead_id,
                models.Consultation.deleted_at.is_(None),  # Exclude soft-deleted
            )
            .order_by(
                models.Consultation.consultation_date.desc(),
                models.Consultation.id.desc(),
            )
            .limit(1)
        )
        result = await self.db.execute(query)
        return result.scalars().first()

    async def get_recent_consultations(
        self,
        lead_id: int,
        limit: int = 5
    ) -> List[models.Consultation]:
        """
        Get recent consultations for a lead.

        Args:
            lead_id: Lead ID
            limit: Number of records to return

        Returns:
            List of Consultation objects (excludes soft-deleted)
        """
        query = (
            select(models.Consultation)
            .where(
                models.Consultation.lead_id == lead_id,
                models.Consultation.deleted_at.is_(None),  # Exclude soft-deleted
            )
            .order_by(
                models.Consultation.consultation_date.desc(),
                models.Consultation.id.desc(),
            )
            .limit(limit)
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())

    # =========================================================================
    # ✅ REASSIGN FEATURE: New methods for architecture compliance
    # =========================================================================

    async def get_by_id_for_update(
        self,
        lead_id: int
    ) -> Optional[models.Lead]:
        """
        Get lead by ID with row-level lock (FOR UPDATE).
        
        ✅ ARCHITECTURE COMPLIANT: Replaces direct query in process_officer_action.
        
        Used when modifying lead state in transactions where you need
        to prevent concurrent modifications.
        
        Args:
            lead_id: Lead ID
            
        Returns:
            Lead with lock acquired, or None if not found
        """
        query = (
            select(models.Lead)
            .where(models.Lead.id == lead_id)
            .with_for_update()
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def count_reassignments_in_period(
        self,
        officer_id: int,
        days: int = 7
    ) -> int:
        """
        Count number of reassignments by an officer within the given period.
        
        ✅ ARCHITECTURE COMPLIANT: Replaces direct query in check_reassign_quota.
        
        Used for enforcing weekly reassign quota for officers.
        
        Args:
            officer_id: Officer ID to count reassignments for
            days: Number of days to look back (default 7 = weekly)
            
        Returns:
            Number of reassignments in the period
        """
        from datetime import datetime, timedelta, timezone
        
        period_start = datetime.now(timezone.utc) - timedelta(days=days)
        
        query = (
            select(func.count(models.AssignmentLog.id))
            .where(
                models.AssignmentLog.officer_id == officer_id,
                models.AssignmentLog.method == "officer_reassign",
                models.AssignmentLog.timestamp >= period_start,
            )
        )
        result = await self.db.execute(query)
        return result.scalar() or 0

    # =========================================================================
    # ✅ RECOMMENDATION ENGINE: Methods for KPI recommendations
    # =========================================================================

    async def count_hot_leads_needing_attention(
        self,
        officer_id: int,
        days_threshold: int = 3
    ) -> int:
        """
        Count hot leads that haven't been contacted in X days.
        
        ✅ ARCHITECTURE COMPLIANT: Replaces direct query in recommendation_engine.
        
        Args:
            officer_id: Officer ID
            days_threshold: Days since last contact
            
        Returns:
            Count of hot leads needing attention
        """
        from datetime import timedelta
        
        threshold_date = datetime.now(timezone.utc) - timedelta(days=days_threshold)
        
        query = (
            select(func.count(models.Lead.id))
            .where(
                models.Lead.assigned_officer_id == officer_id,
                models.Lead.is_hot_lead == True,
                models.Lead.deleted_at.is_(None),
                models.Lead.last_consultation_at < threshold_date,
            )
        )
        result = await self.db.execute(query)
        return result.scalar() or 0

    async def count_stale_leads(
        self,
        officer_id: int,
        days_threshold: int = 14
    ) -> int:
        """
        Count leads with no activity in X days (non-final status only).
        
        ✅ ARCHITECTURE COMPLIANT: Replaces direct query in recommendation_engine.
        
        Args:
            officer_id: Officer ID
            days_threshold: Days of inactivity
            
        Returns:
            Count of stale leads
        """
        from datetime import timedelta
        
        threshold_date = datetime.now(timezone.utc) - timedelta(days=days_threshold)
        
        query = (
            select(func.count(models.Lead.id))
            .join(
                models.ConsultationStatus,
                models.Lead.consultation_status_id == models.ConsultationStatus.id,
                isouter=True
            )
            .where(
                models.Lead.assigned_officer_id == officer_id,
                models.Lead.deleted_at.is_(None),
                models.Lead.updated_at < threshold_date,
                # Only non-final status leads are considered stale
                models.ConsultationStatus.is_final_status == False,
            )
        )
        result = await self.db.execute(query)
        return result.scalar() or 0


