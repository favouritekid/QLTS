# app/services/notification_preference_service.py
"""
Notification Preference Service - Manages user notification preferences.

Complies with Pattern A: Router → Service → Repository
"""
from datetime import datetime
from typing import Callable, Dict, List, Optional, Tuple

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app import models, schemas
from app.core.event_groups import NotificationEventGroup, DEFAULT_GROUP_CHANNELS, NotificationChannel
from app.repositories import NotificationPreferenceRepository

log = structlog.get_logger(__name__)


async def get_user_preference(
    db: AsyncSession, user_id: int
) -> Tuple[models.NotificationPreference, Optional[Callable]]:
    """
    Get notification preference for a user.
    Creates default preference if not exists.

    Returns:
        Tuple of (preference, post_commit_callback)
        Router is responsible for calling db.commit() then callback().
    """
    repo = NotificationPreferenceRepository(db)

    # Check if preference exists
    preference = await repo.get_by_user_id(user_id)

    if not preference:
        log.info("Creating default notification preference", user_id=user_id)
        preference = await repo.get_or_create(user_id)

        # ✅ TRANSACTION FIX: Flush only, let router commit
        async def _post_commit():
            """Execute after router commits the transaction."""
            log.info("Default notification preference created", user_id=user_id)

        return preference, _post_commit

    return preference, None


async def update_user_preference(
    db: AsyncSession,
    user_id: int,
    preference_update: schemas.NotificationPreferenceUpdate,
) -> Tuple[models.NotificationPreference, Callable]:
    """
    Update user notification preferences.
    """
    repo = NotificationPreferenceRepository(db)
    
    # Get or create
    preference = await repo.get_or_create(user_id)

    # Update fields
    update_data = preference_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(preference, field, value)

    await db.flush()
    await db.refresh(preference)

    async def _post_commit():
        """Execute after router commits the transaction."""
        log.info(
            "Updated notification preferences",
            user_id=user_id,
            updated_fields=list(update_data.keys()),
        )

    return preference, _post_commit


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
    """
    repo = NotificationPreferenceRepository(db)
    preference = await repo.get_or_create(user_id)

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


def get_group_preference(
    type_preferences: Optional[Dict],
    group: str,
    channel: str
) -> bool:
    """
    Get the preference setting for a specific group and channel.
    """
    if not type_preferences:
        return True

    group_prefs = type_preferences.get(group.lower())
    if not group_prefs:
        return True

    return group_prefs.get(channel.lower(), True)


async def get_user_group_preferences(
    db: AsyncSession,
    user_id: int
) -> Dict[str, Dict[str, bool]]:
    """
    Get all group preferences for a user.
    """
    repo = NotificationPreferenceRepository(db)
    preference = await repo.get_or_create(user_id)

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
) -> Tuple[models.NotificationPreference, Callable]:
    """
    Set a specific group/channel preference for a user.
    """
    repo = NotificationPreferenceRepository(db)
    preference = await repo.get_or_create(user_id)

    # Initialize type_preferences if None
    if preference.type_preferences is None:
        preference.type_preferences = {}

    # Ensure group exists
    group_key = group.lower()
    if group_key not in preference.type_preferences:
        preference.type_preferences[group_key] = {}

    # Set the channel preference
    preference.type_preferences[group_key][channel.lower()] = enabled

    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(preference, "type_preferences")

    await db.flush()
    await db.refresh(preference)

    async def _post_commit():
        """Execute after router commits the transaction."""
        log.info(
            "Updated group preference",
            user_id=user_id,
            group=group,
            channel=channel,
            enabled=enabled
        )

    return preference, _post_commit


async def filter_users_by_group(
    db: AsyncSession,
    user_ids: List[int],
    group: str,
    channel: str = "browser"
) -> List[int]:
    """
    Filter a list of users by their group/channel preferences.
    """
    if not user_ids:
        return []

    repo = NotificationPreferenceRepository(db)
    preferences = await repo.get_by_user_ids(user_ids)

    filtered_user_ids = []
    group_key = group.lower()
    channel_key = channel.lower()

    for user_id in user_ids:
        pref = preferences.get(user_id)

        if not pref:
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
    """
    repo = NotificationPreferenceRepository(db)
    return await repo.get_by_user_ids(user_ids)
