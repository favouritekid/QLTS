from app.core.rate_limits import limiter, RateLimits
# app/routers/notification_templates.py
"""
✅ PHASE 3.1: Notification Templates CRUD Router

Admin-only API endpoints for managing reusable notification templates.
Templates can be shared across multiple notification rules to reduce duplication.
"""
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import database, models, schemas
from ..core import deps

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/notification-templates", tags=["Notification Templates (Admin)"])

# Admin-only permission dependency
AdminPermissionDep = Depends(deps.check_permission)


@limiter.limit(RateLimits.DATA_READ)  # 1000/hour
@router.get("", response_model=schemas.NotificationTemplatesPage)
async def list_notification_templates(
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = AdminPermissionDep,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    category: Optional[str] = Query(None, description="Filter by category"),
    is_system: Optional[bool] = Query(None, description="Filter by system flag"),
    search: Optional[str] = Query(None, description="Search by name or description"),
    # ✅ NOTIFICATION 2.0: New filters
    allowed_event: Optional[str] = Query(None, description="Filter by allowed event"),
    supported_channel: Optional[str] = Query(None, description="Filter by supported channel"),
):
    """
    (Admin only) Get paginated list of notification templates.

    Query Parameters:
        - page: Page number (default: 1)
        - page_size: Items per page (default: 50, max: 100)
        - category: Filter by category (e.g., "lead", "consultation")
        - is_system: Filter by system flag (true/false)
        - search: Search by name or description
        - allowed_event: Filter templates that support this event (null = all events)
        - supported_channel: Filter templates that support this channel

    Returns:
        Paginated list of notification templates with total count
    """
    skip = (page - 1) * page_size

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

    # ✅ NOTIFICATION 2.0: Filter by allowed_event
    if allowed_event:
        from sqlalchemy import or_
        # Match templates where allowed_events is null OR contains the event
        event_filter = or_(
            models.NotificationTemplate.allowed_events.is_(None),
            models.NotificationTemplate.allowed_events.contains([allowed_event])
        )
        query = query.where(event_filter)
        count_query = count_query.where(event_filter)

    # ✅ NOTIFICATION 2.0: Filter by supported_channel
    if supported_channel:
        # Match templates where supported_channels contains the channel
        channel_filter = models.NotificationTemplate.supported_channels.contains([supported_channel])
        query = query.where(channel_filter)
        count_query = count_query.where(channel_filter)

    # Order by name
    query = query.order_by(models.NotificationTemplate.name)

    # Apply pagination
    query = query.offset(skip).limit(page_size)

    # Execute queries
    result = await db.execute(query)
    templates = result.scalars().all()

    result = await db.execute(count_query)
    total = result.scalar()

    log.info(
        "Listed notification templates",
        admin_id=current_admin.id,
        page=page,
        page_size=page_size,
        total=total,
        filters={
            "category": category,
            "is_system": is_system,
            "search": search,
            "allowed_event": allowed_event,
            "supported_channel": supported_channel
        }
    )

    return {
        "total_count": total,
        "templates": templates
    }


@limiter.limit(RateLimits.DATA_READ)  # 1000/hour
@router.get("/{template_id}", response_model=schemas.NotificationTemplate)
async def get_notification_template(
    template_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = AdminPermissionDep,
):
    """
    (Admin only) Get a specific notification template by ID.

    Returns:
        NotificationTemplate with all details
    """
    result = await db.execute(
        select(models.NotificationTemplate)
        .where(models.NotificationTemplate.id == template_id)
    )
    template = result.scalar_one_or_none()

    if not template:
        log.warning(
            "Notification template not found",
            template_id=template_id,
            admin_id=current_admin.id
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Notification template {template_id} not found"
        )

    log.info(
        "Retrieved notification template",
        template_id=template_id,
        template_name=template.name,
        admin_id=current_admin.id
    )

    return template


