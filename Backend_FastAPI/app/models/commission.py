"""
Commission Models - Quản lý hoa hồng và chính sách hoa hồng
"""
from sqlalchemy import Column, Integer, String, DateTime, Numeric, ForeignKey, Boolean, JSON, Enum as SQLEnum
from sqlalchemy.orm import relationship
from datetime import datetime
from enum import Enum
from app.models.base import Base


class CommissionStatus(str, Enum):
    """Trạng thái hoa hồng"""
    PENDING = "pending"          # Chờ xử lý (lead mới nhập học)
    APPROVED = "approved"        # Đã phê duyệt
    PAID = "paid"               # Đã thanh toán
    REJECTED = "rejected"        # Từ chối
    CANCELLED = "cancelled"      # Hủy bỏ


class CommissionType(str, Enum):
    """Loại hoa hồng"""
    ENROLLMENT = "enrollment"    # Hoa hồng nhập học
    REFERRAL = "referral"       # Hoa hồng giới thiệu
    BONUS = "bonus"             # Thưởng đặc biệt


class CalculationType(str, Enum):
    """Loại tính toán hoa hồng"""
    PERCENTAGE = "percentage"    # Tính theo % học phí
    FIXED_AMOUNT = "fixed_amount"  # Số tiền cố định


class Commission(Base):
    """
    Model đại diện cho Hoa hồng (Commission)

    Ghi nhận hoa hồng cho cộng tác viên khi lead nhập học thành công.
    """
    __tablename__ = "commissions"

    # Primary Key
    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(50), unique=True, nullable=False, index=True)  # Mã hoa hồng: COM001

    # Foreign Keys - Liên kết
    collaborator_id = Column(Integer, ForeignKey("collaborators.id"), nullable=False, index=True)
    lead_id = Column(Integer, ForeignKey("leads.id"), nullable=False, index=True)
    application_id = Column(Integer, ForeignKey("applications.id"), nullable=True, index=True)
    policy_id = Column(Integer, ForeignKey("commission_policies.id"), nullable=True)

    # Phân loại
    commission_type = Column(SQLEnum(CommissionType), default=CommissionType.ENROLLMENT)

    # Số tiền
    base_amount = Column(Numeric(15, 2), nullable=False)  # Số tiền gốc (học phí/revenue)
    commission_rate = Column(Numeric(5, 2), nullable=True)  # Tỷ lệ % (vd: 5.00 = 5%)
    commission_amount = Column(Numeric(15, 2), nullable=False)  # Số tiền hoa hồng thực tế

    # Trạng thái
    status = Column(SQLEnum(CommissionStatus), default=CommissionStatus.PENDING, index=True)

    # Ngày tháng
    earned_at = Column(DateTime, default=datetime.utcnow)  # Ngày phát sinh hoa hồng
    approved_at = Column(DateTime, nullable=True)
    paid_at = Column(DateTime, nullable=True)

    # Người xử lý
    approved_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    paid_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    # Ghi chú
    notes = Column(String(1000), nullable=True)
    rejection_reason = Column(String(500), nullable=True)

    # Audit trail
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    collaborator = relationship("Collaborator", back_populates="commissions")
    lead = relationship("Lead", back_populates="commissions")
    application = relationship("Application")
    policy = relationship("CommissionPolicy")
    approved_by = relationship("User", foreign_keys=[approved_by_user_id])
    paid_by = relationship("User", foreign_keys=[paid_by_user_id])

    def __repr__(self):
        return f"<Commission {self.code} - {self.commission_amount} VND - {self.status}>"


class CommissionPolicy(Base):
    """
    Model đại diện cho Chính sách hoa hồng (Commission Policy)

    Định nghĩa các quy tắc tính hoa hồng cho cộng tác viên.
    """
    __tablename__ = "commission_policies"

    # Primary Key
    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(50), unique=True, nullable=False, index=True)  # Mã chính sách
    name = Column(String(255), nullable=False)
    description = Column(String(1000), nullable=True)

    # Loại tính toán
    calculation_type = Column(SQLEnum(CalculationType), default=CalculationType.PERCENTAGE)

    # Giá trị hoa hồng
    percentage_value = Column(Numeric(5, 2), nullable=True)  # % hoa hồng (vd: 5.00 = 5%)
    fixed_amount = Column(Numeric(15, 2), nullable=True)  # Số tiền cố định (VND)

    # Điều kiện áp dụng (JSON)
    applicable_scope = Column(JSON, nullable=True)  # {"major_programs": [1, 2], "offerings": [3, 4]}
    collaborator_categories = Column(JSON, nullable=True)  # ["VIP", "Gold"] - Loại CTV
    minimum_tuition = Column(Numeric(15, 2), nullable=True)  # Học phí tối thiểu

    # Hiệu lực
    effective_start_date = Column(DateTime, nullable=False)
    effective_end_date = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True)

    # Ưu tiên (số càng cao càng ưu tiên)
    priority = Column(Integer, default=0)

    # Audit trail
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    # Relationships
    created_by = relationship("User", foreign_keys=[created_by_user_id])

    def __repr__(self):
        return f"<CommissionPolicy {self.code} - {self.name}>"
