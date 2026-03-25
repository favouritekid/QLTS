# app/models/tuition_discount_policy.py
"""
Tuition Discount Policy Model - Quản lý chính sách ưu đãi học phí.

Bảng này lưu trữ các chính sách ưu đãi học phí với khả năng:
- Định nghĩa loại ưu đãi (số tiền hoặc phần trăm)
- Giới hạn thời gian hiệu lực
- Xác định phạm vi áp dụng (ngành, chương trình, loại hình)
- Xác định đối tượng được hưởng (sinh viên ưu tiên, vùng miền, v.v.)
- Quy tắc cộng dồn và độ ưu tiên

Ví dụ sử dụng:
- Ưu đãi đăng ký sớm: Giảm 15% cho tất cả ngành từ 01/01 - 31/03
- Ưu đãi ngành nặng nhọc: Giảm 2 triệu cho ngành is_heavy = true
- Ưu đãi con thương binh: Giảm 50% cho đối tượng con_thuong_binh
"""
from datetime import datetime
from sqlalchemy import (
    Boolean, Column, Date, DateTime, Enum, ForeignKey,
    Integer, Numeric, String, Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from .base import Base
import enum


class DiscountTypeEnum(str, enum.Enum):
    """Loại ưu đãi: Số tiền cố định hoặc phần trăm"""
    AMOUNT = "amount"           # Giảm số tiền cố định (VND)
    PERCENTAGE = "percentage"   # Giảm theo phần trăm (%)


class TuitionDiscountPolicy(Base):
    """
    Chính sách ưu đãi học phí.

    Sử dụng JSON fields để linh hoạt định nghĩa phạm vi và điều kiện:
    - applicable_scope: Ngành/chương trình nào được áp dụng
    - target_criteria: Đối tượng sinh viên nào được hưởng
    """
    __tablename__ = "tuition_discount_policy"

    id = Column(Integer, primary_key=True, index=True)

    # === Thông tin cơ bản ===
    code = Column(
        String(50),
        unique=True,
        nullable=False,
        index=True,
        comment="Mã chính sách duy nhất (vd: 'EARLY_BIRD_2025', 'HEAVY_WORK')"
    )
    name = Column(
        String(200),
        nullable=False,
        comment="Tên chính sách hiển thị (vd: 'Ưu đãi đăng ký sớm 2025')"
    )
    description = Column(
        Text,
        nullable=True,
        comment="Mô tả chi tiết về chính sách"
    )

    # === Loại và giá trị ưu đãi ===
    discount_type = Column(
        Enum(
            DiscountTypeEnum,
            name="discount_type_enum",
            values_callable=lambda obj: [e.value for e in obj],
            create_type=False,  # Enum created by migration, not by create_all()
        ),
        nullable=False,
        comment="Loại ưu đãi: 'amount' (VND) hoặc 'percentage' (%)"
    )
    discount_value = Column(
        Numeric(15, 2),
        nullable=False,
        comment="Giá trị ưu đãi: Số tiền (VND) hoặc phần trăm (0-100)"
    )

    # === Thời gian hiệu lực ===
    valid_from = Column(
        Date,
        nullable=True,
        comment="Ngày bắt đầu hiệu lực (NULL = không giới hạn)"
    )
    valid_to = Column(
        Date,
        nullable=True,
        comment="Ngày kết thúc hiệu lực (NULL = vô thời hạn)"
    )

    # === Phạm vi áp dụng (JSON) ===
    # Ví dụ: {"all_programs": true} hoặc {"degree_levels": ["Cao đẳng"], "is_heavy_only": true}
    applicable_scope = Column(
        JSONB,
        nullable=False,
        default={},
        server_default="{}",
        comment="Phạm vi ngành/chương trình áp dụng (JSON)"
    )

    # === Điều kiện đối tượng (JSON) ===
    # Ví dụ: {"priority_types": ["con_thuong_binh", "ho_ngheo"]}
    target_criteria = Column(
        JSONB,
        nullable=False,
        default={},
        server_default="{}",
        comment="Điều kiện đối tượng sinh viên được hưởng (JSON)"
    )

    # === Quy tắc áp dụng ===
    is_stackable = Column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        comment="Có thể cộng dồn với ưu đãi khác không"
    )
    priority = Column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="Độ ưu tiên (cao hơn = áp dụng trước)"
    )
    max_usage = Column(
        Integer,
        nullable=True,
        comment="Giới hạn số lượt sử dụng (NULL = không giới hạn)"
    )
    current_usage = Column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="Số lượt đã sử dụng"
    )

    # === Trạng thái ===
    is_active = Column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
        index=True,
        comment="Trạng thái hoạt động (soft delete)"
    )

    # === Audit trail ===
    created_at = Column(
        DateTime(timezone=True),  # ✅ FIX: Added timezone=True
        nullable=False,
        default=datetime.utcnow,
        server_default="now()",
        comment="Thời điểm tạo"
    )
    updated_at = Column(
        DateTime(timezone=True),  # ✅ FIX: Added timezone=True
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        server_default="now()",
        comment="Thời điểm cập nhật cuối"
    )
    created_by_user_id = Column(
        Integer,
        ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True,
        index=True,  # ✅ FIX: Added index
        comment="User tạo chính sách"
    )
    updated_by_user_id = Column(
        Integer,
        ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True,
        index=True,  # ✅ FIX: Added index
        comment="User cập nhật cuối"
    )

    # === Relationships ===
    created_by = relationship(
        "User",
        foreign_keys=[created_by_user_id],
        lazy="selectin"
    )
    updated_by = relationship(
        "User",
        foreign_keys=[updated_by_user_id],
        lazy="selectin"
    )

    def __repr__(self):
        return f"<TuitionDiscountPolicy {self.id}: {self.code} - {self.name}>"

    @property
    def is_expired(self) -> bool:
        """Kiểm tra chính sách đã hết hạn chưa"""
        if self.valid_to is None:
            return False
        from datetime import date
        return date.today() > self.valid_to

    @property
    def is_started(self) -> bool:
        """Kiểm tra chính sách đã bắt đầu chưa"""
        if self.valid_from is None:
            return True
        from datetime import date
        return date.today() >= self.valid_from

    @property
    def is_within_validity(self) -> bool:
        """Kiểm tra chính sách đang trong thời gian hiệu lực"""
        return self.is_started and not self.is_expired

    @property
    def has_quota_remaining(self) -> bool:
        """Kiểm tra còn quota sử dụng không"""
        if self.max_usage is None:
            return True
        return self.current_usage < self.max_usage
