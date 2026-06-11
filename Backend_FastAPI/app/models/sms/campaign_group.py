# app/models/sms/campaign_group.py
"""SMS campaign ↔ contact_group (nhóm được chọn cho campaign). §4.7"""
from datetime import datetime

from sqlalchemy import (
    DateTime, ForeignKey, Integer, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.models.base import Base


class SmsCampaignGroup(Base):
    """Nhóm được chọn vào 1 campaign. UNIQUE (campaign_id, group_id)."""

    __tablename__ = "sms_campaign_group"

    __table_args__ = (
        UniqueConstraint(
            "campaign_id", "group_id", name="uq_sms_campaign_group",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    campaign_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sms_campaign.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    group_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sms_contact_group.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )

    def __repr__(self) -> str:
        return f"<SmsCampaignGroup campaign={self.campaign_id} group={self.group_id}>"
