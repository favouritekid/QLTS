# app/models/notification.py
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from .base import Base


class Notification(Base):
    """
    Model for user notifications.
    Supports real-time notifications via WebSocket.
    """

    __tablename__ = "notification"

    id = Column(Integer, primary_key=True, index=True)

    # User who receives the notification
    user_id = Column(Integer, ForeignKey("user.id"), nullable=False, index=True)

    # Notification type: info, success, warning, error, admin_update, system
    type = Column(String(50), nullable=False, default="info", index=True)

    # Title of notification
    title = Column(String(255), nullable=False)

    # Message content
    message = Column(Text, nullable=False)

    # Optional link to navigate to
    link = Column(String(512), nullable=True)

    # Additional data in JSON format
    data = Column(JSON, nullable=True)

    # Read status
    is_read = Column(Boolean, nullable=False, default=False, index=True)

    # Timestamps
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True
    )
    read_at = Column(DateTime(timezone=True), nullable=True)

    # Relationship
    # ✅ TASK 6.1: Updated to use back_populates (explicit bidirectional relationship)
    user = relationship("User", back_populates="notifications")

    def __repr__(self) -> str:
        return f"<Notification {self.id}: {self.title} for user {self.user_id}>"


class NotificationRule(Base):
    """
    ✅ PHASE 2.1: Model for notification rules (visual management).

    Allows administrators to manage notification configurations through UI
    instead of hardcoding them in the registry.

    Fields:
        event: SystemEvents enum value (e.g., "LEAD_ASSIGNED")
        title_template: Template string with {placeholders} (e.g., "Lead assigned: {lead_name}")
        message_template: Message template with {placeholders}
        notification_type: Severity level (info, success, warning, error)
        link_template: Optional link template (e.g., "/leads/{lead_id}")
        channels: JSON array of delivery channels ["browser", "email", "sms"]
        recipient_config: JSON object defining resolver {resolver_type, params}
        condition: Optional JSON object for activation conditions
        enabled: Whether this rule is active

    Example recipient_config:
        {
            "resolver_type": "specific_user",
            "params": {"user_field": "officer_id"}
        }
        {
            "resolver_type": "all_users",
            "params": {"exclude_actor": true}
        }
    """

    __tablename__ = "notification_rule"

    id = Column(Integer, primary_key=True, index=True)

    # Event trigger (from SystemEvents enum)
    event = Column(String(100), nullable=False, index=True,
                   comment="SystemEvents enum value (e.g., LEAD_ASSIGNED)")

    # Notification content templates
    title_template = Column(String(255), nullable=False,
                           comment="Title template with {placeholders}")
    message_template = Column(Text, nullable=False,
                             comment="Message template with {placeholders}")
    notification_type = Column(String(20), nullable=False, default="info",
                              comment="Severity: info, success, warning, error")
    link_template = Column(String(512), nullable=True,
                          comment="Optional link template (e.g., /leads/{lead_id})")

    # Delivery configuration
    channels = Column(JSON, nullable=False, default=["browser"],
                     comment="Delivery channels: [\"browser\", \"email\", \"sms\"]")

    # Recipient resolution configuration
    recipient_config = Column(JSON, nullable=False,
                             comment="Resolver config: {resolver_type, params}")

    # Optional activation conditions
    condition = Column(JSON, nullable=True,
                      comment="Optional activation conditions")

    # Enable/disable flag
    enabled = Column(Boolean, nullable=False, default=True, index=True,
                    comment="Enable/disable this rule")

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(),
                       nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(),
                       onupdate=func.now(), nullable=False)

    def __repr__(self) -> str:
        return f"<NotificationRule {self.id}: {self.event} ({self.notification_type})>"
