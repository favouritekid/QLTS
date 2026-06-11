# app/models/sms/contact.py
"""
SMS contact — liên hệ bền vững, duy nhất toàn hệ thống theo
`phone_normalized`. Mang latest-state consent marketing (projection của
ledger `sms_marketing_consent_event`). Consent fail-closed: chỉ
`granted` + có proof hợp lệ mới đủ điều kiện build/export.
Xem `Documents/SMS_MARKETING_MODULE_DESIGN.md` §4.2.
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


class SmsContact(Base):
    """Liên hệ SMS — unique theo phone_normalized (số di động)."""

    __tablename__ = "sms_contact"

    __table_args__ = (
        CheckConstraint(
            "marketing_consent_status IN ('unknown','granted','revoked')",
            name="chk_sms_contact_consent_status",
        ),
        CheckConstraint(
            "marketing_consent_basis IS NULL OR marketing_consent_basis IN "
            "('explicit_form','signed_form','recorded_call','imported_proof')",
            name="chk_sms_contact_consent_basis",
        ),
        # Consent fail-closed: 'granted' BẮT BUỘC đủ 4 trường proof, KHÔNG rỗng
        # (length(btrim)>0 chặn cả NULL lẫn chuỗi rỗng/space).
        CheckConstraint(
            "marketing_consent_status <> 'granted' OR ("
            "marketing_consented_at IS NOT NULL "
            "AND marketing_consent_basis IS NOT NULL "
            "AND length(btrim(coalesce(marketing_consent_proof_ref,''))) > 0 "
            "AND length(btrim(coalesce(consent_disclosure_version,''))) > 0)",
            name="chk_sms_contact_granted_requires_proof",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    phone_raw: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True, comment="số gốc nhập",
    )
    phone_normalized: Mapped[str] = mapped_column(
        String(20), nullable=False, unique=True,
        comment="0xxxxxxxxx — duy nhất toàn hệ thống",
    )
    phone_international: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="84xxxxxxxxx (xuất Excel)",
    )
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source_label: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, comment="nguồn liên hệ",
    )

    # --- Latest-state consent marketing (projection của ledger) ---
    marketing_consent_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="unknown", server_default="unknown",
        comment="unknown / granted / revoked",
    )
    marketing_consented_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
        comment="thời điểm opt-in gần nhất",
    )
    marketing_consent_basis: Mapped[Optional[str]] = mapped_column(
        String(30), nullable=True,
        comment="explicit_form / signed_form / recorded_call / imported_proof",
    )
    marketing_consent_proof_ref: Mapped[Optional[str]] = mapped_column(
        String(512), nullable=True,
        comment="tham chiếu bằng chứng; KHÔNG chứa secret",
    )
    consent_disclosure_version: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True, comment="phiên bản câu chữ đã đồng ý",
    )

    last_handed_off_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
        comment="lần gần nhất số này thuộc batch đã bàn giao (frequency-cap proxy)",
    )

    created_by_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        server_default=func.now(), onupdate=func.now(),
    )

    def __repr__(self) -> str:
        return (
            f"<SmsContact {self.id} {mask_phone(self.phone_normalized)} "
            f"consent={self.marketing_consent_status}>"
        )
