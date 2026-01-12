# app/services/admission_config_service.py
"""
Admission Config Service.

Business logic for Admission Configuration management.
Follows MASTER_ARCHITECTURE.md:
- No HTTPException (domain exceptions only)
- No db.commit() (caller commits)
- Returns (result, callback) tuple
"""

from typing import Callable, Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from app.models.admission_config import AdmissionCriteria
from app.repositories.admission_config_repository import AdmissionConfigRepository
from app.schemas.admission_config import (
    AdmissionCriteriaCreate,
    AdmissionCriteriaUpdate,
)
from app.utils.exceptions import (
    ResourceNotFoundError,
    DuplicateResourceError,
    BusinessRuleViolation,
)


async def _noop_callback():
    """No-op callback for operations without side effects."""
    pass


class AdmissionConfigService:
    """
    Service for Admission Configuration management.
    
    Handles business logic for:
    - AdmissionCriteria CRUD
    - Subject group mappings
    - Validation rules
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = AdmissionConfigRepository(db)

    # =========================================================================
    # CRITERIA CRUD
    # =========================================================================

    async def create_criteria(
        self,
        data: AdmissionCriteriaCreate,
        user: User,
    ) -> tuple[AdmissionCriteria, Callable[[], Any]]:
        """
        Create new AdmissionCriteria.
        
        Validation:
        - method_id must exist
        - code must be unique
        - At least one of min_gpa or min_score required
        
        Returns:
            Tuple of (created criteria, callback)
        """
        # Validate method exists
        method = await self.repo.get_method_by_code(data.method_code)
        if not method:
            raise ResourceNotFoundError(f"Method '{data.method_code}' not found")

        # Check for duplicate code
        existing = await self.repo.get_criteria_by_code(data.code, load_level="light")
        if existing:
            raise DuplicateResourceError(f"Criteria with code '{data.code}' already exists")

        # Business rule: at least one threshold required
        if data.min_gpa is None and data.min_score is None:
            raise BusinessRuleViolation("At least min_gpa or min_score is required")

        # Create criteria
        criteria = await self.repo.create_criteria(
            method_id=method.id,
            code=data.code,
            name=data.name,
            min_gpa=data.min_gpa,
            min_score=data.min_score,
            required_subject_count=data.required_subject_count,
            subject_selection_mode=data.subject_selection_mode or "fixed",
            scoring_method=data.scoring_method or "sum",
            max_possible_score=data.max_possible_score,
            min_subject_score=data.min_subject_score,
            conditions=data.conditions,
            is_active=data.is_active or False,
            policy_version=data.policy_version or "2025.1",
        )

        # Add subject groups if provided
        if data.subject_group_ids:
            await self.repo.add_subject_groups_to_criteria(
                criteria.id,
                data.subject_group_ids
            )

        return criteria, _noop_callback

    async def update_criteria(
        self,
        criteria: AdmissionCriteria,
        data: AdmissionCriteriaUpdate,
        user: User,
    ) -> tuple[AdmissionCriteria, Callable[[], Any]]:
        """
        Update existing AdmissionCriteria.
        
        Note: method_id cannot be changed after creation.
        
        Returns:
            Tuple of (updated criteria, callback)
        """
        # Build update dict from provided fields
        updates = {}
        
        if data.name is not None:
            updates["name"] = data.name
        if data.min_gpa is not None:
            updates["min_gpa"] = data.min_gpa
        if data.min_score is not None:
            updates["min_score"] = data.min_score
        if data.required_subject_count is not None:
            updates["required_subject_count"] = data.required_subject_count
        if data.subject_selection_mode is not None:
            updates["subject_selection_mode"] = data.subject_selection_mode
        if data.scoring_method is not None:
            updates["scoring_method"] = data.scoring_method
        if data.max_possible_score is not None:
            updates["max_possible_score"] = data.max_possible_score
        if data.min_subject_score is not None:
            updates["min_subject_score"] = data.min_subject_score
        if data.conditions is not None:
            updates["conditions"] = data.conditions
        if data.is_active is not None:
            updates["is_active"] = data.is_active
        if data.policy_version is not None:
            updates["policy_version"] = data.policy_version

        # Apply updates
        if updates:
            criteria = await self.repo.update_criteria(criteria, **updates)

        # Update subject groups if provided
        if data.subject_group_ids is not None:
            await self.repo.remove_all_subject_groups_from_criteria(criteria.id)
            if data.subject_group_ids:
                await self.repo.add_subject_groups_to_criteria(
                    criteria.id,
                    data.subject_group_ids
                )

        return criteria, _noop_callback

    async def delete_criteria(
        self,
        criteria: AdmissionCriteria,
        user: User,
    ) -> tuple[bool, Callable[[], Any]]:
        """
        Delete AdmissionCriteria.
        
        Business Rule: Cannot delete if linked to active AdmissionPaths.
        
        Returns:
            Tuple of (success, callback)
        """
        # TODO: Add check for linked AdmissionPaths when that relationship is established
        
        success = await self.repo.delete_criteria(criteria.id)
        return success, _noop_callback

    async def get_criteria(
        self,
        criteria_id: int,
        load_level: str = "with_groups"
    ) -> AdmissionCriteria | None:
        """Get criteria by ID."""
        return await self.repo.get_criteria_by_id(criteria_id, load_level=load_level)
