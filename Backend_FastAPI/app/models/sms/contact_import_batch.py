# app/models/sms/contact_import_batch.py
"""
SMS contact import batch — audit lô import vào nhóm + consent trail.
Bất biến count (anchor test PR-2):
  row_count = valid_count + invalid_count + duplicate_contact_count
  skipped_count = invalid_count + duplicate_contact_count
  added_member_count + existing_member_count = valid_count
  inserted_contact_count <= valid_count
Xem `Documents/SMS_MARKETING_MODULE_DESIGN.md` §4.4.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    CheckConstraint, DateTime, ForeignKey, Integer, String,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.models.base import Base


class SmsContactImportBatch(Base):
    """Lô import liên hệ vào 1 nhóm (counts + consent evidence)."""

    __tablename__ = "sms_contact_import_batch"

    __table_args__ = (
        CheckConstraint(
            "consent_basis IS NULL OR consent_basis IN "
            "('explicit_form','signed_form','recorded_call','imported_proof')",
            name="chk_sms_import_batch_consent_basis",
        ),
        # Count non-âm + 4 bất biến (docstring) enforce tại DB.
        CheckConstraint(
            "row_count >= 0 AND valid_count >= 0 AND invalid_count >= 0 "
            "AND duplicate_contact_count >= 0 AND existing_member_count >= 0 "
            "AND inserted_contact_count >= 0 AND added_member_count >= 0 "
            "AND skipped_count >= 0",
            name="chk_sms_import_batch_counts_nonneg",
        ),
        CheckConstraint(
            "row_count = valid_count + invalid_count + duplicate_contact_count",
            name="chk_sms_import_batch_row_total",
        ),
        CheckConstraint(
            "skipped_count = invalid_count + duplicate_contact_count",
            name="chk_sms_import_batch_skipped_total",
        ),
        CheckConstraint(
            "added_member_count + existing_member_count = valid_count",
            name="chk_sms_import_batch_member_total",
        ),
        CheckConstraint(
            "inserted_contact_count <= valid_count",
            name="chk_sms_import_batch_inserted_le_valid",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("sms_contact_group.id", ondelete="SET NULL"),
        nullable=True, index=True,
        comment="nhóm đích; SET NULL khi xóa group (giữ audit import)",
    )
    file_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    file_sha256: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    source_label: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # --- Consent evidence áp cho contact mới tạo từ lô (nếu đủ proof) ---
    consent_basis: Mapped[Optional[str]] = mapped_column(
        String(30), nullable=True,
        comment="explicit_form / signed_form / recorded_call / imported_proof",
    )
    consent_disclosure_version: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True, comment="bắt buộc nếu lô tạo consent event",
    )
    consent_proof_ref: Mapped[Optional[str]] = mapped_column(
        String(512), nullable=True, comment="bắt buộc nếu lô tạo consent event",
    )
    consent_obtained_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
        comment="bắt buộc nếu lô tạo consent event",
    )

    # --- Counts (set bởi service; bất biến trong docstring) ---
    row_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0",
    )
    valid_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0",
    )
    invalid_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0",
    )
    duplicate_contact_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0",
        comment="trùng phone trong CHÍNH file upload",
    )
    existing_member_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0",
    )
    inserted_contact_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0",
        comment="contact mới tạo (phone chưa từng có)",
    )
    added_member_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0",
    )
    skipped_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0",
    )

    uploaded_by_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )

    def __repr__(self) -> str:
        return (
            f"<SmsContactImportBatch {self.id} group={self.group_id} "
            f"rows={self.row_count}>"
        )
