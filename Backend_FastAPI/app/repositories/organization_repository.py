# app/repositories/organization_repository.py
"""
✅ PHASE 2 - WEEK 1: Organization Repository

Organization unit-specific data access layer.
Handles hierarchical tree queries, filtering, and aggregation.

Benefits:
- Centralized organization query logic
- Hierarchical tree traversal methods
- Testable with repository mocks
- Separates SQL from business logic
"""

from typing import List, Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app import models
from app.repositories.base import BaseRepository


class OrganizationRepository(BaseRepository[models.OrganizationUnit]):
    """Repository for OrganizationUnit model operations."""

    def __init__(self, db: AsyncSession):
        """
        Initialize Organization repository.

        Args:
            db: SQLAlchemy async session
        """
        super().__init__(db, models.OrganizationUnit)

    async def get_filtered(
        self,
        skip: int = 0,
        limit: int = 100,
        type: Optional[str] = None,
        parent_id: Optional[int] = None,
        is_active: bool = True,
    ) -> Tuple[int, List[models.OrganizationUnit]]:
        """
        Get filtered list of organization units.

        Args:
            skip: Number of records to skip
            limit: Maximum number of records to return
            type: Filter by unit type
            parent_id: Filter by parent unit
            is_active: Filter by active status (default: True)

        Returns:
            Tuple of (total_count, units_list)
        """
        # Build base queries
        base_query = select(models.OrganizationUnit)
        count_query = select(func.count(models.OrganizationUnit.id))

        # Apply filters
        filters = []

        if is_active is not None:
            filters.append(models.OrganizationUnit.is_active == is_active)

        if type:
            filters.append(models.OrganizationUnit.type == type)

        if parent_id is not None:
            filters.append(models.OrganizationUnit.parent_id == parent_id)

        # Apply filters to both queries
        if filters:
            base_query = base_query.where(*filters)
            count_query = count_query.where(*filters)

        # Execute count query
        total_count_result = await self.db.execute(count_query)
        total_count = total_count_result.scalar_one_or_none() or 0

        if total_count == 0:
            return 0, []

        # Apply ordering and pagination
        units_query = (
            base_query
            .order_by(models.OrganizationUnit.name.asc())
            .offset(skip)
            .limit(limit)
        )

        # Execute query
        result = await self.db.execute(units_query)
        units = list(result.scalars().all())

        return total_count, units

    async def get_tree(
        self,
        include_inactive: bool = False
    ) -> List[models.OrganizationUnit]:
        """
        Get all organization units as hierarchical tree.

        Returns root-level units with children eager-loaded.

        Args:
            include_inactive: Include soft-deleted units (default: False)

        Returns:
            List of root-level organization units
        """
        query = select(models.OrganizationUnit).where(
            models.OrganizationUnit.parent_id.is_(None)
        )

        if not include_inactive:
            query = query.where(models.OrganizationUnit.is_active == True)

        # Eager load children recursively (up to reasonable depth)
        query = query.options(
            selectinload(models.OrganizationUnit.children).options(
                selectinload(models.OrganizationUnit.children).options(
                    selectinload(models.OrganizationUnit.children)
                )
            )
        )

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_by_type(
        self,
        type: str,
        is_active: bool = True
    ) -> List[models.OrganizationUnit]:
        """
        Get all units of a specific type.

        Args:
            type: Unit type (e.g., "faculty", "department")
            is_active: Filter by active status

        Returns:
            List of organization units
        """
        query = select(models.OrganizationUnit).where(
            models.OrganizationUnit.type == type
        )

        if is_active:
            query = query.where(models.OrganizationUnit.is_active == True)

        query = query.order_by(models.OrganizationUnit.name.asc())

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_children(
        self,
        parent_id: int,
        is_active: bool = True
    ) -> List[models.OrganizationUnit]:
        """
        Get direct children of a unit.

        Args:
            parent_id: Parent unit ID
            is_active: Filter by active status

        Returns:
            List of child units
        """
        query = select(models.OrganizationUnit).where(
            models.OrganizationUnit.parent_id == parent_id
        )

        if is_active:
            query = query.where(models.OrganizationUnit.is_active == True)

        query = query.order_by(models.OrganizationUnit.name.asc())

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_ancestors(
        self,
        unit_id: int
    ) -> List[models.OrganizationUnit]:
        """
        Get all ancestors of a unit (parent, grandparent, etc.).

        Args:
            unit_id: Starting unit ID

        Returns:
            List of ancestor units from nearest to farthest
        """
        ancestors = []
        current_unit = await self.get_by_id(unit_id)

        while current_unit and current_unit.parent_id:
            parent = await self.get_by_id(current_unit.parent_id)
            if parent:
                ancestors.append(parent)
                current_unit = parent
            else:
                break

        return ancestors

    async def get_descendants(
        self,
        unit_id: int,
        include_inactive: bool = False
    ) -> List[models.OrganizationUnit]:
        """
        Get all descendants of a unit (recursive).

        Args:
            unit_id: Starting unit ID
            include_inactive: Include soft-deleted units

        Returns:
            List of all descendant units
        """
        descendants = []

        async def collect_children(parent_id: int):
            children = await self.get_children(parent_id, not include_inactive)
            for child in children:
                descendants.append(child)
                await collect_children(child.id)

        await collect_children(unit_id)
        return descendants

    async def get_root_units(
        self,
        is_active: bool = True
    ) -> List[models.OrganizationUnit]:
        """
        Get all root-level units (units with no parent).

        Args:
            is_active: Filter by active status

        Returns:
            List of root units
        """
        query = select(models.OrganizationUnit).where(
            models.OrganizationUnit.parent_id.is_(None)
        )

        if is_active:
            query = query.where(models.OrganizationUnit.is_active == True)

        query = query.order_by(models.OrganizationUnit.name.asc())

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def count_by_type(self) -> dict:
        """
        Count units grouped by type.

        Returns:
            Dict mapping type to count
        """
        result = await self.db.execute(
            select(
                models.OrganizationUnit.type,
                func.count(models.OrganizationUnit.id).label("count")
            )
            .where(models.OrganizationUnit.is_active == True)
            .group_by(models.OrganizationUnit.type)
        )
        return {row.type: row.count for row in result}

    async def get_with_user_count(
        self,
        is_active: bool = True
    ) -> List[Tuple[models.OrganizationUnit, int]]:
        """
        Get units with user count aggregation.

        Args:
            is_active: Filter by active status

        Returns:
            List of (unit, user_count) tuples
        """
        query = (
            select(
                models.OrganizationUnit,
                func.count(models.User.id).label("user_count")
            )
            .outerjoin(models.User)
            .group_by(models.OrganizationUnit.id)
        )

        if is_active:
            query = query.where(models.OrganizationUnit.is_active == True)

        query = query.order_by(models.OrganizationUnit.name.asc())

        result = await self.db.execute(query)
        return [(row[0], row[1]) for row in result]

    async def get_with_lead_count(
        self,
        is_active: bool = True
    ) -> List[Tuple[models.OrganizationUnit, int]]:
        """
        Get units with lead count aggregation.

        Args:
            is_active: Filter by active status

        Returns:
            List of (unit, lead_count) tuples
        """
        query = (
            select(
                models.OrganizationUnit,
                func.count(models.Lead.id).label("lead_count")
            )
            .outerjoin(models.Lead)
            .where(models.Lead.deleted_at.is_(None))  # Exclude soft-deleted leads
            .group_by(models.OrganizationUnit.id)
        )

        if is_active:
            query = query.where(models.OrganizationUnit.is_active == True)

        query = query.order_by(models.OrganizationUnit.name.asc())

        result = await self.db.execute(query)
        return [(row[0], row[1]) for row in result]

    async def soft_delete_recursive(
        self,
        unit_id: int
    ) -> None:
        """
        Soft delete a unit and all its descendants.

        Args:
            unit_id: Unit ID to soft delete
        """
        unit = await self.get_by_id(unit_id)
        if not unit:
            return

        # Soft delete this unit
        unit.is_active = False
        await self.db.flush()

        # Soft delete all descendants
        descendants = await self.get_descendants(unit_id, include_inactive=True)
        for descendant in descendants:
            descendant.is_active = False

        await self.db.flush()
