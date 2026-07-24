# app/repositories/admission_repository.py
"""
✅ SPRINT 6: Admission Repository

Admission-specific data access layer.
Handles AdmissionProfile, Student CRUD operations and validation queries.

Benefits:
- Centralized admission query logic
- Optimized eager loading for profile views
- Testable with repository mocks
- Separates SQL from business logic
"""

import logging
from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional, Tuple
import unicodedata

log = logging.getLogger(__name__)

from sqlalchemy import select, or_, and_, func, desc, asc, distinct
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, raiseload, selectinload

from app import models
from app.models import ProfileSubjectScore, ProfileDocument
from app.models.admission_config.admission_path import AdmissionPath
from app.models.admission_config.path_subject_group import (
    PathSubjectGroupConfig,
)
from app.models.admission_config.subject import (
    SubjectGroup,
    SubjectGroupSubject,
)
from app.models.admission_profile_choice import (
    AdmissionProfileChoice,
    ProfileChoiceScore,
)
from app.repositories.base import BaseRepository
from app.utils.text_helpers import LIKE_ESCAPE_CHAR, escape_like_pattern


# Phase 3 multi-NV: eager-load chain cho AdmissionProfile.choices + nested
# relations cần thiết để Pydantic AdmissionProfileChoiceResponse compute
# display_path_name + display_program_name + display_degree_level +
# display_subject_group_name + scores nested. Without explicit selectinload,
# lazy access trong async context raises MissingGreenlet (matches pattern
# admission_profile_choice_repository.py:60-83 get_choice_for_user).
#
# Phase 3 follow-up Q1: chain academic_info → offering → program để
# Pydantic compute_display_fields lấy được program.name + degree_level
# (trước fix: chỉ load academic_info → program lazy → swallowed → empty
# → display "2026 - hoc_ba - DOT_1" mất ngành/trình độ).
def _choices_eager_load_options() -> tuple:
    # P0 hotfix multi-NV (2026-06-04): +2 legs so the sync eligibility/
    # submit/display helpers (validate_choice_scores_complete +
    # AdmissionProfileChoiceResponse._compute_display_fields) never lazy-load
    # in async context (MissingGreenlet):
    #   * subject_group → subject_mappings → subject — _resolve_allowed_subjects
    #     walks the M2M to list allowed combo subject codes.
    #   * admission_path → criteria — per-NV computed_total_score scores via
    #     AdmissionScoringService.calculate_score(criteria=path.criteria, …).
    return (
        selectinload(models.AdmissionProfile.choices).selectinload(
            AdmissionProfileChoice.admission_path
        ).selectinload(AdmissionPath.academic_info)
        .selectinload(models.OfferingAcademicInfo.offering)
        .selectinload(models.ProgramOffering.program),
        selectinload(models.AdmissionProfile.choices).selectinload(
            AdmissionProfileChoice.admission_path
        ).selectinload(AdmissionPath.admission_method),
        selectinload(models.AdmissionProfile.choices).selectinload(
            AdmissionProfileChoice.admission_path
        ).selectinload(AdmissionPath.admission_round),
        selectinload(models.AdmissionProfile.choices).selectinload(
            AdmissionProfileChoice.admission_path
        ).selectinload(AdmissionPath.criteria),
        selectinload(models.AdmissionProfile.choices).selectinload(
            AdmissionProfileChoice.path_subject_group_config
        ).selectinload(PathSubjectGroupConfig.subject_group)
        .selectinload(SubjectGroup.subject_mappings)
        .selectinload(SubjectGroupSubject.subject),
        selectinload(models.AdmissionProfile.choices).selectinload(
            AdmissionProfileChoice.scores
        ).selectinload(ProfileChoiceScore.subject),
    )


# =============================================================================
# Học phí HK1 aggregate (Admission List v2)
# =============================================================================
# Dùng chung cho: cột tiền "Đã đóng / Còn lại" + filter "Quá hạn" + sort "Còn lại".
# HK1-predicate mirror ``fee_calculation_service.is_hk1_settled_fee``:
#   tuition + semester_no == 1 + status != cancelled.
# ⚠️ Bản SQL SONG SINH thứ hai: ``services/assignment_service._hk1_fee_exists``
# (giảm trừ tải học phí khỏi phân công lead) — correlate tới Lead thay vì
# AdmissionProfile. Đổi phạm vi HK1 ở đây thì PHẢI sửa cả bên đó, nếu không bảng
# "điểm bận" và danh sách hồ sơ sẽ nói hai con số khác nhau về cùng một hồ sơ.
# Correlate tới AdmissionProfile (outer) để chạy như scalar subquery / EXISTS
# trong query list — KHÔNG N+1 (aggregate, không phải relationship eager-load).
def _hk1_fee_predicate():
    """Correlated predicate: fee HK1 của AdmissionProfile (outer)."""
    from app.models.finance import Fee, FeeStatusEnum
    return and_(
        Fee.admission_profile_id == models.AdmissionProfile.id,
        Fee.fee_type == "tuition",
        Fee.semester_no == 1,
        Fee.status != FeeStatusEnum.cancelled,
    )


def _hk1_paid_subquery():
    """Σ paid_amount fee HK1. coalesce→0 BẮT BUỘC (chưa có HK1 → SUM NULL)."""
    from app.models.finance import Fee
    return (
        select(func.coalesce(func.sum(Fee.paid_amount), 0))
        .where(_hk1_fee_predicate())
        .correlate(models.AdmissionProfile)
        .scalar_subquery()
    )


def _hk1_remaining_subquery():
    """Σ (final − paid − waived) fee HK1. coalesce→0 (cùng lý do)."""
    from app.models.finance import Fee
    return (
        select(
            func.coalesce(
                func.sum(Fee.final_amount - Fee.paid_amount - Fee.waived_amount), 0
            )
        )
        .where(_hk1_fee_predicate())
        .correlate(models.AdmissionProfile)
        .scalar_subquery()
    )


def _hk1_final_subquery():
    """Σ final_amount fee HK1. coalesce→0. Dùng để phân biệt 'có fee HK1' (final>0,
    kể cả miễn 100%) với 'chưa có HK1' (final=0) trong _hk1_status."""
    from app.models.finance import Fee
    return (
        select(func.coalesce(func.sum(Fee.final_amount), 0))
        .where(_hk1_fee_predicate())
        .correlate(models.AdmissionProfile)
        .scalar_subquery()
    )


def _hk1_overdue_exists(today: date):
    """EXISTS hóa đơn HK1 quá hạn — mirror ``routers/invoices._invoice_is_overdue``
    (status IN OVERDUE_DERIVED_STATUSES AND due_date < today)."""
    from app.models.finance import Fee, Invoice, OVERDUE_DERIVED_STATUSES
    return (
        select(Invoice.id)
        .join(Fee, Invoice.fee_id == Fee.id)
        .where(
            _hk1_fee_predicate(),
            Invoice.status.in_(OVERDUE_DERIVED_STATUSES),
            Invoice.due_date < today,
        )
        .correlate(models.AdmissionProfile)
        .exists()
    )


def _hk1_status(paid, remaining, overdue, final) -> str:
    """(paid, remaining, overdue, final) → trạng thái hiển thị. BE emit, FE chỉ map
    màu (thin-client). Normalize None→0 phòng hồ sơ chưa có HK1 (tránh None>0 → 500).

    ``final`` = Σ final_amount HK1: phân biệt 'có fee HK1' (final>0, KỂ CẢ miễn
    100% với paid=0/remaining=0) khỏi 'chưa có HK1' (final=0 → "none"). Nếu chỉ
    xét paid/remaining thì fee miễn-toàn-phần (paid=0, remaining=0) bị gán nhầm
    "none" thay vì đã tất toán."""
    paid = paid or Decimal("0")
    remaining = remaining or Decimal("0")
    final = final or Decimal("0")
    if final <= 0:
        return "none"            # chưa có fee HK1 (hoặc chỉ có fee đã hủy)
    if overdue:
        return "overdue"
    if remaining <= 0:
        return "paid"            # tất toán: đóng đủ HOẶC miễn 100%
    if paid > 0:
        return "partial"
    return "unpaid"              # remaining > 0, chưa đóng đồng nào


