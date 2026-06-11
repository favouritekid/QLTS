# app/models/sms/click_event.py
"""
SMS click event — mỗi lần bấm /r/{code} ghi 1 row (gồm bot, giữ audit).
CTR chính = COUNT(DISTINCT recipient_id) WHERE is_suspected_bot=FALSE /
tổng recipient handed_off. Không lưu IP thô → ip_hash HMAC.
Xem `Documents/SMS_MARKETING_MODULE_DESIGN.md` §4.10.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean, DateTime, ForeignKey, Integer, String,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.models.base import Base


class SmsClickEvent(Base):
    """1 lượt click short-link (bot được flag, không tính CTR chính)."""

    __tablename__ = "sms_click_event"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    recipient_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sms_campaign_recipient.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    campaign_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sms_campaign.id", ondelete="CASCADE"),
        nullable=False, index=True, comment="denormalize query nhanh",
    )
    contact_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("sms_contact.id", ondelete="SET NULL"), nullable=True,
    )
    clicked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True,
    )
    ip_hash: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True,
        comment="HMAC-SHA256(ip, SMS_IP_HASH_SECRET); KHÔNG lưu IP thô/prefix",
    )
    user_agent: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    is_suspected_bot: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false",
    )
    bot_reason: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True,
        comment="known_scanner_ua / prefetch_head / instant_after_send",
    )

    def __repr__(self) -> str:
        return (
            f"<SmsClickEvent {self.id} recipient={self.recipient_id} "
            f"bot={self.is_suspected_bot}>"
        )
