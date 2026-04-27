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
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from .. import database, models, schemas
from ..core.deps import CasbinAuth  # ✅ Phase 2.2: Use standard alias
from ..core.event_groups import (
    NotificationEventGroup,
    NotificationChannel,
    EVENT_GROUP_LABELS,
    DEFAULT_GROUP_CHANNELS,
)
from ..services import notification_preference_service

log = structlog.get_logger(__name__)
router = APIRouter(tags=["Notification Preferences"])


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
    zalo: bool
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
    current_user: models.User = CasbinAuth,
):
    """Get user's notification preferences."""
    # ✅ TRANSACTION FIX: Unpack tuple from service
    preference, callback = await notification_preference_service.get_user_preference(
        db, current_user.id
    )

    # ✅ Router commits transaction
    await db.commit()

    # ✅ Execute post-commit callback if exists
    if callback:
        await callback()

    return preference


@limiter.limit(RateLimits.DATA_WRITE)  # 200/hour
@router.put("/preferences", response_model=schemas.NotificationPreference)
async def update_notification_preferences(
    request: Request,
    preference_update: schemas.NotificationPreferenceUpdate,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = CasbinAuth,
):
    """Update user's notification preferences."""
    # ✅ TRANSACTION FIX: Unpack tuple from service
    preference, callback = await notification_preference_service.update_user_preference(
        db, current_user.id, preference_update
    )

    # ✅ Router commits transaction
    await db.commit()

    # ✅ Execute post-commit callback if exists
    if callback:
        await callback()

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
    current_user: models.User = CasbinAuth,
):
    """
    Get user's notification preferences organized by event groups.

    Returns:
        - List of available event groups with metadata
        - User's preference settings for each group/channel
    """
    # Get event group metadata. Only return groups present in
    # `DEFAULT_GROUP_CHANNELS` — broadcast-only groups (e.g.
    # `ORGANIZATION`) are excluded because they are not user-tunable
    # and were previously rendered as fully-checked tunable rows by
    # the settings UI (service used to fall back to `True` for missing
    # defaults). See `app/core/event_groups.py`.
    groups = []
    for group in NotificationEventGroup:
        if group not in DEFAULT_GROUP_CHANNELS:
            continue
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
    body: UpdateGroupPreferenceRequest,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = CasbinAuth,
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
    # Validate event group. Only groups in `DEFAULT_GROUP_CHANNELS` are
    # user-tunable; broadcast-only groups (e.g. `ORGANIZATION`) reject
    # PATCH so admin-side dispatching invariants stay intact.
    tunable_groups = {g.value for g in DEFAULT_GROUP_CHANNELS.keys()}
    if body.event_group.lower() not in tunable_groups:
        raise HTTPException(
            status_code=400,
            detail=(
                f"event_group '{body.event_group}' is not user-tunable. "
                f"Tunable groups: {sorted(tunable_groups)}"
            ),
        )

    # Validate channel
    valid_channels = [c.value for c in NotificationChannel]
    if body.channel.lower() not in valid_channels:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid channel. Must be one of: {valid_channels}"
        )

    # ✅ TRANSACTION FIX: Unpack tuple from service
    preference, callback = await notification_preference_service.set_user_group_preference(
        db=db,
        user_id=current_user.id,
        group=body.event_group,
        channel=body.channel,
        enabled=body.enabled
    )

    # ✅ Router commits transaction
    await db.commit()

    # ✅ Execute post-commit callback if exists
    if callback:
        await callback()

    log.info(
        "User updated event group preference",
        user_id=current_user.id,
        username=current_user.username,
        group=body.event_group,
        channel=body.channel,
        enabled=body.enabled
    )

    return {
        "success": True,
        "group": body.event_group,
        "channel": body.channel,
        "enabled": body.enabled
    }


@limiter.limit(RateLimits.DATA_READ)  # 1000/hour
@router.get("/event-groups/metadata", response_model=List[EventGroupInfo])
async def get_event_groups_metadata(
    request: Request,
    current_user: models.User = CasbinAuth,
):
    """
    Get metadata for all available event groups.

    This endpoint returns group names and descriptions for UI display
    without fetching user-specific preferences.
    """
    # Same exclusion as `/event-groups`: only return user-tunable
    # groups (`DEFAULT_GROUP_CHANNELS` keys). Broadcast-only groups
    # like `organization` would otherwise render as fake-tunable rows.
    groups = []
    for group in NotificationEventGroup:
        if group not in DEFAULT_GROUP_CHANNELS:
            continue
        labels = EVENT_GROUP_LABELS.get(group, {})
        groups.append(EventGroupInfo(
            id=group.value,
            name_en=labels.get("en", group.value.title()),
            name_vi=labels.get("vi", group.value.title()),
            description_en=labels.get("description_en", ""),
            description_vi=labels.get("description_vi", "")
        ))

    return groups