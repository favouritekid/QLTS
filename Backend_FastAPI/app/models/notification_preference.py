# app/models/notification_preference.py
from sqlalchemy import Boolean, Column, ForeignKey, Integer, JSON, String, Time
from sqlalchemy.orm import relationship

from .base import Base


class NotificationPreference(Base):
    """
    User notification preferences.
    Controls how and when users receive notifications.
    """

    __tablename__ = "notification_preference"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("user.id"), unique=True, nullable=False, index=True)

    # Global settings
    email_enabled = Column(Boolean, nullable=False, default=True)
    sound_enabled = Column(Boolean, nullable=False, default=True)
    browser_enabled = Column(Boolean, nullable=False, default=True)
    zalo_enabled = Column(Boolean, nullable=False, default=False,
                          comment="Zalo ZNS channel — disabled by default until user opts in")

    # Email digest preferences
    email_digest = Column(
        String(20), nullable=False, default="instant"
    )  # instant, daily, weekly, disabled

    # Notification type preferences (JSON)
    # {
    #   "admin_update": {"enabled": true, "email": true, "sound": true},
    #   "new_lead": {"enabled": true, "email": true, "sound": true},
    #   "system": {"enabled": true, "email": false, "sound": false}
    # }
    type_preferences = Column(JSON, nullable=True, default=dict)

    # Quiet hours (do not send notifications during these hours)
    quiet_hours_enabled = Column(Boolean, nullable=False, default=False)
    quiet_hours_start = Column(Time, nullable=True)  # e.g., 22:00
    quiet_hours_end = Column(Time, nullable=True)  # e.g., 08:00

    # Relationships
    # ✅ TASK 6.1: Updated to use back_populates (explicit bidirectional relationship)
    user = relationship("User", back_populates="notification_preference")

    def get_type_preference(self, notification_type: str) -> dict:
        """Get preference for a specific notification type."""
        if not self.type_preferences:
            # Default: all enabled
            return {"enabled": True, "email": True, "sound": True}

        return self.type_preferences.get(
            notification_type, {"enabled": True, "email": True, "sound": True}
        )

    def is_notification_allowed(self, notification_type: str) -> bool:
        """Check if notification type is enabled."""
        pref = self.get_type_preference(notification_type)
        return pref.get("enabled", True)

    def is_email_allowed(self, notification_type: str) -> bool:
        """Check if email notification is allowed for this type."""
        if not self.email_enabled:
            return False
        pref = self.get_type_preference(notification_type)
        return pref.get("email", True)

    def is_sound_allowed(self, notification_type: str) -> bool:
        """Check if sound notification is allowed for this type."""
        if not self.sound_enabled:
            return False
        pref = self.get_type_preference(notification_type)
        return pref.get("sound", True)
