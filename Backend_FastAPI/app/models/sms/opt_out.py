# app/models/sms/opt_out.py
"""
SMS opt-out — latest global suppression theo phone_normalized (toàn cục).
KHÔNG phải consent history. Build và export đều loại số trong bảng này;
suppression xuất hiện sau khi file tạo nhưng trước bàn giao → batch
`invalidated` + build/export lại.
Xem `Documents/SMS_MARKETING_MODULE_DESIGN.md` §4.11.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    CheckConstraint, DateTime, ForeignKey, Integer, String, Text,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.models.base import Base
from app.utils.masking import mask_phone


class SmsOptOut(Base):
    """Số từ chối nhận tin — khóa toàn cục theo phone_normalized."""

    __tablename__ = "sms_opt_out"

    __table_args__ = (
        CheckConstraint(
            "source IN ('landing_optout','manual','sms_reply',"
            "'phone_call','external_suppression')",
            name="chk_sms_opt_out_source",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    phone_normalized: Mapped[str] = mapped_column(
        String(20), nullable=False, unique=True, comment="khóa toàn cục",
    )
    source: Mapped[str] = mapped_column(
        String(30), nullable=False,
        comment="landing_optout/manual/sms_reply/phone_call/external_suppression",
    )
    campaign_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("sms_campaign.id", ondelete="SET NULL"),
        nullable=True, comment="campaign dẫn tới opt-out",
    )
    contact_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("sms_contact.id", ondelete="SET NULL"), nullable=True,
    )
    revoked_by_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True, comment="ai ghi (manual)",
    )
    source_reference: Mapped[Optional[str]] = mapped_column(
        String(512), nullable=True, comment="provider ticket/file/call reference",
    )
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        comment="thời điểm nhận từ chối/nguồn suppression",
    )
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )

    def __repr__(self) -> str:
        return f"<SmsOptOut {mask_phone(self.phone_normalized)} src={self.source}>"
