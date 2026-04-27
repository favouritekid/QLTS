# app/services/notification_template_service.py
"""
Notification Template Service - CRUD operations for notification templates.

Complies with Pattern A: Router → Service → Repository
"""
from typing import Callable, List, Optional, Tuple

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app import models, schemas
from app.utils.exceptions import BadRequest, ResourceNotFoundError, PermissionDeniedError
from app.repositories import NotificationTemplateRepository

log = structlog.get_logger(__name__)


async def get_templates(
    db: AsyncSession,
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
    repo = NotificationTemplateRepository(db)
    return await repo.list_templates(
        skip, limit, category, is_system, search, allowed_event, supported_channel
    )


async def get_template_by_id(
    db: AsyncSession,
    template_id: int,
) -> models.NotificationTemplate:
    """
    Get a notification template by ID.
    """
    repo = NotificationTemplateRepository(db)
    template = await repo.get_by_id(template_id)
    if not template:
        raise ResourceNotFoundError(f"Notification template with ID {template_id} not found")
    return template


async def create_template(
    db: AsyncSession,
    template_data: schemas.NotificationTemplateCreate,
    created_by_user_id: int,
) -> Tuple[models.NotificationTemplate, Callable]:
    """
    Create a new notification template.
    """
    repo = NotificationTemplateRepository(db)
    
    # Check for duplicate name
    existing_template = await repo.get_by_name(template_data.name)
    if existing_template:
        raise BadRequest(
            f"Template with name '{template_data.name}' already exists (ID: {existing_template.id})"
        )

    # Check for duplicate template_code
    existing_by_code = await repo.get_by_template_code(template_data.template_code)
    if existing_by_code:
        raise BadRequest(
            f"Template with code '{template_data.template_code}' already exists (ID: {existing_by_code.id})"
        )

    # Create new template
    new_template = models.NotificationTemplate(
        name=template_data.name,
        template_code=template_data.template_code,
        description=template_data.description,
        title_template=template_data.title_template,
        message_template=template_data.message_template,
        link_template=template_data.link_template,
        variables=template_data.variables,
        category=template_data.category,
        supported_channels=template_data.supported_channels,
        allowed_events=template_data.allowed_events,
        template_type=template_data.template_type,
        is_system=template_data.is_system,
        created_by=created_by_user_id,
        usage_count=0
    )

    db.add(new_template)
    await db.flush()
    await db.refresh(new_template)

    # Create post-commit callback
    template_id = new_template.id
    template_name = new_template.name

    async def _post_commit():
        """Execute after router commits the transaction."""
        log.info(
            "Created notification template",
            template_id=template_id,
            template_name=template_name,
            created_by=created_by_user_id
        )

    return new_template, _post_commit


async def update_template(
    db: AsyncSession,
    template: models.NotificationTemplate,
    template_update: schemas.NotificationTemplateUpdate,
) -> Tuple[models.NotificationTemplate, Callable]:
    """
    Update an existing notification template.
    """
    repo = NotificationTemplateRepository(db)

    # Check if updating name to existing name
    if template_update.name and template_update.name != template.name:
        existing_template = await repo.get_by_name(template_update.name)
        if existing_template:
            raise BadRequest(
                f"Template with name '{template_update.name}' already exists"
            )

    # Track which fields were updated
    updated_fields = []

    # Update fields if provided. `exclude_unset=True` already filters
    # fields the client didn't touch, so we only need to guard non-nullable
    # columns against an explicit `null` from a stale client. Nullable
    # columns are clearable — admin can blank them by sending `null`.
    update_data = template_update.model_dump(exclude_unset=True)
    _CLEARABLE_FIELDS = {"description", "link_template", "variables", "category", "allowed_events"}
    for field, value in update_data.items():
        if value is None and field not in _CLEARABLE_FIELDS:
            continue
        setattr(template, field, value)
        updated_fields.append(field)

    # 1.9e: Find rules that reference this template (for cache invalidation)
    from sqlalchemy import select
    rules_result = await db.execute(
        select(models.NotificationRule.event)
        .where(models.NotificationRule.template_id == template.id)
    )
    affected_events = [row[0] for row in rules_result.fetchall()]

    if updated_fields:
        await db.flush()
        await db.refresh(template)

    # Create post-commit callback
    template_id = template.id
    template_name = template.name

    async def _post_commit():
        """Execute after router commits the transaction."""
        # 1.9e: Invalidate rule cache for any rules using this template
        if affected_events:
            from app.services.notification_rule_loader import invalidate_rule_cache
            for event_name in affected_events:
                await invalidate_rule_cache(event_name)
            log.info(
                "Invalidated rule caches for template update",
                template_id=template_id,
                affected_events=affected_events,
            )

        if updated_fields:
            log.info(
                "Updated notification template",
                template_id=template_id,
                template_name=template_name,
                updated_fields=updated_fields
            )
        else:
            log.info(
                "No fields to update for notification template",
                template_id=template_id
            )

    return template, _post_commit


async def delete_template(
    db: AsyncSession,
    template: models.NotificationTemplate,
) -> Tuple[None, Callable]:
    """
    Delete a notification template.
    """
    # Check if system template
    if template.is_system:
        raise PermissionDeniedError(
            f"Cannot delete system template '{template.name}'"
        )

    # Check if template is in use
    if template.usage_count > 0:
        raise BadRequest(
            f"Cannot delete template '{template.name}' - currently used by {template.usage_count} rule(s)"
        )

    # 1.9e: Find affected rules before delete (for cache invalidation)
    from sqlalchemy import select
    rules_result = await db.execute(
        select(models.NotificationRule.event)
        .where(models.NotificationRule.template_id == template.id)
    )
    affected_events = [row[0] for row in rules_result.fetchall()]

    # Store for logging
    template_id = template.id
    template_name = template.name

    # Delete the template
    await db.delete(template)

    # Create post-commit callback
    async def _post_commit():
        """Execute after router commits the transaction."""
        # 1.9e: Invalidate rule caches for affected events
        if affected_events:
            from app.services.notification_rule_loader import invalidate_rule_cache
            for event_name in affected_events:
                await invalidate_rule_cache(event_name)

        log.info(
            "Deleted notification template",
            template_id=template_id,
            template_name=template_name
        )

    return None, _post_commit
