# app/models/notification_delivery.py
"""
Notification Delivery — per-channel delivery tracking.

Every channel send (browser, email, zalo, sms) creates one row.
This is the source of truth for "was notification X delivered via channel Y?"

Phase B: tracks browser/email. Phase C adds zalo/sms with retry lifecycle.
"""
from sqlalchemy import (
    Column, Integer, String, Text, ForeignKey, DateTime, Index,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func

from .base import Base


class NotificationDelivery(Base):
    __tablename__ = "notification_delivery"

    id = Column(Integer, primary_key=True, index=True)

    # Link to inbox Notification row (nullable for external recipients)
    notification_id = Column(
        Integer,
        ForeignKey("notification.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="FK to Notification inbox row; NULL for external recipients",
    )

    # Event that triggered this delivery
    event = Column(
        String(100), nullable=False,
        comment="SystemEvents.value that triggered this delivery",
    )

    # Channel
    channel = Column(
        String(20), nullable=False,
        comment="Delivery channel: browser, email, zalo, sms",
    )

    # Recipient
    recipient_kind = Column(
        String(20), nullable=False, default="internal",
        comment="internal (has user_id) or external (has destination)",
    )
    user_id = Column(
        Integer,
        ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True,
        comment="Internal recipient user ID",
    )
    source_type = Column(
        String(50), nullable=True,
        comment="Business entity type: lead, admission_profile, collaborator, user",
    )
    source_id = Column(
        Integer, nullable=True,
        comment="Business entity ID",
    )
    destination = Column(
        String(255), nullable=True,
        comment="Normalized email/phone for external delivery",
    )

    # Status
    status = Column(
        String(32), nullable=False, default="queued",
        comment="queued, sent, failed, skipped",
    )
    error_reason = Column(
        Text, nullable=True,
        comment="Error details when status=failed or skip reason when status=skipped",
    )

    # Payload and provider
    payload_snapshot = Column(
        JSONB, nullable=True,
        comment="Snapshot of rendered content at send time",
    )
    provider_message_id = Column(
        String(128), nullable=True,
        comment="Provider message ID (for Zalo/SMS reconciliation in Phase C)",
    )
    dedupe_key = Column(
        String(255), nullable=True,
        comment="Deduplication key for tracing",
    )

    # Phase C0: Action-based execution tracking
    rule_id = Column(
        Integer,
        ForeignKey("notification_rule.id", ondelete="SET NULL"),
        nullable=True,
        comment="FK to the rule that triggered this delivery",
    )
    action_step = Column(
        Integer, nullable=True,
        comment="Step number from NotificationAction (1-based)",
    )
    template_code = Column(
        String(100), nullable=True,
        comment="Template code used for this delivery",
    )

    # Phase C1: Worker execution scheduling
    scheduled_for = Column(
        DateTime(timezone=True), nullable=True,
        comment="When this delivery should execute (NULL = immediate)",
    )
    attempt_count = Column(
        Integer, nullable=False, default=0, server_default="0",
        comment="Number of execution attempts",
    )
    last_attempt_at = Column(
        DateTime(timezone=True), nullable=True,
        comment="When last execution attempt was made",
    )

    # Timestamps
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now(), nullable=False,
    )
    sent_at = Column(
        DateTime(timezone=True), nullable=True,
        comment="When delivery was confirmed sent",
    )

    __table_args__ = (
        Index("ix_delivery_channel_status_created", "channel", "status", created_at.desc()),
        Index("ix_delivery_event_created", "event", created_at.desc()),
        Index("ix_delivery_user_created", "user_id", created_at.desc()),
        Index("ix_delivery_source", "source_type", "source_id", created_at.desc()),
        # NOTE: ix_delivery_worker_poll is a DB-only partial index created in
        # migration zz5f6g7h8i9j0 (WHERE status='queued'). Not declarable in
        # SQLAlchemy model without postgresql_where which would require importing
        # the column expression at class-definition time. The index exists in DB
        # and is used by the Celery worker polling query.
    )

    def __repr__(self) -> str:
        return (
            f"<NotificationDelivery id={self.id} event={self.event} "
            f"channel={self.channel} status={self.status}>"
        )
