# app/repositories/application_repository.py
"""
✅ SPRINT 4: ApplicationRepository

Repository pattern implementation for Application (Hồ sơ Tuyển sinh) data access.
Centralizes all Application-related database queries.
"""

from typing import Optional, List
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app import models
from app.repositories.base import BaseRepository


class ApplicationRepository(BaseRepository[models.Application]):
    """
    Repository for Application (Hồ sơ Tuyển sinh) data access.
    
    ✅ SPRINT 4: Created for application_service migration.
    """
    
    def __init__(self, db: AsyncSession):
        super().__init__(models.Application, db)

    async def get_by_id(
        self,
        application_id: int,
        load_relationships: bool = True,
        load_lead: bool = False,
        include_deleted: bool = False
    ) -> Optional[models.Application]:
        """
        Get Application by ID with optional relationship loading.
        
        Args:
            application_id: Application ID
            load_relationships: Load major_program, program_offering, officer
            load_lead: Load lead with officer and unit
            include_deleted: Include soft-deleted applications
            
        Returns:
            Application or None if not found
        """
        query = select(self.model).where(self.model.id == application_id)
        
        if not include_deleted:
            query = query.where(self.model.deleted_at.is_(None))
        
        # Load lead with nested relationships for IDOR check
        if load_lead or load_relationships:
            query = query.options(
                selectinload(models.Application.lead).options(
                    selectinload(models.Lead.assigned_officer),
                    selectinload(models.Lead.unit)
                )
            )
        
        if load_relationships:
            query = query.options(
                selectinload(models.Application.major_program),
                selectinload(models.Application.program_offering),
                selectinload(models.Application.officer),
            )
        
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def get_by_lead_id(
        self,
        lead_id: int,
        load_relationships: bool = True,
        include_deleted: bool = False
    ) -> Optional[models.Application]:
        """
        Get Application by Lead ID.
        
        Args:
            lead_id: Lead ID
            load_relationships: Load major_program, program_offering, officer
            include_deleted: Include soft-deleted applications
            
        Returns:
            Application or None if not found
        """
        query = select(self.model).where(self.model.lead_id == lead_id)
        
        if not include_deleted:
            query = query.where(self.model.deleted_at.is_(None))
        
        if load_relationships:
            query = query.options(
                selectinload(models.Application.major_program),
                selectinload(models.Application.program_offering),
                selectinload(models.Application.officer),
            )
        
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def check_lead_exists(self, lead_id: int) -> Optional[models.Lead]:
        """Check if Lead exists."""
        query = select(models.Lead).where(models.Lead.id == lead_id)
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def get_with_lead_for_event(
        self,
        application_id: int
    ) -> Optional[models.Application]:
        """
        Get Application by ID with lead and major_program loaded.
        Used for socket event payloads after create.
        """
        query = (
            select(self.model)
            .where(self.model.id == application_id)
            .options(
                selectinload(models.Application.lead),
                selectinload(models.Application.major_program),
            )
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def get_full_for_update(
        self,
        application_id: int
    ) -> Optional[models.Application]:
        """
        Get Application by ID with all relationships loaded.
        Used for reloading after update.
        """
        query = (
            select(self.model)
            .where(self.model.id == application_id)
            .options(
                selectinload(models.Application.major_program),
                selectinload(models.Application.program_offering),
                selectinload(models.Application.officer),
                selectinload(models.Application.lead),
            )
        )
        result = await self.db.execute(query)
        return result.scalar_one()