class AdmissionRepository(BaseRepository[models.AdmissionProfile]):
    """Repository for AdmissionProfile model operations."""

    def __init__(self, db: AsyncSession):
        """
        Initialize Admission repository.
        
        Args:
            db: SQLAlchemy async session
        """
        super().__init__(db, models.AdmissionProfile)

    async def get_by_id_for_update(
        self,
        profile_id: int,
        *,
        populate_existing: bool = False,
        with_choices: bool = False,
    ) -> Optional[models.AdmissionProfile]:
        """Lock the AdmissionProfile row (``SELECT ... FOR UPDATE``).

        Serializes the "fee sees N choices" vs "add/delete/reorder choice"
        race: both fee creation (``FeeCalculationService.calculate_fee``) and
        every NV-structure mutation acquire THIS row lock first, then
        re-validate state under it within the same transaction.

        ``lead`` is ``selectinload``-ed (a separate SELECT) instead of the
        mapper-default ``lazy="joined"`` so the locking query carries no OUTER
        JOIN — Postgres rejects ``FOR UPDATE`` on the nullable side of an outer
        join. ``with_choices`` adds a ``selectinload`` of ``choices`` so the
        caller can re-check ``is_fee_eligible`` under the lock.

        ``raiseload("*")`` suppresses the AdmissionProfile mapper's ~12 other
        ``lazy="selectin"`` relations (student / documents / fees / audit
        ``*_by`` …) that would otherwise all re-fire on this entity load — the
        only consumer (``calculate_fee``) needs just ``lead`` + ``choices``. Any
        stray access to a non-eager-loaded relation then RAISES (caught in
        tests) instead of silently lazy-loading (runtime-only MissingGreenlet in
        async). Scalar columns + ``__dict__.get`` reads are unaffected.

        Args:
            profile_id: AdmissionProfile ID.
            populate_existing: overwrite any in-session instance's attributes
                from the freshly-locked row (otherwise the identity-map copy
                loaded by a non-locking IDOR dependency stays stale on re-check).
            with_choices: eager-load ``choices`` for an under-lock eligibility
                re-check.
        """
        query = (
            select(models.AdmissionProfile)
            .where(models.AdmissionProfile.id == profile_id)
            .options(
                raiseload("*"),
                selectinload(models.AdmissionProfile.lead),
            )
            .with_for_update(of=models.AdmissionProfile)
        )
        if with_choices:
            query = query.options(
                selectinload(models.AdmissionProfile.choices)
            )
        if populate_existing:
            query = query.execution_options(populate_existing=True)
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def get_filtered(
        self,
        skip: int = 0,
        limit: int = 50,
        unit_id: Optional[int] = None,
        **filters
    ) -> List[models.AdmissionProfile]:
        """
        Get filtered list of admission profiles with pagination.
        
        Args:
            skip: Number of records to skip
            limit: Maximum records to return
            unit_id: Filter by lead.unit_id (for IDOR protection)
            **filters: Filter parameters (status, lead_id)
            
        Returns:
            List of AdmissionProfile instances
        """
        query = (
            select(models.AdmissionProfile)
            .join(models.Lead)  # Join for unit_id filter
            .options(
                joinedload(models.AdmissionProfile.lead),
                selectinload(models.AdmissionProfile.student),
                selectinload(models.AdmissionProfile.subject_scores).selectinload(ProfileSubjectScore.subject),
                selectinload(models.AdmissionProfile.documents).joinedload(ProfileDocument.document_type),
            )
            .offset(skip)
            .limit(limit)
        )
        
        # Exclude profiles whose parent Lead is soft-deleted. NOTE: this method
        # is currently unreferenced (dead) — kept defensively in case it is
        # revived; safe to remove the whole method in a separate cleanup.
        query = query.where(models.Lead.deleted_at.is_(None))

        # IDOR Filter: Filter at DB level for non-admin users
        if unit_id is not None:
            query = query.where(models.Lead.unit_id == unit_id)

        if filters.get("status"):
            query = query.where(models.AdmissionProfile.status == filters["status"])
        
        if filters.get("lead_id"):
            query = query.where(models.AdmissionProfile.lead_id == filters["lead_id"])
            
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_filtered_with_count(
        self,
        skip: int = 0,
        limit: int = 50,
        unit_id: Optional[int] = None,
        assigned_officer_id: Optional[int] = None,
        search: Optional[str] = None,
        statuses: Optional[List[str]] = None,
        major_ids: Optional[List[int]] = None,
        academic_year: Optional[int] = None,
        degree_level: Optional[str] = None,
        payment_status: Optional[str] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        sort_by: str = "created_at",
        order: str = "desc",
        assigned_officer_ids: Optional[List[int]] = None,
        assigned_reviewer_ids: Optional[List[int]] = None,
        unassigned: bool = False,
        today: Optional[date] = None,
        with_hk1: bool = False,
        lean: bool = False,
        **filters
    ) -> Tuple[List[models.AdmissionProfile], int]:
        """
        Get filtered list of admission profiles with pagination AND total count.

        Args:
            skip: Number of records to skip
            limit: Maximum records to return
            unit_id: Filter by lead.unit_id (IDOR - manager scope)
            assigned_officer_id: Filter by lead.assigned_officer_id (IDOR - officer scope)
            search: Search term for name, email, citizen_id
            statuses: List of statuses to filter (multi-select)
            major_ids: List of major/program IDs to filter
            academic_year: Filter by academic year
            degree_level: Filter by degree level (via Lead → ProgramOffering → MajorProgram)
            payment_status: Filter by payment status (paid/unpaid/partial/no_fee)
            date_from: Filter profiles created after this date
            date_to: Filter profiles created before this date
            sort_by: Field to sort by (created_at, updated_at, full_name)
            order: Sort order (asc, desc)
            **filters: Additional filter parameters (status, lead_id)

        Returns:
            Tuple of (List of AdmissionProfile instances, total_count)
        """
        # Resolve "today" ONCE per request (passed from service). Default here is a
        # fallback only — service computes per-request so HK1 overdue predicate /
        # sort / column never straddle midnight (mirror routers/invoices.py:139).
        today = today or date.today()

        # Base query for filtering
        base_conditions = []

        # Exclude profiles whose parent Lead is soft-deleted (Lead.deleted_at set).
        # Applies to BOTH count and data queries below (both JOIN Lead).
        base_conditions.append(models.Lead.deleted_at.is_(None))

        # IDOR Filter: Filter at DB level
        if assigned_officer_id is not None:
            base_conditions.append(models.Lead.assigned_officer_id == assigned_officer_id)
        if unit_id is not None:
            base_conditions.append(models.Lead.unit_id == unit_id)

        # Coordination filters (admin/manager) — narrowing ONLY, layered on top of
        # the IDOR scope above (service intersects via _resolve_coordination_filters).
        if assigned_officer_ids:
            base_conditions.append(
                models.Lead.assigned_officer_id.in_(assigned_officer_ids)
            )
        if unassigned:
            base_conditions.append(models.Lead.assigned_officer_id.is_(None))
        if assigned_reviewer_ids:
            base_conditions.append(
                models.AdmissionProfile.assigned_reviewer_id.in_(assigned_reviewer_ids)
            )

        # Multi-status filter (new)
        if statuses and len(statuses) > 0:
            base_conditions.append(models.AdmissionProfile.status.in_(statuses))
        # Backward compatibility: single status from filters
        elif filters.get("status"):
            base_conditions.append(models.AdmissionProfile.status == filters["status"])

        if filters.get("lead_id"):
            base_conditions.append(models.AdmissionProfile.lead_id == filters["lead_id"])

        # Search filter: name diacritic-insensitive (f_unaccent) + exact
        # email/citizen_id. Shared helper keeps list parity with status-counts.
        if search:
            base_conditions.append(self._name_search_condition(search))

        # Major/Program filter via ProgramOffering.program_id (MajorProgram ID)
        # Requires JOIN through Lead → ProgramOffering → MajorProgram
        if major_ids and len(major_ids) > 0:
            base_conditions.append(models.ProgramOffering.program_id.in_(major_ids))

        # Academic year filter
        if academic_year is not None:
            base_conditions.append(models.AdmissionProfile.academic_year == academic_year)

        # Degree level or major filter requires JOIN through ProgramOffering → MajorProgram
        needs_program_join = bool(degree_level) or bool(major_ids)
        if degree_level:
            base_conditions.append(models.MajorProgram.degree_level == degree_level)

        # Payment status filter (subquery EXISTS pattern - no JOIN needed)
        if payment_status:
            self._apply_payment_status_filter(base_conditions, payment_status, today)

        # Date range filter
        if date_from:
            base_conditions.append(models.AdmissionProfile.created_at >= date_from)
        if date_to:
            base_conditions.append(models.AdmissionProfile.created_at <= date_to)

        # Count query
        count_query = (
            select(func.count(models.AdmissionProfile.id))
            .join(models.Lead)
        )
        if needs_program_join:
            count_query = count_query.join(
                models.ProgramOffering, models.Lead.offering_id == models.ProgramOffering.id
            ).join(
                models.MajorProgram, models.ProgramOffering.program_id == models.MajorProgram.id
            )
        if base_conditions:
            count_query = count_query.where(and_(*base_conditions))

        count_result = await self.db.execute(count_query)
        total_count = count_result.scalar() or 0

        # Học phí HK1 aggregate columns (Admission List v2) — labeled scalar
        # subqueries reused both as SELECT columns (cột tiền) AND as the sort key
        # (single source, no drift). coalesce→0 inside the helpers.
        # Chỉ build khi with_hk1=True (list path): tránh 4 correlated subquery/row
        # trên /export (10k) + /stats (toàn bộ hồ sơ) vốn KHÔNG dùng cột HK1.
        hk1_cols: list = []
        remaining_col = None
        if with_hk1:
            paid_col = _hk1_paid_subquery().label("tuition_paid_hk1")
            remaining_col = _hk1_remaining_subquery().label("tuition_remaining_hk1")
            overdue_col = _hk1_overdue_exists(today).label("tuition_overdue_hk1")
            final_col = _hk1_final_subquery().label("tuition_final_hk1")
            hk1_cols = [paid_col, remaining_col, overdue_col, final_col]

        # Determine sort column and order
        sort_column = models.AdmissionProfile.created_at  # default
        if sort_by == "updated_at":
            sort_column = models.AdmissionProfile.updated_at
        elif sort_by == "full_name":
            sort_column = models.Lead.full_name
        elif sort_by == "status":
            sort_column = models.AdmissionProfile.status
        elif sort_by == "remaining_hk1" and remaining_col is not None:
            sort_column = remaining_col

        order_func = desc if order == "desc" else asc

        # Data query with pagination
        data_query = (
            select(models.AdmissionProfile, *hk1_cols)
            .join(models.Lead)
        )
        if needs_program_join:
            data_query = data_query.join(
                models.ProgramOffering, models.Lead.offering_id == models.ProgramOffering.id
            ).join(
                models.MajorProgram, models.ProgramOffering.program_id == models.MajorProgram.id
            )
        # Eager NHẸ dùng chung: lead→officer + offering→program (program_name) +
        # documents (doc-debt) + reviewer. HK1 money đến từ correlated subquery
        # (with_hk1), KHÔNG từ offering.academic_info_history → đã BỎ eager nhánh đó
        # (grep: không đường list/detail admission nào đọc semester_tuitions) để
        # khỏi tải ~2 SELECT/trang rồi vứt — ngay trên endpoint đang tối ưu.
        _eager_opts = [
            selectinload(models.AdmissionProfile.assigned_reviewer),
            selectinload(models.AdmissionProfile.lead).options(
                selectinload(models.Lead.assigned_officer),
                selectinload(models.Lead.offering).options(
                    selectinload(models.ProgramOffering.program),
                ),
            ),
            selectinload(models.AdmissionProfile.documents).joinedload(ProfileDocument.document_type),
        ]
        if not lean:
            # Graph NẶNG (student + subject_scores + choices 6-nhánh) CHỈ cần khi
            # caller chạy `_compute_frontend_fields`/`_compute_completion_percent`
            # per-row (list-đầy-đủ/export/stats-cũ). Đường LIST NHẸ (lean=True) đọc
            # cached_completion/cached_readiness từ cột nên KHÔNG cần graph này →
            # payload + thời gian giảm mạnh. (Multi-NV eligibility/completion read
            # profile.choices → thiếu eager sẽ MissingGreenlet, nên chỉ bỏ khi lean.)
            _eager_opts += [
                selectinload(models.AdmissionProfile.student),
                selectinload(models.AdmissionProfile.subject_scores).selectinload(ProfileSubjectScore.subject),
                *_choices_eager_load_options(),
            ]
        else:
            # lean=True: student/subject_scores/fees khai báo lazy="selectin" ở MAPPER
            # (models/admission.py) → BỎ khỏi .options() KHÔNG tắt được, vẫn nạp mặc
            # định (+ subject_scores.subject KHÔNG nạp trên lean → chạm score.subject =
            # MissingGreenlet ngầm). raiseload TẮT HẲN eager 3 quan hệ này (đường lean
            # KHÔNG đọc chúng: chỉ cached cols + program_name/HK1(subquery)/tên phụ
            # trách + documents) → giảm ~N query/trang THẬT + biến bẫy MissingGreenlet
            # thành lỗi rõ nếu tương lai ai lỡ chạm.
            _eager_opts += [
                raiseload(models.AdmissionProfile.student),
                raiseload(models.AdmissionProfile.subject_scores),
                raiseload(models.AdmissionProfile.fees),
            ]
        data_query = (
            data_query.options(*_eager_opts)
            # Stable secondary key: ties on the primary sort (esp. remaining_hk1 where
            # many profiles share a value, or no-HK1 rows all = 0) would otherwise
            # duplicate/skip across LIMIT/OFFSET pages (mirror Invoice.id tiebreaker
            # in fee_repository).
            .order_by(order_func(sort_column), asc(models.AdmissionProfile.id))
            .offset(skip).limit(limit)
        )
        if base_conditions:
            data_query = data_query.where(and_(*base_conditions))

        def _set_program_name(profile):
            # Extract program_name while in async context (avoids MissingGreenlet
            # during serialization).
            program_name = None
            if profile.lead and profile.lead.offering and profile.lead.offering.program:
                program_name = profile.lead.offering.program.name
            object.__setattr__(profile, "program_name", program_name)

        result = await self.db.execute(data_query)
        profiles = []
        if with_hk1:
            # Rows are tuples (AdmissionProfile, paid, remaining, overdue, final)
            # because of the HK1 columns — unpack instead of .scalars().
            for profile, paid_hk1, remaining_hk1, overdue_hk1, final_hk1 in result.all():
                overdue_hk1 = bool(overdue_hk1)
                object.__setattr__(profile, "tuition_paid_hk1", paid_hk1)
                object.__setattr__(profile, "tuition_remaining_hk1", remaining_hk1)
                object.__setattr__(profile, "tuition_overdue_hk1", overdue_hk1)
                object.__setattr__(
                    profile, "tuition_hk1_status",
                    _hk1_status(paid_hk1, remaining_hk1, overdue_hk1, final_hk1),
                )
                _set_program_name(profile)
                profiles.append(profile)
        else:
            # No HK1 columns (export / stats) — plain entity rows.
            for profile in result.scalars().all():
                _set_program_name(profile)
                profiles.append(profile)

        return profiles, total_count

    @staticmethod
    def _apply_payment_status_filter(
        base_conditions: list,
        payment_status: str,
        today: Optional[date] = None,
    ) -> None:
        """Apply payment status subquery filter to base_conditions.

        ``overdue`` (Admission List v2) = có hóa đơn HK1 quá hạn chưa thanh toán
        (mirror cột ``tuition_overdue_hk1``). ``today`` truyền từ caller (per-request)
        để không lệch qua nửa đêm; fallback ``date.today()`` nếu None.
        """
        from app.models import Fee, FeeStatusEnum

        today = today or date.today()

        if payment_status == "overdue":
            # CỐ Ý chỉ xét HK1 (khớp cột "Học phí HK1"/sort của Admission List v2),
            # KHÁC các nhánh paid/unpaid/partial/no_fee bên dưới (xét MỌI fee). Đừng
            # "đồng bộ" nhánh này sang all-fees — sẽ phá parity với cột HK1.
            base_conditions.append(_hk1_overdue_exists(today))
            return
        if payment_status == "paid":
            # All fees are paid/waived (no unpaid fees exist) AND has at least one fee
            unpaid_exists = select(Fee.id).where(
                Fee.admission_profile_id == models.AdmissionProfile.id,
                Fee.status.notin_([FeeStatusEnum.paid, FeeStatusEnum.waived, FeeStatusEnum.cancelled])
            ).correlate(models.AdmissionProfile).exists()
            has_fees = select(Fee.id).where(
                Fee.admission_profile_id == models.AdmissionProfile.id
            ).correlate(models.AdmissionProfile).exists()
            base_conditions.append(has_fees)
            base_conditions.append(~unpaid_exists)
        elif payment_status == "unpaid":
            unpaid_exists = select(Fee.id).where(
                Fee.admission_profile_id == models.AdmissionProfile.id,
                Fee.status.in_([FeeStatusEnum.pending, FeeStatusEnum.calculated, FeeStatusEnum.overdue])
            ).correlate(models.AdmissionProfile).exists()
            base_conditions.append(unpaid_exists)
        elif payment_status == "partial":
            partial_exists = select(Fee.id).where(
                Fee.admission_profile_id == models.AdmissionProfile.id,
                Fee.status == FeeStatusEnum.partial
            ).correlate(models.AdmissionProfile).exists()
            base_conditions.append(partial_exists)
        elif payment_status == "no_fee":
            no_fees = ~select(Fee.id).where(
                Fee.admission_profile_id == models.AdmissionProfile.id
            ).correlate(models.AdmissionProfile).exists()
            base_conditions.append(no_fees)

    def _name_search_condition(self, search: str):
        """Diacritic-insensitive name search (+ exact email/citizen_id).

        ``f_unaccent(full_name)`` is backed by ``ix_lead_fullname_unaccent_trgm``
        (migration leadsrch01) so "nguyen" matches "Nguyễn". Keeps
        ``escape=LIKE_ESCAPE_CHAR`` because the term is escaped literal via
        ``escape_like_pattern()``. Shared by the list query and
        ``_build_base_conditions`` (status-counts) so list + tab counts agree.
        """
        normalized = unicodedata.normalize("NFC", search.strip())
        term = f"%{escape_like_pattern(normalized)}%"
        return or_(
            func.f_unaccent(models.Lead.full_name).ilike(
                func.f_unaccent(term), escape=LIKE_ESCAPE_CHAR
            ),
            models.Lead.email.ilike(term, escape=LIKE_ESCAPE_CHAR),
            models.AdmissionProfile.citizen_id.ilike(
                term, escape=LIKE_ESCAPE_CHAR
            ),
        )

    # =========================================================================
    # AGGREGATE QUERY METHODS (Phase 2 & 3)
    # =========================================================================

    def _build_base_conditions(
        self,
        unit_id: Optional[int] = None,
        assigned_officer_id: Optional[int] = None,
        search: Optional[str] = None,
        major_ids: Optional[List[int]] = None,
        academic_year: Optional[int] = None,
        degree_level: Optional[str] = None,
        payment_status: Optional[str] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        assigned_officer_ids: Optional[List[int]] = None,
        assigned_reviewer_ids: Optional[List[int]] = None,
        unassigned: bool = False,
        today: Optional[date] = None,
    ) -> Tuple[list, bool]:
        """Build shared filter conditions for aggregate queries.

        Keeps status-counts in lockstep with the list query (same coordination
        filters + payment_status incl. "overdue").

        Returns:
            Tuple of (conditions list, needs_program_join bool)
        """
        today = today or date.today()
        conditions = []
        # Exclude soft-deleted leads' profiles (parity with list + aggregate).
        conditions.append(models.Lead.deleted_at.is_(None))
        if assigned_officer_id is not None:
            conditions.append(models.Lead.assigned_officer_id == assigned_officer_id)
        if unit_id is not None:
            conditions.append(models.Lead.unit_id == unit_id)
        # Coordination filters (parity with get_filtered_with_count).
        if assigned_officer_ids:
            conditions.append(models.Lead.assigned_officer_id.in_(assigned_officer_ids))
        if unassigned:
            conditions.append(models.Lead.assigned_officer_id.is_(None))
        if assigned_reviewer_ids:
            conditions.append(
                models.AdmissionProfile.assigned_reviewer_id.in_(assigned_reviewer_ids)
            )
        if search:
            # Same diacritic-insensitive search as the list query (parity).
            conditions.append(self._name_search_condition(search))
        if major_ids and len(major_ids) > 0:
            conditions.append(models.ProgramOffering.program_id.in_(major_ids))
        if academic_year is not None:
            conditions.append(models.AdmissionProfile.academic_year == academic_year)
        needs_join = bool(degree_level) or bool(major_ids)
        if degree_level:
            conditions.append(models.MajorProgram.degree_level == degree_level)
        if payment_status:
            self._apply_payment_status_filter(conditions, payment_status, today)
        if date_from:
            conditions.append(models.AdmissionProfile.created_at >= date_from)
        if date_to:
            conditions.append(models.AdmissionProfile.created_at <= date_to)
        return conditions, needs_join

    async def get_status_counts(
        self,
        unit_id: Optional[int] = None,
        assigned_officer_id: Optional[int] = None,
        search: Optional[str] = None,
        major_ids: Optional[List[int]] = None,
        academic_year: Optional[int] = None,
        degree_level: Optional[str] = None,
        payment_status: Optional[str] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        assigned_officer_ids: Optional[List[int]] = None,
        assigned_reviewer_ids: Optional[List[int]] = None,
        unassigned: bool = False,
        today: Optional[date] = None,
    ) -> dict:
        """
        Get count of profiles grouped by status.
        Applies all filters EXCEPT status (to count for all tabs).

        Returns:
            dict with 'counts' (status -> count) and 'total'
        """
        conditions, needs_join = self._build_base_conditions(
            unit_id=unit_id, assigned_officer_id=assigned_officer_id,
            search=search, major_ids=major_ids,
            academic_year=academic_year, degree_level=degree_level,
            payment_status=payment_status, date_from=date_from, date_to=date_to,
            assigned_officer_ids=assigned_officer_ids,
            assigned_reviewer_ids=assigned_reviewer_ids,
            unassigned=unassigned, today=today,
        )

        query = (
            select(
                models.AdmissionProfile.status,
                func.count(models.AdmissionProfile.id)
            )
            .join(models.Lead)
        )
        if needs_join:
            query = query.join(
                models.ProgramOffering, models.Lead.offering_id == models.ProgramOffering.id
            ).join(
                models.MajorProgram, models.ProgramOffering.program_id == models.MajorProgram.id
            )
        if conditions:
            query = query.where(and_(*conditions))
        query = query.group_by(models.AdmissionProfile.status)

        result = await self.db.execute(query)
        rows = result.all()

        counts = {row[0]: row[1] for row in rows}
        total = sum(counts.values())
        return {"counts": counts, "total": total}

    async def get_aggregate_stats(
        self,
        unit_id: Optional[int] = None,
        assigned_officer_id: Optional[int] = None,
        academic_year: Optional[int] = None,
    ) -> dict:
        """
        Get aggregate statistics for admission profiles.

        Returns:
            dict with total_profiles, status counts, conversion_rate, avg_completion
        """
        conditions = []
        # Exclude soft-deleted leads' profiles (parity with list + status counts).
        conditions.append(models.Lead.deleted_at.is_(None))
        if assigned_officer_id is not None:
            conditions.append(models.Lead.assigned_officer_id == assigned_officer_id)
        if unit_id is not None:
            conditions.append(models.Lead.unit_id == unit_id)
        if academic_year is not None:
            conditions.append(models.AdmissionProfile.academic_year == academic_year)

        # Status counts in one query
        query = (
            select(
                models.AdmissionProfile.status,
                func.count(models.AdmissionProfile.id),
            )
            .join(models.Lead)
        )
        if conditions:
            query = query.where(and_(*conditions))
        query = query.group_by(models.AdmissionProfile.status)

        result = await self.db.execute(query)
        rows = result.all()

        # avg_completion — ĐỌC read-model `cached_completion` (perf/admissions-list)
        # bằng AVG SQL, thay cho fetch-all mọi hồ sơ + Python loop (~2.1s → ~ms).
        # AVG bỏ qua NULL (hồ sơ chưa được sweep tính); COALESCE 0 cho cửa sổ đầu
        # khi mọi hàng còn NULL. Eventual-consistent với list (cùng cột).
        avg_query = select(
            func.coalesce(func.avg(models.AdmissionProfile.cached_completion), 0.0)
        ).join(models.Lead)
        if conditions:
            avg_query = avg_query.where(and_(*conditions))
        avg_completion = round(
            float((await self.db.execute(avg_query)).scalar() or 0.0), 1
        )

        status_counts = {}
        total = 0
        for status_val, cnt in rows:
            status_counts[status_val] = cnt
            total += cnt

        draft_count = status_counts.get("draft", 0)
        submitted_count = status_counts.get("submitted", 0) + status_counts.get("resubmitted", 0)
        approved_count = (
            status_counts.get("approved", 0) +
            status_counts.get("confirmed", 0) +
            status_counts.get("overridden", 0)
        )
        enrolled_count = status_counts.get("enrolled", 0)
        rejected_count = status_counts.get("rejected", 0)
        # F6: surface the withdrawal states as their own buckets — before this
        # they were counted in ``total`` but had no named bucket, so the returned
        # counts did not sum to total_profiles and the withdrawal cohort was a
        # silent orphan in any breakdown that trusts these fields.
        withdrawn_count = status_counts.get("withdrawn", 0)
        withdrawal_pending_count = status_counts.get("withdrawal_pending", 0)
        conversion_rate = round((enrolled_count / total) * 100, 1) if total > 0 else 0.0

        return {
            "total_profiles": total,
            "draft_count": draft_count,
            "submitted_count": submitted_count,
            "approved_count": approved_count,
            "enrolled_count": enrolled_count,
            "rejected_count": rejected_count,
            "withdrawn_count": withdrawn_count,
            "withdrawal_pending_count": withdrawal_pending_count,
            "conversion_rate": conversion_rate,
            "avg_completion": avg_completion,
        }

    async def get_distinct_academic_years(
        self,
        unit_id: Optional[int] = None,
        assigned_officer_id: Optional[int] = None,
    ) -> List[int]:
        """
        Get distinct academic years that have admission profiles.
        Ordered descending (most recent first).

        Args:
            unit_id: Filter by lead.unit_id (IDOR - manager)
            assigned_officer_id: Filter by lead.assigned_officer_id (IDOR - officer)

        Returns:
            List of academic years (integers)
        """
        query = (
            select(distinct(models.AdmissionProfile.academic_year))
            .join(models.Lead)
            .where(models.AdmissionProfile.academic_year.isnot(None))
            # Exclude years that exist only via soft-deleted leads' profiles.
            .where(models.Lead.deleted_at.is_(None))
        )
        if assigned_officer_id is not None:
            query = query.where(models.Lead.assigned_officer_id == assigned_officer_id)
        if unit_id is not None:
            query = query.where(models.Lead.unit_id == unit_id)
        query = query.order_by(desc(models.AdmissionProfile.academic_year))

        result = await self.db.execute(query)
        return [row[0] for row in result.all()]

    # =========================================================================
    # CREATE PROFILE METHODS
    # =========================================================================

    async def get_profile_by_lead_id(
        self,
        lead_id: int
    ) -> Optional[models.AdmissionProfile]:
        """
        DEPRECATED (Wave 4 #15b — Lead one-to-many migration).

        Returns the lead's MOST RECENT profile (highest ``academic_year``)
        for backward compatibility with callers that still expect a
        single profile per lead. Wave 4 PR #15c FE migrate is on the
        critical path to remove this method's call sites; new code MUST
        use ``list_profiles_by_lead_id`` (multi-year) or
        ``get_profile_by_lead_year`` (composite-UNIQUE-keyed lookup).

        Logs a warning when the lead actually has >1 profile so the
        ambiguity is visible during the migration window — silent
        "return latest" would hide cases where the caller's expectation
        of a single profile breaks.

        Args:
            lead_id: Lead ID

        Returns:
            Latest AdmissionProfile by ``academic_year DESC`` (or None).
        """
        stmt = (
            select(models.AdmissionProfile)
            .where(models.AdmissionProfile.lead_id == lead_id)
            .order_by(models.AdmissionProfile.academic_year.desc())
        )
        result = await self.db.execute(stmt)
        rows = list(result.scalars().all())
        if len(rows) > 1:
            log.warning(
                "get_profile_by_lead_id called on a lead with multiple "
                "profiles; deprecated behavior returns the latest year. "
                "Caller should migrate to list_profiles_by_lead_id or "
                "get_profile_by_lead_year (Wave 4 #15b).",
                extra={"lead_id": lead_id, "profile_count": len(rows)},
            )
        return rows[0] if rows else None

    async def list_profiles_by_lead_id(
        self,
        lead_id: int,
    ) -> list[models.AdmissionProfile]:
        """Wave 4 #15b — multi-year list lookup.

        Returns all profiles for a lead ordered ``academic_year DESC``
        so the most recent year is first. Documents are eager-loaded
        for callers that follow this query với fee/document checks.
        """
        stmt = (
            select(models.AdmissionProfile)
            .where(models.AdmissionProfile.lead_id == lead_id)
            .order_by(models.AdmissionProfile.academic_year.desc())
            .options(selectinload(models.AdmissionProfile.documents))
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def list_profiles_with_pending_diploma(
        self,
        unit_id: Optional[int] = None,
        assigned_officer_id: Optional[int] = None,
        due_before: Optional[date] = None,
    ) -> list[models.AdmissionProfile]:
        """PR #13.7 — hồ sơ còn "nợ bằng" (Giấy CN tốt nghiệp tạm thời).

        Lọc ``ProfileDocument.graduation_proof_kind == 'provisional_cert'``.
        IDOR scope mirror ``_resolve_idor_filters``: ``unit_id``
        (``lead.unit_id``) + ``assigned_officer_id`` (``lead.assigned_officer_id``),
        bỏ qua khi None (admin). ``due_before`` (optional): chỉ lấy hồ sơ có
        hạn bổ sung <= ngày (sắp / đã quá hạn). Eager-load lead +
        assigned_officer + documents.document_type để service dựng tên thí
        sinh + officer + lấy hạn không N+1. Order ``supplement_due_date`` tăng
        dần (gần hạn nhất trước; Postgres ASC = NULLS LAST).
        """
        stmt = (
            select(models.AdmissionProfile)
            .join(
                models.Lead,
                models.AdmissionProfile.lead_id == models.Lead.id,
            )
            .join(
                ProfileDocument,
                ProfileDocument.profile_id == models.AdmissionProfile.id,
            )
            .where(ProfileDocument.graduation_proof_kind == "provisional_cert")
            # Review F3 — chỉ nhắc hồ sơ CÒN actionable: bỏ withdrawn (thí sinh
            # rút) + withdrawal_pending (PR-B: đang rút, chờ hoàn tiền) + dropped
            # (is_dropped=True, status vẫn 'enrolled'). GIỮ enrolled-không-dropped
            # (đúng use case: nhập học với giấy tạm thời, vẫn nợ bằng) + rejected
            # (có thể resubmit; reject_document đã clear field khi reject ở tầng doc).
            .where(
                models.AdmissionProfile.status.notin_(
                    ("withdrawn", "withdrawal_pending")
                )
            )
            .where(models.AdmissionProfile.is_dropped.isnot(True))
            # Exclude profiles whose parent Lead is soft-deleted (don't remind
            # diploma debt for leads that have been removed).
            .where(models.Lead.deleted_at.is_(None))
            .options(
                selectinload(models.AdmissionProfile.lead).selectinload(
                    models.Lead.assigned_officer
                ),
                selectinload(models.AdmissionProfile.documents).joinedload(
                    ProfileDocument.document_type
                ),
            )
            .order_by(asc(ProfileDocument.supplement_due_date))
        )
        if due_before is not None:
            stmt = stmt.where(ProfileDocument.supplement_due_date <= due_before)
        if unit_id is not None:
            stmt = stmt.where(models.Lead.unit_id == unit_id)
        if assigned_officer_id is not None:
            stmt = stmt.where(
                models.Lead.assigned_officer_id == assigned_officer_id
            )
        result = await self.db.execute(stmt)
        return list(result.scalars().unique().all())

    async def get_profile_by_lead_year(
        self,
        lead_id: int,
        academic_year: int,
    ) -> Optional[models.AdmissionProfile]:
        """Wave 4 #15b — composite-UNIQUE-keyed single-profile lookup.

        Hits the ``uq_admission_profile_lead_year`` UNIQUE shipped by
        Wave 3-E ``phase1_15a`` (PR #223 squash 15f52c8e), so this
        query returns at most one row by definition.
        """
        stmt = (
            select(models.AdmissionProfile)
            .where(models.AdmissionProfile.lead_id == lead_id)
            .where(models.AdmissionProfile.academic_year == academic_year)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_lead_with_offering(
        self,
        lead_id: int
    ) -> Optional[models.Lead]:
        """
        Get lead with offering and admission_profile loaded.
        
        ✅ SPRINT 6: For create_profile validation.
        
        Args:
            lead_id: Lead ID
            
        Returns:
            Lead with offering and admission_profile relationships loaded
        """
        stmt = (
            select(models.Lead)
            .where(models.Lead.id == lead_id)
            .options(
                joinedload(models.Lead.offering),
                selectinload(models.Lead.admission_profiles),
            )
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_latest_consultation_for_lead(
        self,
        lead_id: int
    ) -> Optional[models.Consultation]:
        """
        Get the latest consultation for a lead (by consultation_date) — DÙNG CHO
        ADMISSION ELIGIBILITY (admission_service.py:1662).

        ✅ EDGE CASE #9 FIX: Validate consultation completeness before admission.

        🔴 review#2 fix#4 — PARITY VỚI LeadRepository.get_latest_consultation LÀ CÓ
        CHỦ ĐÍCH KHÁC NHAU, KHÔNG PHẢI BUG:
          - ORDERING đồng nhất (consultation_date DESC, id DESC) — tie-break B4b.
          - SYSTEM-FILTER KHÁC: hàm này CỐ Ý GỒM cuộc method='system' (reopen/
            auto-close/milestone), còn LeadRepository.get_latest_consultation
            (exclude_system=True mặc định) LOẠI chúng. Vì eligibility nhập học
            (decision ②) VẪN tính cuộc system (nó luôn có status → nới lỏng check
            'no_consultation'/'consultation_missing_status', chỉ chặn nếu status
            is_universal). Nếu sau muốn eligibility bỏ system → đổi nghiệp vụ MỚI,
            phải mở lại decision ②, KHÔNG âm thầm ở đây.

        Args:
            lead_id: Lead ID

        Returns:
            Latest Consultation (GỒM system) with status loaded, or None
        """
        stmt = (
            select(models.Consultation)
            .where(
                models.Consultation.lead_id == lead_id,
                models.Consultation.deleted_at.is_(None)  # Exclude soft-deleted
                # (GỒM system — xem docstring #4)
            )
            .options(
                joinedload(models.Consultation.consultation_status),
                joinedload(models.Consultation.officer),
            )
            # B4b: tie-break id.desc() (ORDERING đồng nhất LeadRepository +
            # _resolve_revert_target). Cùng consultation_date (add dùng now()) mà
            # thiếu tie-break → thứ tự do Postgres quyết định.
            .order_by(
                models.Consultation.consultation_date.desc(),
                models.Consultation.id.desc(),
            )
            .limit(1)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_profile_by_id_with_lead(
        self,
        profile_id: int
    ) -> Optional[models.AdmissionProfile]:
        """
        Get profile with lead relationship loaded.
        
        ✅ SPRINT 6: For get_profile and IDOR checks.
        
        Args:
            profile_id: AdmissionProfile ID
            
        Returns:
            AdmissionProfile with lead and student relationships
        """
        stmt = (
            select(models.AdmissionProfile)
            .where(models.AdmissionProfile.id == profile_id)
            .options(
                joinedload(models.AdmissionProfile.lead).options(
                    selectinload(models.Lead.assigned_officer),
                    selectinload(models.Lead.offering).options(
                        selectinload(models.ProgramOffering.program),
                        selectinload(models.ProgramOffering.academic_info_history)
                        .selectinload(models.OfferingAcademicInfo.semester_tuitions),
                    ),
                ),
                selectinload(models.AdmissionProfile.assigned_reviewer),
                selectinload(models.AdmissionProfile.student),
                selectinload(models.AdmissionProfile.subject_scores).selectinload(ProfileSubjectScore.subject),
                selectinload(models.AdmissionProfile.documents).joinedload(ProfileDocument.document_type),
                *_choices_eager_load_options(),
            )
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_round_for_profile_cutoff(
        self,
        profile: models.AdmissionProfile,
    ) -> Optional[models.OfferingAdmissionRound]:
        """Resolve OfferingAdmissionRound từ ``profile.applied_rules`` snapshot.

        Used by ``admission_service.submit_and_evaluate`` round-cutoff gate
        (PR-2 ship 2026-05-28). Profile snapshot stores ``admission_path_id``
        tại create-time → repo lookup path → round.

        Returns None nếu:
        - ``applied_rules`` rỗng hoặc thiếu ``admission_path_id`` (legacy
          profile, pre-snapshot era — caller should log + skip gate)
        - path không tồn tại (FK orphan; defensive, should not happen)

        Caller responsibility:
        - Handle None → skip cutoff gate + emit observability warning so ops
          can find legacy profiles bypassing the round-cutoff fail-closed.
        - Call ``assert_round_open(round)`` (utils.admission_round_guards)
          on non-None return to enforce 410 Gone.

        Extracted via PR #346 review nit #2: removes the inline 20-line
        block in submit_and_evaluate + ugly ``sa_select_cutoff`` aliases
        which existed to dodge top-level ``select``/``selectinload`` name
        collisions inside the function-local scope.
        """
        applied_rules = profile.applied_rules or {}
        path_id_raw = applied_rules.get("admission_path_id")
        if path_id_raw is None:
            return None
        try:
            path_id = int(path_id_raw)
        except (TypeError, ValueError):
            return None
        return await self.get_round_for_path(path_id)

    async def get_round_for_path(self, path_id: int):
        """F3 — round cutoff cho MỘT path cụ thể. Dùng khi ĐỔI NGÀNH: cutoff phải
        đánh giá theo path MỚI (``_apply_major_change_snapshot`` chưa rewrite
        ``applied_rules.admission_path_id`` — dời sang nhánh success), nếu không
        ``get_round_for_profile_cutoff`` sẽ đọc round của path CŨ → chặn/lọt sai."""
        stmt = (
            select(AdmissionPath)
            .where(AdmissionPath.id == path_id)
            .options(selectinload(AdmissionPath.admission_round))
        )
        path = (await self.db.execute(stmt)).scalar_one_or_none()
        if path is None:
            return None
        return path.admission_round

    async def reload_profile_with_lead(
        self,
        profile_id: int
    ) -> Optional[models.AdmissionProfile]:
        """
        Reload profile after creation with lead relationship.
        
        ✅ SPRINT 6: For create_profile response.
        
        Args:
            profile_id: AdmissionProfile ID
            
        Returns:
            AdmissionProfile with lead and student loaded
        """
        stmt = (
            select(models.AdmissionProfile)
            .where(models.AdmissionProfile.id == profile_id)
            .options(
                joinedload(models.AdmissionProfile.lead).options(
                    joinedload(models.Lead.assigned_officer),
                    selectinload(models.Lead.offering).options(
                        selectinload(models.ProgramOffering.program),
                        selectinload(models.ProgramOffering.academic_info_history)
                        .selectinload(models.OfferingAcademicInfo.semester_tuitions),
                    ),
                ),
                selectinload(models.AdmissionProfile.assigned_reviewer),
                selectinload(models.AdmissionProfile.student),  # Prevent MissingGreenlet
                selectinload(models.AdmissionProfile.subject_scores).selectinload(ProfileSubjectScore.subject),
                selectinload(models.AdmissionProfile.documents).joinedload(ProfileDocument.document_type),
                *_choices_eager_load_options(),
            )
        )
        result = await self.db.execute(stmt)
        return result.scalar_one()

    # =========================================================================
    # VALIDATION METHODS
    # =========================================================================

    async def check_citizen_id_exists(
        self,
        citizen_id: str,
        academic_year: int,
        exclude_profile_id: Optional[int] = None
    ) -> Optional[models.AdmissionProfile]:
        """
        Check if citizen_id is already used by another profile IN THE SAME YEAR.
        
        ✅ UPDATED: Now filters by academic_year to allow same citizen
        to apply in different years.
        
        Args:
            citizen_id: Citizen ID to check
            academic_year: Academic year to check within
            exclude_profile_id: Profile ID to exclude (current profile)
            
        Returns:
            Existing AdmissionProfile or None
        """
        stmt = select(models.AdmissionProfile).where(
            models.AdmissionProfile.citizen_id == citizen_id,
            models.AdmissionProfile.academic_year == academic_year,
        )
        if exclude_profile_id:
            stmt = stmt.where(models.AdmissionProfile.id != exclude_profile_id)
        
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def check_citizen_id_enrolled(
        self,
        citizen_id: str
    ) -> Optional[models.Student]:
        """
        Check if citizen_id is already enrolled (has Student record).
        
        ✅ SPRINT 6: For submit_and_evaluate validation.
        
        Args:
            citizen_id: Citizen ID to check
            
        Returns:
            Existing Student or None
        """
        stmt = (
            select(models.Student)
            .join(models.AdmissionProfile)
            .where(models.AdmissionProfile.citizen_id == citizen_id)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def check_student_code_exists(
        self,
        student_code: str
    ) -> bool:
        """
        Check if student_code already exists.
        
        ✅ SPRINT 6: For enroll_student code generation.
        
        Args:
            student_code: Student code to check
            
        Returns:
            True if exists, False otherwise
        """
        stmt = select(models.Student).where(
            models.Student.student_code == student_code
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none() is not None

    # =========================================================================
    # DOCUMENT MANAGEMENT METHODS (JSONB → Relational Migration)
    # =========================================================================

    async def initialize_documents_for_profile(
        self,
        profile_id: int,
        document_type_codes: List[str]
    ) -> List[models.ProfileDocument]:
        """
        Initialize ProfileDocument records for a new admission profile.

        Replaces: _generate_documents_checklist() JSONB generation

        Args:
            profile_id: AdmissionProfile ID
            document_type_codes: List of document type codes (e.g., ["HOC_BA", "CCCD"])

        Returns:
            List of created ProfileDocument records with status="missing"
        """
        # Fetch document types by codes
        stmt = select(models.ConfigDocumentType).where(
            models.ConfigDocumentType.code.in_(document_type_codes)
        )
        result = await self.db.execute(stmt)
        doc_types = list(result.scalars().all())

        # Create ProfileDocument records
        created_docs = []
        for doc_type in doc_types:
            doc = models.ProfileDocument(
                profile_id=profile_id,
                document_type_id=doc_type.id,
                status="missing",
                file_path=None,
                uploaded_at=None,
            )
            self.db.add(doc)
            created_docs.append(doc)

        await self.db.flush()  # Get IDs without committing
        return created_docs

    async def add_path_documents_delta(
        self,
        profile_id: int,
        document_type_codes: List[str],
    ) -> List[models.ProfileDocument]:
        """Idempotent DELTA INSERT cho re-resolve (feat audience — P0-B).

        Khác ``initialize_documents_for_profile`` (add VÔ ĐIỀU KIỆN): chỉ tạo
        ProfileDocument cho code CHƯA tồn tại trong tier ``category='path'``,
        set ``category='path'`` tường minh → KHÔNG vi phạm partial-unique
        ``uq_profile_document_path``. KHÔNG xóa / đụng row đã có upload.

        Trả: list ProfileDocument mới tạo (rỗng nếu không có code thiếu).
        """
        if not document_type_codes:
            return []

        # Codes đã có (category='path') cho profile này.
        existing_stmt = (
            select(models.ConfigDocumentType.code)
            .join(
                models.ProfileDocument,
                models.ProfileDocument.document_type_id
                == models.ConfigDocumentType.id,
            )
            .where(
                models.ProfileDocument.profile_id == profile_id,
                models.ProfileDocument.category == "path",
            )
        )
        existing_codes = set(
            (await self.db.execute(existing_stmt)).scalars().all()
        )

        missing_codes = [
            c for c in document_type_codes if c not in existing_codes
        ]
        if not missing_codes:
            return []

        dt_stmt = select(models.ConfigDocumentType).where(
            models.ConfigDocumentType.code.in_(missing_codes)
        )
        doc_types = list((await self.db.execute(dt_stmt)).scalars().all())

        created: List[models.ProfileDocument] = []
        for dt in doc_types:
            doc = models.ProfileDocument(
                profile_id=profile_id,
                document_type_id=dt.id,
                category="path",
                status="missing",
                file_path=None,
                uploaded_at=None,
            )
            self.db.add(doc)
            created.append(doc)

        await self.db.flush()
        return created

    async def get_document_by_type(
        self,
        profile_id: int,
        document_type_code: str
    ) -> Optional[models.ProfileDocument]:
        """
        Get ProfileDocument by profile_id and document type code.

        Replaces: JSONB checklist filtering in upload_document()

        Args:
            profile_id: AdmissionProfile ID
            document_type_code: Document type code (e.g., "HOC_BA")

        Returns:
            ProfileDocument record or None
        """
        stmt = (
            select(models.ProfileDocument)
            .join(models.ConfigDocumentType)
            .where(
                models.ProfileDocument.profile_id == profile_id,
                models.ConfigDocumentType.code == document_type_code,
            )
            .options(joinedload(models.ProfileDocument.document_type))
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_document_by_id(
        self,
        document_id: int,
    ) -> Optional[models.ProfileDocument]:
        """Lookup a ProfileDocument by primary key.

        Used by the authed document-download endpoint (PR1 Commit 1). The
        caller binds the result to an already IDOR-authorized profile
        (``doc.profile_id == profile.id``) before serving the file, so no
        join/eager-load is needed here — only ``file_path`` is read.
        """
        stmt = select(models.ProfileDocument).where(
            models.ProfileDocument.id == document_id
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def update_document_status(
        self,
        profile_id: int,
        document_type_code: str,
        status: str,
        file_path: Optional[str] = None,
        uploaded_at = None,  # datetime or str (for backward compatibility)
        actual_submission_format: Optional[str] = None,
    ) -> Optional[models.ProfileDocument]:
        """
        Update ProfileDocument status and file metadata.

        Replaces: JSONB checklist mutation with flag_modified() in upload_document()

        Args:
            profile_id: AdmissionProfile ID
            document_type_code: Document type code
            status: New status (missing | uploaded | verified | rejected)
            file_path: File path (if uploaded)
            uploaded_at: Upload timestamp as datetime (if uploaded)
            actual_submission_format: Declared document format (original | certified_copy | photo)

        Returns:
            Updated ProfileDocument or None if not found
        """
        doc = await self.get_document_by_type(profile_id, document_type_code)
        if not doc:
            return None

        doc.status = status
        if file_path:
            doc.file_path = file_path
        if uploaded_at is not None:
            # Handle both datetime and string (backward compatibility)
            if isinstance(uploaded_at, str):
                from datetime import datetime
                # Parse ISO format string to datetime
                doc.uploaded_at = datetime.fromisoformat(uploaded_at.replace('Z', '+00:00'))
            else:
                doc.uploaded_at = uploaded_at
        if actual_submission_format:
            doc.actual_submission_format = actual_submission_format

        return doc

    async def get_uploaded_documents(
        self,
        profile_id: int
    ) -> List[models.ProfileDocument]:
        """
        Get all uploaded documents for a profile.

        Replaces: JSONB checklist filtering in enroll_student()

        Args:
            profile_id: AdmissionProfile ID

        Returns:
            List of ProfileDocument with status="uploaded" and file_path not null
        """
        stmt = (
            select(models.ProfileDocument)
            .where(
                models.ProfileDocument.profile_id == profile_id,
                or_(
                    and_(models.ProfileDocument.status == "uploaded", models.ProfileDocument.file_path.isnot(None)),
                    models.ProfileDocument.status == "verified",  # Also include verified (uploaded + checked)
                    models.ProfileDocument.status == "paper_submitted"
                )
            )
            .options(joinedload(models.ProfileDocument.document_type))
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_all_documents(
        self,
        profile_id: int
    ) -> List[models.ProfileDocument]:
        """
        Get ALL documents for a profile (regardless of status).

        Phase 7: For completion percentage calculation in _compute_frontend_fields

        Args:
            profile_id: AdmissionProfile ID

        Returns:
            List of all ProfileDocument for this profile
        """
        stmt = (
            select(models.ProfileDocument)
            .where(models.ProfileDocument.profile_id == profile_id)
            .options(joinedload(models.ProfileDocument.document_type))
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def mark_paper_submitted(
        self,
        profile_id: int,
        document_type_code: str,
        officer_id: int,
        actual_submission_format: Optional[str] = None,
        graduation_proof_kind: Optional[str] = None,
        supplement_due_date: Optional[date] = None,
    ) -> Optional[models.ProfileDocument]:
        """
        Mark a document as paper submitted (officer confirms receipt).

        For documents where requires_upload=false.

        Args:
            profile_id: AdmissionProfile ID
            document_type_code: Document type code
            officer_id: ID of officer confirming receipt
            actual_submission_format: Declared format (original|certified_copy|photo)
            graduation_proof_kind: PR#13 — official_diploma|provisional_cert
                (chỉ áp cho giấy tốt nghiệp THPT bang_tot_nghiep_thpt)
            supplement_due_date: PR#13 — hạn bổ sung khi provisional_cert

        Returns:
            Updated ProfileDocument or None if not found
        """
        from datetime import datetime, timezone

        doc = await self.get_document_by_type(profile_id, document_type_code)
        if not doc:
            return None

        doc.status = "paper_submitted"
        doc.paper_submitted_at = datetime.now(timezone.utc)
        doc.paper_submitted_by = officer_id
        if actual_submission_format:
            doc.actual_submission_format = actual_submission_format

        # PR #13 — loại giấy tốt nghiệp (bằng chính thức / giấy tạm thời).
        if graduation_proof_kind is not None:
            doc.graduation_proof_kind = graduation_proof_kind
            doc.supplement_due_date = (
                supplement_due_date
                if graduation_proof_kind == "provisional_cert"
                else None
            )

        return doc

    async def update_graduation_proof(
        self,
        profile_id: int,
        document_type_code: str,
        new_kind: str,
    ) -> Optional[models.ProfileDocument]:
        """PR #13 — nâng cấp loại giấy tốt nghiệp (vd provisional→official).

        Dùng khi hồ sơ ĐÃ nộp giấy (status paper_submitted/verified) rồi thí
        sinh bổ sung bằng chính thức. KHÔNG đổi status (khác
        mark_paper_submitted vốn theo policy chỉ chạy khi status='missing').
        official_diploma → xoá hạn bổ sung.
        """
        doc = await self.get_document_by_type(profile_id, document_type_code)
        if not doc:
            return None

        doc.graduation_proof_kind = new_kind
        if new_kind == "official_diploma":
            doc.supplement_due_date = None
        return doc

    async def reset_document(
        self,
        profile_id: int,
        document_type_code: str,
    ) -> Optional[models.ProfileDocument]:
        """
        Reset a document to 'missing' status (undo submission).

        Use case: User accidentally clicked "Đã nộp" or uploaded wrong file.
        Simple undo without complex audit trail.

        Args:
            profile_id: AdmissionProfile ID
            document_type_code: Document type code

        Returns:
            Updated ProfileDocument or None if not found
        """
        doc = await self.get_document_by_type(profile_id, document_type_code)
        if not doc:
            return None

        # Reset to missing state. ADM-031 round 10 review (B2): verified_by
        # was previously left dangling — every other verifier-side column
        # was cleared but the user id stuck around, so audit queries on
        # verified_by saw a verifier id for a document that is currently
        # missing. Clear it alongside verified_at so the row is fully
        # rewound.
        doc.status = "missing"
        doc.file_path = None
        doc.actual_submission_format = None
        doc.verified_format = None
        doc.uploaded_at = None
        doc.verified_at = None
        doc.verified_by = None
        doc.paper_submitted_at = None
        doc.paper_submitted_by = None
        doc.rejected_at = None
        doc.rejected_by = None
        doc.rejection_reason = None
        # PR #13 — rewind graduation proof fields.
        doc.graduation_proof_kind = None
        doc.supplement_due_date = None

        return doc

    async def reject_document(
        self,
        profile_id: int,
        document_type_code: str,
        officer_id: int,
        reason: str,
    ) -> Optional[models.ProfileDocument]:
        """
        Reject a document with reason.
        
        User will need to re-upload or resubmit.
        
        Args:
            profile_id: AdmissionProfile ID
            document_type_code: Document type code
            officer_id: ID of officer rejecting
            reason: Rejection reason
            
        Returns:
            Updated ProfileDocument or None if not found
        """
        from datetime import datetime, timezone
        
        doc = await self.get_document_by_type(profile_id, document_type_code)
        if not doc:
            return None
        
        doc.status = "rejected"
        doc.rejection_reason = reason
        doc.rejected_at = datetime.now(timezone.utc)
        doc.rejected_by = officer_id
        # PR #13 — a rejected graduation submission voids the "nợ bằng" debt
        # fields (mirror reset_document) so the pending-diploma reminder + the
        # detail badge don't surface a debt on a rejected row.
        doc.graduation_proof_kind = None
        doc.supplement_due_date = None

        return doc

    async def confirm_document_format(
        self,
        profile_id: int,
        document_type_code: str,
        verified_format: str,
        officer_id: int,
    ) -> Optional[models.ProfileDocument]:
        """
        Confirm document format and mark as verified.

        This method performs the full verification:
        1. Updates verified_format (original | certified_copy | photo)
        2. Sets status to 'verified'
        3. Records verification timestamp
        4. Records officer who verified

        Args:
            profile_id: AdmissionProfile ID
            document_type_code: Document type code
            verified_format: original | certified_copy | photo
            officer_id: ID of officer performing verification

        Returns:
            Updated ProfileDocument or None
        """
        from datetime import datetime, timezone

        doc = await self.get_document_by_type(profile_id, document_type_code)
        if not doc:
            return None

        # Full verification update
        doc.verified_format = verified_format
        doc.status = "verified"
        doc.verified_at = datetime.now(timezone.utc)
        doc.verified_by = officer_id

        return doc

    # =========================================================================
    # CONFIRMATION TOKEN METHODS (Magic Link)
    # =========================================================================

    async def create_confirmation_token(
        self,
        profile_id: int,
        token: str,
        expires_at,
        action_type: str = "confirm",
    ) -> models.AdmissionConfirmationToken:
        """
        Issue (or refresh) the magic-link token for a profile + action.

        ADM-023 (2026-04-29): when an existing token row is present we
        REUSE it — only ``token``, ``expires_at`` and ``confirmed_at``
        are updated. The brute-force counters (``attempt_count``,
        ``lock_until``, ``locked_at``, ``lock_count``) are PRESERVED so
        an abuser can't simply request a fresh link to escape the
        ladder.

        Wave 7 (2026-05-16): add ``action_type`` param cho generate-side
        của 3 actions submit/resubmit/withdraw (W2-1 fix). Default 'confirm'
        cho backward-compat. Single token per profile semantics preserved
        — generating link cho action mới sẽ overwrite existing token
        (officer chỉ tạo 1 magic-link tại 1 thời điểm cho mỗi candidate).

        Args:
            profile_id: AdmissionProfile ID
            token: URL-safe random token string
            expires_at: Token expiration timestamp
            action_type: One of confirm | submit | resubmit | withdraw

        Returns:
            The single token row (refreshed or newly created).
        """
        from sqlalchemy import select as _select

        existing = (
            await self.db.execute(
                _select(models.AdmissionConfirmationToken).where(
                    models.AdmissionConfirmationToken.profile_id == profile_id
                )
            )
        ).scalar_one_or_none()

        if existing is not None:
            # Refresh value + expiry + action_type, clear consumed marker
            # so the new link is usable. Counters intentionally untouched.
            existing.token = token
            existing.expires_at = expires_at
            existing.confirmed_at = None
            existing.action_type = action_type  # Wave 7 — overwrite action
            # New email window starts → previous reminder dedupes are
            # stale (different expires_at). Reset reminder markers so
            # the beat task re-fires for the new window.
            existing.reminder_24h_sent_at = None
            existing.reminder_6h_sent_at = None
            await self.db.flush()
            return existing

        token_obj = models.AdmissionConfirmationToken(
            profile_id=profile_id,
            token=token,
            expires_at=expires_at,
            action_type=action_type,
        )
        self.db.add(token_obj)
        await self.db.flush()
        return token_obj

    async def get_token_by_value(
        self,
        token: str
    ) -> Optional[models.AdmissionConfirmationToken]:
        """
        Get confirmation token with profile and lead relationships loaded.

        Args:
            token: Token string from URL

        Returns:
            AdmissionConfirmationToken with profile.lead loaded, or None
        """
        stmt = (
            select(models.AdmissionConfirmationToken)
            .where(models.AdmissionConfirmationToken.token == token)
            .options(
                joinedload(models.AdmissionConfirmationToken.profile)
                .joinedload(models.AdmissionProfile.lead)
            )
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_token_for_confirm(
        self,
        token: str,
    ) -> Optional[models.AdmissionConfirmationToken]:
        """
        ADM-013: profile-first 3-step pessimistic lock for the magic-link
        confirm flow. Earlier shape used a single ``selectinload(profile)
        + with_for_update()`` query, which only locks the token row —
        the relationship load runs as a separate SELECT without a lock,
        so confirm could race override/finalize on the profile row.

        The new shape locks profile first, then token, then re-validates
        the FK so that confirm, override, and finalize all share the
        same lock order (profile → token-related work). With identical
        ordering across the three flows Postgres serialises them
        cleanly without deadlocks.

        Steps:
          1. Resolve ``profile_id`` from the token value (no lock; fast
             bail-out when the token is missing or already purged).
          2. ``SELECT AdmissionProfile FOR UPDATE`` for that
             ``profile_id`` (eager-load lead so the service can read
             ``profile.lead`` without firing a lazy load on the locked
             instance).
          3. ``SELECT AdmissionConfirmationToken FOR UPDATE`` by token
             value.
          4. Re-validate that ``token.profile_id`` still matches the
             locked profile. If override invalidated the token while we
             were waiting on the profile lock — or, in the unlikely
             event of a token recreated for a different profile — bail.

        Caller-side idempotency (``confirmed_at``, ``locked_at``,
        ``expires_at``) is preserved untouched: this method only
        changes when/where locks are acquired, never the validation
        rules in ``verify_and_confirm``.

        Args:
            token: Token string from URL.

        Returns:
            ``AdmissionConfirmationToken`` row-locked, with the
            ``profile`` relationship pre-bound to the *same* locked
            profile instance (no extra round-trip), or ``None`` if any
            of the four steps fails.
        """
        from sqlalchemy.orm import selectinload
        from sqlalchemy.orm.attributes import set_committed_value

        # Step 1 — Resolve profile_id without locking. If the token
        # has been deleted (e.g. an override invalidated it before this
        # request landed), surface as not-found cheaply.
        pid_stmt = select(models.AdmissionConfirmationToken.profile_id).where(
            models.AdmissionConfirmationToken.token == token
        )
        profile_id = (await self.db.execute(pid_stmt)).scalar_one_or_none()
        if profile_id is None:
            return None

        # Step 2 — Lock the profile row first. Eager-load lead so the
        # service body can read ``profile.lead`` without triggering an
        # async lazy load on the locked instance.
        profile_stmt = (
            select(models.AdmissionProfile)
            .where(models.AdmissionProfile.id == profile_id)
            .options(selectinload(models.AdmissionProfile.lead))
            .with_for_update()
        )
        locked_profile = (
            await self.db.execute(profile_stmt)
        ).scalar_one_or_none()
        if locked_profile is None:
            # Profile was deleted between resolve and lock (extremely
            # unlikely under the cascade FK, but defensive).
            return None

        # Step 3 — Lock the token row. Lock acquired AFTER the profile
        # lock so all three flows (confirm, override, finalize) share
        # the same profile→token ordering.
        token_stmt = (
            select(models.AdmissionConfirmationToken)
            .where(models.AdmissionConfirmationToken.token == token)
            .with_for_update()
        )
        token_obj = (await self.db.execute(token_stmt)).scalar_one_or_none()
        if token_obj is None:
            # Override/finalize ran during our profile-lock wait and
            # invalidated the token. Treat as not-found.
            return None

        # Step 4 — Re-validate FK after acquiring both locks. The
        # only realistic way this fails is if an override deleted the
        # token and a brand-new token was issued for a *different*
        # profile under the same value (impossible with 256-bit
        # randomness, but bail safely if it ever happens).
        if token_obj.profile_id != locked_profile.id:
            return None

        # Bind the locked profile onto the token's ``profile``
        # relationship without dirtying the session and without an
        # extra SELECT. Identity map already holds ``locked_profile``
        # for this PK, so this is the same instance the service will
        # mutate; the token's lazy-loaded relationship is short-
        # circuited to point at it.
        set_committed_value(token_obj, "profile", locked_profile)
        return token_obj

    async def increment_token_attempts(
        self,
        token_obj: models.AdmissionConfirmationToken,
        max_attempts: int = 5
    ) -> None:
        """
        Increment failed CCCD verification attempt count.
        
        Locks token if max attempts exceeded.
        
        Args:
            token_obj: Token to update
            max_attempts: Max attempts before locking (from config)
        """
        from datetime import datetime, timezone
        
        token_obj.attempt_count += 1
        if token_obj.attempt_count >= max_attempts:
            token_obj.locked_at = datetime.now(timezone.utc)
        await self.db.flush()

    async def mark_token_used(
        self,
        token_obj: models.AdmissionConfirmationToken,
    ) -> None:
        """
        Mark token as used (consumed). Does NOT change profile status.
        Profile state transition is handled by the service layer.

        Args:
            token_obj: Token to mark as used
        """
        from datetime import datetime, timezone

        token_obj.confirmed_at = datetime.now(timezone.utc)
        await self.db.flush()

    async def invalidate_existing_tokens(
        self,
        profile_id: int
    ) -> None:
        """
        Delete any existing tokens for a profile.
        
        Called before creating a new token (for resend functionality).
        
        Args:
            profile_id: AdmissionProfile ID
        """
        from sqlalchemy import delete
        
        stmt = delete(models.AdmissionConfirmationToken).where(
            models.AdmissionConfirmationToken.profile_id == profile_id
        )
        await self.db.execute(stmt)
        await self.db.flush()
    async def get_profile_scores(self, profile_id: int) -> list:
        """
        Get all subject scores for a profile.
        
        Args:
            profile_id: AdmissionProfile ID
            
        Returns:
            List of ProfileSubjectScore
        """
        from app.models.admission_config.profile_data import ProfileSubjectScore
        from sqlalchemy.orm import selectinload
        
        result = await self.db.execute(
            select(ProfileSubjectScore)
            .options(selectinload(ProfileSubjectScore.subject))
            .where(ProfileSubjectScore.profile_id == profile_id)
        )
        return result.scalars().all()

    async def update_profile_scores(
        self, 
        profile_id: int, 
        subject_scores: dict[str, float]
    ) -> list:
        """
        Update subject scores for a profile (Bulk Upsert).

        Strategy:
        1. Resolve subject codes to IDs
        2. Bulk update/insert into ProfileSubjectScore
        
        Args:
            profile_id: AdmissionProfile ID
            subject_scores: Dict of {subject_code: score}
        """
        from app.models.admission_config.profile_data import ProfileSubjectScore
        from app.models.admission_config.subject import Subject
        from sqlalchemy import delete, select
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        if not subject_scores:
            return []

        # 1. Resolve Subject Codes -> IDs
        # TODO: Caching mechanism for Subject IDs if performance needed
        stmt = select(Subject.id, Subject.code).where(
            Subject.code.in_(subject_scores.keys())
        )
        result = await self.db.execute(stmt)
        subjects = result.all() # [(id, code), ...]
        
        subject_map = {row.code: row.id for row in subjects}
        
        # Check for invalid codes
        invalid_codes = set(subject_scores.keys()) - set(subject_map.keys())
        if invalid_codes:
            # We silently ignore invalid codes or could raise error
            # For now, let's ignore to be robust, but log warning in service
            pass

        # 2. Sync Strategy: Delete scores NOT in the new list
        # This prevents "orphaned" scores if applicant changes subject group (e.g., A00 -> D01)
        valid_subject_ids = list(subject_map.values())
        
        if valid_subject_ids:
            delete_stmt = delete(ProfileSubjectScore).where(
                ProfileSubjectScore.profile_id == profile_id,
                ProfileSubjectScore.subject_id.notin_(valid_subject_ids)
            )
        else:
            # If no valid subjects provided but function called (and not None), clear all scores
            delete_stmt = delete(ProfileSubjectScore).where(
                ProfileSubjectScore.profile_id == profile_id
            )
            
        await self.db.execute(delete_stmt)

        # 3. Prepare Data for Upsert
        upsert_data = []
        for code, score in subject_scores.items():
            if code in subject_map:
                upsert_data.append({
                    "profile_id": profile_id,
                    "subject_id": subject_map[code],
                    "score": score,
                })
        
        if not upsert_data:
            return []

        # 4. Execute Upsert (PostgreSQL specific)
        # INSERT ... ON CONFLICT (profile_id, subject_id) DO UPDATE SET score = EXCLUDED.score
        stmt = pg_insert(ProfileSubjectScore).values(upsert_data)
        stmt = stmt.on_conflict_do_update(
            index_elements=['profile_id', 'subject_id'], # uq_profile_subject_score
            set_=dict(score=stmt.excluded.score)
        )
        
        await self.db.execute(stmt)
        
        # Return updated scores
        return await self.get_profile_scores(profile_id)
