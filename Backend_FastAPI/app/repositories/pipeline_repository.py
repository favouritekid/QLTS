# app/repositories/pipeline_repository.py
"""
✅ SPRINT 4: PipelineRepository

Repository pattern implementation for Pipeline Configuration data access.
Centralizes all PipelineStage and ConsultationStatus database queries.
"""

from typing import Optional, List, Dict, Any, Tuple
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.repositories.base import BaseRepository


class PipelineRepository(BaseRepository[models.PipelineStage]):
    """
    Repository for Pipeline Configuration data access.
    
    ✅ SPRINT 4: Created for pipeline_service migration.
    Handles both PipelineStage and ConsultationStatus queries.
    """
    
    def __init__(self, db: AsyncSession):
        super().__init__(db, models.PipelineStage)  # ✅ Fix: correct arg order

    async def get_filtered(
        self,
        skip: int = 0,
        limit: int = 100,
        **filters
    ) -> Tuple[int, List[models.PipelineStage]]:
        """
        Get filtered pipeline stages with pagination.
        
        ✅ SPRINT 4: Required abstract method implementation.
        """
        query = select(self.model).order_by(self.model.order)
        count_query = select(func.count(self.model.id))
        
        # Apply pagination
        query = query.offset(skip).limit(limit)
        
        # Execute
        total_result = await self.db.execute(count_query)
        total = total_result.scalar_one()
        
        result = await self.db.execute(query)
        stages = list(result.scalars().all())
        
        return total, stages

    # =========================================================================
    # PIPELINE STAGE METHODS
    # =========================================================================

    async def get_all_stages_ordered(self) -> List[models.PipelineStage]:
        """Get all pipeline stages ordered by order field."""
        query = select(models.PipelineStage).order_by(models.PipelineStage.order)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def check_stage_name_exists(
        self,
        name: str,
        exclude_id: Optional[str] = None
    ) -> bool:
        """Check if a stage name already exists."""
        query = select(models.PipelineStage).where(
            models.PipelineStage.name == name
        )
        if exclude_id:
            query = query.where(models.PipelineStage.id != exclude_id)
        result = await self.db.scalar(query)
        return result is not None

    async def check_stage_order_exists(
        self,
        order: int,
        exclude_id: Optional[str] = None
    ) -> bool:
        """Check if a stage order already exists."""
        query = select(models.PipelineStage).where(
            models.PipelineStage.order == order
        )
        if exclude_id:
            query = query.where(models.PipelineStage.id != exclude_id)
        result = await self.db.scalar(query)
        return result is not None

    async def count_statuses_in_stage(self, stage_id: str) -> int:
        """Count consultation statuses linked to a stage."""
        query = select(func.count(models.ConsultationStatus.id)).where(
            models.ConsultationStatus.stage_id == stage_id
        )
        result = await self.db.scalar(query)
        return result or 0

    # =========================================================================
    # CONSULTATION STATUS METHODS
    # =========================================================================

    async def get_all_statuses(self) -> List[models.ConsultationStatus]:
        """Get all consultation statuses."""
        query = select(models.ConsultationStatus)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def check_status_name_exists(
        self,
        name: str,
        exclude_id: Optional[str] = None
    ) -> bool:
        """Check if a status name already exists."""
        query = select(models.ConsultationStatus).where(
            models.ConsultationStatus.name == name
        )
        if exclude_id:
            query = query.where(models.ConsultationStatus.id != exclude_id)
        result = await self.db.scalar(query)
        return result is not None

    async def count_leads_using_status(self, status_id: str) -> int:
        """Count leads using a specific status."""
        query = select(func.count(models.Lead.id)).where(
            models.Lead.consultation_status_id == status_id
        )
        result = await self.db.scalar(query)
        return result or 0

    async def count_consultations_using_status(self, status_id: str) -> int:
        """Count consultation records using a specific status (excluding soft-deleted)."""
        query = select(func.count(models.Consultation.id)).where(
            models.Consultation.consultation_status_id == status_id,
            models.Consultation.deleted_at.is_(None),  # Exclude soft-deleted consultations
        )
        result = await self.db.scalar(query)
        return result or 0

    # =========================================================================
    # STATUS LOOKUP METHODS
    # =========================================================================

    async def get_statuses_for_stage(self, stage_id: str) -> List[models.ConsultationStatus]:
        """Get all consultation statuses for a specific stage."""
        from sqlalchemy.orm import selectinload
        
        query = (
            select(models.ConsultationStatus)
            .where(models.ConsultationStatus.stage_id == stage_id)
            .options(selectinload(models.ConsultationStatus.stage))
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_universal_statuses(self) -> List[models.ConsultationStatus]:
        """Get all universal (global) consultation statuses."""
        from sqlalchemy.orm import selectinload
        
        query = (
            select(models.ConsultationStatus)
            .where(models.ConsultationStatus.is_universal == True)
            .options(selectinload(models.ConsultationStatus.stage))
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())

    # =========================================================================
    # ALLOWED TRANSITION METHODS
    # =========================================================================

    async def get_all_transitions_with_statuses(self) -> List[models.AllowedTransition]:
        """Get all allowed transitions with related statuses loaded."""
        from sqlalchemy.orm import selectinload
        
        query = (
            select(models.AllowedTransition)
            .options(
                selectinload(models.AllowedTransition.from_status).selectinload(models.ConsultationStatus.stage),
                selectinload(models.AllowedTransition.to_status).selectinload(models.ConsultationStatus.stage),
            )
            .order_by(models.AllowedTransition.from_status_id)
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_transition_by_id_with_statuses(
        self,
        transition_id: int
    ) -> Optional[models.AllowedTransition]:
        """Get a transition by ID with related statuses loaded."""
        from sqlalchemy.orm import selectinload
        
        query = (
            select(models.AllowedTransition)
            .options(
                selectinload(models.AllowedTransition.from_status).selectinload(models.ConsultationStatus.stage),
                selectinload(models.AllowedTransition.to_status).selectinload(models.ConsultationStatus.stage),
            )
            .where(models.AllowedTransition.id == transition_id)
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def check_transition_exists(
        self,
        from_status_id: str,
        to_status_id: str
    ) -> bool:
        """Check if at least one transition between two statuses exists.

        (from_status_id, to_status_id) is NOT unique — the same pair can have
        several rows with different trigger_type (e.g. sts04->sts20 exists as
        both 'system' for the SLA beat and 'role' for manual close). Use
        LIMIT 1 + .first() instead of scalar_one_or_none(), which would raise
        MultipleResultsFound on such a pair.
        """
        from sqlalchemy import and_

        query = select(models.AllowedTransition.id).where(
            and_(
                models.AllowedTransition.from_status_id == from_status_id,
                models.AllowedTransition.to_status_id == to_status_id
            )
        ).limit(1)
        result = await self.db.execute(query)
        return result.first() is not None

    async def get_all_statuses_with_stage(self) -> List[models.ConsultationStatus]:
        """Get all statuses with stage relationship loaded."""
        from sqlalchemy.orm import selectinload
        
        query = (
            select(models.ConsultationStatus)
            .options(selectinload(models.ConsultationStatus.stage))
            .order_by(
                models.ConsultationStatus.is_universal.desc(),
                models.ConsultationStatus.stage_id,
                models.ConsultationStatus.name
            )
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_allowed_next_statuses_from(
        self,
        from_status_id: str
    ) -> List[models.ConsultationStatus]:
        """Get statuses allowed as transition destinations from a given status."""
        from sqlalchemy.orm import selectinload
        
        query = (
            select(models.ConsultationStatus)
            .join(
                models.AllowedTransition,
                models.ConsultationStatus.id == models.AllowedTransition.to_status_id
            )
            .where(models.AllowedTransition.from_status_id == from_status_id)
            .options(selectinload(models.ConsultationStatus.stage))
            .order_by(models.ConsultationStatus.name)
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_universal_statuses_with_stage(self) -> List[models.ConsultationStatus]:
        """Get all universal statuses with stage relationship loaded."""
        from sqlalchemy.orm import selectinload
        
        query = (
            select(models.ConsultationStatus)
            .where(models.ConsultationStatus.is_universal == True)
            .options(selectinload(models.ConsultationStatus.stage))
            .order_by(models.ConsultationStatus.name)
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())

    # =========================================================================
    # VALIDATION METHODS (Sprint 5)
    # =========================================================================

    async def check_stage_name_exists(
        self,
        name: str,
        exclude_id: Optional[str] = None
    ) -> bool:
        """
        Check if a pipeline stage with given name already exists.
        
        Args:
            name: Stage name to check
            exclude_id: Optional stage ID to exclude (for updates)
            
        Returns:
            True if name exists, False otherwise
        """
        query = select(models.PipelineStage).where(
            models.PipelineStage.name == name
        )
        if exclude_id:
            query = query.where(models.PipelineStage.id != exclude_id)
        
        result = await self.db.execute(query)
        return result.scalar_one_or_none() is not None

    async def check_stage_order_exists(
        self,
        order: int,
        exclude_id: Optional[str] = None
    ) -> bool:
        """
        Check if a pipeline stage with given order already exists.
        
        Args:
            order: Stage order to check
            exclude_id: Optional stage ID to exclude (for updates)
            
        Returns:
            True if order exists, False otherwise
        """
        query = select(models.PipelineStage).where(
            models.PipelineStage.order == order
        )
        if exclude_id:
            query = query.where(models.PipelineStage.id != exclude_id)
        
        result = await self.db.execute(query)
        return result.scalar_one_or_none() is not None

    async def count_statuses_by_stage(self, stage_id: str) -> int:
        """
        Count consultation statuses belonging to a stage.
        
        Args:
            stage_id: Stage ID to count statuses for
            
        Returns:
            Number of statuses
        """
        query = select(func.count(models.ConsultationStatus.id)).where(
            models.ConsultationStatus.stage_id == stage_id
        )
        result = await self.db.execute(query)
        return result.scalar_one() or 0

    async def check_status_name_exists(
        self,
        name: str,
        exclude_id: Optional[str] = None
    ) -> bool:
        """
        Check if a consultation status with given name already exists.
        
        Args:
            name: Status name to check
            exclude_id: Optional status ID to exclude (for updates)
            
        Returns:
            True if name exists, False otherwise
        """
        query = select(models.ConsultationStatus).where(
            models.ConsultationStatus.name == name
        )
        if exclude_id:
            query = query.where(models.ConsultationStatus.id != exclude_id)
        
        result = await self.db.execute(query)
        return result.scalar_one_or_none() is not None

    async def count_leads_by_status(self, status_id: str) -> int:
        """
        Count leads using a consultation status.
        
        Args:
            status_id: Status ID to check
            
        Returns:
            Number of leads using this status
        """
        query = select(func.count(models.Lead.id)).where(
            models.Lead.consultation_status_id == status_id
        )
        result = await self.db.execute(query)
        return result.scalar_one() or 0

    async def count_consultations_by_status(self, status_id: str) -> int:
        """
        Count consultations using a consultation status.
        
        Args:
            status_id: Status ID to check
            
        Returns:
            Number of consultations using this status
        """
        query = select(func.count(models.Consultation.id)).where(
            models.Consultation.consultation_status_id == status_id,
            models.Consultation.deleted_at.is_(None),  # Exclude soft-deleted consultations
        )
        result = await self.db.execute(query)
        return result.scalar_one() or 0

    async def check_transition_exists_by_object(
        self,
        from_status_id: str,
        to_status_id: str
    ) -> Optional[models.AllowedTransition]:
        """
        Get existing transition if it exists.
        
        Args:
            from_status_id: Source status ID
            to_status_id: Target status ID
            
        Returns:
            AllowedTransition object or None
        """
        from sqlalchemy import and_

        # (from, to) is not unique (multiple trigger_type rows possible, e.g.
        # sts04->sts20) — return the first match rather than scalar_one_or_none.
        query = select(models.AllowedTransition).where(
            and_(
                models.AllowedTransition.from_status_id == from_status_id,
                models.AllowedTransition.to_status_id == to_status_id
            )
        ).limit(1)
        result = await self.db.execute(query)
        return result.scalars().first()

