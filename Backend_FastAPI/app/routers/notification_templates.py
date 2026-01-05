from app.core.rate_limits import limiter, RateLimits
# app/routers/notification_templates.py
"""
✅ PHASE 3.1: Notification Templates CRUD Router

Admin-only API endpoints for managing reusable notification templates.
Templates can be shared across multiple notification rules to reduce duplication.

REFACTORED: CRUD logic moved to notification_template_service.py
Router now only handles HTTP concerns and orchestration.
"""
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from .. import database, models, schemas
from app.core.deps import CasbinAuth, get_notification_template_for_admin  # Phase 2.2
from ..services import notification_template_service
from ..utils.exceptions import BadRequest, PermissionDeniedError, ResourceNotFoundError

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/notification-templates", tags=["Notification Templates (Admin)"])

# Admin-only permission dependency


@limiter.limit(RateLimits.DATA_READ)  # 1000/hour
@router.get("", response_model=schemas.NotificationTemplatesPage)
async def list_notification_templates(
    request: Request,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = CasbinAuth,
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

    templates, total = await notification_template_service.get_templates(
        db=db,
        skip=skip,
        limit=page_size,
        category=category,
        is_system=is_system,
        search=search,
        allowed_event=allowed_event,
        supported_channel=supported_channel,
    )

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
    request: Request,
    template: models.NotificationTemplate = Depends(get_notification_template_for_admin),
    current_admin: models.User = CasbinAuth,
):
    """
    (Admin only) Get a specific notification template by ID.

    Returns:
        NotificationTemplate with all details
    """
    log.info(
        "Retrieved notification template",
        template_id=template.id,
        template_name=template.name,
        admin_id=current_admin.id
    )

    return template


@limiter.limit(RateLimits.DATA_WRITE)  # 200/hour
@router.post("", response_model=schemas.NotificationTemplate, status_code=status.HTTP_201_CREATED)
async def create_notification_template(
    request: Request,
    template_data: schemas.NotificationTemplateCreate,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = CasbinAuth,
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
    try:
        template, callback = await notification_template_service.create_template(
            db=db,
            template_data=template_data,
            created_by_user_id=current_admin.id,
        )

        # ✅ TRANSACTION PATTERN: Commit and execute callback
        await db.commit()
        await callback()

        return template

    except BadRequest as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@limiter.limit(RateLimits.DATA_WRITE)  # 200/hour
@router.put("/{template_id}", response_model=schemas.NotificationTemplate)
async def update_notification_template(
    request: Request,
    template_update: schemas.NotificationTemplateUpdate,
    template: models.NotificationTemplate = Depends(get_notification_template_for_admin),
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = CasbinAuth,
):
    """
    (Admin only) Update an existing notification template.

    Supports partial updates - only provided fields will be updated.

    Body:
        NotificationTemplateUpdate schema (all fields optional)

    Returns:
        Updated NotificationTemplate
    """
    try:
        updated_template, callback = await notification_template_service.update_template(
            db=db,
            template=template,
            template_update=template_update,
        )

        # ✅ TRANSACTION PATTERN: Commit and execute callback
        await db.commit()
        await callback()

        return updated_template

    except BadRequest as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@limiter.limit(RateLimits.DATA_WRITE)  # 200/hour
@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_notification_template(
    request: Request,
    template: models.NotificationTemplate = Depends(get_notification_template_for_admin),
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = CasbinAuth,
):
    """
    (Admin only) Delete a notification template.

    WARNING: Cannot delete system templates or templates currently in use.

    Returns:
        No content (204)
    """
    try:
        _, callback = await notification_template_service.delete_template(
            db=db,
            template=template,
        )

        # ✅ TRANSACTION PATTERN: Commit and execute callback
        await db.commit()
        await callback()

        return None

    except PermissionDeniedError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e)
        )
    except BadRequest as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )