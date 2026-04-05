# app/models/notification_consent.py
"""
Notification Consent — latest-state consent for external channel delivery.

Unique per (channel, source_type, source_id).
No consent record = no external send.
Phase B: latest-state only. Phase D: full history table.
"""
from sqlalchemy import (
    Column, Integer, String, Text, ForeignKey, DateTime, UniqueConstraint,
)
from sqlalchemy.sql import func

from .base import Base


class NotificationConsent(Base):
    __tablename__ = "notification_consent"

    id = Column(Integer, primary_key=True, index=True)

    # Channel + entity = unique consent
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

    # Contact info snapshot
    normalized_phone = Column(
        String(20), nullable=True,
        comment="Normalized phone for Zalo/SMS (e.g. 84901234567)",
    )
    normalized_email = Column(
        String(255), nullable=True,
        comment="Normalized email for external email delivery",
    )

    # Consent state
    consent_status = Column(
        String(20), nullable=False, default="granted",
        comment="granted or revoked",
    )
    consent_source = Column(
        String(50), nullable=False, default="manual",
        comment="How consent was obtained: manual, csv_import, system_seed",
    )
    granted_by = Column(
        Integer,
        ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True,
        comment="Admin/staff who recorded consent",
    )
    granted_at = Column(
        DateTime(timezone=True), nullable=True,
        comment="When consent was granted",
    )
    revoked_at = Column(
        DateTime(timezone=True), nullable=True,
        comment="When consent was revoked (latest revocation)",
    )
    notes = Column(
        Text, nullable=True,
        comment="Free-text notes about consent",
    )

    # Timestamps
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now(), nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("channel", "source_type", "source_id",
                         name="uq_consent_channel_source"),
    )

    def __repr__(self) -> str:
        return (
            f"<NotificationConsent id={self.id} channel={self.channel} "
            f"source={self.source_type}:{self.source_id} status={self.consent_status}>"
        )
