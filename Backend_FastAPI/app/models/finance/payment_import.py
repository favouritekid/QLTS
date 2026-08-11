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
    CheckConstraint, DateTime, ForeignKey, Index, Integer, Numeric, String,
    Text, UniqueConstraint, func, text,
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
    """Trục KIỂM: đọc/đối chiếu dòng ra kết quả dùng được không.

    Không đổi sau bước xem trước. Số phận ở bước ghi tiền nằm ở trục thứ hai
    (:class:`PaymentImportCommitStatusEnum`) — trộn hai thứ vào một cột là lỗi
    của bản trước, và nó đẻ ra cả một dòng "đã ghi tiền" vẫn nằm trong tập chọn
    lại, lẫn một bộ đếm cộng dồn theo số lần thử.
    """
    matched = "matched"        # khớp sạch
    warned = "warned"          # khớp nhưng có cảnh báo (lệch tên/tràn đợt/nghi trùng)
    error = "error"            # KHÔNG dùng được (không khớp / vượt tổng / sai định dạng)


class PaymentImportCommitStatusEnum(str, enum.Enum):
    """Trục GHI: số phận của dòng ở bước ghi tiền.

    ``committed`` là quyền quyết định việc KHÔNG thử lại. Khoá idempotency của
    ``Payment`` chỉ là hàng rào phụ: nó chặn theo (lô, dòng, HOÁ ĐƠN) nên không
    chặn được phần tiền rơi sang một đợt khác khi đợt cũ đã hết dư.
    """
    pending = "pending"        # chưa thử ghi, hoặc thử rồi bị hoãn
    duplicate_review_required = "duplicate_review_required"  # hàng rào giữ lại
    committed = "committed"    # đã ghi, có payment_ids
    failed = "failed"          # đã thử và hỏng ở bước ghi
    #: Dòng hỏng từ khâu đọc — KHÔNG có gì để ghi. Tách riêng khỏi ``pending``
    #: (xếp vào đó là nói nó đang chờ) và khỏi ``failed`` (xếp vào đó là đổ lỗi
    #: cho bước ghi, thứ chưa hề chạm tới nó).
    not_applicable = "not_applicable"


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
        # Idempotency tại DB: tối đa 1 batch CÒN HIỆU LỰC (preview/committed) cho mỗi
        # file → chống re-import + double-commit cùng file (kể cả 2 upload race).
        # 'void' thoát ràng buộc nên đảo batch sai rồi import lại được.
        Index(
            "uq_payment_import_batch_active_file",
            "file_sha256",
            unique=True,
            postgresql_where=text("status <> 'void'"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # Cấp batch (kế toán chọn khi import — không có trên từng dòng file)
    academic_year: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    semester_no: Mapped[int] = mapped_column(Integer, nullable=False)

    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    row_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0")
    matched_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0")
    warned_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0")
    failed_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0")
    # ── Họ đếm thứ hai: trục GHI. Tách khỏi ba cột trên (trục KIỂM) vì trộn
    # chúng là đếm một dòng hai lần — lô #5 trên máy dev có đúng một dòng mà sổ
    # ghi `warned_count=1` cộng `failed_count=1`. Mỗi họ tự cộng bằng
    # `row_count`; cả hai đều là PROJECTION, đếm lại từ trạng thái dòng thực tế
    # sau mỗi lượt, không cộng dồn theo số lần thử.
    committed_row_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0",
        comment="Số dòng đã ghi được tiền",
    )
    review_required_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0",
        comment="Số dòng bị hàng rào nghi trùng giữ lại, đang chờ xác nhận",
    )
    commit_failed_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0",
        comment="Số dòng đã thử ghi và hỏng",
    )
    not_applicable_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0",
        comment="Số dòng hỏng từ khâu đọc — không có gì để ghi",
    )
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
        default=lambda: datetime.now(timezone.utc), server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc), server_default=func.now(),
    )
    committed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True)
    voided_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True)
    void_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    rows: Mapped[List["PaymentImportRow"]] = relationship(
        "PaymentImportRow", back_populates="batch",
        cascade="all, delete-orphan",
        # lazy mặc định (select) — KHÔNG eager: list batch không kéo hết dòng của
        # mọi batch; chỉ selectinload(rows) trong query xem chi tiết 1 batch.
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
            "validation_status IN ('matched', 'warned', 'error')",
            name="chk_payment_import_row_validation_status",
        ),
        CheckConstraint(
            "commit_status IN ('pending', 'duplicate_review_required', "
            "'committed', 'failed', 'not_applicable')",
            name="chk_payment_import_row_commit_status",
        ),
        # Bảng chân trị ở tầng cơ sở dữ liệu, không chỉ trong tài liệu: dòng
        # hỏng-từ-khâu-đọc thì KHÔNG có gì để ghi, và ngược lại.
        CheckConstraint(
            "(validation_status = 'error') = (commit_status = 'not_applicable')",
            name="chk_payment_import_row_two_axes",
        ),
        # `committed` ⟺ CÓ mã phiếu. Hai chiều, và cả hai đều quan trọng:
        #   → một dòng "đã ghi" mà không có mã phiếu là mất dấu tiền (không
        #     void được, không đối soát được);
        #   ← một dòng có mã phiếu mà chưa "committed" là tiền đã vào nhưng vẫn
        #     nằm trong tập chọn lại — đúng đường ghi hai lần.
        # Service có đặt hai thứ này trong cùng savepoint, nhưng một lần sửa
        # SQL lúc chữa dữ liệu thì không đi qua service.
        # `CASE` chứ không phải `AND` nối tiếp — cùng dạng biểu thức với backfill
        # của `imp2axis20260807`, và cùng một lý do PHÒNG THỦ. Đã đo trên PG16:
        # ở CHECK (một *expression*) PostgreSQL short-circuit trái→phải nên bản
        # `AND` không vỡ; chỗ nó KHÔNG hứa thứ tự là *qual*, và ở đó
        # `jsonb_array_length` gặp scalar vỡ thật (22023) — backfill đã dính.
        # Giữ `CASE` ở đây vì tài liệu không hứa gì, và vì biểu thức này đã bị
        # sao chép sang qual đúng một lần rồi. Số đo:
        # tests/services/test_payment_import_row_committed_check.py
        CheckConstraint(
            "(commit_status = 'committed') = "
            "(CASE "
            " WHEN payment_ids IS NULL THEN false "
            " WHEN jsonb_typeof(payment_ids) <> 'array' THEN false "
            " ELSE jsonb_array_length(payment_ids) > 0 "
            "END)",
            name="chk_payment_import_row_committed_has_payments",
        ),
        # "Chờ xác nhận trùng" chỉ có nghĩa với dòng CÓ cảnh báo.
        CheckConstraint(
            "commit_status <> 'duplicate_review_required' "
            "OR validation_status = 'warned'",
            name="chk_payment_import_row_review_needs_warn",
        ),
        # Chống trùng dòng (parser chạy lại/bug) → void & đối soát theo row_no rõ ràng.
        UniqueConstraint(
            "batch_id", "row_no", name="uq_payment_import_row_batch_rowno"
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

    #: Trục KIỂM — xem :class:`PaymentImportRowStatusEnum`.
    validation_status: Mapped[str] = mapped_column(String(12), nullable=False)
    #: Trục GHI — xem :class:`PaymentImportCommitStatusEnum`. Đây mới là thứ
    #: quyết định dòng có được thử lại hay không; ``validation_status`` không
    #: bao giờ trả lời câu hỏi đó.
    commit_status: Mapped[str] = mapped_column(
        String(28),
        nullable=False,
        default=PaymentImportCommitStatusEnum.pending.value,
        server_default="pending",
    )
    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(15, 2), nullable=True)
    payment_ids: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    #: Phiếu xác nhận nghi trùng do máy chủ cấp cho ĐÚNG dòng này, ở cuối lượt
    #: ghi vừa rồi. Giao diện gửi lại nguyên văn khi kế toán xác nhận. Cấp ở
    #: cuối lượt chứ không phải lúc dòng bị chặn: phiếu mang theo
    #: ``fee.duplicate_guard_version``, và mỗi dòng ghi được lại làm nó nhích —
    #: phiếu cấp sớm sẽ chết trước khi kế toán kịp nhìn thấy.
    duplicate_review_token: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )

    batch: Mapped["PaymentImportBatch"] = relationship(
        "PaymentImportBatch", back_populates="rows",
    )

    def __repr__(self) -> str:
        # HAI trục, không phải `self.status` (cột đã đổi tên). Một `__repr__`
        # đọc thuộc tính không tồn tại chỉ nổ khi ai đó log dòng ra — tức là
        # đúng lúc họ đang gỡ một lỗi khác.
        return (
            f"<PaymentImportRow b{self.batch_id}#{self.row_no}: "
            f"{self.validation_status}/{self.commit_status}>"
        )
