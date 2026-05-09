# app/repositories/admission_path_repository.py
"""
Admission Path Repository.

Provides data access for AdmissionPath entities with:
- Eager loading of relationships (selectinload)
- N+1 prevention
- No business logic (pure data access)
"""

from typing import Iterable, List, Optional, Sequence, Tuple
from sqlalchemy import select, func, distinct, or_, cast
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.admission_config import (
    AdmissionPath,
    AdmissionCriteria,
    CriteriaSubjectGroup,
    DocumentGroup,
    DocumentGroupItem,
    SubjectGroup,
    SubjectGroupSubject,
)
from app.models.offering_academic_info import OfferingAcademicInfo
from app.models.program_offering import ProgramOffering
from app.repositories.base import BaseRepository


# phase1_03 (#184 Wave 1 PR-1B') — typed array element for ``@>`` /
# ``&&`` casts. ``create_type=False`` because the migration owns the
# DDL. ``literal_column("admission_audience")`` was the first cut but
# fails compile (AttributeError on ``_variant_mapping`` per Codex
# review on PR-1B'); the real type expression is needed for SQLA to
# render the proper ``CAST(... AS admission_audience[])``.
_AUDIENCE_ENUM_TYPE = postgresql.ENUM(
    "POST_THCS",
    "POST_THPT",
    "LIEN_THONG_TC",
    "LIEN_THONG_CD",
    "VLVH",
    name="admission_audience",
    create_type=False,
)
_AUDIENCE_ARRAY_TYPE = postgresql.ARRAY(_AUDIENCE_ENUM_TYPE)


