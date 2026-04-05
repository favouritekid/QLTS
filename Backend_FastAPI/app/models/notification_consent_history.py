# app/models/notification_consent_history.py
"""
Phase E1: Notification Consent History — immutable audit trail for consent changes.

Append-only table. Every grant/revoke action on NotificationConsent produces
one row here, capturing old_status -> new_status along with who performed it.
"""
from sqlalchemy import (
    Column, Integer, String, Text, ForeignKey, DateTime, Index,
)
from sqlalchemy.sql import func

from .base import Base


class NotificationConsentHistory(Base):
    __tablename__ = "notification_consent_history"

    id = Column(Integer, primary_key=True, index=True)

    # Link to the consent record (nullable: consent could be deleted)
    consent_id = Column(
        Integer,
        ForeignKey("notification_consent.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="FK to notification_consent (nullable if consent deleted)",
    )

    # Denormalized entity identifiers (always populated)
    channel = Column(
        String(20), nullable=False,
        comment="Channel: zalo, sms, email",
    )
    source_type = Column(
        String(50), nullable=False,
        comment="Entity type: lead, admission_profile, collaborator",
    )
    source_id = Column(
        Integer, nullable=False,
        comment="Entity ID",
    )

    # Action details
    action = Column(
        String(20), nullable=False,
        comment="Action: granted, revoked",
    )
    old_status = Column(
        String(20), nullable=True,
        comment="Previous consent_status (null for first grant)",
    )
    new_status = Column(
        String(20), nullable=False,
        comment="New consent_status after this action",
    )

    # Who performed the action
    performed_by = Column(
        Integer,
        ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True,
        comment="User who performed the action",
    )

    # Immutable timestamp
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )

    # M1: Declare indexes to match migration (prevents autogenerate drift)
    __table_args__ = (
        Index("ix_consent_history_source", "source_type", "source_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<NotificationConsentHistory id={self.id} consent_id={self.consent_id} "
            f"action={self.action} {self.old_status}->{self.new_status}>"
        )
