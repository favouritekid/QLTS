# app/repositories/notification_rule_repository.py
from typing import List, Optional, Tuple
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app import models, schemas
from .base import BaseRepository


class NotificationRuleRepository(BaseRepository[models.NotificationRule]):
    """
    Repository for NotificationRule model.
    Handles CRUD operations and related actions/templates logic.
    """

    def __init__(self, db: AsyncSession):
        super().__init__(db, models.NotificationRule)

    async def get_filtered(
        self,
        skip: int = 0,
        limit: int = 100,
        **filters
    ) -> Tuple[List[models.NotificationRule], int]:
        """Get filtered rules with pagination."""
        return await self.list_rules(skip, limit, filters.get("event"), filters.get("enabled"))

    async def get_by_id(self, rule_id: int) -> Optional[models.NotificationRule]:
        """Get rule by ID with actions eager loaded."""
        query = (
            select(self.model)
            .where(self.model.id == rule_id)
            .options(selectinload(self.model.actions))
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def get_by_event(self, event: str) -> Optional[models.NotificationRule]:
        """Get rule by event type."""
        query = select(self.model).where(self.model.event == event)
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def list_rules(
        self,
        skip: int = 0,
        limit: int = 50,
        event: Optional[str] = None,
        enabled: Optional[bool] = None,
    ) -> Tuple[List[models.NotificationRule], int]:
        """
        Get paginated list of notification rules with filters.
        """
        # Build query with filters (eager load actions)
        query = select(self.model).options(selectinload(self.model.actions))
        count_query = select(func.count()).select_from(self.model)

        if event:
            query = query.where(self.model.event == event)
            count_query = count_query.where(self.model.event == event)

        if enabled is not None:
            query = query.where(self.model.enabled == enabled)
            count_query = count_query.where(self.model.enabled == enabled)

        # Order by event name
        query = query.order_by(self.model.event)

        # Apply pagination
        query = query.offset(skip).limit(limit)

        # Execute queries
        result = await self.db.execute(query)
        rules = list(result.scalars().all())

        result = await self.db.execute(count_query)
        total = result.scalar() or 0

        return rules, total

    async def create_with_actions(
        self, 
        rule_data: schemas.NotificationRuleCreate
    ) -> models.NotificationRule:
        """
        Create a new rule along with its actions and update template usage.
        """
        # Create new rule
        new_rule = models.NotificationRule(
            event=rule_data.event,
            title_template=rule_data.title_template,
            message_template=rule_data.message_template,
            notification_type=rule_data.notification_type,
            link_template=rule_data.link_template,
            channels=rule_data.channels,
            recipient_config=rule_data.recipient_config,
            condition=rule_data.condition,
            enabled=rule_data.enabled,
            template_id=rule_data.template_id
        )
        self.db.add(new_rule)
        await self.db.flush()

        # Create actions
        for action_data in rule_data.actions:
            new_action = models.NotificationAction(
                rule_id=new_rule.id,
                step=action_data.step,
                channel=action_data.channel,
                template_code=action_data.template_code,
                delay_minutes=action_data.delay_minutes,
                config=action_data.config
            )
            self.db.add(new_action)

        # Increment usage_count if template is referenced
        if rule_data.template_id:
            await self.update_template_usage(rule_data.template_id, 1)

        await self.db.flush()
        await self.db.refresh(new_rule)
        return new_rule

    async def delete_actions(self, rule_id: int) -> None:
        """Delete all actions for a rule."""
        await self.db.execute(
            delete(models.NotificationAction)
            .where(models.NotificationAction.rule_id == rule_id)
        )

    async def add_actions(self, rule_id: int, actions: List[schemas.NotificationActionCreate]) -> None:
        """Add new actions to a rule."""
        for action_data in actions:
            new_action = models.NotificationAction(
                rule_id=rule_id,
                step=action_data.step,
                channel=action_data.channel,
                template_code=action_data.template_code,
                delay_minutes=action_data.delay_minutes,
                config=action_data.config
            )
            self.db.add(new_action)

    async def update_template_usage(self, template_id: int, delta: int) -> None:
        """Update the usage_count of a NotificationTemplate."""
        await self.db.execute(
            update(models.NotificationTemplate)
            .where(models.NotificationTemplate.id == template_id)
            .values(usage_count=models.NotificationTemplate.usage_count + delta)
        )

    async def delete_rule(self, rule: models.NotificationRule) -> None:
        """Delete rule and decrement template usage."""
        if rule.template_id:
            await self.update_template_usage(rule.template_id, -1)
        await self.db.delete(rule)
