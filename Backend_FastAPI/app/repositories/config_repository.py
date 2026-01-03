# app/repositories/config_repository.py
"""
✅ PATTERN A COMPLIANT - Config Repository

Repository for all configuration-related models:
- OfficerAssignmentConfig
- SkillRequirementRule
- ConfigDegreeLevel
- ConfigOfferingType
- ConfigDocumentType

Following Repository Pattern to separate data access from business logic.
"""

from typing import Any, List, Optional, Tuple

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app import models
from app.repositories.base import BaseRepository


class AssignmentConfigRepository(BaseRepository[models.OfficerAssignmentConfig]):
    """Repository for OfficerAssignmentConfig model."""

    def __init__(self, db: AsyncSession):
        super().__init__(db, models.OfficerAssignmentConfig)

    async def get_by_unit_id(self, unit_id: int) -> Optional[models.OfficerAssignmentConfig]:
        """Get assignment config by unit ID."""
        result = await self.db.execute(
            select(self.model).where(self.model.unit_id == unit_id)
        )
        return result.scalar_one_or_none()

    async def get_by_unit_id_for_update(self, unit_id: int) -> Optional[models.OfficerAssignmentConfig]:
        """Get assignment config by unit ID with row lock for update."""
        result = await self.db.execute(
            select(self.model)
            .where(self.model.unit_id == unit_id)
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def get_filtered(
        self,
        skip: int = 0,
        limit: int = 100,
        **filters
    ) -> Tuple[int, List[models.OfficerAssignmentConfig]]:
        """Get filtered assignment configs."""
        query = select(self.model)
        count = await self.count()
        
        result = await self.db.execute(query.offset(skip).limit(limit))
        return count, list(result.scalars().all())


class SkillRuleRepository(BaseRepository[models.SkillRequirementRule]):
    """Repository for SkillRequirementRule model."""

    def __init__(self, db: AsyncSession):
        super().__init__(db, models.SkillRequirementRule)

    async def get_all_rules(self) -> List[models.SkillRequirementRule]:
        """Get all skill rules."""
        result = await self.db.execute(select(self.model))
        return list(result.scalars().all())

    async def get_filtered(
        self,
        skip: int = 0,
        limit: int = 100,
        **filters
    ) -> Tuple[int, List[models.SkillRequirementRule]]:
        """Get filtered skill rules."""
        query = select(self.model)
        count = await self.count()
        
        result = await self.db.execute(query.offset(skip).limit(limit))
        return count, list(result.scalars().all())


class DegreeLevelRepository(BaseRepository[models.ConfigDegreeLevel]):
    """Repository for ConfigDegreeLevel model."""

    def __init__(self, db: AsyncSession):
        super().__init__(db, models.ConfigDegreeLevel)

    async def get_all_active(self, active_only: bool = True) -> List[models.ConfigDegreeLevel]:
        """Get all degree levels ordered by display_order."""
        query = select(self.model)
        
        if active_only:
            query = query.where(self.model.is_active == True)
        
        query = query.order_by(self.model.display_order)
        
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_by_code(self, code: str) -> Optional[models.ConfigDegreeLevel]:
        """Get degree level by code."""
        result = await self.db.execute(
            select(self.model).where(self.model.code == code)
        )
        return result.scalar_one_or_none()

    async def get_by_name(self, name: str) -> Optional[models.ConfigDegreeLevel]:
        """Get degree level by name."""
        result = await self.db.execute(
            select(self.model).where(self.model.name == name)
        )
        return result.scalar_one_or_none()

    async def check_code_exists(self, code: str, exclude_id: Optional[int] = None) -> bool:
        """Check if code already exists (optionally excluding an ID for updates)."""
        query = select(self.model).where(self.model.code == code)
        if exclude_id:
            query = query.where(self.model.id != exclude_id)
        result = await self.db.execute(query)
        return result.scalar_one_or_none() is not None

    async def check_name_exists(self, name: str, exclude_id: Optional[int] = None) -> bool:
        """Check if name already exists (optionally excluding an ID for updates)."""
        query = select(self.model).where(self.model.name == name)
        if exclude_id:
            query = query.where(self.model.id != exclude_id)
        result = await self.db.execute(query)
        return result.scalar_one_or_none() is not None

    async def is_used_by_programs(self, name: str) -> bool:
        """Check if degree level is being used by any MajorProgram."""
        result = await self.db.execute(
            select(models.MajorProgram)
            .where(models.MajorProgram.degree_level == name)
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def get_programs_by_degree_name(self, name: str) -> List[models.MajorProgram]:
        """Get all MajorPrograms using this degree level name."""
        result = await self.db.execute(
            select(models.MajorProgram)
            .where(models.MajorProgram.degree_level == name)
        )
        return list(result.scalars().all())

    async def get_filtered(
        self,
        skip: int = 0,
        limit: int = 100,
        **filters
    ) -> Tuple[int, List[models.ConfigDegreeLevel]]:
        """Get filtered degree levels."""
        active_only = filters.get("active_only", True)
        query = select(self.model)
        
        if active_only:
            query = query.where(self.model.is_active == True)
        
        count = await self.count(self.model.is_active == True if active_only else None)
        
        query = query.order_by(self.model.display_order).offset(skip).limit(limit)
        result = await self.db.execute(query)
        return count, list(result.scalars().all())


class OfferingTypeRepository(BaseRepository[models.ConfigOfferingType]):
    """Repository for ConfigOfferingType model."""

    def __init__(self, db: AsyncSession):
        super().__init__(db, models.ConfigOfferingType)

    async def get_all_active(self, active_only: bool = True) -> List[models.ConfigOfferingType]:
        """Get all offering types ordered by display_order."""
        query = select(self.model)
        
        if active_only:
            query = query.where(self.model.is_active == True)
        
        query = query.order_by(self.model.display_order)
        
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_by_code(self, code: str) -> Optional[models.ConfigOfferingType]:
        """Get offering type by code."""
        result = await self.db.execute(
            select(self.model).where(self.model.code == code)
        )
        return result.scalar_one_or_none()

    async def get_by_name(self, name: str) -> Optional[models.ConfigOfferingType]:
        """Get offering type by name."""
        result = await self.db.execute(
            select(self.model).where(self.model.name == name)
        )
        return result.scalar_one_or_none()

    async def check_code_exists(self, code: str, exclude_id: Optional[int] = None) -> bool:
        """Check if code already exists."""
        query = select(self.model).where(self.model.code == code)
        if exclude_id:
            query = query.where(self.model.id != exclude_id)
        result = await self.db.execute(query)
        return result.scalar_one_or_none() is not None

    async def check_name_exists(self, name: str, exclude_id: Optional[int] = None) -> bool:
        """Check if name already exists."""
        query = select(self.model).where(self.model.name == name)
        if exclude_id:
            query = query.where(self.model.id != exclude_id)
        result = await self.db.execute(query)
        return result.scalar_one_or_none() is not None

    async def is_used_by_offerings(self, name: str) -> bool:
        """Check if offering type is being used by any ProgramOffering."""
        result = await self.db.execute(
            select(models.ProgramOffering)
            .where(models.ProgramOffering.offering_type == name)
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def get_offerings_by_type_name(self, name: str) -> List[models.ProgramOffering]:
        """Get all ProgramOfferings using this offering type."""
        result = await self.db.execute(
            select(models.ProgramOffering)
            .where(models.ProgramOffering.offering_type == name)
        )
        return list(result.scalars().all())

    async def get_filtered(
        self,
        skip: int = 0,
        limit: int = 100,
        **filters
    ) -> Tuple[int, List[models.ConfigOfferingType]]:
        """Get filtered offering types."""
        active_only = filters.get("active_only", True)
        query = select(self.model)
        
        if active_only:
            query = query.where(self.model.is_active == True)
        
        count = await self.count(self.model.is_active == True if active_only else None)
        
        query = query.order_by(self.model.display_order).offset(skip).limit(limit)
        result = await self.db.execute(query)
        return count, list(result.scalars().all())


class DocumentTypeRepository(BaseRepository[models.ConfigDocumentType]):
    """Repository for ConfigDocumentType model."""

    def __init__(self, db: AsyncSession):
        super().__init__(db, models.ConfigDocumentType)

    async def get_all_active(self, active_only: bool = True) -> List[models.ConfigDocumentType]:
        """Get all document types ordered by display_order."""
        query = select(self.model)
        
        if active_only:
            query = query.where(self.model.is_active == True)
        
        query = query.order_by(self.model.display_order, self.model.name)
        
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_by_code(self, code: str) -> Optional[models.ConfigDocumentType]:
        """Get document type by code."""
        result = await self.db.execute(
            select(self.model).where(self.model.code == code)
        )
        return result.scalar_one_or_none()

    async def get_by_name(self, name: str) -> Optional[models.ConfigDocumentType]:
        """Get document type by name."""
        result = await self.db.execute(
            select(self.model).where(self.model.name == name)
        )
        return result.scalar_one_or_none()

    async def check_code_exists(self, code: str, exclude_id: Optional[int] = None) -> bool:
        """Check if code already exists."""
        query = select(self.model).where(self.model.code == code)
        if exclude_id:
            query = query.where(self.model.id != exclude_id)
        result = await self.db.execute(query)
        return result.scalar_one_or_none() is not None

    async def check_name_exists(self, name: str, exclude_id: Optional[int] = None) -> bool:
        """Check if name already exists."""
        query = select(self.model).where(self.model.name == name)
        if exclude_id:
            query = query.where(self.model.id != exclude_id)
        result = await self.db.execute(query)
        return result.scalar_one_or_none() is not None

    async def get_all_offerings_with_admission_rules(self) -> List[models.ProgramOffering]:
        """Get all program offerings that have admission rules configured."""
        result = await self.db.execute(
            select(models.ProgramOffering)
            .where(models.ProgramOffering.admission_rules.isnot(None))
        )
        return list(result.scalars().all())

    async def get_filtered(
        self,
        skip: int = 0,
        limit: int = 100,
        **filters
    ) -> Tuple[int, List[models.ConfigDocumentType]]:
        """Get filtered document types."""
        active_only = filters.get("active_only", True)
        query = select(self.model)
        
        if active_only:
            query = query.where(self.model.is_active == True)
        
        count = await self.count(self.model.is_active == True if active_only else None)
        
        query = query.order_by(self.model.display_order).offset(skip).limit(limit)
        result = await self.db.execute(query)
        return count, list(result.scalars().all())


class DistributionRuleRepository(BaseRepository[models.OfferingDistributionConfig]):
    """Repository for OfferingDistributionConfig (Distribution Rules) model."""

    def __init__(self, db: AsyncSession):
        super().__init__(db, models.OfferingDistributionConfig)

    async def get_all_with_relations(self) -> List[models.OfferingDistributionConfig]:
        """Get all distribution rules with offering and unit relationships."""
        result = await self.db.execute(
            select(self.model)
            .options(
                selectinload(self.model.offering)
                .selectinload(models.ProgramOffering.program),
                selectinload(self.model.unit)
            )
            .order_by(
                self.model.priority.asc(),
                self.model.id
            )
        )
        return list(result.scalars().all())

    async def get_by_units_with_relations(self, unit_ids: List[int]) -> List[models.OfferingDistributionConfig]:
        """Get distribution rules filtered by unit IDs with relationships."""
        if not unit_ids:
            return []
            
        result = await self.db.execute(
            select(self.model)
            .where(self.model.unit_id.in_(unit_ids))
            .options(
                selectinload(self.model.offering)
                .selectinload(models.ProgramOffering.program),
                selectinload(self.model.unit)
            )
            .order_by(
                self.model.priority.asc(),
                self.model.id
            )
        )
        return list(result.scalars().all())

    async def get_by_id_with_relations(self, rule_id: int) -> Optional[models.OfferingDistributionConfig]:
        """Get a specific distribution rule by ID with relationships."""
        result = await self.db.execute(
            select(self.model)
            .where(self.model.id == rule_id)
            .options(
                selectinload(self.model.offering)
                .selectinload(models.ProgramOffering.program),
                selectinload(self.model.unit)
            )
        )
        return result.scalar_one_or_none()

    async def check_duplicate(self, offering_id: int, unit_id: int, exclude_id: Optional[int] = None) -> bool:
        """Check if a distribution rule already exists for the given offering and unit."""
        query = select(self.model).where(
            self.model.offering_id == offering_id,
            self.model.unit_id == unit_id
        )
        if exclude_id:
            query = query.where(self.model.id != exclude_id)
            
        result = await self.db.execute(query)
        return result.scalar_one_or_none() is not None

    async def create_and_fetch(self, rule_in: Any) -> models.OfferingDistributionConfig:
        """Create a new rule and return it with full relations."""
        # Use existing base create if available, or manual add
        db_obj = self.model(**rule_in.model_dump())
        self.db.add(db_obj)
        await self.db.flush()
        
        # Re-fetch with relations
        return await self.get_by_id_with_relations(db_obj.id)

    async def update_and_fetch(self, rule_id: int, rule_in: Any) -> Optional[models.OfferingDistributionConfig]:
        """Update a rule and return it with full relations."""
        db_obj = await self.get_by_id(rule_id)
        if not db_obj:
            return None
            
        update_data = rule_in.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(db_obj, field, value)
            
        await self.db.flush()
        
        # Re-fetch with relations
        return await self.get_by_id_with_relations(rule_id)
    async def delete_document_type(
        self,
        type_id: int,
        # ... logic
    ):
        pass # Placeholder as we're pasting inside existing file

class SystemCategoryRepository(BaseRepository[models.ConfigSystemCategory]):
    """Repository for ConfigSystemCategory model."""

    def __init__(self, db: AsyncSession):
        super().__init__(db, models.ConfigSystemCategory)

    async def get_by_type(self, type: str, active_only: bool = True) -> List[models.ConfigSystemCategory]:
        """Get categories by type ordered by display_order."""
        query = select(self.model).where(self.model.type == type)
        
        if active_only:
            query = query.where(self.model.is_active == True)
        
        query = query.order_by(self.model.display_order, self.model.name)
        
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_by_type_and_code(self, type: str, code: str) -> Optional[models.ConfigSystemCategory]:
        """Get category by type and code."""
        result = await self.db.execute(
            select(self.model).where(
                self.model.type == type,
                self.model.code == code
            )
        )
        return result.scalar_one_or_none()
    
    async def create_or_update(self, type: str, code: str, name: str) -> Tuple[models.ConfigSystemCategory, bool]:
        """Create or update category."""
        existing = await self.get_by_type_and_code(type, code)
        if existing:
            existing.name = name
            await self.db.flush()
            await self.db.refresh(existing)
            return existing, False
        else:
            new_cat = models.ConfigSystemCategory(
                type=type,
                code=code,
                name=name,
                is_active=True
            )
            self.db.add(new_cat)
            await self.db.flush()
            await self.db.refresh(new_cat)
            return new_cat, True

    async def get_filtered(
        self,
        skip: int = 0,
        limit: int = 100,
        **filters
    ) -> Tuple[int, List[models.ConfigSystemCategory]]:
        """
        Get filtered listing of categories.
        """
        query = select(self.model)
        
        if "type" in filters:
            query = query.where(self.model.type == filters["type"])
            
        if "is_active" in filters:
             query = query.where(self.model.is_active == filters["is_active"])

        # Count total
        count_query = select(func.count()).select_from(query.subquery())
        total = (await self.db.execute(count_query)).scalar() or 0
        
        # Order by display_order then name
        query = query.order_by(self.model.display_order, self.model.name)
        
        # Apply pagination
        query = query.offset(skip).limit(limit)
        
        result = await self.db.execute(query)
        return total, list(result.scalars().all())
