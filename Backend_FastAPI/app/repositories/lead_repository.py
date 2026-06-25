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

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app import models
from app.repositories.base import BaseRepository


def pending_followup_status_subquery():
    """``select(ConsultationStatus.id)`` của các status đủ điều kiện FOLLOW-UP.

    Follow-up = non-final AND không thuộc ``CANCELLED_FOLLOWUP_STATUS_IDS``.
    MỘT nguồn predicate dùng chung cho ``next_activity_at``
    (``LeadRepository._earliest_pending_scheduled``) và reminder task
    (``notification_tasks.check_consultation_reminders_task``) — KHÔNG copy
    logic để tránh lệch nhau âm thầm khi đổi định nghĩa.

    Lưu ý: is_universal KHÔNG phải tiêu chí loại — sts01/sts15 (không nghe máy /
    nhắn tin không phản hồi) là universal nhưng có scheduled_at vẫn là retry
    follow-up hợp lệ. Chỉ trạng thái HỦY (sts19) bị loại vì cancel giữ nguyên
    scheduled_at cũ (sẽ gửi nhắc lịch đã hủy nếu không loại).
    """
    from app.services.phase_manager import CANCELLED_FOLLOWUP_STATUS_IDS

    return select(models.ConsultationStatus.id).where(
        models.ConsultationStatus.is_final == False,
        models.ConsultationStatus.id.not_in(CANCELLED_FOLLOWUP_STATUS_IDS),
    )


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
                    selectinload(models.ProgramOffering.academic_info_history).selectinload(
                        models.OfferingAcademicInfo.semester_tuitions
                    ),
                ),
                selectinload(models.Lead.unit).options(
                    selectinload(models.OrganizationUnit.parent),
                    selectinload(models.OrganizationUnit.children),
                    selectinload(models.OrganizationUnit.major_programs),
                ),
                selectinload(models.Lead.assigned_officer),
                selectinload(models.Lead.pipeline_stage),
                selectinload(models.Lead.consultation_status).selectinload(models.ConsultationStatus.stage),
                selectinload(models.Lead.admission_profiles),
                # Collaborator referrer
                selectinload(models.Lead.referrer),
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
                    selectinload(models.ProgramOffering.academic_info_history).selectinload(
                        models.OfferingAcademicInfo.semester_tuitions
                    ),
                ),
                selectinload(models.Lead.unit),
                selectinload(models.Lead.assigned_officer),
                selectinload(models.Lead.pipeline_stage),
                selectinload(models.Lead.consultation_status).selectinload(models.ConsultationStatus.stage),
                selectinload(models.Lead.admission_profiles),
                # Collaborator referrer
                selectinload(models.Lead.referrer),
            )
            .where(self.model.id == lead_id)
        )

        if not include_deleted:
            query = query.where(self.model.deleted_at.is_(None))

        result = await self.db.execute(query)
        return result.scalars().first()

    def _build_filters(
        self,
        status: Optional[str] = None,
        assigned_officer_id: Optional[str] = None,
        unit_id: Optional[int] = None,
        unit_ids: Optional[List[int]] = None,
        offering_id: Optional[str] = None,
        source: Optional[str] = None,
        search: Optional[str] = None,
        pipeline_stage_id: Optional[str] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        date_field: str = "created_at",
        referrer_id: Optional[int] = None,
        validity_status: Optional[str] = None,
        score_min: Optional[int] = None,
        score_max: Optional[int] = None,
        lead_ids: Optional[List[int]] = None,
        loss_reason: Optional[str] = None,
        is_final: Optional[bool] = None,
        counts_for_funnel: Optional[bool] = None,
        # === LEAD_FILTER_UX_PLAN §4: actionable + consultation_status filters ===
        unassigned: Optional[bool] = None,
        overdue: Optional[bool] = None,
        next_activity_from: Optional[datetime] = None,
        next_activity_to: Optional[datetime] = None,
        no_consultation: Optional[bool] = None,
        is_hot: Optional[bool] = None,
        consultation_status_id: Optional[str] = None,
    ) -> list:
        """Build reusable filter list for leads queries (shared by get_filtered + get_summary)."""
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

        # unit_ids (dashboard scope) takes precedence over unit_id (manual filter)
        if unit_ids:
            filters.append(models.Lead.unit_id.in_(unit_ids))
        elif unit_id is not None:
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
            # Escape LIKE wildcards so a literal % / _ typed by the user matches
            # literally instead of acting as a wildcard (mirror vn_school_service
            # search). Backslash is PostgreSQL's default LIKE/ILIKE escape char.
            escaped_search = (
                normalized_search.replace("\\", "\\\\")
                .replace("%", "\\%")
                .replace("_", "\\_")
            )
            search_term = f"%{escaped_search}%"
            # Name: diacritic-insensitive via f_unaccent on both sides ("nguyen
            # van" → "Nguyễn Văn"), backed by ix_lead_fullname_unaccent_trgm
            # (migration leadsrch01). email/phone: plain ilike (email rarely has
            # diacritics, phone is digits) — see LEAD_FILTER_UX_PLAN §3.1/§10.5.
            search_conditions = or_(
                func.f_unaccent(models.Lead.full_name).ilike(
                    func.f_unaccent(search_term)
                ),
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
        # Filter by date_from and/or date_to on specified date_field
        ALLOWED_DATE_FIELDS = {"created_at", "updated_at", "last_consultation_at"}
        if date_from or date_to:
            if date_field not in ALLOWED_DATE_FIELDS:
                date_field = "created_at"  # Default fallback

            date_column = getattr(models.Lead, date_field)
            
            if date_from:
                filters.append(date_column >= date_from)
            if date_to:
                filters.append(date_column <= date_to)

        # === COLLABORATOR FILTERS ===
        if referrer_id is not None:
            filters.append(models.Lead.referrer_id == referrer_id)

        if validity_status:
            v_statuses = [s.strip() for s in validity_status.split(",") if s.strip()]
            if v_statuses:
                filters.append(models.Lead.validity_status.in_(v_statuses))

        # === SCORE RANGE FILTER ===
        if score_min is not None:
            filters.append(models.Lead.lead_score >= score_min)
        if score_max is not None:
            filters.append(models.Lead.lead_score <= score_max)

        # === SELECTIVE EXPORT (lead_ids) ===
        if lead_ids:
            filters.append(models.Lead.id.in_(lead_ids))

        # === LOSS REASON (EXISTS subquery on Consultation) ===
        if loss_reason:
            from sqlalchemy import exists as sa_exists
            filters.append(
                sa_exists(
                    select(models.Consultation.id).where(
                        models.Consultation.lead_id == models.Lead.id,
                        models.Consultation.loss_reason_code == loss_reason,
                    )
                )
            )

        # === CONSULTATION STATUS FILTERS (correlated subquery) ===
        # V12: Match dashboard KPI definition for active leads and funnel counts
        if is_final is not None:
            from sqlalchemy import exists as sa_exists
            final_subq = select(models.ConsultationStatus.id).where(
                models.ConsultationStatus.id == models.Lead.consultation_status_id,
                models.ConsultationStatus.is_final == True,
            )
            if is_final:
                filters.append(sa_exists(final_subq))
            else:
                # Non-final: is_final=False OR consultation_status_id IS NULL
                filters.append(~sa_exists(final_subq))

        if counts_for_funnel is not None:
            from sqlalchemy import exists as sa_exists
            funnel_subq = select(models.ConsultationStatus.id).where(
                models.ConsultationStatus.id == models.Lead.consultation_status_id,
                models.ConsultationStatus.counts_for_funnel == counts_for_funnel,
            )
            filters.append(sa_exists(funnel_subq))

        # === ACTIONABLE FILTERS (LEAD_FILTER_UX_PLAN §4) ===
        # Bool convention: only add a predicate when the param is True.
        # None/False ⇒ no filter (avoid "inverting" the meaning — memory
        # empty-filter-falsy-check-audit; use `is True`, not `if param`).
        if unassigned is True:
            filters.append(models.Lead.assigned_officer_id.is_(None))

        if overdue is True:
            # Realtime predicate via func.now() (DB-side, tz-correct).
            # Deliberately NOT the materialized is_overdue column (can go stale).
            filters.append(
                and_(
                    models.Lead.next_activity_at.is_not(None),
                    models.Lead.next_activity_at < func.now(),
                )
            )

        if next_activity_from is not None:
            filters.append(models.Lead.next_activity_at >= next_activity_from)
        if next_activity_to is not None:
            filters.append(models.Lead.next_activity_at <= next_activity_to)

        if no_consultation is True:
            # consultation_count is NOT NULL default 0 (lead.py:169) → no OR IS NULL.
            filters.append(models.Lead.consultation_count == 0)

        if is_hot is True:
            filters.append(models.Lead.is_hot_lead.is_(True))

        # Multi-select: consultation_status_id (mirror pipeline_stage_id above)
        if consultation_status_id:
            cs_ids = [s.strip() for s in consultation_status_id.split(",") if s.strip()]
            if cs_ids:
                if len(cs_ids) == 1:
                    filters.append(models.Lead.consultation_status_id == cs_ids[0])
                else:
                    filters.append(models.Lead.consultation_status_id.in_(cs_ids))

        return filters

    async def get_summary(self, filters: list) -> dict:
        """Compute aggregate summary over the full filtered set (no pagination)."""
        summary_query = select(
            func.count(models.Lead.id).label("total_count"),
            func.count(models.Lead.id).filter(
                models.Lead.status == "new"
            ).label("new_count"),
            func.count(models.Lead.id).filter(
                models.Lead.is_hot_lead == True  # noqa: E712
            ).label("high_score_count"),
            func.count(models.Lead.id).filter(
                models.Lead.status == "converted"
            ).label("converted_count"),
        )
        if filters:
            summary_query = summary_query.where(*filters)

        result = await self.db.execute(summary_query)
        row = result.one()
        total = row.total_count or 0
        converted = row.converted_count or 0
        return {
            "new_count": row.new_count or 0,
            "high_score_count": row.high_score_count or 0,
            "converted_count": converted,
            "conversion_rate": round((converted / total) * 100, 1) if total > 0 else 0.0,
        }

    async def get_filtered(
        self,
        skip: int = 0,
        limit: int = 10,
        status: Optional[str] = None,
        assigned_officer_id: Optional[str] = None,
        unit_id: Optional[int] = None,
        unit_ids: Optional[List[int]] = None,
        offering_id: Optional[str] = None,
        source: Optional[str] = None,
        search: Optional[str] = None,
        sort_by: str = "created_at",
        order: str = "desc",
        pipeline_stage_id: Optional[str] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        date_field: str = "created_at",
        referrer_id: Optional[int] = None,
        validity_status: Optional[str] = None,
        score_min: Optional[int] = None,
        score_max: Optional[int] = None,
        lead_ids: Optional[List[int]] = None,
        loss_reason: Optional[str] = None,
        is_final: Optional[bool] = None,
        counts_for_funnel: Optional[bool] = None,
        # === LEAD_FILTER_UX_PLAN §4: actionable + consultation_status filters ===
        unassigned: Optional[bool] = None,
        overdue: Optional[bool] = None,
        next_activity_from: Optional[datetime] = None,
        next_activity_to: Optional[datetime] = None,
        no_consultation: Optional[bool] = None,
        is_hot: Optional[bool] = None,
        consultation_status_id: Optional[str] = None,
    ) -> Tuple[int, List[models.Lead]]:
        """Get filtered list of leads with pagination and eager loading."""
        filters = self._build_filters(
            status=status, assigned_officer_id=assigned_officer_id,
            unit_id=unit_id, unit_ids=unit_ids,
            offering_id=offering_id, source=source,
            search=search, pipeline_stage_id=pipeline_stage_id,
            date_from=date_from, date_to=date_to, date_field=date_field,
            referrer_id=referrer_id, validity_status=validity_status,
            score_min=score_min, score_max=score_max, lead_ids=lead_ids,
            loss_reason=loss_reason,
            is_final=is_final, counts_for_funnel=counts_for_funnel,
            unassigned=unassigned, overdue=overdue,
            next_activity_from=next_activity_from,
            next_activity_to=next_activity_to,
            no_consultation=no_consultation, is_hot=is_hot,
            consultation_status_id=consultation_status_id,
        )

        base_query = select(models.Lead)
        count_query = select(func.count(models.Lead.id))

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
        ALLOWED_SORT_FIELDS = {
            "created_at", "updated_at", "full_name", "email", "phone",
            "lead_score", "status", "source", "last_consultation_at",
            "next_activity_at", "consultation_count", "cached_urgency_score",
        }
        if sort_by not in ALLOWED_SORT_FIELDS:
            sort_by = "created_at"
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
                    sort_column.desc(),
                    models.Lead.id.desc()
                )
            else:
                leads_query = base_query.order_by(
                    activity_priority.asc(),
                    models.Lead.next_activity_at.asc().nullslast(),
                    sort_column.asc(),
                    models.Lead.id.desc()
                )
        else:
            if order.lower() == "desc":
                leads_query = base_query.order_by(sort_column.desc(), models.Lead.id.desc())
            else:
                leads_query = base_query.order_by(sort_column.asc(), models.Lead.id.desc())

        # ✅ Apply eager loading with ALL relationships required by schema
        leads_query = (
            leads_query.options(
                selectinload(models.Lead.offering).options(
                    selectinload(models.ProgramOffering.program),
                    selectinload(models.ProgramOffering.academic_info_history).selectinload(
                        models.OfferingAcademicInfo.semester_tuitions
                    ),
                ),
                selectinload(models.Lead.assigned_officer),
                selectinload(models.Lead.unit),
                selectinload(models.Lead.consultation_status).selectinload(models.ConsultationStatus.stage),
                selectinload(models.Lead.pipeline_stage),
                selectinload(models.Lead.admission_profiles),
                # Collaborator referrer
                selectinload(models.Lead.referrer),
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

    async def _earliest_pending_scheduled(
        self,
        lead_id: int
    ) -> Optional[datetime]:
        """
        MIN(scheduled_at) của các consultation còn FOLLOW-UP (cần liên hệ tiếp).

        Nguồn sự thật DUY NHẤT cho ``next_activity_at`` — dùng chung bởi
        ``update_next_activity`` (ghi thẳng field) và
        ``get_consultation_aggregates`` (cache service đọc để set
        ``next_activity_at`` + ``is_overdue``), và CÙNG predicate với reminder
        task (``pending_followup_status_subquery``) → một nguồn duy nhất.

        Follow-up = ``ConsultationStatus`` non-final AND không thuộc
        ``CANCELLED_FOLLOWUP_STATUS_IDS``. is_universal KHÔNG phải tiêu chí:
        sts01/sts15 (không nghe máy / nhắn tin không phản hồi) có scheduled_at
        VẪN là hẹn gọi lại cần tính; chỉ sts19 (đã hủy) bị loại. KHÔNG dùng
        ``reminder_sent``.

        ✅ B1 — "hẹn còn sống": consultation là append-only và backend KHÔNG bao
        giờ tự clear ``scheduled_at``, nên một hẹn QUÁ KHỨ ở consultation cũ có
        thể đã được xử lý bằng một lần liên hệ MỚI HƠN (dòng mới không đặt lịch).
        Nếu tính hết mọi hẹn quá khứ → hồi sinh hẹn đã xong thành "quá hạn" giả
        (đo prod 2026-06-19: 0 → 41 lead, 100% giả). Quy tắc:
        - ``scheduled_at`` TƯƠNG LAI (>= now) → luôn tính (hẹn sắp tới).
        - ``scheduled_at`` QUÁ KHỨ → chỉ tính nếu thuộc consultation MỚI NHẤT
          của lead (``consultation_date`` = MAX) — tức officer chưa liên hệ lại
          sau đó. "Latest" theo ``consultation_date`` (cùng định nghĩa với
          update-consultation flow + get_consultation_aggregates cũ).

        Returns:
            ``datetime`` sớm nhất, hoặc ``None`` nếu không có hẹn còn sống.
        """
        # consultation_date mới nhất của lead = mốc "lần liên hệ gần nhất".
        latest_consultation_date = (
            select(func.max(models.Consultation.consultation_date))
            .where(
                models.Consultation.lead_id == lead_id,
                models.Consultation.deleted_at.is_(None),
            )
            .scalar_subquery()
        )

        result = await self.db.execute(
            select(func.min(models.Consultation.scheduled_at)).where(
                models.Consultation.lead_id == lead_id,
                models.Consultation.scheduled_at.isnot(None),
                models.Consultation.consultation_status_id.in_(
                    pending_followup_status_subquery()
                ),
                models.Consultation.deleted_at.is_(None),  # Exclude soft-deleted
                or_(
                    # Hẹn tương lai luôn còn sống.
                    models.Consultation.scheduled_at >= func.now(),
                    # Hẹn quá khứ chỉ còn sống nếu CHƯA bị liên hệ mới hơn vượt qua.
                    models.Consultation.consultation_date
                    == latest_consultation_date,
                ),
            )
        )
        return result.scalar_one_or_none()

    async def update_next_activity(
        self,
        lead_id: int
    ) -> None:
        """
        Update lead's next_activity_at field.

        Hẹn quá hạn (ở consultation mới nhất) vẫn là next activity — chỉ là overdue.

        Logic (xem ``_earliest_pending_scheduled`` — nguồn dùng chung):
        - MIN(scheduled_at) của hẹn follow-up "còn sống" (non-final, KHÔNG hủy)
        - Hẹn tương lai luôn tính; hẹn quá khứ chỉ tính nếu thuộc consultation
          MỚI NHẤT của lead (B1 — tránh hồi sinh hẹn đã xử lý thành quá hạn giả)
        - KHÔNG dùng reminder_sent

        Args:
            lead_id: Lead ID to update
        """
        lead = await self.db.get(models.Lead, lead_id)
        if not lead:
            return

        lead.next_activity_at = await self._earliest_pending_scheduled(lead_id)
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
        unit_ids: Optional[List[int]] = None,
        officer_id: Optional[int] = None,
    ) -> dict:
        """
        Count leads grouped by status.

        Args:
            unit_id: Filter by single unit (manual filter)
            unit_ids: Filter by multiple units (dashboard scope, takes precedence)
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

        if unit_ids:
            query = query.where(models.Lead.unit_id.in_(unit_ids))
        elif unit_id is not None:
            query = query.where(models.Lead.unit_id == unit_id)

        if officer_id is not None:
            query = query.where(models.Lead.assigned_officer_id == officer_id)

        result = await self.db.execute(query)
        return {row.status: row.count for row in result}

    async def count_by_consultation_status(self, filters: list) -> dict:
        """
        Count leads grouped by consultation_status_id over a pre-built filter set.

        Mirrors get_summary's filter contract (shared _build_filters output) so
        the "Giai đoạn" filter tree honours the EXACT same scope as the lead
        list. The caller passes scope-only filters → "static per-scope" counts
        (Documents/LEAD_STAGE_TREE_FILTER_PLAN.md §2). Leads with NULL
        consultation_status_id are bucketed under "__null__" so the tree never
        hides a lead.
        """
        query = (
            select(
                models.Lead.consultation_status_id,
                func.count(models.Lead.id).label("count"),
            )
            .group_by(models.Lead.consultation_status_id)
        )
        if filters:
            query = query.where(*filters)

        result = await self.db.execute(query)
        return {
            ("__null__" if row.consultation_status_id is None
             else row.consultation_status_id): row.count
            for row in result
        }

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
                       pending_next_activity (earliest PENDING scheduled_at;
                       xem _earliest_pending_scheduled — cùng nguồn với
                       update_next_activity)
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

        # Query 2: earliest PENDING scheduled_at — CÙNG NGUỒN với
        # update_next_activity (qua _earliest_pending_scheduled) nên cache
        # service và đường ghi trực tiếp luôn nhất quán next_activity_at.
        # Trước đây lấy scheduled_at của consultation MỚI NHẤT (bất kể status,
        # thiếu filter is_universal) → lệch với update_next_activity và bỏ sót
        # hẹn pending cũ khi có consultation mới hơn không đặt lịch. Đã hợp nhất.
        pending_next_activity = await self._earliest_pending_scheduled(lead_id)

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
        Check which normalized phones in the provided list already exist in DB.
        Queries the lead_phone_identity table (canonical source of truth)
        instead of raw lead.phone/lead.phone2 columns.

        Args:
            phones: List of normalized phone numbers to check

        Returns:
            Set of normalized phone numbers that already exist (active)
        """
        if not phones:
            return set()

        # Filter out empty strings and duplicates from input
        valid_phones = {p for p in phones if p}
        if not valid_phones:
            return set()

        query = (
            select(models.LeadPhoneIdentity.phone_normalized)
            .where(
                models.LeadPhoneIdentity.deleted_at.is_(None),
                models.LeadPhoneIdentity.phone_normalized.in_(valid_phones),
            )
        )

        result = await self.db.execute(query)
        return {row[0] for row in result.all()}

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

    async def check_batch_email_conflict(
        self, emails: list[str], unit_id: Optional[int] = None
    ) -> set[str]:
        """
        Check which emails in the provided list already exist in DB.

        Args:
            emails: List of emails to check
            unit_id: If provided, only check within this unit (per-unit scope).
                     If None, check globally (backward-compatible fallback).

        Returns:
            Set of lowercased emails that already exist
        """
        if not emails:
            return set()

        valid_emails = {e.lower() for e in emails if e}
        if not valid_emails:
            return set()

        conditions = [
            models.Lead.deleted_at.is_(None),
            func.lower(models.Lead.email).in_(valid_emails),
        ]
        if unit_id is not None:
            conditions.append(models.Lead.unit_id == unit_id)

        query = select(models.Lead.email).where(*conditions)

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
        lead_id: int,
        *,
        populate_existing: bool = False,
    ) -> Optional[models.Lead]:
        """
        Get lead by ID with row-level lock (FOR UPDATE).

        ✅ ARCHITECTURE COMPLIANT: Replaces direct query in process_officer_action.

        Used when modifying lead state in transactions where you need
        to prevent concurrent modifications.

        Args:
            lead_id: Lead ID
            populate_existing: When True, OVERWRITE the in-session instance's
                attributes from the freshly-locked row (SQLAlchemy otherwise
                returns the cached identity-map instance WITHOUT refreshing it,
                so a re-check after the lock would read pre-lock/stale values —
                e.g. a lead already loaded by a non-locking IDOR dependency).
                Set True when the caller re-validates state under the lock.

        Returns:
            Lead with lock acquired, or None if not found
        """
        query = (
            select(models.Lead)
            .where(models.Lead.id == lead_id)
            .with_for_update()
        )
        if populate_existing:
            query = query.execution_options(populate_existing=True)
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
                # Include leads with NULL status (no consultation yet)
                or_(
                    models.ConsultationStatus.is_final == False,
                    models.Lead.consultation_status_id.is_(None)
                ),
            )
        )
        result = await self.db.execute(query)
        return result.scalar() or 0

    # =========================================================================
    # COLLABORATOR SYSTEM (Phase 1)
    # =========================================================================

    async def check_first_touch_for_update(self, phone: str) -> Optional[models.Lead]:
        """
        Check first-touch lock: Find existing lead by phone with FOR UPDATE lock.

        Used in CTV claim workflow to prevent race conditions.
        Loads referrer relationship to check if lead already has a referrer.

        Args:
            phone: Phone number to check

        Returns:
            Lead with FOR UPDATE lock, or None
        """
        result = await self.db.execute(
            select(models.Lead)
            .options(selectinload(models.Lead.referrer))
            .where(
                or_(
                    models.Lead.phone == phone,
                    models.Lead.phone2 == phone,
                ),
                models.Lead.deleted_at.is_(None),
            )
            .with_for_update()
        )
        return result.scalars().first()

    async def reassign_unprocessed_leads(
        self,
        referrer_id: int,
        from_officer_id: int,
        to_officer_id: int,
        to_unit_id: int,
        only_statuses: set[str],
    ) -> int:
        """
        Reassign unprocessed leads from one officer to another (EC-1: CTV re-assignment).

        Only reassigns leads that:
        - Have the given referrer_id
        - Are assigned to from_officer_id
        - Have status in only_statuses (e.g. {"new"})
        - Are not soft-deleted

        Args:
            referrer_id: CTV who referred these leads
            from_officer_id: Current officer
            to_officer_id: New officer
            to_unit_id: New officer's unit
            only_statuses: Only reassign leads with these statuses

        Returns:
            Number of leads reassigned
        """
        from sqlalchemy import update

        stmt = (
            update(models.Lead)
            .where(
                models.Lead.referrer_id == referrer_id,
                models.Lead.assigned_officer_id == from_officer_id,
                models.Lead.status.in_(only_statuses),
                models.Lead.deleted_at.is_(None),
            )
            .values(
                assigned_officer_id=to_officer_id,
                unit_id=to_unit_id,
            )
        )
        result = await self.db.execute(stmt)
        return result.rowcount

    async def get_leads_by_referrer(
        self,
        referrer_id: int,
        skip: int = 0,
        limit: int = 10,
    ) -> Tuple[int, List[models.Lead]]:
        """
        Get leads referred by a collaborator (for CTV self-service).
        No unit filter — EC-5: cross-unit visibility.

        Args:
            referrer_id: Collaborator ID
            skip: Offset
            limit: Max results

        Returns:
            Tuple of (total_count, leads)
        """
        filters = [
            models.Lead.referrer_id == referrer_id,
            models.Lead.deleted_at.is_(None),
        ]

        count_query = select(func.count(models.Lead.id)).where(*filters)
        total_result = await self.db.execute(count_query)
        total_count = total_result.scalar_one_or_none() or 0

        if total_count == 0:
            return 0, []

        leads_query = (
            select(models.Lead)
            .options(
                selectinload(models.Lead.assigned_officer),
                selectinload(models.Lead.pipeline_stage),
                selectinload(models.Lead.consultation_status),
                selectinload(models.Lead.unit),
            )
            .where(*filters)
            .order_by(models.Lead.created_at.desc())
            .offset(skip)
            .limit(limit)
        )

        result = await self.db.execute(leads_query)
        leads = list(result.scalars().all())

        return total_count, leads

    async def count_leads_by_referrer_and_validity(
        self,
        referrer_id: int,
    ) -> dict:
        """
        Count leads by validity_status for a collaborator (for CTV stats).
        Uses a single GROUP BY query instead of 4 separate COUNT queries.

        Returns:
            Dict with total, valid, qualified, converted counts
        """
        # Single optimized query with GROUP BY
        result = await self.db.execute(
            select(
                models.Lead.validity_status,
                models.Lead.status,
                func.count(models.Lead.id).label("cnt"),
            )
            .where(
                models.Lead.referrer_id == referrer_id,
                models.Lead.deleted_at.is_(None),
            )
            .group_by(models.Lead.validity_status, models.Lead.status)
        )
        rows = result.all()

        total = 0
        valid = 0
        qualified = 0
        converted = 0

        for row in rows:
            total += row.cnt
            if row.validity_status == "valid":
                valid += row.cnt
            elif row.validity_status == "qualified":
                qualified += row.cnt
            if row.status == "converted":
                converted += row.cnt

        return {
            "total_leads": total,
            "valid_leads": valid,
            "qualified_leads": qualified,
            "converted_leads": converted,
        }

    # =========================================================================
    # PHONE IDENTITY METHODS (PR3: True Phone Identity Model)
    # =========================================================================

    async def register_phone_identities(
        self,
        lead_id: int,
        phone: Optional[str],
        phone2: Optional[str] = None,
    ) -> None:
        """
        Insert phone identity rows for a lead.

        Called after creating a lead. Inserts one row per non-null phone
        into lead_phone_identity with deleted_at=NULL so the partial
        unique index enforces system-wide uniqueness.

        Args:
            lead_id: Lead ID
            phone: Primary phone (normalized)
            phone2: Secondary phone (normalized, optional)
        """
        from app.utils.phone_helpers import normalize_vietnam_phone

        for slot, raw_phone in [("phone", phone), ("phone2", phone2)]:
            if not raw_phone:
                continue
            normalized = normalize_vietnam_phone(raw_phone) or raw_phone
            identity = models.LeadPhoneIdentity(
                lead_id=lead_id,
                phone_normalized=normalized,
                slot=slot,
                deleted_at=None,
            )
            self.db.add(identity)

    async def unregister_phone_identities(self, lead_id: int) -> None:
        """
        Soft-delete all phone identity rows for a lead.

        Called when a lead is soft-deleted. Sets deleted_at on all
        active identity rows so the partial unique index releases the
        phone numbers for reuse.

        Args:
            lead_id: Lead ID
        """
        from sqlalchemy import update

        now = datetime.now(timezone.utc)
        stmt = (
            update(models.LeadPhoneIdentity)
            .where(
                models.LeadPhoneIdentity.lead_id == lead_id,
                models.LeadPhoneIdentity.deleted_at.is_(None),
            )
            .values(deleted_at=now)
        )
        await self.db.execute(stmt)

    async def restore_phone_identities(self, lead_id: int) -> None:
        """
        Restore (un-soft-delete) phone identity rows for a lead.

        Called when a lead is restored. Clears deleted_at so the partial
        unique index re-enforces uniqueness. The caller must handle
        IntegrityError if the phone is now taken by another lead.

        Args:
            lead_id: Lead ID
        """
        from sqlalchemy import update

        stmt = (
            update(models.LeadPhoneIdentity)
            .where(
                models.LeadPhoneIdentity.lead_id == lead_id,
                models.LeadPhoneIdentity.deleted_at.isnot(None),
            )
            .values(deleted_at=None)
        )
        await self.db.execute(stmt)

    async def update_phone_identities(
        self,
        lead_id: int,
        phone: Optional[str],
        phone2: Optional[str] = None,
    ) -> None:
        """
        Replace all phone identity rows for a lead.

        Called when phone or phone2 is updated. Hard-deletes existing
        rows and inserts new ones so the partial unique index validates
        the new values.

        Args:
            lead_id: Lead ID
            phone: New primary phone (normalized)
            phone2: New secondary phone (normalized, optional)
        """
        from sqlalchemy import delete

        # Hard-delete old identity rows (they're an auxiliary index, not audit data)
        stmt = delete(models.LeadPhoneIdentity).where(
            models.LeadPhoneIdentity.lead_id == lead_id
        )
        await self.db.execute(stmt)

        # Insert new identity rows
        await self.register_phone_identities(lead_id, phone, phone2)

