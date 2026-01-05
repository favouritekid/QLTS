# app/repositories/admission_config_repository.py
"""
Admission Config Repository.

THIN LAYER - Read-only config access.
NO business logic. NO scoring calculations.

Load Level Strategy:
- light: Minimal data, fast queries
- with_groups: Include related groups (for UI)
- full: Deep load with subjects (for scoring)

Usage:
    repo = AdmissionConfigRepository(db)
    subjects = await repo.get_subjects()
    criteria = await repo.get_criteria_by_code("HB_DH_3MON", load_level="full")
"""

from typing import Literal, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.admission_config import (
    Subject,
    SubjectGroup,
    SubjectGroupSubject,
    AdmissionMethod,
    AdmissionCriteria,
    CriteriaSubjectGroup,
    OfferingAdmissionConfig,
)

# Type alias for load depth control
LoadLevel = Literal["light", "with_groups", "full"]


from app.repositories.base import BaseRepository

class AdmissionConfigRepository(BaseRepository[AdmissionCriteria]):
    """Repository for Admission Config entities (read-only)."""

    def __init__(self, db: AsyncSession):
        super().__init__(db, AdmissionCriteria)

    # =========================================================================
    # SUBJECTS
    # =========================================================================

    async def get_subjects(self, active_only: bool = True) -> list[Subject]:
        """Get all subjects."""
        query = select(Subject).order_by(Subject.display_order)
        if active_only:
            query = query.where(Subject.is_active == True)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_subject_by_code(self, code: str) -> Optional[Subject]:
        """Get subject by code."""
        result = await self.db.execute(
            select(Subject).where(Subject.code == code)
        )
        return result.scalar_one_or_none()

    async def get_subjects_by_ids(self, ids: list[int]) -> list[Subject]:
        """Get subjects by list of IDs."""
        result = await self.db.execute(
            select(Subject).where(Subject.id.in_(ids))
        )
        return list(result.scalars().all())

    # =========================================================================
    # SUBJECT GROUPS
    # =========================================================================

    async def get_subject_groups(
        self, 
        with_subjects: bool = True,
        active_only: bool = True
    ) -> list[SubjectGroup]:
        """Get all subject groups, optionally with subject mappings."""
        query = select(SubjectGroup).order_by(SubjectGroup.display_order)
        
        if with_subjects:
            query = query.options(
                selectinload(SubjectGroup.subject_mappings)
                .selectinload(SubjectGroupSubject.subject)
            )
        
        if active_only:
            query = query.where(SubjectGroup.is_active == True)
        
        result = await self.db.execute(query)
        return list(result.scalars().unique().all())

    async def get_subject_group_by_code(
        self, 
        code: str,
        with_subjects: bool = True
    ) -> Optional[SubjectGroup]:
        """Get subject group by code."""
        query = select(SubjectGroup).where(SubjectGroup.code == code)
        
        if with_subjects:
            query = query.options(
                selectinload(SubjectGroup.subject_mappings)
                .selectinload(SubjectGroupSubject.subject)
            )
        
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def get_subjects_in_group(
        self, 
        group_code: str,
        active_only: bool = True
    ) -> list[Subject]:
        """
        Get all subjects in a group, ordered by position.
        
        FIX: Now respects is_active for both group and subjects.
        """
        query = (
            select(Subject)
            .join(SubjectGroupSubject)
            .join(SubjectGroup)
            .where(SubjectGroup.code == group_code)
            .order_by(SubjectGroupSubject.position)
        )
        
        # ✅ FIX: Check is_active for both group and subjects
        if active_only:
            query = query.where(
                SubjectGroup.is_active == True,
                Subject.is_active == True
            )
        
        result = await self.db.execute(query)
        return list(result.scalars().all())

    # =========================================================================
    # ADMISSION METHODS
    # =========================================================================

    async def get_admission_methods(
        self, 
        active_only: bool = True
    ) -> list[AdmissionMethod]:
        """Get all admission methods."""
        query = select(AdmissionMethod).order_by(AdmissionMethod.display_order)
        if active_only:
            query = query.where(AdmissionMethod.is_active == True)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_method_by_code(self, code: str) -> Optional[AdmissionMethod]:
        """Get admission method by code."""
        result = await self.db.execute(
            select(AdmissionMethod).where(AdmissionMethod.code == code)
        )
        return result.scalar_one_or_none()

    # =========================================================================
    # ADMISSION CRITERIA
    # =========================================================================

    async def get_criteria_by_method(
        self, 
        method_code: str,
        active_only: bool = True,
        load_level: LoadLevel = "with_groups"
    ) -> list[AdmissionCriteria]:
        """
        Get all criteria for a method.
        
        FIX: Added order_by and load_level control.
        """
        query = (
            select(AdmissionCriteria)
            .join(AdmissionMethod)
            .where(AdmissionMethod.code == method_code)
            .order_by(AdmissionCriteria.id)  # ✅ FIX: Deterministic order
        )
        
        # ✅ FIX: Load level control
        query = self._apply_criteria_load_level(query, load_level)
        
        if active_only:
            query = query.where(AdmissionCriteria.is_active == True)
        
        result = await self.db.execute(query)
        return list(result.scalars().unique().all())

    async def get_criteria_by_code(
        self, 
        code: str,
        load_level: LoadLevel = "with_groups"
    ) -> Optional[AdmissionCriteria]:
        """
        Get single criteria by code.
        
        Load levels:
        - light: criteria + method only
        - with_groups: + subject group codes
        - full: + subjects in each group (for scoring)
        """
        query = select(AdmissionCriteria).where(AdmissionCriteria.code == code)
        
        # ✅ FIX: Configurable load depth
        query = self._apply_criteria_load_level(query, load_level)
        
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def get_all_criteria(
        self,
        active_only: bool = True,
        load_level: LoadLevel = "light"
    ) -> list[AdmissionCriteria]:
        """Get all criteria with configurable load level."""
        query = (
            select(AdmissionCriteria)
            .order_by(AdmissionCriteria.id)  # ✅ Deterministic
        )
        
        query = self._apply_criteria_load_level(query, load_level)
        
        if active_only:
            query = query.where(AdmissionCriteria.is_active == True)
        
        result = await self.db.execute(query)
        return list(result.scalars().unique().all())

    def _apply_criteria_load_level(self, query, load_level: LoadLevel):
        """
        Apply selectinload based on load level.
        
        - light: Only method (for listings)
        - with_groups: + subject groups (for UI selection)
        - full: + subjects in groups (for scoring)
        """
        if load_level == "light":
            # Just load method for display
            query = query.options(
                selectinload(AdmissionCriteria.method)
            )
        
        elif load_level == "with_groups":
            # Load method + subject groups (no subjects)
            query = query.options(
                selectinload(AdmissionCriteria.method),
                selectinload(AdmissionCriteria.subject_group_mappings)
                .selectinload(CriteriaSubjectGroup.subject_group)
            )
        
        elif load_level == "full":
            # Full depth: method + groups + subjects
            query = query.options(
                selectinload(AdmissionCriteria.method),
                selectinload(AdmissionCriteria.subject_group_mappings)
                .selectinload(CriteriaSubjectGroup.subject_group)
                .selectinload(SubjectGroup.subject_mappings)
                .selectinload(SubjectGroupSubject.subject)
            )
        
        return query

    # =========================================================================
    # OFFERING ADMISSION CONFIG
    # =========================================================================

    async def get_offering_configs(
        self, 
        academic_info_id: int,
        active_only: bool = True,
        load_level: LoadLevel = "with_groups"
    ) -> list[OfferingAdmissionConfig]:
        """Get admission configs for an offering."""
        query = (
            select(OfferingAdmissionConfig)
            .where(OfferingAdmissionConfig.academic_info_id == academic_info_id)
        )
        
        # Apply load level for embedded criteria
        if load_level == "light":
            query = query.options(
                selectinload(OfferingAdmissionConfig.criteria)
            )
        elif load_level == "with_groups":
            query = query.options(
                selectinload(OfferingAdmissionConfig.criteria)
                .selectinload(AdmissionCriteria.method)
            )
        elif load_level == "full":
            query = query.options(
                selectinload(OfferingAdmissionConfig.criteria)
                .selectinload(AdmissionCriteria.method),
                selectinload(OfferingAdmissionConfig.criteria)
                .selectinload(AdmissionCriteria.subject_group_mappings)
                .selectinload(CriteriaSubjectGroup.subject_group)
            )
        
        if active_only:
            query = query.where(OfferingAdmissionConfig.is_active == True)
        
        result = await self.db.execute(query)
        return list(result.scalars().unique().all())

    async def get_offering_config_by_id(
        self,
        config_id: int,
        load_level: LoadLevel = "with_groups"
    ) -> Optional[OfferingAdmissionConfig]:
        """Get single offering config by ID."""
        query = (
            select(OfferingAdmissionConfig)
            .where(OfferingAdmissionConfig.id == config_id)
        )
        
        if load_level == "light":
            query = query.options(
                selectinload(OfferingAdmissionConfig.criteria)
            )
        elif load_level == "with_groups":
            query = query.options(
                selectinload(OfferingAdmissionConfig.criteria)
                .selectinload(AdmissionCriteria.method),
                selectinload(OfferingAdmissionConfig.criteria)
                .selectinload(AdmissionCriteria.subject_group_mappings)
                .selectinload(CriteriaSubjectGroup.subject_group)
            )
        elif load_level == "full":
            query = query.options(
                selectinload(OfferingAdmissionConfig.criteria)
                .selectinload(AdmissionCriteria.method),
                selectinload(OfferingAdmissionConfig.criteria)
                .selectinload(AdmissionCriteria.subject_group_mappings)
                .selectinload(CriteriaSubjectGroup.subject_group)
                .selectinload(SubjectGroup.subject_mappings)
                .selectinload(SubjectGroupSubject.subject)
            )
        
        result = await self.db.execute(query)
        return result.scalar_one_or_none()
