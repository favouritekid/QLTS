# app/repositories/notification_preference_repository.py
from typing import Dict, List, Optional, Tuple
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from .base import BaseRepository


class NotificationPreferenceRepository(BaseRepository[models.NotificationPreference]):
    """
    Repository for NotificationPreference model.
    Handles user settings for notifications.
    """

    def __init__(self, db: AsyncSession):
        super().__init__(db, models.NotificationPreference)

    async def get_filtered(
        self,
        skip: int = 0,
        limit: int = 100,
        **filters
    ) -> Tuple[int, List[models.NotificationPreference]]:
        """Get filtered preferences with pagination."""
        query = select(self.model)
        
        if "user_id" in filters and filters["user_id"]:
            query = query.where(self.model.user_id == filters["user_id"])
        
        total = await self.count()
        query = query.offset(skip).limit(limit)
        result = await self.db.execute(query)
        return total, list(result.scalars().all())

    async def get_by_user_id(self, user_id: int) -> Optional[models.NotificationPreference]:
        """Get preference by user ID."""
        query = select(self.model).where(self.model.user_id == user_id)
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def get_by_user_ids(self, user_ids: List[int]) -> Dict[int, models.NotificationPreference]:
        """Bulk fetch preferences for multiple users."""
        if not user_ids:
            return {}
        query = select(self.model).where(self.model.user_id.in_(user_ids))
        result = await self.db.execute(query)
        return {pref.user_id: pref for pref in result.scalars().all()}

    async def get_or_create(self, user_id: int) -> models.NotificationPreference:
        """
        Get preference for a user, or create a default one if it doesn't exist.
        """
        preference = await self.get_by_user_id(user_id)
        if not preference:
            preference = models.NotificationPreference(
                user_id=user_id,
                email_enabled=True,
                sound_enabled=True,
                browser_enabled=True,
                email_digest="instant",
                type_preferences={},
                quiet_hours_enabled=False,
            )
            self.db.add(preference)
            await self.db.flush()
            await self.db.refresh(preference)
        return preference
