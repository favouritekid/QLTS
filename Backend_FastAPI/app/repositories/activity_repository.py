# app/repositories/activity_repository.py
"""
ActivityRepository - Data access for UserActivityLog

Provides queries for:
- Activity log filtering with pagination
- User statistics aggregation
"""

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import and_, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app import models
from app.repositories.base import BaseRepository


class ActivityRepository(BaseRepository[models.UserActivityLog]):
    """Repository for UserActivityLog operations."""
    
    def __init__(self, db: AsyncSession):
        super().__init__(db, models.UserActivityLog)
    
    async def get_filtered(
        self,
        skip: int = 0,
        limit: int = 50,
        actor_id: Optional[int] = None,
        target_user_id: Optional[int] = None,
        action: Optional[str] = None,
        resource_type: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> Tuple[int, List[models.UserActivityLog]]:
        """
        Get activity logs with optional filters.
        
        Args:
            skip: Number of records to skip
            limit: Maximum records to return
            actor_id: Filter by actor user ID
            target_user_id: Filter by target user ID
            action: Filter by action type
            resource_type: Filter by resource type
            start_date: Filter logs after this date
            end_date: Filter logs before this date
            
        Returns:
            Tuple of (total_count, list of activity logs)
        """
        # Build filters
        filters = self._build_filters(
            actor_id=actor_id,
            target_user_id=target_user_id,
            action=action,
            resource_type=resource_type,
            start_date=start_date,
            end_date=end_date,
        )
        
        # Count total
        count_query = select(func.count()).select_from(models.UserActivityLog)
        if filters:
            count_query = count_query.where(and_(*filters))
        total_result = await self.db.execute(count_query)
        total_count = total_result.scalar() or 0
        
        # Get logs with user details
        query = (
            select(models.UserActivityLog)
            .options(
                selectinload(models.UserActivityLog.actor),
                selectinload(models.UserActivityLog.target_user),
            )
            .order_by(desc(models.UserActivityLog.created_at))
            .offset(skip)
            .limit(limit)
        )
        
        if filters:
            query = query.where(and_(*filters))
        
        result = await self.db.execute(query)
        logs = list(result.scalars().all())
        
        return total_count, logs
    
    def _build_filters(
        self,
        actor_id: Optional[int] = None,
        target_user_id: Optional[int] = None,
        action: Optional[str] = None,
        resource_type: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> List[Any]:
        """Build filter conditions for activity log queries."""
        filters = []
        if actor_id is not None:
            filters.append(models.UserActivityLog.actor_id == actor_id)
        if target_user_id is not None:
            filters.append(models.UserActivityLog.target_user_id == target_user_id)
        if action is not None:
            filters.append(models.UserActivityLog.action == action)
        if resource_type is not None:
            filters.append(models.UserActivityLog.resource_type == resource_type)
        if start_date is not None:
            filters.append(models.UserActivityLog.created_at >= start_date)
        if end_date is not None:
            filters.append(models.UserActivityLog.created_at <= end_date)
        return filters
    
    async def get_user_counts_by_status(self) -> Dict[str, int]:
        """
        Get user counts grouped by status.
        
        Returns:
            Dict mapping status -> count
        """
        query = (
            select(
                models.User.status,
                func.count(models.User.id).label("count")
            )
            .group_by(models.User.status)
        )
        result = await self.db.execute(query)
        return {row.status: row.count for row in result}
    
    async def get_total_user_count(self) -> int:
        """Get total user count."""
        query = select(func.count()).select_from(models.User)
        result = await self.db.execute(query)
        return result.scalar() or 0
    
    async def get_user_counts_by_role(self) -> Dict[str, int]:
        """
        Get user counts grouped by role.
        
        Returns:
            Dict mapping role -> count
        """
        query = (
            select(
                models.User.role,
                func.count(models.User.id).label("count")
            )
            .group_by(models.User.role)
        )
        result = await self.db.execute(query)
        return {row.role: row.count for row in result}
