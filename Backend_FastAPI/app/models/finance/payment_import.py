# app/models/finance/payment_import.py
"""
Payment Import models - Bulk payment verify via file import (BV).

Kế toán thu offline → import file tổng hợp → hệ thống tự xác minh (auto-verify)
hàng loạt. Luồng 2 pha: preview (dry-run, KHÔNG ghi tiền) → commit (auto-verify
từng dòng dưới khóa, re-validate). Maker-checker giữ: kế toán = maker, system_user
= checker.

Ref: Documents/BULK_PAYMENT_IMPORT_VERIFY_PLAN.md (DESIGN v2).
"""
import enum
from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import (
    CheckConstraint, DateTime, ForeignKey, Integer, Numeric, String, Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.user import User


class PaymentImportBatchStatusEnum(str, enum.Enum):
    """Import batch lifecycle."""
    preview = "preview"        # dry-run resolved, chưa ghi Payment
    committed = "committed"    # đã auto-verify các dòng MATCHED
    void = "void"              # đã đảo (rút lại) batch committed sai


class PaymentImportRowStatusEnum(str, enum.Enum):
    """Per-row outcome of resolve/validate."""
    matched = "matched"        # ghi được (có thể kèm warning)
    warned = "warned"          # ghi được + cảnh báo (lệch tên / tràn nhiều đợt / nghi trùng)
    error = "error"            # KHÔNG ghi (không khớp / vượt tổng / sai định dạng)


class PaymentImportBatch(Base):
    """A bulk payment-import lô.

    ``file_sha256`` chống re-import cùng file. Đếm ``matched/warned/failed`` cho
    đối soát. Trạng thái ``preview`` → ``committed`` → (``void`` nếu đảo).
    """
    __tablename__ = "payment_import_batch"
    __table_args__ = (
        CheckConstraint(
            "status IN ('preview', 'committed', 'void')",
            name="chk_payment_import_batch_status",
        ),
        CheckConstraint("semester_no >= 1", name="chk_payment_import_batch_semester"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # Cấp batch (kế toán chọn khi import — không có trên từng dòng file)
    academic_year: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    semester_no: Mapped[int] = mapped_column(Integer, nullable=False)

    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    matched_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    warned_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_amount: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), nullable=False, default=Decimal("0"), server_default="0",
        comment="Tổng tiền dự kiến/đã ghi (gốc học phí)",
    )

    status: Mapped[str] = mapped_column(
        String(20), nullable=False,
        default=PaymentImportBatchStatusEnum.preview.value,
        server_default="preview", index=True,
    )

    created_by_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True, index=True,
        comment="Kế toán import (maker)",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    committed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True)
    voided_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True)
    void_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    rows: Mapped[List["PaymentImportRow"]] = relationship(
        "PaymentImportRow", back_populates="batch",
        cascade="all, delete-orphan", lazy="selectin",
    )
    created_by: Mapped[Optional["User"]] = relationship("User")

    def __repr__(self) -> str:
        return (
            f"<PaymentImportBatch {self.id}: {self.status} "
            f"HK{self.semester_no}/{self.academic_year} rows={self.row_count}>"
        )


class PaymentImportRow(Base):
    """Một dòng của batch — audit + truy vết dòng → Payment đã tạo.

    ``raw`` giữ dữ liệu gốc của dòng (JSONB) để đối soát. ``payment_ids`` lưu các
    Payment auto-verify sinh ra (1 dòng có thể → N Payment khi phân bổ nhiều đợt),
    phục vụ void/đảo.
    """
    __tablename__ = "payment_import_row"
    __table_args__ = (
        CheckConstraint(
            "status IN ('matched', 'warned', 'error')",
            name="chk_payment_import_row_status",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("payment_import_batch.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    row_no: Mapped[int] = mapped_column(Integer, nullable=False)

    citizen_id: Mapped[Optional[str]] = mapped_column(String(12), nullable=True)
    raw: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    # Audit snapshot (plain int, không FK — giữ id kể cả khi hồ sơ đổi)
    resolved_profile_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    resolved_fee_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    status: Mapped[str] = mapped_column(String(12), nullable=False)
    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(15, 2), nullable=True)
    payment_ids: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)

    batch: Mapped["PaymentImportBatch"] = relationship(
        "PaymentImportBatch", back_populates="rows",
    )

    def __repr__(self) -> str:
        return f"<PaymentImportRow b{self.batch_id}#{self.row_no}: {self.status}>"
