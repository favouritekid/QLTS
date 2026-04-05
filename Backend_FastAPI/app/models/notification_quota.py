# app/models/notification_quota.py
"""
Phase D1: Notification Quota — per-channel/provider quota tracking.

Tracks daily/monthly quotas for external channels (Zalo ZNS, SMS).
Supports quota check before delivery and sync from provider responses.
"""
from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime, Date, UniqueConstraint, Index,
)
from sqlalchemy.sql import func

from .base import Base


class NotificationQuota(Base):
    __tablename__ = "notification_quota"

    id = Column(Integer, primary_key=True, index=True)

    channel = Column(
        String(20), nullable=False,
        comment="Channel: zalo, sms, email",
    )
    provider = Column(
        String(50), nullable=False, default="default",
        comment="Provider identifier (e.g., zalo_zns, twilio, ses)",
    )

    # Period tracking
    period = Column(
        String(20), nullable=False, default="daily",
        comment="Quota period: daily, monthly",
    )
    period_start = Column(
        Date, nullable=False,
        comment="Start date of the quota period",
    )

    # Quota values
    quota_limit = Column(
        Integer, nullable=False,
        comment="Maximum sends allowed in this period",
    )
    quota_used = Column(
        Integer, nullable=False, default=0, server_default="0",
        comment="Sends consumed in this period",
    )
    quota_remaining = Column(
        Integer, nullable=True,
        comment="Remaining sends (synced from provider when available)",
    )

    # Status
    blocked = Column(
        Boolean, nullable=False, default=False, server_default="false",
        comment="True if quota exhausted and channel blocked for this period",
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
        UniqueConstraint(
            "channel", "provider", "period", "period_start",
            name="uq_quota_channel_provider_period",
        ),
        Index("ix_quota_channel_period", "channel", "period_start"),
    )

    def __repr__(self) -> str:
        return (
            f"<NotificationQuota id={self.id} channel={self.channel} "
            f"provider={self.provider} period={self.period} "
            f"used={self.quota_used}/{self.quota_limit}>"
        )
