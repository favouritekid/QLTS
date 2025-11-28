# app/routers/notification_rules.py
"""
✅ PHASE 2.2: Notification Rules CRUD Router

Admin-only API endpoints for managing notification rules.
Allows administrators to create, read, update, and delete notification
rules through UI instead of modifying code.
"""
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import database, models, schemas
from ..core import deps

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/notification-rules", tags=["Notification Rules (Admin)"])

# Admin-only permission dependency
AdminPermissionDep = Depends(deps.check_permission)


@router.get("", response_model=schemas.NotificationRulesPage)
async def list_notification_rules(
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = AdminPermissionDep,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    event: Optional[str] = Query(None, description="Filter by event type"),
    enabled: Optional[bool] = Query(None, description="Filter by enabled status"),
):
    """
    (Admin only) Get paginated list of notification rules.

    Query Parameters:
        - page: Page number (default: 1)
        - page_size: Items per page (default: 50, max: 100)
        - event: Filter by event type (e.g., "LEAD_ASSIGNED")
        - enabled: Filter by enabled status (true/false)

    Returns:
        Paginated list of notification rules with total count
    """
    skip = (page - 1) * page_size

    # Build query with filters
    query = select(models.NotificationRule)
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
    query = query.offset(skip).limit(page_size)

    # Execute queries
    result = await db.execute(query)
    rules = result.scalars().all()

    result = await db.execute(count_query)
    total = result.scalar()

    log.info(
        "Listed notification rules",
        admin_id=current_admin.id,
        page=page,
        page_size=page_size,
        total=total,
        filters={"event": event, "enabled": enabled}
    )

    return {
        "total_count": total,
        "rules": rules
    }


@router.get("/{rule_id}", response_model=schemas.NotificationRule)
async def get_notification_rule(
    rule_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = AdminPermissionDep,
):
    """
    (Admin only) Get a specific notification rule by ID.

    Returns:
        NotificationRule with all details
    """
    result = await db.execute(
        select(models.NotificationRule)
        .where(models.NotificationRule.id == rule_id)
    )
    rule = result.scalar_one_or_none()

    if not rule:
        log.warning(
            "Notification rule not found",
            rule_id=rule_id,
            admin_id=current_admin.id
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Notification rule {rule_id} not found"
        )

    log.info(
        "Retrieved notification rule",
        rule_id=rule_id,
        event_type=rule.event,
        admin_id=current_admin.id
    )

    return rule


@router.post("", response_model=schemas.NotificationRule, status_code=status.HTTP_201_CREATED)
async def create_notification_rule(
    rule_data: schemas.NotificationRuleCreate,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = AdminPermissionDep,
):
    """
    (Admin only) Create a new notification rule.

    Body:
        NotificationRuleCreate schema with:
        - event: SystemEvents enum value
        - title_template: Template with {placeholders}
        - message_template: Message template
        - notification_type: Severity (info/success/warning/error)
        - link_template: Optional link template
        - channels: ["browser", "email", "sms"]
        - recipient_config: Resolver configuration
        - condition: Optional activation conditions
        - enabled: Enable/disable flag

    Returns:
        Created NotificationRule
    """
    # Check if rule already exists for this event
    existing_result = await db.execute(
        select(models.NotificationRule)
        .where(models.NotificationRule.event == rule_data.event)
    )
    existing_rule = existing_result.scalar_one_or_none()

    if existing_rule:
        log.warning(
            "Duplicate notification rule attempt",
            event_type=rule_data.event,
            existing_rule_id=existing_rule.id,
            admin_id=current_admin.id
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Notification rule for event '{rule_data.event}' already exists (ID: {existing_rule.id})"
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
        enabled=rule_data.enabled
    )

    db.add(new_rule)
    await db.commit()
    await db.refresh(new_rule)

    log.info(
        "Created notification rule",
        rule_id=new_rule.id,
        event_type=new_rule.event,
        admin_id=current_admin.id,
        channels=new_rule.channels
    )

    return new_rule


@router.put("/{rule_id}", response_model=schemas.NotificationRule)
async def update_notification_rule(
    rule_id: int,
    rule_update: schemas.NotificationRuleUpdate,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = AdminPermissionDep,
):
    """
    (Admin only) Update an existing notification rule.

    Supports partial updates - only provided fields will be updated.

    Body:
        NotificationRuleUpdate schema (all fields optional)

    Returns:
        Updated NotificationRule
    """
    # Get existing rule
    result = await db.execute(
        select(models.NotificationRule)
        .where(models.NotificationRule.id == rule_id)
    )
    rule = result.scalar_one_or_none()

    if not rule:
        log.warning(
            "Notification rule not found for update",
            rule_id=rule_id,
            admin_id=current_admin.id
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Notification rule {rule_id} not found"
        )

    # Track which fields were updated
    updated_fields = []

    # Update fields if provided
    update_data = rule_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if value is not None:
            setattr(rule, field, value)
            updated_fields.append(field)

    if updated_fields:
        await db.commit()
        await db.refresh(rule)

        log.info(
            "Updated notification rule",
            rule_id=rule_id,
            event_type=rule.event,
            admin_id=current_admin.id,
            updated_fields=updated_fields
        )
    else:
        log.info(
            "No fields to update for notification rule",
            rule_id=rule_id,
            admin_id=current_admin.id
        )

    return rule


@router.patch("/{rule_id}/toggle", response_model=schemas.NotificationRule)
async def toggle_notification_rule(
    rule_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = AdminPermissionDep,
):
    """
    (Admin only) Toggle enabled/disabled status of a notification rule.

    This is a convenience endpoint for quickly enabling/disabling rules
    without needing to send the full update payload.

    Returns:
        Updated NotificationRule with toggled enabled status
    """
    # Get existing rule
    result = await db.execute(
        select(models.NotificationRule)
        .where(models.NotificationRule.id == rule_id)
    )
    rule = result.scalar_one_or_none()

    if not rule:
        log.warning(
            "Notification rule not found for toggle",
            rule_id=rule_id,
            admin_id=current_admin.id
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Notification rule {rule_id} not found"
        )

    # Toggle enabled status
    old_status = rule.enabled
    rule.enabled = not rule.enabled

    await db.commit()
    await db.refresh(rule)

    log.info(
        "Toggled notification rule status",
        rule_id=rule_id,
        event_type=rule.event,
        admin_id=current_admin.id,
        old_status=old_status,
        new_status=rule.enabled
    )

    return rule


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_notification_rule(
    rule_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = AdminPermissionDep,
):
    """
    (Admin only) Delete a notification rule.

    WARNING: This permanently deletes the rule. Consider disabling
    the rule instead if you might need it later.

    Returns:
        No content (204)
    """
    # Get existing rule
    result = await db.execute(
        select(models.NotificationRule)
        .where(models.NotificationRule.id == rule_id)
    )
    rule = result.scalar_one_or_none()

    if not rule:
        log.warning(
            "Notification rule not found for deletion",
            rule_id=rule_id,
            admin_id=current_admin.id
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Notification rule {rule_id} not found"
        )

    # Store event for logging
    event_type = rule.event

    # Delete the rule
    await db.delete(rule)
    await db.commit()

    log.info(
        "Deleted notification rule",
        rule_id=rule_id,
        event_type=event_type,
        admin_id=current_admin.id
    )

    return None
