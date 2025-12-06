# app/services/notification_template_service.py
"""
Notification Template Service - CRUD operations for notification templates.

Extracted from router layer to comply with layered architecture:
Router → Security → Service → Model

This service handles:
1. List templates with filters and pagination
2. Get template by ID
3. Create template with duplicate check
4. Update template with name uniqueness validation
5. Delete template with system/usage checks
"""
from typing import Callable, List, Optional, Tuple

import structlog
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import models, schemas
from ..utils.exceptions import BadRequest, ResourceNotFoundError, PermissionDeniedError

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

    Args:
        db: Database session
        skip: Number of records to skip
        limit: Maximum number of records to return
        category: Filter by category
        is_system: Filter by system flag
        search: Search by name or description
        allowed_event: Filter by allowed event
        supported_channel: Filter by supported channel

    Returns:
        Tuple of (templates list, total count)
    """
    # Build query with filters
    query = select(models.NotificationTemplate)
    count_query = select(func.count()).select_from(models.NotificationTemplate)

    if category:
        query = query.where(models.NotificationTemplate.category == category)
        count_query = count_query.where(models.NotificationTemplate.category == category)

    if is_system is not None:
        query = query.where(models.NotificationTemplate.is_system == is_system)
        count_query = count_query.where(models.NotificationTemplate.is_system == is_system)

    if search:
        search_pattern = f"%{search}%"
        search_filter = (
            models.NotificationTemplate.name.ilike(search_pattern) |
            models.NotificationTemplate.description.ilike(search_pattern)
        )
        query = query.where(search_filter)
        count_query = count_query.where(search_filter)

    if allowed_event:
        event_filter = or_(
            models.NotificationTemplate.allowed_events.is_(None),
            models.NotificationTemplate.allowed_events.contains([allowed_event])
        )
        query = query.where(event_filter)
        count_query = count_query.where(event_filter)

    if supported_channel:
        channel_filter = models.NotificationTemplate.supported_channels.contains([supported_channel])
        query = query.where(channel_filter)
        count_query = count_query.where(channel_filter)

    # Order by name
    query = query.order_by(models.NotificationTemplate.name)

    # Apply pagination
    query = query.offset(skip).limit(limit)

    # Execute queries
    result = await db.execute(query)
    templates = list(result.scalars().all())

    result = await db.execute(count_query)
    total = result.scalar()

    return templates, total


async def get_template_by_id(
    db: AsyncSession,
    template_id: int,
) -> models.NotificationTemplate:
    """
    Get a notification template by ID.

    Args:
        db: Database session
        template_id: Template ID

    Returns:
        NotificationTemplate model

    Raises:
        ResourceNotFoundError: If template not found
    """
    result = await db.execute(
        select(models.NotificationTemplate)
        .where(models.NotificationTemplate.id == template_id)
    )
    template = result.scalar_one_or_none()

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

    IMPORTANT: This function does NOT commit the transaction.
    Router must call db.commit() and then execute the returned callback.

    Args:
        db: Database session
        template_data: Template creation data
        created_by_user_id: ID of user creating the template

    Returns:
        Tuple of (created template, post_commit_callback)

    Raises:
        BadRequest: If template with same name already exists
    """
    # Check for duplicate name
    existing_result = await db.execute(
        select(models.NotificationTemplate)
        .where(models.NotificationTemplate.name == template_data.name)
    )
    existing_template = existing_result.scalar_one_or_none()

    if existing_template:
        raise BadRequest(
            f"Template with name '{template_data.name}' already exists (ID: {existing_template.id})"
        )

    # Create new template
    new_template = models.NotificationTemplate(
        name=template_data.name,
        description=template_data.description,
        title_template=template_data.title_template,
        message_template=template_data.message_template,
        link_template=template_data.link_template,
        variables=template_data.variables,
        category=template_data.category,
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

    IMPORTANT: This function does NOT commit the transaction.
    Router must call db.commit() and then execute the returned callback.

    Args:
        db: Database session
        template: Existing template model
        template_update: Update data

    Returns:
        Tuple of (updated template, post_commit_callback)

    Raises:
        BadRequest: If new name conflicts with existing template
    """
    # Check if updating name to existing name
    if template_update.name and template_update.name != template.name:
        existing_result = await db.execute(
            select(models.NotificationTemplate)
            .where(models.NotificationTemplate.name == template_update.name)
        )
        existing_template = existing_result.scalar_one_or_none()
        if existing_template:
            raise BadRequest(
                f"Template with name '{template_update.name}' already exists"
            )

    # Track which fields were updated
    updated_fields = []

    # Update fields if provided
    update_data = template_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if value is not None:
            setattr(template, field, value)
            updated_fields.append(field)

    if updated_fields:
        await db.flush()
        await db.refresh(template)

    # Create post-commit callback
    template_id = template.id
    template_name = template.name

    async def _post_commit():
        """Execute after router commits the transaction."""
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

    IMPORTANT: This function does NOT commit the transaction.
    Router must call db.commit() and then execute the returned callback.

    Args:
        db: Database session
        template: Template to delete

    Returns:
        Tuple of (None, post_commit_callback)

    Raises:
        PermissionDeniedError: If template is a system template
        BadRequest: If template is in use by notification rules
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

    # Store for logging
    template_id = template.id
    template_name = template.name

    # Delete the template
    await db.delete(template)

    # Create post-commit callback
    async def _post_commit():
        """Execute after router commits the transaction."""
        log.info(
            "Deleted notification template",
            template_id=template_id,
            template_name=template_name
        )

    return None, _post_commit
