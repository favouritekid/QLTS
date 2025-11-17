# app/models/user_activity.py
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from .base import Base


class UserActivityLog(Base):
    """
    Model to track user activities and changes for audit purposes.
    Tracks who did what, when, and what changed.
    """

    __tablename__ = "user_activity_log"

    id = Column(Integer, primary_key=True, index=True)

    # User who performed the action
    actor_id = Column(Integer, ForeignKey("user.id"), nullable=True, index=True)

    # Target user (for user management actions)
    target_user_id = Column(Integer, ForeignKey("user.id"), nullable=True, index=True)

    # Action type: login, logout, create_user, update_user, delete_user, change_role, etc.
    action = Column(String(100), nullable=False, index=True)

    # Resource type: user, lead, organization, etc.
    resource_type = Column(String(50), nullable=False, index=True)

    # Resource ID
    resource_id = Column(Integer, nullable=True)

    # Description of the action
    description = Column(Text, nullable=True)

    # Changes made (JSON format for flexibility)
    # Example: {"old": {"role": "user"}, "new": {"role": "admin"}}
    changes = Column(JSON, nullable=True)

    # IP address
    ip_address = Column(String(45), nullable=True)

    # User agent
    user_agent = Column(String(256), nullable=True)

    # Timestamp (automatically set)
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True
    )

    # Relationships
    # ✅ TASK 6.1: Updated to use back_populates (explicit bidirectional relationship)
    actor = relationship(
        "User",
        foreign_keys=[actor_id],
        back_populates="activities_performed"
    )
    target_user = relationship(
        "User",
        foreign_keys=[target_user_id],
        back_populates="activities_received"
    )

    def __repr__(self) -> str:
        return f"<UserActivityLog {self.action} by user {self.actor_id} at {self.created_at}>"
