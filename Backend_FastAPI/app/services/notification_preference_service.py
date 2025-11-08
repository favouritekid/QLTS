# app/services/notification_preference_service.py
from datetime import datetime, time
from typing import Optional

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import models, schemas

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
