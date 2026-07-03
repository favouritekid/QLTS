# app/models/sms/landing_session.py
"""
SMS landing session (Phase 2 §16.4) — 1 lượt xem landing để đo deep engagement.
Khóa thống nhất gắn interest = `contact_id`. Session token là bearer token →
CHỈ lưu `session_token_hash` = HMAC-SHA256(token, SMS_SESSION_TOKEN_HASH_SECRET),
KHÔNG lưu raw (chống giả lập engagement nếu DB/log lộ — P1-2 §16.7).

MVP đo-quan-tâm: source_type luôn 'campaign' (resolve qua recipient); trường
consult (`consult_link_id`) DEFER tới khi làm P2-3. IP luôn `ip_hash`, không thô.
Xem `Documents/SMS_MARKETING_MODULE_DESIGN.md` §16.4 + `SMS_PHASE2_PR7_SCOPE.md`.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean, DateTime, ForeignKey, Integer, String,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.models.base import Base


class SmsLandingSession(Base):
    """1 phiên xem landing (đo dwell qua heartbeat); token lưu hash."""

    __tablename__ = "sms_landing_session"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contact_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sms_contact.id", ondelete="CASCADE"),
        nullable=False, index=True,
        comment="khóa thống nhất gắn interest (campaign & consult resolve về contact)",
    )
    source_type: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="campaign",
        comment="campaign / consult (MVP chỉ campaign)",
    )
    recipient_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("sms_campaign_recipient.id", ondelete="SET NULL"),
        nullable=True, index=True,
        comment="nguồn campaign (NULL nếu consult)",
    )
    campaign_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("sms_campaign.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    consult_link_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("sms_consult_link.id", ondelete="SET NULL"),
        nullable=True, index=True,
        comment="nguồn consult officer (NULL nếu campaign) — P2-3",
    )
    session_token_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True,
        comment="HMAC-SHA256(session_token, SMS_SESSION_TOKEN_HASH_SECRET); no raw",
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
    last_heartbeat_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    ended_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    active_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0",
        comment="tổng dwell toàn phiên (cộng dồn từ heartbeat các trang)",
    )
    ip_hash: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True,
        comment="HMAC-SHA256(ip, SMS_IP_HASH_SECRET); KHÔNG lưu IP thô",
    )
    user_agent: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    is_suspected_bot: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false",
    )

    def __repr__(self) -> str:
        return (
            f"<SmsLandingSession {self.id} contact={self.contact_id} "
            f"active={self.active_seconds}s bot={self.is_suspected_bot}>"
        )
