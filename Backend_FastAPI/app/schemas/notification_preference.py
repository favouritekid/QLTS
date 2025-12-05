# app/schemas/notification_preference.py
from datetime import time
from typing import Dict, Optional

from pydantic import BaseModel, ConfigDict, Field


class NotificationTypePreference(BaseModel):
    """Preference for a specific notification type."""

    enabled: bool = True
    email: bool = True
    sound: bool = True


class NotificationPreferenceBase(BaseModel):
    """Base notification preference schema."""

    email_enabled: bool = True
    sound_enabled: bool = True
    browser_enabled: bool = True
    email_digest: str = Field(
        default="instant", pattern="^(instant|daily|weekly|disabled)$"
    )
    type_preferences: Optional[Dict[str, NotificationTypePreference]] = None
    quiet_hours_enabled: bool = False
    quiet_hours_start: Optional[time] = None
    quiet_hours_end: Optional[time] = None


class NotificationPreferenceCreate(NotificationPreferenceBase):
    """Schema for creating notification preferences."""

    user_id: int


class NotificationPreferenceUpdate(BaseModel):
    """Schema for updating notification preferences."""

    email_enabled: Optional[bool] = None
    sound_enabled: Optional[bool] = None
    browser_enabled: Optional[bool] = None
    email_digest: Optional[str] = Field(
        default=None, pattern="^(instant|daily|weekly|disabled)$"
    )
    type_preferences: Optional[Dict[str, dict]] = None
    quiet_hours_enabled: Optional[bool] = None
    quiet_hours_start: Optional[time] = None
    quiet_hours_end: Optional[time] = None


class NotificationPreference(NotificationPreferenceBase):
    """Schema for notification preference response."""

    id: int
    user_id: int

    model_config = ConfigDict(from_attributes=True)