@limiter.limit(RateLimits.DATA_WRITE)  # 200/hour
@router.post("", response_model=schemas.NotificationTemplate, status_code=status.HTTP_201_CREATED)
async def create_notification_template(
    template_data: schemas.NotificationTemplateCreate,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = AdminPermissionDep,
):
    """
    (Admin only) Create a new notification template.

    Body:
        NotificationTemplateCreate schema with:
        - name: Unique template name
        - description: Optional description
        - title_template: Template with {placeholders}
        - message_template: Message template
        - link_template: Optional link template
        - variables: List of available variables
        - category: Template category
        - is_system: System template flag

    Returns:
        Created NotificationTemplate
    """
    # Check if template with same name already exists
    existing_result = await db.execute(
        select(models.NotificationTemplate)
        .where(models.NotificationTemplate.name == template_data.name)
    )
    existing_template = existing_result.scalar_one_or_none()

    if existing_template:
        log.warning(
            "Duplicate template name attempt",
            template_name=template_data.name,
            existing_template_id=existing_template.id,
            admin_id=current_admin.id
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Template with name '{template_data.name}' already exists (ID: {existing_template.id})"
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
        created_by=current_admin.id,
        usage_count=0
    )

    db.add(new_template)
    await db.commit()
    await db.refresh(new_template)

    log.info(
        "Created notification template",
        template_id=new_template.id,
        template_name=new_template.name,
        category=new_template.category,
        admin_id=current_admin.id
    )

    return new_template


@limiter.limit(RateLimits.DATA_WRITE)  # 200/hour
@router.put("/{template_id}", response_model=schemas.NotificationTemplate)
async def update_notification_template(
    template_id: int,
    template_update: schemas.NotificationTemplateUpdate,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = AdminPermissionDep,
):
    """
    (Admin only) Update an existing notification template.

    Supports partial updates - only provided fields will be updated.

    Body:
        NotificationTemplateUpdate schema (all fields optional)

    Returns:
        Updated NotificationTemplate
    """
    # Get existing template
    result = await db.execute(
        select(models.NotificationTemplate)
        .where(models.NotificationTemplate.id == template_id)
    )
    template = result.scalar_one_or_none()

    if not template:
        log.warning(
            "Notification template not found for update",
            template_id=template_id,
            admin_id=current_admin.id
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Notification template {template_id} not found"
        )

    # Check if updating name to existing name
    if template_update.name and template_update.name != template.name:
        existing_result = await db.execute(
            select(models.NotificationTemplate)
            .where(models.NotificationTemplate.name == template_update.name)
        )
        existing_template = existing_result.scalar_one_or_none()
        if existing_template:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Template with name '{template_update.name}' already exists"
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
        await db.commit()
        await db.refresh(template)

        log.info(
            "Updated notification template",
            template_id=template_id,
            template_name=template.name,
            admin_id=current_admin.id,
            updated_fields=updated_fields
        )
    else:
        log.info(
            "No fields to update for notification template",
            template_id=template_id,
            admin_id=current_admin.id
        )

    return template


@limiter.limit(RateLimits.DATA_WRITE)  # 200/hour
@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_notification_template(
    template_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = AdminPermissionDep,
):
    """
    (Admin only) Delete a notification template.

    WARNING: Cannot delete system templates or templates currently in use.

    Returns:
        No content (204)
    """
    # Get existing template
    result = await db.execute(
        select(models.NotificationTemplate)
        .where(models.NotificationTemplate.id == template_id)
    )
    template = result.scalar_one_or_none()

    if not template:
        log.warning(
            "Notification template not found for deletion",
            template_id=template_id,
            admin_id=current_admin.id
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Notification template {template_id} not found"
        )

    # Check if system template
    if template.is_system:
        log.warning(
            "Attempted to delete system template",
            template_id=template_id,
            template_name=template.name,
            admin_id=current_admin.id
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Cannot delete system template '{template.name}'"
        )

    # Check if template is in use
    if template.usage_count > 0:
        log.warning(
            "Attempted to delete template in use",
            template_id=template_id,
            template_name=template.name,
            usage_count=template.usage_count,
            admin_id=current_admin.id
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot delete template '{template.name}' - currently used by {template.usage_count} rule(s)"
        )

    # Store name for logging
    template_name = template.name

    # Delete the template
    await db.delete(template)
    await db.commit()

    log.info(
        "Deleted notification template",
        template_id=template_id,
        template_name=template_name,
        admin_id=current_admin.id
    )

    return None