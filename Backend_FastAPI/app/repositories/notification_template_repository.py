# app/repositories/notification_template_repository.py
from typing import List, Optional, Tuple
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from .base import BaseRepository


class NotificationTemplateRepository(BaseRepository[models.NotificationTemplate]):
    """
    Repository for NotificationTemplate model.
    Handles CRUD operations and advanced filtering.
    """

    def __init__(self, db: AsyncSession):
        super().__init__(db, models.NotificationTemplate)

    async def get_filtered(
        self,
        skip: int = 0,
        limit: int = 100,
        **filters
    ) -> Tuple[int, List[models.NotificationTemplate]]:
        """Get filtered templates with pagination."""
        templates, total = await self.list_templates(
            skip, limit,
            filters.get("category"),
            filters.get("is_system"),
            filters.get("search"),
            filters.get("allowed_event"),
            filters.get("supported_channel")
        )
        return total, templates

    async def get_by_name(self, name: str) -> Optional[models.NotificationTemplate]:
        """Get template by name."""
        query = select(self.model).where(self.model.name == name)
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def list_templates(
        self,
        skip: int = 0,
        limit: int = 50,
        category: Optional[str] = None,
        is_system: Optional[bool] = None,
        search: Optional[str] = None,
        allowed_event: Optional[str] = None,
        supported_channel: Optional[str] = None,
    ) -> Tuple[List[models.NotificationTemplate], int]:
        """
        Get paginated list of notification templates with filters.
        """
        # Build query with filters
        query = select(self.model)
        count_query = select(func.count()).select_from(self.model)

        if category:
            query = query.where(self.model.category == category)
            count_query = count_query.where(self.model.category == category)

        if is_system is not None:
            query = query.where(self.model.is_system == is_system)
            count_query = count_query.where(self.model.is_system == is_system)

        if search:
            search_pattern = f"%{search}%"
            search_filter = (
                self.model.name.ilike(search_pattern) |
                self.model.description.ilike(search_pattern)
            )
            query = query.where(search_filter)
            count_query = count_query.where(search_filter)

        if allowed_event:
            # allowed_events is a JSON array in Postgres
            event_filter = or_(
                self.model.allowed_events.is_(None),
                self.model.allowed_events.contains([allowed_event])
            )
            query = query.where(event_filter)
            count_query = count_query.where(event_filter)

        if supported_channel:
            # supported_channels is a JSON array
            channel_filter = self.model.supported_channels.contains([supported_channel])
            query = query.where(channel_filter)
            count_query = count_query.where(channel_filter)

        # Order by name
        query = query.order_by(self.model.name)

        # Apply pagination
        query = query.offset(skip).limit(limit)

        # Execute queries
        result = await self.db.execute(query)
        templates = list(result.scalars().all())

        result = await self.db.execute(count_query)
        total = result.scalar() or 0

        return templates, total
