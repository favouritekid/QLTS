from app.core.rate_limits import limiter, RateLimits
# app/routers/notification_preferences.py
"""
Notification Preferences Router - API endpoints for managing notification preferences.

This module provides endpoints for:
1. Getting/updating general notification preferences
2. Getting/updating event group preferences (NEW)
3. Getting available event groups metadata (NEW)
"""
from typing import Dict, List

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from .. import database, models, schemas
from ..core import deps
from ..core.event_groups import (
    NotificationEventGroup,
    NotificationChannel,
    EVENT_GROUP_LABELS,
)
from ..services import notification_preference_service

log = structlog.get_logger(__name__)
router = APIRouter(tags=["Notification Preferences"])
PermissionDep = Depends(deps.check_permission)


# =============================================================================
# SCHEMAS FOR NEW ENDPOINTS
# =============================================================================

class EventGroupInfo(BaseModel):
    """Event group metadata for frontend display."""
    id: str
    name_en: str
    name_vi: str
    description_en: str
    description_vi: str


class EventGroupPreference(BaseModel):
    """Preference settings for an event group."""
    group: str
    browser: bool
    email: bool
    sms: bool


class EventGroupPreferencesResponse(BaseModel):
    """Response containing all event group preferences."""
    groups: List[EventGroupInfo]
    preferences: Dict[str, Dict[str, bool]]


class UpdateGroupPreferenceRequest(BaseModel):
    """Request to update a single group/channel preference."""
    event_group: str
    channel: str
    enabled: bool


# =============================================================================
# EXISTING ENDPOINTS (Backward Compatible)
# =============================================================================

@limiter.limit(RateLimits.DATA_READ)  # 1000/hour
@router.get("/preferences", response_model=schemas.NotificationPreference)
async def get_notification_preferences(
    request: Request,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = PermissionDep,
):
    """Get user's notification preferences."""
    preference = await notification_preference_service.get_user_preference(
        db, current_user.id
    )

    return preference


@limiter.limit(RateLimits.DATA_WRITE)  # 200/hour
@router.put("/preferences", response_model=schemas.NotificationPreference)
async def update_notification_preferences(
    request: Request,
    preference_update: schemas.NotificationPreferenceUpdate,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = PermissionDep,
):
    """Update user's notification preferences."""
    preference = await notification_preference_service.update_user_preference(
        db, current_user.id, preference_update
    )

    log.info(
        "User updated notification preferences",
        user_id=current_user.id,
        username=current_user.username,
    )

    return preference


# =============================================================================
# NEW ENDPOINTS FOR EVENT GROUPS
# =============================================================================

@limiter.limit(RateLimits.DATA_READ)  # 1000/hour
@router.get("/event-groups", response_model=EventGroupPreferencesResponse)
async def get_event_group_preferences(
    request: Request,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = PermissionDep,
):
    """
    Get user's notification preferences organized by event groups.

    Returns:
        - List of available event groups with metadata
        - User's preference settings for each group/channel
    """
    # Get event group metadata
    groups = []
    for group in NotificationEventGroup:
        labels = EVENT_GROUP_LABELS.get(group, {})
        groups.append(EventGroupInfo(
            id=group.value,
            name_en=labels.get("en", group.value.title()),
            name_vi=labels.get("vi", group.value.title()),
            description_en=labels.get("description_en", ""),
            description_vi=labels.get("description_vi", "")
        ))

    # Get user's preferences
    preferences = await notification_preference_service.get_user_group_preferences(
        db, current_user.id
    )

    return EventGroupPreferencesResponse(
        groups=groups,
        preferences=preferences
    )


@limiter.limit(RateLimits.DATA_WRITE)  # 200/hour
@router.patch("/event-groups")
async def update_event_group_preference(
    request: Request,
    request: UpdateGroupPreferenceRequest,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = PermissionDep,
):
    """
    Update a single event group/channel preference.

    Args:
        request: Contains event_group, channel, and enabled flag

    Example:
        PATCH /api/notifications/event-groups
        {
            "event_group": "lead",
            "channel": "browser",
            "enabled": false
        }
    """
    # Validate event group
    valid_groups = [g.value for g in NotificationEventGroup]
    if request.event_group.lower() not in valid_groups:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid event_group. Must be one of: {valid_groups}"
        )

    # Validate channel
    valid_channels = [c.value for c in NotificationChannel]
    if request.channel.lower() not in valid_channels:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid channel. Must be one of: {valid_channels}"
        )

    # Update preference
    preference = await notification_preference_service.set_user_group_preference(
        db=db,
        user_id=current_user.id,
        group=request.event_group,
        channel=request.channel,
        enabled=request.enabled
    )

    log.info(
        "User updated event group preference",
        user_id=current_user.id,
        username=current_user.username,
        group=request.event_group,
        channel=request.channel,
        enabled=request.enabled
    )

    return {
        "success": True,
        "group": request.event_group,
        "channel": request.channel,
        "enabled": request.enabled
    }


@limiter.limit(RateLimits.DATA_READ)  # 1000/hour
@router.get("/event-groups/metadata", response_model=List[EventGroupInfo])
async def get_event_groups_metadata(
    request: Request,
    current_user: models.User = PermissionDep,
):
    """
    Get metadata for all available event groups.

    This endpoint returns group names and descriptions for UI display
    without fetching user-specific preferences.
    """
    groups = []
    for group in NotificationEventGroup:
        labels = EVENT_GROUP_LABELS.get(group, {})
        groups.append(EventGroupInfo(
            id=group.value,
            name_en=labels.get("en", group.value.title()),
            name_vi=labels.get("vi", group.value.title()),
            description_en=labels.get("description_en", ""),
            description_vi=labels.get("description_vi", "")
        ))

    return groups