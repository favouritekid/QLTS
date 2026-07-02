# app/models/sms/consult_link.py
"""
SMS consult link (Phase 2 §16.4) — link tư vấn 1-1 officer gửi lead (NGOÀI
campaign). Officer tạo → sinh short code (bearer) → gửi tay/Zalo cho lead →
lead vào landing 2 tầng → dwell đo về CÙNG `contact_id` (khóa thống nhất với
campaign). Chỉ lưu `token_hash` (HMAC), KHÔNG raw code.

MVP (P2-Q1 chốt): link luôn trỏ danh mục ĐẦY ĐỦ (`landing_type=qlts_hosted`),
officer KHÔNG chọn ngành riêng. Consult 1-1 KHÔNG tự cấp consent marketing —
contact tạo từ lead giữ `marketing_consent_status='unknown'` (§16.5).
Xem `Documents/SMS_MARKETING_MODULE_DESIGN.md` §16.4.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    DateTime, ForeignKey, Index, Integer, String, text,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.models.base import Base


class SmsConsultLink(Base):
    """Link tư vấn officer↔lead — resolve `/r/{code}` như recipient (nhánh 2)."""

    __tablename__ = "sms_consult_link"

    __table_args__ = (
        # token_hash phải UNIQUE (resolve /r/{code}); partial để an toàn nếu
        # tương lai có hàng token NULL (hiện luôn set). hex 64 [0-9a-f].
        Index(
            "uq_sms_consult_link_token_hash",
            "token_hash",
            unique=True,
            postgresql_where=text("token_hash IS NOT NULL"),
        ),
        Index("ix_sms_consult_link_lead_id", "lead_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lead_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("lead.id", ondelete="CASCADE"),
        nullable=False,
        comment="lead officer tạo link tư vấn cho",
    )
    contact_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sms_contact.id", ondelete="CASCADE"),
        nullable=False, index=True,
        comment="contact match/tạo từ phone lead — khóa thống nhất interest",
    )
    created_by_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True, index=True,
        comment="officer tạo link (SET NULL nếu user xoá — giữ lịch sử)",
    )
    token_hash: Mapped[str] = mapped_column(
        String(64), nullable=False,
        comment="HMAC-SHA256(code, SMS_TOKEN_HASH_SECRET); resolve /r/{code}",
    )
    landing_type: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="qlts_hosted",
        comment="MVP luôn qlts_hosted (danh mục đầy đủ)",
    )
    landing_url: Mapped[Optional[str]] = mapped_column(
        String(1024), nullable=True,
        comment="external (DEFER) — MVP NULL, resolve → /lp/{code} nội bộ",
    )

    # --- Click denormalize (bot tách khỏi human) — đối xứng recipient ---
    raw_click_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0",
    )
    human_click_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0",
    )
    first_human_clicked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    last_human_clicked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
        comment="NULL = không hết hạn (link tư vấn cá nhân)",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )

    def __repr__(self) -> str:
        return (
            f"<SmsConsultLink {self.id} lead={self.lead_id} "
            f"contact={self.contact_id} by={self.created_by_id}>"
        )
