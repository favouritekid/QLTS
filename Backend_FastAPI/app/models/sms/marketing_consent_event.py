# app/models/sms/marketing_consent_event.py
"""
SMS marketing consent event — ledger BẤT BIẾN (append-only). API không
UPDATE/DELETE. Latest-state trên `sms_contact` chỉ là projection để lọc
nhanh; service cập nhật projection + append event trong cùng transaction.
Re-import KHÔNG được biến `unknown` thành `granted` nếu thiếu đủ
disclosure/proof/time.
Xem `Documents/SMS_MARKETING_MODULE_DESIGN.md` §4.12.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger, CheckConstraint, DateTime, ForeignKey, Integer, String,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.models.base import Base


class SmsMarketingConsentEvent(Base):
    """Ledger consent marketing (granted/revoked) — append-only, có proof."""

    __tablename__ = "sms_marketing_consent_event"

    __table_args__ = (
        CheckConstraint(
            "event_type IN ('granted','revoked')",
            name="chk_sms_consent_event_type",
        ),
        CheckConstraint(
            "basis IN ('explicit_form','signed_form','recorded_call','imported_proof')",
            name="chk_sms_consent_event_basis",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    contact_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sms_contact.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    phone_normalized_snapshot: Mapped[str] = mapped_column(
        String(20), nullable=False,
        comment="bằng chứng vẫn đọc được nếu contact đổi/xóa",
    )
    event_type: Mapped[str] = mapped_column(String(20), nullable=False)
    basis: Mapped[str] = mapped_column(
        String(30), nullable=False,
        comment="explicit_form / signed_form / recorded_call / imported_proof",
    )
    disclosure_version: Mapped[str] = mapped_column(
        String(50), nullable=False, comment="nội dung đồng ý áp dụng",
    )
    proof_reference: Mapped[str] = mapped_column(
        String(512), nullable=False,
        comment="tham chiếu artifact bên ngoài hoặc object private",
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, comment="thời điểm sự kiện thực",
    )
    recorded_by_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True,
    )
    import_batch_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("sms_contact_import_batch.id", ondelete="SET NULL"),
        nullable=True,
    )
    metadata_json: Mapped[Optional[dict]] = mapped_column(
        JSONB, nullable=True,
        comment="metadata tối thiểu, không chứa secret/PII thừa",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )

    def __repr__(self) -> str:
        return (
            f"<SmsMarketingConsentEvent {self.id} contact={self.contact_id} "
            f"{self.event_type}>"
        )
