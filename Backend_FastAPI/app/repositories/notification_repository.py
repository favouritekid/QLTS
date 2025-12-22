# app/repositories/notification_repository.py
from typing import List, Optional, Tuple
from sqlalchemy import and_, cast, desc, func, insert, select, String
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from .base import BaseRepository

class NotificationRepository(BaseRepository[models.Notification]):
    """
    Repository for Notification model.
    ✅ PATTERN A COMPLIANT
    """

    def __init__(self, db: AsyncSession):
        super().__init__(db, models.Notification)

    async def get_filtered(
        self,
        skip: int = 0,
        limit: int = 100,
        user_id: Optional[int] = None,
        unread_only: bool = False,
        **kwargs
    ) -> Tuple[int, List[models.Notification]]:
        """
        Get paginated notifications with filtering.
        """
        filters = []
        if user_id is not None:
            filters.append(self.model.user_id == user_id)
        if unread_only:
            filters.append(self.model.is_read == False)

        where_clause = and_(*filters) if filters else None
        
        # Count total
        total = await self.count(where_clause)
        
        # Get records
        query = select(self.model).offset(skip).limit(limit).order_by(desc(self.model.created_at))
        if where_clause is not None:
            query = query.where(where_clause)
            
        result = await self.db.execute(query)
        return total, list(result.scalars().all())

    async def get_unread_count(self, user_id: int) -> int:
        """Count unread notifications for a user."""
        return await self.count(
            and_(
                self.model.user_id == user_id,
                self.model.is_read == False
            )
        )

    async def get_total_count(self, user_id: int) -> int:
        """Count total notifications for a user."""
        return await self.count(self.model.user_id == user_id)

    async def get_by_ids(self, notification_ids: List[int]) -> List[models.Notification]:
        """Fetch notifications by a list of IDs."""
        if not notification_ids:
            return []
            
        query = select(self.model).where(self.model.id.in_(notification_ids))
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_by_dedupe_key(self, user_ids: List[int], dedupe_key: str) -> List[int]:
        """
        Find user IDs who already have a notification with the given dedupe_key.
        """
        query = select(self.model.user_id).where(
            and_(
                self.model.user_id.in_(user_ids),
                func.json_extract(self.model.data, "$.dedupe_key") == dedupe_key
            )
        )
        result = await self.db.execute(query)
        return [row[0] for row in result.fetchall()]

    async def bulk_create(self, values: List[dict]) -> List[int]:
        """
        Perform bulk insert of notifications.
        Returns list of created IDs.
        """
        if not values:
            return []
            
        result = await self.db.execute(
            insert(self.model)
            .values(values)
            .returning(self.model.id)
        )
        return [row[0] for row in result.fetchall()]

    async def get_unread_for_user(self, user_id: int, notification_ids: Optional[List[int]] = None) -> List[models.Notification]:
        """
        Get unread notifications for a specific user.
        Optionally restricted to a list of IDs.
        """
        filters = [
            self.model.user_id == user_id,
            self.model.is_read == False
        ]
        if notification_ids:
            filters.append(self.model.id.in_(notification_ids))
            
        query = select(self.model).where(and_(*filters))
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_for_user_by_id(self, user_id: int, notification_id: int) -> Optional[models.Notification]:
        """Get a specific notification if it belongs to the user."""
        query = select(self.model).where(
            and_(
                self.model.id == notification_id,
                self.model.user_id == user_id
            )
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()
