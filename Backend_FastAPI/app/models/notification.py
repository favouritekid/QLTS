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
    user = relationship("User", backref="notifications")

    def __repr__(self) -> str:
        return f"<Notification {self.id}: {self.title} for user {self.user_id}>"
