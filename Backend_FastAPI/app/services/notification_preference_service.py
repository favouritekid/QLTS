# app/services/notification_preference_service.py
"""
Notification Preference Service - Manages user notification preferences.

This service handles:
1. Getting/creating default preferences
2. Updating preferences
3. Checking quiet hours
4. Filtering users by group-based preferences (NEW)

Preference JSON Schema (type_preferences):
    {
        "lead": {
            "browser": true,
            "email": true,
            "sms": false
        },
        "finance": {
            "browser": false,
            "email": true
        }
    }

Rules:
- Group = key at level 1 (lowercase)
- Channel = key at level 2
- If user doesn't have a group → all channels default to True
- If user has group but missing channel → default to True
"""
from datetime import datetime, time
from typing import Dict, List, Optional

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import models, schemas
from ..core.event_groups import NotificationEventGroup, DEFAULT_GROUP_CHANNELS, NotificationChannel

log = structlog.get_logger(__name__)


async def get_user_preference(
    db: AsyncSession, user_id: int
) -> Optional[models.NotificationPreference]:
    """
    Get notification preference for a user.
    Creates default preference if not exists.
    """
    stmt = select(models.NotificationPreference).where(
        models.NotificationPreference.user_id == user_id
    )
    result = await db.execute(stmt)
    preference = result.scalar_one_or_none()

    # Create default preference if not exists
    if not preference:
        log.info("Creating default notification preference", user_id=user_id)
        preference = models.NotificationPreference(
            user_id=user_id,
            email_enabled=True,
            sound_enabled=True,
            browser_enabled=True,
            email_digest="instant",
            type_preferences={},
            quiet_hours_enabled=False,
        )
        db.add(preference)
        await db.commit()
        await db.refresh(preference)

    return preference


async def update_user_preference(
    db: AsyncSession,
    user_id: int,
    preference_update: schemas.NotificationPreferenceUpdate,
) -> models.NotificationPreference:
    """Update user notification preferences."""
    # Get or create preference
    preference = await get_user_preference(db, user_id)

    # Update fields
    update_data = preference_update.model_dump(exclude_unset=True)

    for field, value in update_data.items():
        setattr(preference, field, value)

    await db.commit()
    await db.refresh(preference)

    log.info(
        "Updated notification preferences",
        user_id=user_id,
        updated_fields=list(update_data.keys()),
    )

    return preference


async def is_quiet_hours(preference: models.NotificationPreference) -> bool:
    """Check if current time is within quiet hours."""
    if not preference.quiet_hours_enabled:
        return False

    if not preference.quiet_hours_start or not preference.quiet_hours_end:
        return False

    now = datetime.now().time()
    start = preference.quiet_hours_start
    end = preference.quiet_hours_end

    # Handle overnight quiet hours (e.g., 22:00 - 08:00)
    if start > end:
        return now >= start or now <= end
    else:
        return start <= now <= end


async def should_send_notification(
    db: AsyncSession, user_id: int, notification_type: str
) -> dict:
    """
    Check if notification should be sent based on user preferences.
    Returns dict with flags for different notification channels.
    """
    preference = await get_user_preference(db, user_id)

    # Check if in quiet hours
    in_quiet_hours = await is_quiet_hours(preference)

    # Get type-specific preferences
    type_allowed = preference.is_notification_allowed(notification_type)
    email_allowed = preference.is_email_allowed(notification_type)
    sound_allowed = preference.is_sound_allowed(notification_type)

    return {
        "create_notification": type_allowed and not in_quiet_hours,
        "send_email": email_allowed and not in_quiet_hours,
        "allow_sound": sound_allowed and not in_quiet_hours,
        "allow_browser": preference.browser_enabled and not in_quiet_hours,
        "in_quiet_hours": in_quiet_hours,
    }


# =============================================================================
# GROUP-BASED PREFERENCE FUNCTIONS (Event-Driven Architecture)
# =============================================================================

def get_group_preference(
    type_preferences: Optional[Dict],
    group: str,
    channel: str
) -> bool:
    """
    Get the preference setting for a specific group and channel.

    Args:
        type_preferences: User's type_preferences JSON (can be None or empty)
        group: The event group (e.g., "lead", "finance")
        channel: The channel (e.g., "browser", "email")

    Returns:
        True if the channel is enabled for this group, False otherwise.
        Default is True if group/channel not specified.
    """
    if not type_preferences:
        # No preferences set, use defaults (all enabled)
        return True

    group_prefs = type_preferences.get(group.lower())
    if not group_prefs:
        # Group not configured, default to True
        return True

    # Get channel preference, default to True if not set
    return group_prefs.get(channel.lower(), True)


