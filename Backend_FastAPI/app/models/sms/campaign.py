# app/models/sms/campaign.py
"""
SMS campaign — đợt gửi quảng cáo. Build sinh snapshot recipient theo
`build_revision`. Gate export fail-closed: consent + DNC + opt-out-channel
attestation đều phải khớp `build_revision` hiện tại.
Status: draft → ready → exported → handed_off → closed (KHÔNG có
sent/delivered vì QLTS không nhận DLR).
Xem `Documents/SMS_MARKETING_MODULE_DESIGN.md` §4.6.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    CheckConstraint, DateTime, ForeignKey, Integer, String, Text,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.models.base import Base


class SmsCampaign(Base):
    """Đợt SMS quảng cáo tuyển sinh (Phase 1 luôn là advertising → [QC])."""

    __tablename__ = "sms_campaign"

    __table_args__ = (
        CheckConstraint(
            "status IN ('draft','ready','exported','handed_off','closed')",
            name="chk_sms_campaign_status",
        ),
        CheckConstraint(
            "landing_type IN ('qlts_hosted','external')",
            name="chk_sms_campaign_landing_type",
        ),
        CheckConstraint("build_revision >= 0", name="chk_sms_campaign_build_revision"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    code: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="draft", server_default="draft",
    )
    frequency_cap_days: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True,
        comment="NULL = dùng SMS_FREQUENCY_CAP_DAYS mặc định",
    )
    sms_template: Mapped[str] = mapped_column(
        Text, nullable=False, comment="chứa {name}/{full_name}/{link}",
    )

    # --- Landing (§19) ---
    landing_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="qlts_hosted",
        server_default="qlts_hosted",
    )
    landing_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    landing_headline: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    landing_body: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, comment="plain text; KHÔNG render HTML (XSS)",
    )
    landing_cta_label: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    landing_cta_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # --- Build revision + link lifecycle ---
    build_revision: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0",
        comment="tăng sau mỗi build",
    )
    link_expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    optout_instruction_snapshot: Mapped[Optional[str]] = mapped_column(
        String(160), nullable=True,
        comment="hướng dẫn từ chối qua SMS/điện thoại đã chèn vào tin cuối",
    )

    # --- Attestation: consent (khớp build_revision) ---
    consent_checked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    consent_checked_by_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True,
    )
    consent_reference: Mapped[Optional[str]] = mapped_column(
        String(512), nullable=True,
    )
    consent_checked_build_revision: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True,
    )

    # --- Attestation: DNC ---
    dnc_checked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    dnc_checked_by_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True,
    )
    dnc_reference: Mapped[Optional[str]] = mapped_column(
        String(512), nullable=True, comment="nguồn/case/report đối soát thực tế",
    )
    dnc_checked_build_revision: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True,
    )

    # --- Attestation: opt-out channel (SMS/điện thoại đang hoạt động) ---
    optout_channel_checked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    optout_channel_checked_by_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True,
    )
    optout_channel_reference: Mapped[Optional[str]] = mapped_column(
        String(512), nullable=True,
    )
    optout_channel_checked_build_revision: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True,
    )

    created_by_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        server_default=func.now(), onupdate=func.now(),
    )
    handed_off_marked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    def __repr__(self) -> str:
        return f"<SmsCampaign {self.id} {self.code} rev={self.build_revision}>"
