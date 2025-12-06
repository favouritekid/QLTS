# app/services/notification_rule_crud_service.py
"""
Notification Rule CRUD Service - CRUD operations for notification rules.

Extracted from router layer to comply with layered architecture:
Router → Security → Service → Model

Note: This is separate from notification_rule_loader.py which handles
rule loading and caching for the notification dispatcher.

This service handles:
1. List rules with filters and pagination
2. Get rule by ID
3. Create rule with duplicate check and template usage tracking
4. Update rule with actions and template usage tracking
5. Toggle rule enabled status
6. Delete rule with template usage tracking
"""
from typing import Callable, List, Optional, Tuple

import structlog
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .. import models, schemas
from ..utils.exceptions import BadRequest
from .notification_rule_loader import invalidate_rule_cache

log = structlog.get_logger(__name__)


async def get_rules(
    db: AsyncSession,
    skip: int = 0,
    limit: int = 50,
    event: Optional[str] = None,
    enabled: Optional[bool] = None,
) -> Tuple[List[models.NotificationRule], int]:
    """
    Get paginated list of notification rules with filters.

    Args:
        db: Database session
        skip: Number of records to skip
        limit: Maximum number of records to return
        event: Filter by event type
        enabled: Filter by enabled status

    Returns:
        Tuple of (rules list, total count)
    """
    # Build query with filters (eager load actions)
    query = select(models.NotificationRule).options(selectinload(models.NotificationRule.actions))
    count_query = select(func.count()).select_from(models.NotificationRule)

    if event:
        query = query.where(models.NotificationRule.event == event)
        count_query = count_query.where(models.NotificationRule.event == event)

    if enabled is not None:
        query = query.where(models.NotificationRule.enabled == enabled)
        count_query = count_query.where(models.NotificationRule.enabled == enabled)

    # Order by event name
    query = query.order_by(models.NotificationRule.event)

    # Apply pagination
    query = query.offset(skip).limit(limit)

    # Execute queries
    result = await db.execute(query)
    rules = list(result.scalars().all())

    result = await db.execute(count_query)
    total = result.scalar()

    return rules, total


async def create_rule(
    db: AsyncSession,
    rule_data: schemas.NotificationRuleCreate,
) -> Tuple[models.NotificationRule, Callable]:
    """
    Create a new notification rule.

    IMPORTANT: This function does NOT commit the transaction.
    Router must call db.commit() and then execute the returned callback.

    Args:
        db: Database session
        rule_data: Rule creation data

    Returns:
        Tuple of (created rule, post_commit_callback)

    Raises:
        BadRequest: If rule for this event already exists
    """
    # Check if rule already exists for this event
    existing_result = await db.execute(
        select(models.NotificationRule)
        .where(models.NotificationRule.event == rule_data.event)
    )
    existing_rule = existing_result.scalar_one_or_none()

    if existing_rule:
        raise BadRequest(
            f"Notification rule for event '{rule_data.event}' already exists (ID: {existing_rule.id})"
        )

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

    db.add(new_rule)
    await db.flush()  # Get the rule ID

    # Create actions for this rule
    for action_data in rule_data.actions:
        new_action = models.NotificationAction(
            rule_id=new_rule.id,
            step=action_data.step,
            channel=action_data.channel,
            template_code=action_data.template_code,
            delay_minutes=action_data.delay_minutes,
            config=action_data.config
        )
        db.add(new_action)

    # Increment usage_count if template is referenced
    if rule_data.template_id:
        await db.execute(
            update(models.NotificationTemplate)
            .where(models.NotificationTemplate.id == rule_data.template_id)
            .values(usage_count=models.NotificationTemplate.usage_count + 1)
        )

    await db.flush()
    await db.refresh(new_rule)

    # Create post-commit callback
    rule_id = new_rule.id
    event_type = new_rule.event
    template_id = rule_data.template_id
    actions_count = len(rule_data.actions)

    async def _post_commit():
        """Execute after router commits the transaction."""
        # Invalidate cache for this event
        await invalidate_rule_cache(event_type)

        log.info(
            "Created notification rule",
            rule_id=rule_id,
            event_type=event_type,
            template_id=template_id,
            actions_count=actions_count
        )

    return new_rule, _post_commit


