# app/repositories/user_repository.py
"""
✅ PHASE 2 - WEEK 1: User Repository

User-specific data access layer.
Handles all User CRUD operations, filtering, and statistics.

Benefits:
- Centralized user query logic
- Full-text search optimization
- Testable with repository mocks
- Separates SQL from business logic
"""

from typing import Dict, List, Optional, Tuple

from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app import models
from app.core.constants import UserRole
from app.repositories.base import BaseRepository


class UserRepository(BaseRepository[models.User]):
    """Repository for User model operations."""

    def __init__(self, db: AsyncSession):
        """
        Initialize User repository.

        Args:
            db: SQLAlchemy async session
        """
        super().__init__(db, models.User)

    async def get_filtered(
        self,
        skip: int = 0,
        limit: int = 50,
        search: Optional[str] = None,
        role: Optional[str] = None,
        status: Optional[str] = None,
        unit_id: Optional[int] = None,
        sort_by: str = "created_at",
        order: str = "desc",
    ) -> Tuple[int, List[models.User]]:
        """
        Get filtered list of users with pagination.

        Uses full-text search (search_vector) for performance.

        Args:
            skip: Number of records to skip
            limit: Maximum number of records to return
            search: Search term for username/email/full_name
            role: Filter by role
            status: Filter by status
            unit_id: Filter by organization unit
            sort_by: Column to sort by (default: created_at)
            order: Sort order (asc/desc)

        Returns:
            Tuple of (total_count, user_list)
        """
        # Build base queries
        base_query = select(models.User)
        count_query = select(func.count(models.User.id))

        # Apply filters
        filters = []

        if role:
            filters.append(models.User.role == role)

        if status:
            filters.append(models.User.status == status)

        if unit_id is not None:
            filters.append(models.User.unit_id == unit_id)

        # Full-text search using search_vector (optimized)
        if search:
            search_term = search.strip()
            # Use PostgreSQL full-text search if search_vector exists
            # Otherwise fallback to ILIKE (slower but works)
            filters.append(
                or_(
                    models.User.search_vector.op("@@")(
                        func.plainto_tsquery("english", search_term)
                    ),
                    models.User.username.ilike(f"%{search_term}%"),
                    models.User.email.ilike(f"%{search_term}%"),
                    models.User.full_name.ilike(f"%{search_term}%"),
                )
            )

        # Apply filters to both queries
        if filters:
            base_query = base_query.where(*filters)
            count_query = count_query.where(*filters)

        # Execute count query
        total_count_result = await self.db.execute(count_query)
        total_count = total_count_result.scalar_one_or_none() or 0

        if total_count == 0:
            return 0, []

        # Apply sorting
        sort_column = getattr(models.User, sort_by, models.User.id)

        if order.lower() == "desc":
            users_query = base_query.order_by(sort_column.desc())
        else:
            users_query = base_query.order_by(sort_column.asc())

        # Apply eager loading and pagination
        users_query = (
            users_query.options(
                selectinload(models.User.unit),
                selectinload(models.User.current_assignment),
            )
            .offset(skip)
            .limit(limit)
        )

        # Execute query
        result = await self.db.execute(users_query)
        users = list(result.scalars().all())

        return total_count, users

    async def search_with_hierarchy(
        self,
        skip: int = 0,
        limit: int = 100,
        role: Optional[str] = None,
        status: Optional[str] = None,
        unit_id: Optional[int] = None,
        include_children: bool = False,
        search: Optional[str] = None,
        sort_by: str = "id",
        order: str = "asc",
    ) -> Tuple[int, List[models.User]]:
        """
        Get users with hierarchical unit filtering and full-text search.
        
        ✅ SPRINT 2: Added for user_service migration.
        
        This method supports:
        - Hierarchical unit filter via recursive CTE
        - Full-text search using search_vector (PostgreSQL ts_vector)
        - Multi-value filters (comma-separated)
        - Eager loading for N+1 prevention
        
        Args:
            skip: Number of records to skip
            limit: Maximum number of records to return
            role: Filter by role (comma-separated for multi-select)
            status: Filter by status (comma-separated for multi-select)
            unit_id: Filter by organization unit
            include_children: If True, include users from child units (uses CTE)
            search: Full-text search term
            sort_by: Column to sort by
            order: Sort order (asc/desc)
            
        Returns:
            Tuple of (total_count, user_list)
        """
        # Build base query with eager loading
        query = select(self.model).options(
            selectinload(models.User.unit),
            selectinload(models.User.sessions),
        )
        
        filters = []
        
        # =========================================================================
        # HIERARCHICAL UNIT FILTER (CTE-based)
        # =========================================================================
        if unit_id is not None:
            if include_children:
                # Recursive CTE to get all descendant unit IDs
                cte_query = text("""
                    WITH RECURSIVE unit_hierarchy AS (
                        SELECT id FROM organization_unit WHERE id = :unit_id
                        UNION ALL
                        SELECT u.id FROM organization_unit u
                        JOIN unit_hierarchy uh ON u.parent_id = uh.id
                    )
                    SELECT id FROM unit_hierarchy
                """)
                
                # Execute CTE to get list of unit IDs
                hierarchy_result = await self.db.execute(cte_query, {"unit_id": unit_id})
                all_unit_ids = [row[0] for row in hierarchy_result.fetchall()]
                
                if all_unit_ids:
                    filters.append(models.User.unit_id.in_(all_unit_ids))
            else:
                # Simple exact match
                filters.append(models.User.unit_id == unit_id)
        
        # =========================================================================
        # ROLE & STATUS FILTERS (multi-value support)
        # =========================================================================
        if role:
            values = [v.strip() for v in role.split(",") if v.strip()]
            if values:
                filters.append(models.User.role.in_(values))
        
        if status:
            values = [v.strip() for v in status.split(",") if v.strip()]
            if values:
                filters.append(models.User.status.in_(values))
        
        # =========================================================================
        # FULL-TEXT SEARCH (using search_vector with GIN index)
        # =========================================================================
        if search:
            search_term = search.strip().replace(' ', ' & ')
            filters.append(
                models.User.search_vector.op('@@')(
                    func.to_tsquery('simple', search_term)
                )
            )
        
        # Apply filters
        if filters:
            query = query.where(*filters)
        
        # Count query
        count_query = select(func.count()).select_from(query.alias())
        total_count_result = await self.db.execute(count_query)
        total_count = total_count_result.scalar_one()
        
        if total_count == 0:
            return 0, []
        
        # Apply sorting
        sort_column = getattr(models.User, sort_by, models.User.id)
        if order.lower() == "desc":
            query = query.order_by(sort_column.desc())
        else:
            query = query.order_by(sort_column.asc())
        
        # Apply pagination
        query = query.offset(skip).limit(limit)
        
        # Execute
        result = await self.db.execute(query)
        users = list(result.scalars().all())
        
        return total_count, users

    async def get_by_username(self, username: str) -> Optional[models.User]:
        """
        Get user by username.

        Args:
            username: Username to search

        Returns:
            User instance or None
        """
        result = await self.db.execute(
            select(models.User).where(models.User.username == username)
        )
        return result.scalars().first()

    async def get_by_email(self, email: str) -> Optional[models.User]:
        """
        Get user by email address.

        Args:
            email: Email to search

        Returns:
            User instance or None
        """
        result = await self.db.execute(
            select(models.User).where(models.User.email == email)
        )
        return result.scalars().first()

    async def get_by_active_jti(self, jti: str) -> Optional[models.User]:
        """
        Get user by active JWT ID (for token validation).

        Args:
            jti: JWT ID to search

        Returns:
            User instance or None
        """
        result = await self.db.execute(
            select(models.User).where(models.User.active_jti == jti)
        )
        return result.scalars().first()

    async def get_statistics(self) -> Dict[str, int]:
        """
        Get user statistics.

        Returns:
            Dictionary with user counts by status
        """
        # Total users
        total_result = await self.db.execute(
            select(func.count(models.User.id))
        )
        total_users = total_result.scalar_one_or_none() or 0

        # Active users
        active_result = await self.db.execute(
            select(func.count(models.User.id))
            .where(models.User.status == "active")
        )
        active_users = active_result.scalar_one_or_none() or 0

        # Pending users
        pending_result = await self.db.execute(
            select(func.count(models.User.id))
            .where(models.User.status == "pending")
        )
        pending_users = pending_result.scalar_one_or_none() or 0

        # Banned users
        banned_result = await self.db.execute(
            select(func.count(models.User.id))
            .where(models.User.status == "banned")
        )
        banned_users = banned_result.scalar_one_or_none() or 0

        return {
            "total_users": total_users,
            "active_users": active_users,
            "pending_users": pending_users,
            "banned_users": banned_users,
        }

    async def get_recent_statistics(self, days: int = 7) -> Dict[str, int]:
        """
        Get statistics for recent activity.

        Args:
            days: Number of days to look back

        Returns:
            Dictionary with recent user counts
        """
        from datetime import datetime, timedelta, timezone

        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)

        # New users in last N days
        new_users_result = await self.db.execute(
            select(func.count(models.User.id))
            .where(models.User.id.isnot(None))
            .where(
                text("created_at >= :cutoff").bindparams(cutoff=cutoff_date)
            )
        )
        new_users = new_users_result.scalar_one_or_none() or 0

        return {
            f"new_users_last_{days}_days": new_users,
        }

    async def get_officers_by_availability(
        self,
        availability_status: str = "available",
        limit: int = 100
    ) -> List[models.User]:
        """
        Get officers (role=officer) by availability status.

        Args:
            availability_status: Filter by availability (available/busy/offline)
            limit: Maximum results

        Returns:
            List of officer users
        """
        result = await self.db.execute(
            select(models.User)
            .where(models.User.role == UserRole.OFFICER)
            .where(models.User.availability_status == availability_status)
            .where(models.User.status == "active")
            .order_by(models.User.last_assigned_at.asc().nullsfirst())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_officers_by_unit(
        self,
        unit_id: int,
        active_only: bool = True
    ) -> List[models.User]:
        """
        Get officers assigned to a specific unit.

        Args:
            unit_id: Organization unit ID
            active_only: Only return active users

        Returns:
            List of officer users
        """
        query = (
            select(models.User)
            .where(models.User.role == UserRole.OFFICER)
            .where(models.User.unit_id == unit_id)
        )

        if active_only:
            query = query.where(models.User.status == "active")

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def count_by_role(self) -> Dict[str, int]:
        """
        Count users grouped by role.

        Returns:
            Dict mapping role to count
        """
        result = await self.db.execute(
            select(
                models.User.role,
                func.count(models.User.id).label("count")
            )
            .group_by(models.User.role)
        )
        return {row.role: row.count for row in result}

    async def count_by_unit(self) -> Dict[int, int]:
        """
        Count users grouped by unit.

        Returns:
            Dict mapping unit_id to count
        """
        result = await self.db.execute(
            select(
                models.User.unit_id,
                func.count(models.User.id).label("count")
            )
            .where(models.User.unit_id.isnot(None))
            .group_by(models.User.unit_id)
        )
        return {row.unit_id: row.count for row in result}

    async def update_availability(
        self,
        user_id: int,
        availability_status: str
    ) -> Optional[models.User]:
        """
        Update user availability status.

        Args:
            user_id: User ID
            availability_status: New availability status

        Returns:
            Updated user or None if not found
        """
        user = await self.get_by_id(user_id)
        if not user:
            return None

        user.availability_status = availability_status
        await self.db.flush()
        await self.db.refresh(user)
        return user

    async def increment_lead_score(
        self,
        user_id: int,
        score: int
    ) -> Optional[models.User]:
        """
        Increment user's total lead score.

        Args:
            user_id: User ID
            score: Score to add

        Returns:
            Updated user or None if not found
        """
        user = await self.get_by_id(user_id)
        if not user:
            return None

        user.total_lead_score += score
        await self.db.flush()
        await self.db.refresh(user)
        return user

    # =========================================================================
    # BULK METHODS (Sprint 4 Hotfix)
    # =========================================================================

    async def get_all(self) -> List[models.User]:
        """
        Get all users (for admin operations like casbin sync).
        
        ✅ SPRINT 4 HOTFIX: Added for sync_users_with_casbin refactoring.
        
        Returns:
            List of all users
        """
        query = select(models.User)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_by_ids(self, user_ids: List[int]) -> List[models.User]:
        """
        Get users by list of IDs.
        
        ✅ SPRINT 4 HOTFIX: Added for sync_users_with_casbin refactoring.
        
        Args:
            user_ids: List of user IDs
            
        Returns:
            List of users matching the IDs
        """
        query = select(models.User).where(models.User.id.in_(user_ids))
        result = await self.db.execute(query)
        return list(result.scalars().all())

    # =========================================================================
    # SPRINT 5: User Service Migration Methods
    # =========================================================================

    async def get_active_assignment_by_user(
        self,
        user_id: int
    ) -> Optional[models.UserUnitAssignment]:
        """
        Get the active unit assignment for a user.
        
        ✅ SPRINT 5: Added for user_service migration.
        
        Args:
            user_id: User ID
            
        Returns:
            Active UserUnitAssignment or None
        """
        query = select(models.UserUnitAssignment).where(
            models.UserUnitAssignment.user_id == user_id,
            models.UserUnitAssignment.is_active == True
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def get_user_for_delete(self, user_id: int) -> Optional[models.User]:
        """
        Get user with all relationships loaded for cascade delete.
        
        ✅ SPRINT 5: Added for user_service migration.
        Without eager loading, SQLAlchemy lazy-loads during cascade delete,
        which fails in async mode with "greenlet_spawn has not been called".
        
        Args:
            user_id: User ID
            
        Returns:
            User with sessions, unit_assignments, notification_preference loaded
        """
        query = (
            select(models.User)
            .where(models.User.id == user_id)
            .options(
                selectinload(models.User.sessions),
                selectinload(models.User.unit_assignments),
                selectinload(models.User.notification_preference),
            )
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def get_users_by_ids_for_delete(
        self,
        user_ids: List[int]
    ) -> List[models.User]:
        """
        Get users by IDs with relationships loaded for bulk delete.
        
        ✅ SPRINT 5: Added for user_service bulk actions migration.
        
        Args:
            user_ids: List of user IDs
            
        Returns:
            List of users with cascade-delete relationships loaded
        """
        query = (
            select(models.User)
            .where(models.User.id.in_(user_ids))
            .options(
                selectinload(models.User.sessions),
                selectinload(models.User.unit_assignments),
                selectinload(models.User.notification_preference),
            )
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def count_consultations_by_officers(
        self,
        officer_ids: List[int]
    ) -> Dict[int, int]:
        """
        Count consultations grouped by officer ID.
        
        ✅ SPRINT 5: Added for user_service bulk delete validation.
        
        Args:
            officer_ids: List of officer (user) IDs
            
        Returns:
            Dict mapping officer_id to consultation count
        """
        from sqlalchemy import func as sql_func
        
        query = (
            select(
                models.Consultation.officer_id,
                sql_func.count(models.Consultation.id)
            )
            .where(models.Consultation.officer_id.in_(officer_ids))
            .group_by(models.Consultation.officer_id)
        )
        result = await self.db.execute(query)
        return {row[0]: row[1] for row in result.all()}

    # =========================================================================
    # PHASE 2: Auth Refactor - Pessimistic Lock Methods
    # =========================================================================

    async def get_by_username_for_update(
        self,
        username: str
    ) -> Optional[models.User]:
        """
        Get user by username with pessimistic lock.

        ✅ PHASE 2: Added for auth refactor - refresh token flow.

        Uses SELECT ... FOR UPDATE to prevent concurrent modifications
        during token refresh operations.

        Args:
            username: Username to search and lock

        Returns:
            Locked User instance or None if not found
        """
        result = await self.db.execute(
            select(models.User)
            .where(models.User.username == username)
            .with_for_update(nowait=False)
        )
        return result.scalar_one_or_none()