class AdmissionPathRepository(BaseRepository[AdmissionPath]):
    """
    Repository for AdmissionPath entity.
    
    Follows MASTER_ARCHITECTURE.md:
    - No business logic
    - Uses selectinload for relationships
    - Returns None if not found (no exceptions)
    """
    
    def __init__(self, db: AsyncSession):
        super().__init__(db, AdmissionPath)
    
    # =========================================================================
    # STANDARD CRUD WITH EAGER LOADING
    # =========================================================================
    
    async def get_by_ids(self, ids: Iterable[int]) -> List[AdmissionPath]:
        """Batch fetch paths by ID list — used by the list-endpoint
        minor-correction resolver to avoid N+1 path queries.

        Returns the matching rows in undefined order; callers that need
        a dict keyed by id should build it from the result. Empty input
        short-circuits to avoid emitting an ``IN ()`` clause.
        """
        unique_ids = list({i for i in ids if i is not None})
        if not unique_ids:
            return []
        stmt = select(AdmissionPath).where(AdmissionPath.id.in_(unique_ids))
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_by_id_with_relations(
        self,
        path_id: int
    ) -> Optional[AdmissionPath]:
        """
        Get path by ID with all relationships loaded.
        
        Returns:
            AdmissionPath with academic_info, admission_method loaded, or None
        """
        query = (
            select(AdmissionPath)
            .where(AdmissionPath.id == path_id)
            .options(
                selectinload(AdmissionPath.academic_info)
                .selectinload(OfferingAcademicInfo.offering)
                .selectinload(ProgramOffering.program),
                selectinload(AdmissionPath.admission_method),
                selectinload(AdmissionPath.activator),
                selectinload(AdmissionPath.criteria).selectinload(
                    AdmissionCriteria.subject_group_mappings
                ).selectinload(CriteriaSubjectGroup.subject_group)
                .selectinload(SubjectGroup.subject_mappings)
                .selectinload(SubjectGroupSubject.subject),
            )
        )
        result = await self.db.execute(query)
        return result.scalars().first()
    
    async def get_paths_by_academic_info(
        self,
        academic_info_id: int
    ) -> List[AdmissionPath]:
        """
        Get all paths for a specific academic info (offering + year).
        
        Returns:
            List of AdmissionPath with relationships loaded
        """
        query = (
            select(AdmissionPath)
            .where(AdmissionPath.academic_info_id == academic_info_id)
            .options(
                selectinload(AdmissionPath.academic_info)
                .selectinload(OfferingAcademicInfo.offering)
                .selectinload(ProgramOffering.program),
                selectinload(AdmissionPath.admission_method),
                selectinload(AdmissionPath.activator),
                selectinload(AdmissionPath.criteria).selectinload(
                    AdmissionCriteria.subject_group_mappings
                ).selectinload(CriteriaSubjectGroup.subject_group),
            )
            .order_by(AdmissionPath.display_order, AdmissionPath.id)
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())
    
    async def get_path_by_offering_and_method(
        self,
        academic_info_id: int,
        admission_method_id: int
    ) -> Optional[AdmissionPath]:
        """
        Check if a path already exists for this offering + method combination.

        Used for unique constraint validation and profile creation.

        ✅ FIX: Eager load admission_method to prevent MissingGreenlet error
        when service code accesses admission_path.admission_method.status.
        """
        query = (
            select(AdmissionPath)
            .where(
                AdmissionPath.academic_info_id == academic_info_id,
                AdmissionPath.admission_method_id == admission_method_id
            )
            .options(
                selectinload(AdmissionPath.admission_method)  # ← FIX: Eager load
            )
        )
        result = await self.db.execute(query)
        return result.scalars().first()

    async def get_path_by_round_and_method(
        self,
        admission_round_id: int,
        academic_info_id: int,
        admission_method_id: int,
    ) -> Optional[AdmissionPath]:
        """Phase 2 v8.2 PR-2B v2 — 3-col lookup helper.

        Returns matching path under (round, academic_info, method) tuple
        per Q5 v8.2 UNIQUE constraint (PR-2C v2 swap). Eager loads
        admission_method để tránh MissingGreenlet downstream.
        """
        query = (
            select(AdmissionPath)
            .where(
                AdmissionPath.admission_round_id == admission_round_id,
                AdmissionPath.academic_info_id == academic_info_id,
                AdmissionPath.admission_method_id == admission_method_id,
            )
            .options(selectinload(AdmissionPath.admission_method))
        )
        result = await self.db.execute(query)
        return result.scalars().first()

    async def list_paths_by_audience(
        self,
        audience: str,
        *,
        academic_info_id: Optional[int] = None,
        include_legacy_null: bool = True,
    ) -> List[AdmissionPath]:
        """List active paths visible to a single ``admission_audience``.

        phase1_03 (#184 Wave 1 PR-1B') — uses PostgreSQL containment
        operator ``@>`` so the query hits the
        ``ix_admission_path_applicable_to`` GIN index. NEVER rewrite
        this as ``WHERE :audience = ANY(applicable_to)`` — that
        operator yields the same logical result but the planner
        cannot pick a GIN index for ``= ANY(arr)``, so the storefront
        endpoint would seq-scan the entire ``admission_path`` table
        (PLAN line 2646-2657 anti-pattern).

        ``include_legacy_null=True`` (default) ORs in paths whose
        ``applicable_to`` is NULL — required for Phase 1+2 because
        legacy / not-yet-backfilled paths must remain visible.
        Phase 3 flips this to ``False`` after the validator gate
        ("X path null applicable_to → admin set trước") completes.
        """
        # CAST([:audience] AS admission_audience[]) — typed PG ENUM
        # array so the @> operator hits the GIN index. Using
        # ``literal_column("admission_audience")`` for the inner type
        # fails compile on SQLAlchemy 2.x; the real type expression
        # ``postgresql.ARRAY(postgresql.ENUM(...))`` is required.
        audience_array = cast([audience], _AUDIENCE_ARRAY_TYPE)
        contains = AdmissionPath.applicable_to.op("@>")(audience_array)

        if include_legacy_null:
            audience_filter = or_(
                AdmissionPath.applicable_to.is_(None),
                contains,
            )
        else:
            audience_filter = contains

        query = (
            select(AdmissionPath)
            .where(audience_filter)
            .options(
                selectinload(AdmissionPath.admission_method),
                selectinload(AdmissionPath.academic_info)
                .selectinload(OfferingAcademicInfo.offering)
                .selectinload(ProgramOffering.program),
            )
            .order_by(AdmissionPath.display_order, AdmissionPath.id)
        )
        if academic_info_id is not None:
            query = query.where(AdmissionPath.academic_info_id == academic_info_id)

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def list_paths_by_audiences_overlap(
        self,
        audiences: Sequence[str],
        *,
        academic_info_id: Optional[int] = None,
        include_legacy_null: bool = True,
    ) -> List[AdmissionPath]:
        """List active paths whose audience overlaps any of ``audiences``.

        phase1_03 (#184 Wave 1 PR-1B') — uses PostgreSQL overlap
        operator ``&&`` so the query hits the GIN index. Same
        anti-pattern guard as ``list_paths_by_audience``: NEVER use
        ``= ANY()`` (planner can't pick GIN).

        Empty input → returns no paths (matches "audience filter
        active but caller passed no buckets" semantic). Caller
        wanting "all audiences" should not invoke this method.
        """
        if not audiences:
            return []

        audience_array = cast(list(audiences), _AUDIENCE_ARRAY_TYPE)
        overlaps = AdmissionPath.applicable_to.op("&&")(audience_array)

        if include_legacy_null:
            audience_filter = or_(
                AdmissionPath.applicable_to.is_(None),
                overlaps,
            )
        else:
            audience_filter = overlaps

        query = (
            select(AdmissionPath)
            .where(audience_filter)
            .options(
                selectinload(AdmissionPath.admission_method),
                selectinload(AdmissionPath.academic_info)
                .selectinload(OfferingAcademicInfo.offering)
                .selectinload(ProgramOffering.program),
            )
            .order_by(AdmissionPath.display_order, AdmissionPath.id)
        )
        if academic_info_id is not None:
            query = query.where(AdmissionPath.academic_info_id == academic_info_id)

        result = await self.db.execute(query)
        return list(result.scalars().all())
    
    async def get_active_paths_by_offering_id(
        self,
        offering_id: int
    ) -> List[AdmissionPath]:
        """
        Get all ACTIVE paths for a ProgramOffering (across all academic years).
        
        Used by LeadApplicationForm dropdown to show available admission methods.
        
        Returns:
            List of active AdmissionPath with method + criteria loaded
        """
        query = (
            select(AdmissionPath)
            .join(OfferingAcademicInfo)
            .where(
                OfferingAcademicInfo.offering_id == offering_id,
                OfferingAcademicInfo.is_published == True,
                AdmissionPath.status == "active"
            )
            .options(
                selectinload(AdmissionPath.academic_info)
                .selectinload(OfferingAcademicInfo.offering)
                .selectinload(ProgramOffering.program),
                selectinload(AdmissionPath.admission_method),
                # Eager load criteria with subject groups (for LeadApplicationForm)
                selectinload(AdmissionPath.criteria).selectinload(
                    AdmissionCriteria.subject_group_mappings
                ).selectinload(CriteriaSubjectGroup.subject_group),
            )
            .order_by(AdmissionPath.display_order, AdmissionPath.id)
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())
    
    # =========================================================================
    # ACADEMIC YEAR QUERIES
    # =========================================================================
    
    async def get_distinct_years(self) -> List[int]:
        """
        Get all distinct academic years from OfferingAcademicInfo.
        
        Returns:
            List of years sorted DESC (newest first)
        """
        query = (
            select(distinct(OfferingAcademicInfo.academic_year))
            .where(OfferingAcademicInfo.is_deleted == False)
            .order_by(OfferingAcademicInfo.academic_year.desc())
        )
        result = await self.db.execute(query)
        return [row[0] for row in result.all()]
    
    # =========================================================================
    # DOCUMENT GROUP QUERIES (Override Resolution)
    # =========================================================================
    
    async def get_document_groups_for_path(
        self,
        offering_type_id: int,
        admission_method_id: int,
        admission_path_id: int | None = None,
    ) -> Tuple[List[DocumentGroup], List[DocumentGroup], List[DocumentGroup]]:
        """
        Get document groups for 3-tier resolution
        (phase1_06 / #184 Wave 1 PR-1C').

        Returns a triple ordered from highest to lowest precedence:
            (path_groups, method_specific_groups, shared_groups)

        * **Tier 1** — ``admission_path_id = X`` (when caller passes
          ``admission_path_id``). Path-specific override; wins over
          everything else when present. Empty list when caller passes
          ``None`` (legacy callers, e.g. profile creation pre-PR-1C').
        * **Tier 2** — ``admission_path_id IS NULL`` AND
          ``admission_method_id = Y``. Existing legacy method-specific
          override; preserved for backward-compat with shared/method
          configs not yet migrated to path-level.
        * **Tier 3** — ``admission_path_id IS NULL`` AND
          ``admission_method_id IS NULL`` AND ``offering_type_id = Z``.
          Default offering-type-wide shared bucket.

        The caller (``admission_path_service.resolve_documents_for_path``)
        applies the precedence: tier 1 wins fully if present; else
        tier 2 wins fully; else tier 3.
        """
        # Tier 1 — path-specific (only when caller passes a path id;
        # legacy callers send None and skip this query entirely).
        path_groups: List[DocumentGroup] = []
        if admission_path_id is not None:
            path_query = (
                select(DocumentGroup)
                .where(
                    DocumentGroup.admission_path_id == admission_path_id,
                    DocumentGroup.is_active == True,
                )
                .options(
                    selectinload(DocumentGroup.items).selectinload(
                        DocumentGroupItem.document_type
                    )
                )
            )
            path_result = await self.db.execute(path_query)
            path_groups = list(path_result.scalars().all())

        # Tier 3 — shared (applies to all methods of the offering type).
        # Note: admission_path_id IS NULL filter required to keep
        # path-level rows out of the shared bucket once they exist.
        shared_query = (
            select(DocumentGroup)
            .where(
                DocumentGroup.offering_type_id == offering_type_id,
                DocumentGroup.admission_method_id == None,  # noqa: E711
                DocumentGroup.admission_path_id == None,  # noqa: E711
                DocumentGroup.is_active == True
            )
            .options(
                selectinload(DocumentGroup.items).selectinload(
                    DocumentGroupItem.document_type
                )
            )
        )

        # Tier 2 — method-specific, NOT path-specific.
        method_query = (
            select(DocumentGroup)
            .where(
                DocumentGroup.offering_type_id == offering_type_id,
                DocumentGroup.admission_method_id == admission_method_id,
                DocumentGroup.admission_path_id == None,  # noqa: E711
                DocumentGroup.is_active == True
            )
            .options(
                selectinload(DocumentGroup.items).selectinload(
                    DocumentGroupItem.document_type
                )
            )
        )

        shared_result = await self.db.execute(shared_query)
        method_result = await self.db.execute(method_query)

        return (
            path_groups,
            list(method_result.scalars().all()),
            list(shared_result.scalars().all()),
        )
    
    # =========================================================================
    # FILTERED QUERIES (Required by BaseRepository)
    # =========================================================================
    
    async def get_filtered(
        self,
        skip: int = 0,
        limit: int = 100,
        **filters
    ) -> Tuple[int, List[AdmissionPath]]:
        """
        Get filtered paths with pagination.
        
        Filters:
            - academic_year: int
            - status: str
            - admission_method_id: int
        """
        query = select(AdmissionPath)
        count_query = select(func.count()).select_from(AdmissionPath)
        
        # Apply filters
        if filters.get("academic_info_id"):
            query = query.where(
                AdmissionPath.academic_info_id == filters["academic_info_id"]
            )
            count_query = count_query.where(
                AdmissionPath.academic_info_id == filters["academic_info_id"]
            )
        
        if filters.get("status"):
            query = query.where(AdmissionPath.status == filters["status"])
            count_query = count_query.where(AdmissionPath.status == filters["status"])
        
        if filters.get("admission_method_id"):
            query = query.where(
                AdmissionPath.admission_method_id == filters["admission_method_id"]
            )
            count_query = count_query.where(
                AdmissionPath.admission_method_id == filters["admission_method_id"]
            )
        
        # Add eager loading
        query = query.options(
            selectinload(AdmissionPath.academic_info)
            .selectinload(OfferingAcademicInfo.offering)
            .selectinload(ProgramOffering.program),
            selectinload(AdmissionPath.admission_method),
            selectinload(AdmissionPath.criteria).selectinload(
                AdmissionCriteria.subject_group_mappings
            ).selectinload(CriteriaSubjectGroup.subject_group),
        )
        
        # Pagination
        query = query.offset(skip).limit(limit).order_by(
            AdmissionPath.display_order, AdmissionPath.id
        )
        
        # Execute
        total = await self.db.execute(count_query)
        result = await self.db.execute(query)
        
        return (total.scalar() or 0, list(result.scalars().all()))