async def get_user_group_preferences(
    db: AsyncSession,
    user_id: int
) -> Dict[str, Dict[str, bool]]:
    """
    Get all group preferences for a user.

    Returns a dictionary with all event groups and their channel settings.
    Merges user preferences with defaults.

    Args:
        db: Database session
        user_id: User ID

    Returns:
        Dict structure:
        {
            "lead": {"browser": True, "email": True, "sms": False},
            "finance": {"browser": True, "email": True, "sms": False},
            ...
        }
    """
    preference = await get_user_preference(db, user_id)

    result = {}
    for group in NotificationEventGroup:
        group_key = group.value.lower()

        # Start with defaults
        defaults = DEFAULT_GROUP_CHANNELS.get(group, {})
        channel_prefs = {
            channel.value: defaults.get(channel, True)
            for channel in NotificationChannel
        }

        # Override with user preferences if set
        if preference.type_preferences and group_key in preference.type_preferences:
            user_group_prefs = preference.type_preferences[group_key]
            for channel_key, enabled in user_group_prefs.items():
                if channel_key in channel_prefs:
                    channel_prefs[channel_key] = enabled

        result[group_key] = channel_prefs

    return result


async def set_user_group_preference(
    db: AsyncSession,
    user_id: int,
    group: str,
    channel: str,
    enabled: bool
) -> models.NotificationPreference:
    """
    Set a specific group/channel preference for a user.

    Args:
        db: Database session
        user_id: User ID
        group: Event group (e.g., "lead")
        channel: Channel (e.g., "browser")
        enabled: Whether to enable notifications

    Returns:
        Updated NotificationPreference
    """
    preference = await get_user_preference(db, user_id)

    # Initialize type_preferences if None
    if preference.type_preferences is None:
        preference.type_preferences = {}

    # Ensure group exists
    group_key = group.lower()
    if group_key not in preference.type_preferences:
        preference.type_preferences[group_key] = {}

    # Set the channel preference
    preference.type_preferences[group_key][channel.lower()] = enabled

    # Mark JSON as modified (SQLAlchemy needs this for JSON columns)
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(preference, "type_preferences")

    await db.commit()
    await db.refresh(preference)

    log.info(
        "Updated group preference",
        user_id=user_id,
        group=group,
        channel=channel,
        enabled=enabled
    )

    return preference


async def filter_users_by_group(
    db: AsyncSession,
    user_ids: List[int],
    group: str,
    channel: str = "browser"
) -> List[int]:
    """
    Filter a list of users by their group/channel preferences.

    This is the main function used by the notification dispatcher
    to filter out users who have disabled notifications for a group.

    Args:
        db: Database session
        user_ids: List of user IDs to filter
        group: Event group (e.g., "lead")
        channel: Channel to check (default: "browser")

    Returns:
        List of user IDs who have the notification enabled
    """
    if not user_ids:
        return []

    # Bulk fetch preferences for all users
    result = await db.execute(
        select(models.NotificationPreference)
        .where(models.NotificationPreference.user_id.in_(user_ids))
    )
    preferences = {pref.user_id: pref for pref in result.scalars().all()}

    filtered_user_ids = []
    group_key = group.lower()
    channel_key = channel.lower()

    for user_id in user_ids:
        pref = preferences.get(user_id)

        if not pref:
            # No preference record, use defaults (enabled)
            filtered_user_ids.append(user_id)
            continue

        # Check global channel toggle first
        if channel_key == "browser" and not pref.browser_enabled:
            continue
        if channel_key == "email" and not pref.email_enabled:
            continue
        if channel_key == "sound" and not pref.sound_enabled:
            continue

        # Check quiet hours
        if await is_quiet_hours(pref):
            continue

        # Check group-specific preference
        if get_group_preference(pref.type_preferences, group_key, channel_key):
            filtered_user_ids.append(user_id)

    log.info(
        "Filtered users by group preference",
        original_count=len(user_ids),
        filtered_count=len(filtered_user_ids),
        group=group,
        channel=channel
    )

    return filtered_user_ids


async def bulk_get_user_preferences(
    db: AsyncSession,
    user_ids: List[int]
) -> Dict[int, models.NotificationPreference]:
    """
    Bulk fetch preferences for multiple users.

    Args:
        db: Database session
        user_ids: List of user IDs

    Returns:
        Dict mapping user_id to NotificationPreference
    """
    if not user_ids:
        return {}

    result = await db.execute(
        select(models.NotificationPreference)
        .where(models.NotificationPreference.user_id.in_(user_ids))
    )

    return {pref.user_id: pref for pref in result.scalars().all()}
