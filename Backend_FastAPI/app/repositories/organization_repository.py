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

    # =========================================================================
    # DETAIL VIEW METHODS (Sprint 3)
    # =========================================================================

    async def get_by_id_full(
        self,
        unit_id: int
    ) -> Optional[models.OrganizationUnit]:
        """
        Get organization unit by ID with ALL relationships loaded.
        
        ✅ SPRINT 3: Added for organization_service migration.
        
        Includes:
        - Parent unit
        - Child units
        - Major programs with offerings and academic info
        
        Args:
            unit_id: Unit ID to fetch
            
        Returns:
            OrganizationUnit with all relations or None if not found
        """
        query = (
            select(self.model)
            .options(
                selectinload(models.OrganizationUnit.parent),
                selectinload(models.OrganizationUnit.children),
                selectinload(models.OrganizationUnit.major_programs).selectinload(
                    models.MajorProgram.offerings
                ).selectinload(
                    models.ProgramOffering.academic_info_history
                ),
            )
            .where(self.model.id == unit_id)
        )
        
        result = await self.db.execute(query)
        return result.scalars().unique().first()

    async def get_major_program_by_id_full(
        self,
        program_id: int
    ) -> Optional[models.MajorProgram]:
        """
        Get major program by ID with full relationship loading.
        
        ✅ SPRINT 3: Added for organization_service migration.
        
        Includes:
        - Offerings with academic info history
        - Parent unit
        
        Args:
            program_id: MajorProgram ID to fetch
            
        Returns:
            MajorProgram with all relations or None if not found
        """
        query = (
            select(models.MajorProgram)
            .options(
                selectinload(models.MajorProgram.offerings).selectinload(
                    models.ProgramOffering.academic_info_history
                ),
                selectinload(models.MajorProgram.unit)
            )
            .where(models.MajorProgram.id == program_id)
        )
        
        result = await self.db.execute(query)
        return result.scalars().unique().first()

    async def get_offering_by_id_full(
        self,
        offering_id: int
    ) -> Optional[models.ProgramOffering]:
        """
        Get program offering by ID with full relationship loading.
        
        ✅ SPRINT 3: Added for organization_service migration.
        
        Includes:
        - Academic info history
        - Parent program
        
        Args:
            offering_id: ProgramOffering ID to fetch
            
        Returns:
            ProgramOffering with all relations or None if not found
        """
        query = (
            select(models.ProgramOffering)
            .options(
                selectinload(models.ProgramOffering.academic_info_history),
                selectinload(models.ProgramOffering.program)
            )
            .where(models.ProgramOffering.id == offering_id)
        )
        
        result = await self.db.execute(query)
        return result.scalars().unique().first()

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

        # Eager load children recursively with major_programs (up to reasonable depth)
        # ✅ FIX: Load major_programs at each level to prevent MissingGreenlet error
        query = query.options(
            selectinload(models.OrganizationUnit.major_programs).selectinload(
                models.MajorProgram.offerings
            ),
            selectinload(models.OrganizationUnit.children).options(
                selectinload(models.OrganizationUnit.major_programs).selectinload(
                    models.MajorProgram.offerings
                ),
                selectinload(models.OrganizationUnit.children).options(
                    selectinload(models.OrganizationUnit.major_programs).selectinload(
                        models.MajorProgram.offerings
                    ),
                    selectinload(models.OrganizationUnit.children).options(
                        selectinload(models.OrganizationUnit.major_programs).selectinload(
                            models.MajorProgram.offerings
                        )
                    )
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

    # =========================================================================
    # VALIDATION HELPERS (Sprint 3 - Continued)
    # =========================================================================

    async def check_duplicate_name(
        self,
        name: str,
        parent_id: Optional[int],
        exclude_id: Optional[int] = None
    ) -> Optional[models.OrganizationUnit]:
        """
        Check for duplicate unit name within the same parent.
        Only checks active units.
        
        Args:
            name: Unit name to check
            parent_id: Parent unit ID (None for root)
            exclude_id: Unit ID to exclude (for updates)
            
        Returns:
            Existing unit if duplicate found, None otherwise
        """
        query = select(self.model).where(
            self.model.name == name.strip(),
            self.model.parent_id == parent_id,
            self.model.is_active == True
        )
        
        if exclude_id is not None:
            query = query.where(self.model.id != exclude_id)
        
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def check_duplicate_program_code(
        self,
        code: str,
        exclude_id: Optional[int] = None
    ) -> Optional[models.MajorProgram]:
        """
        Check for duplicate MajorProgram code.
        
        Args:
            code: Program code to check
            exclude_id: Program ID to exclude (for updates)
            
        Returns:
            Existing program if duplicate found, None otherwise
        """
        query = select(models.MajorProgram).where(
            models.MajorProgram.code == code
        )
        
        if exclude_id is not None:
            query = query.where(models.MajorProgram.id != exclude_id)
        
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def get_user_counts_by_unit(self) -> dict:
        """
        Get active user counts grouped by unit_id.
        
        Returns:
            Dict mapping unit_id -> user_count
        """
        query = (
            select(
                models.User.unit_id,
                func.count(models.User.id).label("user_count")
            )
            .where(
                models.User.unit_id.isnot(None),
                models.User.status == "active"
            )
            .group_by(models.User.unit_id)
        )
        
        result = await self.db.execute(query)
        return {row.unit_id: row.user_count for row in result.all()}

    async def check_duplicate_offering(
        self,
        program_id: int,
        offering_type: str,
        exclude_id: Optional[int] = None
    ) -> Optional[models.ProgramOffering]:
        """
        Check for duplicate ProgramOffering (same program + offering_type).
        
        Args:
            program_id: Parent program ID
            offering_type: Offering type to check
            exclude_id: Offering ID to exclude (for updates)
            
        Returns:
            Existing offering if duplicate found, None otherwise
        """
        query = select(models.ProgramOffering).where(
            models.ProgramOffering.program_id == program_id,
            models.ProgramOffering.offering_type == offering_type
        )
        
        if exclude_id is not None:
            query = query.where(models.ProgramOffering.id != exclude_id)
        
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    # =========================================================================
    # ACADEMIC INFO METHODS (Sprint 3 - Final)
    # =========================================================================

    async def get_academic_info_by_id(
        self,
        academic_info_id: int
    ) -> Optional[models.OfferingAcademicInfo]:
        """Get academic info by ID."""
        query = select(models.OfferingAcademicInfo).where(
            models.OfferingAcademicInfo.id == academic_info_id
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def get_academic_info_by_offering_and_year(
        self,
        offering_id: int,
        academic_year: int
    ) -> Optional[models.OfferingAcademicInfo]:
        """Get academic info for a specific offering and year."""
        query = select(models.OfferingAcademicInfo).where(
            models.OfferingAcademicInfo.offering_id == offering_id,
            models.OfferingAcademicInfo.academic_year == academic_year
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def get_current_academic_info(
        self,
        offering_id: int,
        current_year: int
    ) -> Optional[models.OfferingAcademicInfo]:
        """Get current year's published academic info for an offering."""
        query = select(models.OfferingAcademicInfo).where(
            models.OfferingAcademicInfo.offering_id == offering_id,
            models.OfferingAcademicInfo.academic_year == current_year,
            models.OfferingAcademicInfo.is_published == True
        ).limit(1)
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def get_academic_info_history(
        self,
        offering_id: int,
        published_only: bool = False
    ) -> List[models.OfferingAcademicInfo]:
        """Get all academic info history for an offering, ordered by year (newest first)."""
        query = select(models.OfferingAcademicInfo).where(
            models.OfferingAcademicInfo.offering_id == offering_id
        )
        
        if published_only:
            query = query.where(models.OfferingAcademicInfo.is_published == True)
        
        query = query.order_by(models.OfferingAcademicInfo.academic_year.desc())
        
        result = await self.db.execute(query)
        return list(result.scalars().all())

    # =========================================================================
    # TREE & VALIDATION METHODS (Sprint 3 - Final Batch)
    # =========================================================================

    async def get_tree_with_programs(
        self,
        depth: int = 9
    ) -> List[models.OrganizationUnit]:
        """
        Get organization tree with programs and offerings loaded.
        
        Args:
            depth: Maximum depth for recursive loading
            
        Returns:
            List of root organization units with all descendants
        """
        from ..services.organization_service import create_recursive_unit_loader
        
        recursive_loader = create_recursive_unit_loader(depth=depth)
        
        query = (
            select(self.model)
            .where(
                self.model.is_active == True,
                self.model.parent_id == None
            )
            .options(
                selectinload(models.OrganizationUnit.major_programs).selectinload(
                    models.MajorProgram.offerings
                ).selectinload(
                    models.ProgramOffering.academic_info_history
                ),
                recursive_loader,
                selectinload(models.OrganizationUnit.parent)
            )
            .order_by(self.model.name)
        )
        
        result = await self.db.execute(query)
        return list(result.scalars().unique().all())

    async def check_cycle_in_hierarchy(
        self,
        unit_id: int,
        new_parent_id: int
    ) -> bool:
        """
        Check if setting new_parent_id would create a cycle.
        Uses recursive CTE to traverse up from new_parent_id.
        
        Returns:
            True if cycle detected, False otherwise
        """
        from sqlalchemy import text
        
        ancestor_cte_sql = text("""
            WITH RECURSIVE ancestor_chain AS (
                SELECT id, parent_id, 1 as depth
                FROM organization_unit
                WHERE id = :new_parent_id
                UNION ALL
                SELECT u.id, u.parent_id, ac.depth + 1
                FROM organization_unit u
                JOIN ancestor_chain ac ON u.id = ac.parent_id
                WHERE ac.depth < 100
            )
            SELECT id FROM ancestor_chain WHERE id = :unit_id LIMIT 1;
        """)
        
        result = await self.db.execute(
            ancestor_cte_sql,
            {"new_parent_id": new_parent_id, "unit_id": unit_id}
        )
        return result.scalar_one_or_none() is not None

    async def count_active_children(self, unit_id: int) -> int:
        """Count active child units."""
        query = select(func.count(self.model.id)).where(
            self.model.parent_id == unit_id,
            self.model.is_active == True
        )
        result = await self.db.execute(query)
        return result.scalar_one() or 0

    async def count_active_programs(self, unit_id: int) -> int:
        """Count active major programs for a unit."""
        query = select(func.count(models.MajorProgram.id)).where(
            models.MajorProgram.unit_id == unit_id,
            models.MajorProgram.is_active == True
        )
        result = await self.db.execute(query)
        return result.scalar_one() or 0

    async def count_assigned_users(self, unit_id: int) -> int:
        """Count users assigned to a unit."""
        query = select(func.count(models.User.id)).where(
            models.User.unit_id == unit_id,
            models.User.status == "active"
        )
        result = await self.db.execute(query)
        return result.scalar_one() or 0

    # =========================================================================
    # TREE AGGREGATION & SEARCH (Sprint 3 - Final)
    # =========================================================================

    async def get_tree_for_aggregation(
        self,
        include_inactive: bool = False
    ) -> List[models.OrganizationUnit]:
        """
        Get organization tree for aggregation (no academic info history).

        Used by get_tree_with_aggregation for efficient tree building.
        Academic info is loaded separately for the specific year.

        Returns flat list of ALL units (not just roots) with major_programs loaded.
        """
        query = (
            select(self.model)
            .options(
                # ✅ FIX: Load major_programs for all units to prevent MissingGreenlet error
                selectinload(models.OrganizationUnit.major_programs).selectinload(
                    models.MajorProgram.offerings
                ),
                # Note: children relationship is loaded but service doesn't use it (builds tree manually)
                # But if accessed, children should also have major_programs loaded
                selectinload(models.OrganizationUnit.children).selectinload(
                    models.OrganizationUnit.major_programs
                ).selectinload(
                    models.MajorProgram.offerings
                )
            )
            .order_by(self.model.name)
        )

        if not include_inactive:
            query = query.where(self.model.is_active == True)

        result = await self.db.execute(query)
        return list(result.scalars().unique().all())

    async def get_academic_info_for_year(
        self,
        academic_year: int
    ) -> List[models.OfferingAcademicInfo]:
        """Get all published academic info for a specific year."""
        query = (
            select(models.OfferingAcademicInfo)
            .where(
                models.OfferingAcademicInfo.academic_year == academic_year,
                models.OfferingAcademicInfo.is_published == True
            )
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_descendant_unit_ids(self, unit_id: int) -> List[int]:
        """
        Get all descendant unit IDs using recursive CTE.
        Includes the starting unit_id.
        """
        from sqlalchemy import text
        
        sql = text("""
            WITH RECURSIVE unit_hierarchy AS (
               SELECT id FROM organization_unit WHERE id = :unit_id
               UNION ALL
               SELECT u.id FROM organization_unit u
               JOIN unit_hierarchy uh ON u.parent_id = uh.id
            )
            SELECT id FROM unit_hierarchy;
        """)
        
        result = await self.db.execute(sql, {"unit_id": unit_id})
        return [row[0] for row in result]

    async def search_programs_in_hierarchy(
        self,
        unit_ids: List[int],
        search_term: Optional[str] = None,
        limit: int = 20
    ) -> List[models.MajorProgram]:
        """
        Search for active programs in the given unit IDs.
        
        Args:
            unit_ids: List of unit IDs to search in
            search_term: Optional search term for name filtering
            limit: Maximum results to return
            
        Returns:
            List of matching MajorProgram objects
        """
        if not unit_ids:
            return []
        
        query = select(models.MajorProgram).options(
            selectinload(models.MajorProgram.offerings).selectinload(models.ProgramOffering.academic_info_history)
        ).filter(
            models.MajorProgram.unit_id.in_(unit_ids),
            models.MajorProgram.is_active == True
        )
        
        if search_term:
            safe_pattern = f"%{search_term.strip()}%"
            query = query.filter(models.MajorProgram.name.ilike(safe_pattern))
        
        query = query.order_by(models.MajorProgram.name).limit(limit)
        
        result = await self.db.execute(query)
        return list(result.scalars().all())

    # =========================================================================
    # MAJOR PROGRAMS (Dropdown / Flat List)
    # =========================================================================

    async def get_all_major_programs(
        self,
        search_term: Optional[str] = None,
        is_active: bool = True
    ) -> List[models.MajorProgram]:
        """
        Get all major programs (flat list).
        
        Args:
            search_term: Optional search term for name filtering
            is_active: Filter by active status
            
        Returns:
            List of MajorProgram objects
        """
        # ✅ FIX: Eager load offerings to prevent MissingGreenlet error during response validation
        query = select(models.MajorProgram).options(
            selectinload(models.MajorProgram.offerings).selectinload(models.ProgramOffering.academic_info_history)
        )
        
        if is_active:
             query = query.where(models.MajorProgram.is_active == True)
             
        if search_term:
            safe_pattern = f"%{search_term.strip()}%"
            query = query.filter(models.MajorProgram.name.ilike(safe_pattern))
            
        query = query.order_by(models.MajorProgram.name)
        
        result = await self.db.execute(query)
        return list(result.scalars().all())

    # =========================================================================
    # PROGRAM OFFERINGS (Dropdown / Flat List)
    # =========================================================================

    async def get_all_offerings(
        self,
        is_active: Optional[bool] = None,
        skip: int = 0,
        limit: int = 1000,
    ) -> List[models.ProgramOffering]:
        """
        Get all program offerings as flat list for dropdowns.

        Includes eager loading of parent program for display name.

        Args:
            is_active: Filter by active status (None = all)
            skip: Offset for pagination
            limit: Maximum results

        Returns:
            List of ProgramOffering with program loaded
        """
        query = (
            select(models.ProgramOffering)
            .options(
                selectinload(models.ProgramOffering.program),  # Eager load for display
                selectinload(models.ProgramOffering.academic_info_history)
            )
        )

        if is_active is not None:
            query = query.where(models.ProgramOffering.is_active == is_active)

        query = (
            query
            .order_by(models.ProgramOffering.offering_type)
            .offset(skip)
            .limit(limit)
        )

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_all_academic_infos(
        self,
        is_active: Optional[bool] = None,
        skip: int = 0,
        limit: int = 1000,
    ) -> List[models.OfferingAcademicInfo]:
        """
        Get all academic infos as flat list for admin panels.

        Args:
            is_active: Filter by deleted status (None = all, True = not deleted)
            skip: Offset for pagination
            limit: Maximum results

        Returns:
            List of OfferingAcademicInfo
        """
        query = select(models.OfferingAcademicInfo)

        if is_active is True:
            query = query.where(models.OfferingAcademicInfo.is_deleted == False)

        query = (
            query
            .order_by(
                models.OfferingAcademicInfo.academic_year.desc(),
                models.OfferingAcademicInfo.offering_id
            )
            .offset(skip)
            .limit(limit)
        )

        result = await self.db.execute(query)
        return list(result.scalars().all())