async def update_rule(
    db: AsyncSession,
    rule: models.NotificationRule,
    rule_update: schemas.NotificationRuleUpdate,
) -> Tuple[models.NotificationRule, Callable]:
    """
    Update an existing notification rule.

    IMPORTANT: This function does NOT commit the transaction.
    Router must call db.commit() and then execute the returned callback.

    Args:
        db: Database session
        rule: Existing rule model
        rule_update: Update data

    Returns:
        Tuple of (updated rule, post_commit_callback)
    """
    # Track template_id changes for usage_count updates
    old_template_id = rule.template_id
    updated_fields = []

    # Update fields if provided (exclude actions, handle separately)
    update_data = rule_update.model_dump(exclude_unset=True, exclude={"actions"})
    for field, value in update_data.items():
        if value is not None:
            setattr(rule, field, value)
            updated_fields.append(field)

    # Handle actions update
    if rule_update.actions is not None:
        # Delete all existing actions
        await db.execute(
            delete(models.NotificationAction)
            .where(models.NotificationAction.rule_id == rule.id)
        )

        # Create new actions
        for action_data in rule_update.actions:
            new_action = models.NotificationAction(
                rule_id=rule.id,
                step=action_data.step,
                channel=action_data.channel,
                template_code=action_data.template_code,
                delay_minutes=action_data.delay_minutes,
                config=action_data.config
            )
            db.add(new_action)

        updated_fields.append("actions")

    # Update usage_count if template_id changed
    if "template_id" in updated_fields:
        new_template_id = rule.template_id

        # Decrement old template's usage_count
        if old_template_id:
            await db.execute(
                update(models.NotificationTemplate)
                .where(models.NotificationTemplate.id == old_template_id)
                .values(usage_count=models.NotificationTemplate.usage_count - 1)
            )

        # Increment new template's usage_count
        if new_template_id:
            await db.execute(
                update(models.NotificationTemplate)
                .where(models.NotificationTemplate.id == new_template_id)
                .values(usage_count=models.NotificationTemplate.usage_count + 1)
            )

    if updated_fields:
        await db.flush()
        await db.refresh(rule)

    # Create post-commit callback
    rule_id = rule.id
    event_type = rule.event
    template_changed = "template_id" in updated_fields

    async def _post_commit():
        """Execute after router commits the transaction."""
        # Invalidate cache for this event
        await invalidate_rule_cache(event_type)

        if updated_fields:
            log.info(
                "Updated notification rule",
                rule_id=rule_id,
                event_type=event_type,
                updated_fields=updated_fields,
                template_changed=template_changed
            )
        else:
            log.info(
                "No fields to update for notification rule",
                rule_id=rule_id
            )

    return rule, _post_commit


async def toggle_rule(
    db: AsyncSession,
    rule: models.NotificationRule,
) -> Tuple[models.NotificationRule, Callable]:
    """
    Toggle enabled/disabled status of a notification rule.

    IMPORTANT: This function does NOT commit the transaction.
    Router must call db.commit() and then execute the returned callback.

    Args:
        db: Database session
        rule: Rule to toggle

    Returns:
        Tuple of (updated rule, post_commit_callback)
    """
    # Toggle enabled status
    old_status = rule.enabled
    rule.enabled = not rule.enabled

    await db.flush()
    await db.refresh(rule)

    # Create post-commit callback
    rule_id = rule.id
    event_type = rule.event
    new_status = rule.enabled

    async def _post_commit():
        """Execute after router commits the transaction."""
        # Invalidate cache for this event
        await invalidate_rule_cache(event_type)

        log.info(
            "Toggled notification rule status",
            rule_id=rule_id,
            event_type=event_type,
            old_status=old_status,
            new_status=new_status
        )

    return rule, _post_commit


async def delete_rule(
    db: AsyncSession,
    rule: models.NotificationRule,
) -> Tuple[None, Callable]:
    """
    Delete a notification rule.

    IMPORTANT: This function does NOT commit the transaction.
    Router must call db.commit() and then execute the returned callback.

    Args:
        db: Database session
        rule: Rule to delete

    Returns:
        Tuple of (None, post_commit_callback)
    """
    # Store for callback
    rule_id = rule.id
    event_type = rule.event
    template_id = rule.template_id

    # Decrement usage_count if template is referenced
    if template_id:
        await db.execute(
            update(models.NotificationTemplate)
            .where(models.NotificationTemplate.id == template_id)
            .values(usage_count=models.NotificationTemplate.usage_count - 1)
        )

    # Delete the rule (actions cascade automatically if FK set up)
    await db.delete(rule)

    # Create post-commit callback
    async def _post_commit():
        """Execute after router commits the transaction."""
        # Invalidate cache for this event
        await invalidate_rule_cache(event_type)

        log.info(
            "Deleted notification rule",
            rule_id=rule_id,
            event_type=event_type,
            template_id=template_id
        )

    return None, _post_commit
