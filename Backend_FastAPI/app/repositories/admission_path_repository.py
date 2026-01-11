# app/repositories/admission_path_repository.py
"""
Admission Path Repository.

Provides data access for AdmissionPath entities with:
- Eager loading of relationships (selectinload)
- N+1 prevention
- No business logic (pure data access)
"""

from typing import List, Optional, Tuple
from sqlalchemy import select, func, distinct
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.admission_config import AdmissionPath, DocumentGroup, DocumentGroupItem
from app.models.offering_academic_info import OfferingAcademicInfo
from app.repositories.base import BaseRepository


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
                selectinload(AdmissionPath.academic_info).selectinload(
                    OfferingAcademicInfo.offering
                ),
                selectinload(AdmissionPath.admission_method),
                selectinload(AdmissionPath.activator),
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
                selectinload(AdmissionPath.admission_method),
                selectinload(AdmissionPath.activator),
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
        
        Used for unique constraint validation.
        """
        query = (
            select(AdmissionPath)
            .where(
                AdmissionPath.academic_info_id == academic_info_id,
                AdmissionPath.admission_method_id == admission_method_id
            )
        )
        result = await self.db.execute(query)
        return result.scalars().first()
    
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
        admission_method_id: int
    ) -> Tuple[List[DocumentGroup], List[DocumentGroup]]:
        """
        Get document groups for resolution.
        
        Returns:
            Tuple of (shared_groups, method_specific_groups)
            - shared_groups: admission_method_id IS NULL
            - method_specific_groups: admission_method_id = given method
        """
        # Shared groups (applies to all methods)
        shared_query = (
            select(DocumentGroup)
            .where(
                DocumentGroup.offering_type_id == offering_type_id,
                DocumentGroup.admission_method_id == None,  # noqa: E711
                DocumentGroup.is_active == True
            )
            .options(
                selectinload(DocumentGroup.items).selectinload(
                    DocumentGroupItem.document_type
                )
            )
        )
        
        # Method-specific groups (override)
        method_query = (
            select(DocumentGroup)
            .where(
                DocumentGroup.offering_type_id == offering_type_id,
                DocumentGroup.admission_method_id == admission_method_id,
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
            list(shared_result.scalars().all()),
            list(method_result.scalars().all())
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
            selectinload(AdmissionPath.admission_method),
            selectinload(AdmissionPath.academic_info),
        )
        
        # Pagination
        query = query.offset(skip).limit(limit).order_by(
            AdmissionPath.display_order, AdmissionPath.id
        )
        
        # Execute
        total = await self.db.execute(count_query)
        result = await self.db.execute(query)
        
        return (total.scalar() or 0, list(result.scalars().all()))
