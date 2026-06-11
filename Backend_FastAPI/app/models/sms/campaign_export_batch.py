# app/models/sms/campaign_export_batch.py
"""
SMS campaign export batch — 1 file Excel/nhà mạng/revision, có lifecycle
idempotent. File lưu NGOÀI public webroot. UNIQUE (campaign, revision,
carrier) → gọi export lại cùng revision trả batch generated hiện có.
Xem `Documents/SMS_MARKETING_MODULE_DESIGN.md` §4.9 / §8.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger, CheckConstraint, DateTime, ForeignKey, Integer, String, Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class SmsCampaignExportBatch(Base):
    """File export per nhà mạng + trạng thái vòng đời."""

    __tablename__ = "sms_campaign_export_batch"

    __table_args__ = (
        UniqueConstraint(
            "campaign_id", "build_revision", "carrier_bucket",
            name="uq_sms_export_campaign_rev_carrier",
        ),
        CheckConstraint(
            "status IN ('pending','generated','handed_off',"
            "'failed','purged','invalidated')",
            name="chk_sms_export_batch_status",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    campaign_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sms_campaign.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    build_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    group_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("sms_contact_group.id", ondelete="SET NULL"),
        nullable=True, comment="NULL nếu export gộp nhiều nhóm (B2)",
    )
    group_name_snapshot: Mapped[Optional[str]] = mapped_column(
        String(200), nullable=True, comment="nhãn filename (B2)",
    )
    carrier_bucket: Mapped[str] = mapped_column(String(20), nullable=False)
    recipient_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0",
    )
    file_name: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True,
        comment="{Nhóm}-{Campaign}-{NhàMạng}.xlsx (set khi generated)",
    )
    storage_path: Mapped[Optional[str]] = mapped_column(
        String(512), nullable=True, comment="NGOÀI public webroot (§11.7)",
    )
    file_sha256: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    file_size_bytes: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    purged_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default="pending",
    )
    failure_reason: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, comment="lỗi tạo/ghi file đã sanitize",
    )
    invalidated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    generated_by_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True,
    )
    generated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    marked_handed_off_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
        comment="bấm 'Đã bàn giao' per nhà mạng",
    )

    def __repr__(self) -> str:
        return (
            f"<SmsCampaignExportBatch {self.id} campaign={self.campaign_id} "
            f"{self.carrier_bucket} status={self.status}>"
        )
