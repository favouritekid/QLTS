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

from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from app import models
from app.repositories.base import BaseRepository


class AdmissionRepository(BaseRepository[models.AdmissionProfile]):
    """Repository for AdmissionProfile model operations."""

    def __init__(self, db: AsyncSession):
        """
        Initialize Admission repository.
        
        Args:
            db: SQLAlchemy async session
        """
        super().__init__(db, models.AdmissionProfile)

    async def get_filtered(
        self,
        skip: int = 0,
        limit: int = 50,
        **filters
    ) -> List[models.AdmissionProfile]:
        """
        Get filtered list of admission profiles with pagination.
        
        Args:
            skip: Number of records to skip
            limit: Maximum records to return
            **filters: Filter parameters
            
        Returns:
            List of AdmissionProfile instances
        """
        query = (
            select(models.AdmissionProfile)
            .options(
                joinedload(models.AdmissionProfile.lead),
                selectinload(models.AdmissionProfile.student),
            )
            .offset(skip)
            .limit(limit)
        )
        
        if filters.get("status"):
            query = query.where(models.AdmissionProfile.status == filters["status"])
        
        if filters.get("lead_id"):
            query = query.where(models.AdmissionProfile.lead_id == filters["lead_id"])
            
        result = await self.db.execute(query)
        return list(result.scalars().all())

    # =========================================================================
    # CREATE PROFILE METHODS
    # =========================================================================

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
                selectinload(models.Lead.admission_profile),
            )
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
                joinedload(models.AdmissionProfile.lead),
                selectinload(models.AdmissionProfile.student),
            )
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

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
            AdmissionProfile with lead loaded
        """
        stmt = (
            select(models.AdmissionProfile)
            .where(models.AdmissionProfile.id == profile_id)
            .options(
                joinedload(models.AdmissionProfile.lead),
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
        exclude_profile_id: Optional[int] = None
    ) -> Optional[models.AdmissionProfile]:
        """
        Check if citizen_id is already used by another profile.
        
        ✅ SPRINT 6: For submit_and_evaluate validation.
        
        Args:
            citizen_id: Citizen ID to check
            exclude_profile_id: Profile ID to exclude (current profile)
            
        Returns:
            Existing AdmissionProfile or None
        """
        stmt = select(models.AdmissionProfile).where(
            models.AdmissionProfile.citizen_id == citizen_id,
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
