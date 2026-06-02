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

from sqlalchemy import select, func
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
    AdmissionPath,
)

# Type alias for load depth control
LoadLevel = Literal["light", "with_groups", "full"]


from app.repositories.base import BaseRepository

class AdmissionConfigRepository(BaseRepository[AdmissionCriteria]):
    """Repository for Admission Config entities (read-only)."""

    def __init__(self, db: AsyncSession):
        super().__init__(db, AdmissionCriteria)

    # =========================================================================
    # INTEGRITY CHECKS (Red Team Fix)
    # =========================================================================

    async def check_subject_usage(self, subject_id: int) -> bool:
        """
        Check if Subject is used in any SubjectGroup.
        Returns True if used, False if safe to delete.
        """
        query = select(SubjectGroupSubject).where(SubjectGroupSubject.subject_id == subject_id).limit(1)
        result = await self.db.execute(query)
        return result.first() is not None

    async def check_subject_group_usage(self, group_id: int) -> bool:
        """
        Check if SubjectGroup is used in any AdmissionCriteria.
        Returns True if used, False if safe to delete.
        """
        query = select(CriteriaSubjectGroup).where(CriteriaSubjectGroup.subject_group_id == group_id).limit(1)
        result = await self.db.execute(query)
        return result.first() is not None

    async def check_criteria_usage(self, criteria_id: int) -> bool:
        """
        Check if AdmissionCriteria is used in any OfferingAdmissionConfig or AdmissionPath.
        Returns True if used, False if safe to delete.

        Phase 0c hot-fix (2026-05-02): both `OfferingAdmissionConfig` and
        `AdmissionPath` declare the FK column as ``criteria_id`` — verified
        in `app/models/admission_config/offering_config.py:38` and
        `app/models/admission_config/admission_path.py:82`. The previous
        ``admission_criteria_id`` references on this method raised
        ``AttributeError`` at runtime any time an admin tried to delete a
        criteria that was actually in use; the BusinessRuleViolation that
        protects the data was never reached. Locked by
        `tests/repositories/test_admission_config_repository_p0c.py`.
        """
        # Check OfferingConfig
        q1 = select(OfferingAdmissionConfig).where(OfferingAdmissionConfig.criteria_id == criteria_id).limit(1)
        r1 = await self.db.execute(q1)
        if r1.first():
            return True

        # Check AdmissionPath (FK column verified `criteria_id`).
        q2 = select(AdmissionPath).where(AdmissionPath.criteria_id == criteria_id).limit(1)
        r2 = await self.db.execute(q2)
        if r2.first():
            return True

        return False

    async def get_filtered(
        self,
        skip: int = 0,
        limit: int = 100,
        **filters
    ) -> tuple[int, list[AdmissionCriteria]]:
        """
        Implement abstract method for filtered queries.
        For Admission Config, we primarily use specific get methods.
        This generic implementation is minimal to satisfy BaseRepository.
        """
        query = select(AdmissionCriteria)
        
        # Simple generic filtering
        for key, value in filters.items():
            if hasattr(AdmissionCriteria, key) and value is not None:
                query = query.where(getattr(AdmissionCriteria, key) == value)
                
        # Count
        count_query = select(func.count()).select_from(query.subquery())
        total = await self.db.scalar(count_query) or 0
        
        # Pagination
        query = query.offset(skip).limit(limit)
        result = await self.db.execute(query)
        
        return total, list(result.scalars().all())

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

    async def get_subject_by_id(self, subject_id: int) -> Optional[Subject]:
        """Get subject by ID."""
        result = await self.db.execute(
            select(Subject).where(Subject.id == subject_id)
        )
        return result.scalar_one_or_none()

    async def create_subject(
        self,
        code: str,
        name_vi: str,
        display_order: int = 0,
        is_active: bool = True,
    ) -> Subject:
        """Create new Subject."""
        subject = Subject(
            code=code,
            name_vi=name_vi,
            display_order=display_order,
            is_active=is_active,
        )
        self.db.add(subject)
        await self.db.flush()
        return subject

    async def update_subject(
        self,
        subject: Subject,
        **updates
    ) -> Subject:
        """Update existing Subject."""
        for key, value in updates.items():
            if value is not None and hasattr(subject, key):
                setattr(subject, key, value)
        await self.db.flush()
        return subject

    async def delete_subject(self, subject_id: int) -> bool:
        """Delete Subject by ID."""
        result = await self.db.execute(
            select(Subject).where(Subject.id == subject_id)
        )
        subject = result.scalar_one_or_none()
        if not subject:
            return False
        await self.db.delete(subject)
        await self.db.flush()
        return True

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

    async def get_subject_group_by_id(
        self,
        group_id: int,
        with_subjects: bool = True
    ) -> Optional[SubjectGroup]:
        """Get subject group by ID."""
        query = select(SubjectGroup).where(SubjectGroup.id == group_id)
        
        if with_subjects:
            query = query.options(
                selectinload(SubjectGroup.subject_mappings)
                .selectinload(SubjectGroupSubject.subject)
            )
        
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def create_subject_group(
        self,
        code: str,
        name: str,
        display_order: int = 0,
        is_active: bool = True,
    ) -> SubjectGroup:
        """Create new SubjectGroup."""
        group = SubjectGroup(
            code=code,
            name=name,
            display_order=display_order,
            is_active=is_active,
        )
        self.db.add(group)
        await self.db.flush()
        return group

    async def update_subject_group(
        self,
        group: SubjectGroup,
        **updates
    ) -> SubjectGroup:
        """Update existing SubjectGroup."""
        for key, value in updates.items():
            if value is not None and hasattr(group, key):
                setattr(group, key, value)
        await self.db.flush()
        return group

    async def delete_subject_group(self, group_id: int) -> bool:
        """Delete SubjectGroup by ID."""
        result = await self.db.execute(
            select(SubjectGroup).where(SubjectGroup.id == group_id)
        )
        group = result.scalar_one_or_none()
        if not group:
            return False
        await self.db.delete(group)
        await self.db.flush()
        return True

    async def update_subject_group_mappings(
        self,
        group_id: int,
        subject_ids: list[int]
    ) -> SubjectGroup:
        """
        Replace all subject mappings for a group.
        
        Args:
            group_id: SubjectGroup ID
            subject_ids: List of Subject IDs to link (ordered)
        
        Returns:
            Updated SubjectGroup with new mappings
        """
        from sqlalchemy import delete as sql_delete
        
        # Remove existing mappings
        await self.db.execute(
            sql_delete(SubjectGroupSubject).where(
                SubjectGroupSubject.subject_group_id == group_id
            )
        )
        
        # Add new mappings with position
        for position, subject_id in enumerate(subject_ids, start=1):
            mapping = SubjectGroupSubject(
                subject_group_id=group_id,
                subject_id=subject_id,
                position=position,
            )
            self.db.add(mapping)
        
        await self.db.flush()
        return await self.get_subject_group_by_id(group_id, with_subjects=True)

    async def get_subject_group_subject(
        self, group_id: int, subject_id: int
    ) -> Optional[SubjectGroupSubject]:
        """Get the join row linking a subject to a group (or None)."""
        result = await self.db.execute(
            select(SubjectGroupSubject).where(
                SubjectGroupSubject.subject_group_id == group_id,
                SubjectGroupSubject.subject_id == subject_id,
            )
        )
        return result.scalar_one_or_none()

    async def add_subject_group_subject(
        self, group_id: int, subject_id: int, position: int
    ) -> SubjectGroupSubject:
        """Insert one subject→group mapping at the given position."""
        mapping = SubjectGroupSubject(
            subject_group_id=group_id,
            subject_id=subject_id,
            position=position,
        )
        self.db.add(mapping)
        await self.db.flush()
        return mapping

    async def delete_subject_group_subject(
        self, group_id: int, subject_id: int
    ) -> bool:
        """Remove one subject→group mapping. Returns False if absent."""
        mapping = await self.get_subject_group_subject(group_id, subject_id)
        if not mapping:
            return False
        await self.db.delete(mapping)
        await self.db.flush()
        return True

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

    async def get_method_by_id(self, method_id: int) -> Optional[AdmissionMethod]:
        """Get admission method by ID."""
        result = await self.db.execute(
            select(AdmissionMethod).where(AdmissionMethod.id == method_id)
        )
        return result.scalar_one_or_none()

    async def create_method(
        self,
        code: str,
        name: str,
        description: str | None = None,
        requires_gpa: bool = False,
        requires_subject_scores: bool = True,
        display_order: int = 0,
        is_active: bool = True,
    ) -> AdmissionMethod:
        """
        Create new AdmissionMethod.
        
        Raises:
            IntegrityError if code already exists.
        """
        method = AdmissionMethod(
            code=code,
            name=name,
            description=description,
            requires_gpa=requires_gpa,
            requires_subject_scores=requires_subject_scores,
            display_order=display_order,
            is_active=is_active,
        )
        self.db.add(method)
        await self.db.flush()
        return method

    async def update_method(
        self,
        method: AdmissionMethod,
        **updates
    ) -> AdmissionMethod:
        """
        Update existing AdmissionMethod.
        
        Args:
            method: The method entity to update
            **updates: Fields to update (name, description, is_active, etc.)
        
        Returns:
            Updated method entity
        """
        for key, value in updates.items():
            if value is not None and hasattr(method, key):
                setattr(method, key, value)
        await self.db.flush()
        return method

    async def delete_method(self, method_id: int) -> bool:
        """
        Delete AdmissionMethod by ID.
        
        Returns:
            True if deleted, False if not found
        """
        result = await self.db.execute(
            select(AdmissionMethod).where(AdmissionMethod.id == method_id)
        )
        method = result.scalar_one_or_none()
        if not method:
            return False
        await self.db.delete(method)
        await self.db.flush()
        return True

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

    # =========================================================================
    # ADMISSION CRITERIA CRUD (Write Operations)
    # =========================================================================

    async def create_criteria(
        self,
        method_id: int,
        code: str,
        name: str,
        min_gpa: float | None = None,
        min_score: float | None = None,
        required_subject_count: int | None = None,
        subject_selection_mode: str = "fixed",
        scoring_method: str = "sum",
        max_possible_score: float | None = None,
        min_subject_score: float | None = None,
        conditions: str | None = None,
        is_active: bool = False,  # Draft by default
        policy_version: str = "2025.1",
    ) -> AdmissionCriteria:
        """
        Create new AdmissionCriteria.
        
        Note: Criteria is created as inactive (draft) by default.
        Caller must set is_active=True or call subsequent update.
        """
        criteria = AdmissionCriteria(
            method_id=method_id,
            code=code,
            name=name,
            min_gpa=min_gpa,
            min_score=min_score,
            required_subject_count=required_subject_count,
            subject_selection_mode=subject_selection_mode,
            scoring_method=scoring_method,
            max_possible_score=max_possible_score,
            min_subject_score=min_subject_score,
            conditions=conditions,
            is_active=is_active,
            policy_version=policy_version,
        )
        self.db.add(criteria)
        await self.db.flush()
        return criteria

    async def update_criteria(
        self,
        criteria: AdmissionCriteria,
        **updates
    ) -> AdmissionCriteria:
        """
        Update existing AdmissionCriteria.
        
        Args:
            criteria: The criteria entity to update
            **updates: Fields to update (min_gpa, min_score, is_active, etc.)
        
        Returns:
            Updated criteria entity
        """
        allowed_fields = {
            "name", "min_gpa", "min_score", "required_subject_count",
            "subject_selection_mode", "scoring_method", "max_possible_score",
            "min_subject_score", "conditions", "is_active", "policy_version",
            "effective_from", "effective_to",
        }
        
        for field, value in updates.items():
            if field in allowed_fields:
                setattr(criteria, field, value)
        
        await self.db.flush()
        return criteria

    async def delete_criteria(self, criteria_id: int) -> bool:
        """
        Delete AdmissionCriteria by ID.
        
        Returns:
            True if deleted, False if not found
        """
        criteria = await self.db.get(AdmissionCriteria, criteria_id)
        if not criteria:
            return False
        
        await self.db.delete(criteria)
        await self.db.flush()
        return True

    async def get_criteria_by_id(
        self,
        criteria_id: int,
        load_level: LoadLevel = "with_groups"
    ) -> AdmissionCriteria | None:
        """Get single criteria by ID with configurable load level."""
        query = select(AdmissionCriteria).where(AdmissionCriteria.id == criteria_id)
        query = self._apply_criteria_load_level(query, load_level)
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def add_subject_groups_to_criteria(
        self,
        criteria_id: int,
        subject_group_ids: list[int]
    ) -> list[CriteriaSubjectGroup]:
        """
        Add subject group mappings to criteria.
        
        Creates CriteriaSubjectGroup entries linking criteria to allowed groups.
        """
        mappings = []
        for group_id in subject_group_ids:
            mapping = CriteriaSubjectGroup(
                criteria_id=criteria_id,
                subject_group_id=group_id
            )
            self.db.add(mapping)
            mappings.append(mapping)
        
        await self.db.flush()
        return mappings

    async def remove_all_subject_groups_from_criteria(
        self,
        criteria_id: int
    ) -> int:
        """
        Remove all subject group mappings from criteria.
        
        Returns:
            Number of mappings removed
        """
        from sqlalchemy import delete
        
        stmt = delete(CriteriaSubjectGroup).where(
            CriteriaSubjectGroup.criteria_id == criteria_id
        )
        result = await self.db.execute(stmt)
        await self.db.flush()
        return result.rowcount
