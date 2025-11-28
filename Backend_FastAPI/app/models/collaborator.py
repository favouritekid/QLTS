"""
Collaborator Model - Quản lý thông tin cộng tác viên
"""
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Numeric, JSON, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime
from app.models.base import Base


class Collaborator(Base):
    """
    Model đại diện cho Cộng tác viên (Collaborator/Referrer)

    Cộng tác viên là người giới thiệu lead vào hệ thống và nhận hoa hồng
    khi lead nhập học thành công.
    """
    __tablename__ = "collaborators"

    # Primary Key
    id = Column(Integer, primary_key=True, index=True)

    # Mã định danh
    code = Column(String(50), unique=True, nullable=False, index=True)  # Mã CTV: CTV001, CTV002

    # Thông tin cơ bản
    full_name = Column(String(255), nullable=False)
    email = Column(String(255), unique=True, nullable=False, index=True)
    phone = Column(String(20), nullable=False)
    phone2 = Column(String(20), nullable=True)

    # Thông tin định danh & thanh toán
    id_number = Column(String(20), nullable=True)  # CMND/CCCD
    tax_code = Column(String(20), nullable=True)   # Mã số thuế
    bank_account = Column(String(50), nullable=True)
    bank_name = Column(String(100), nullable=True)
    bank_branch = Column(String(100), nullable=True)

    # Địa chỉ
    address = Column(String(500), nullable=True)
    city = Column(String(100), nullable=True)
    district = Column(String(100), nullable=True)

    # Phân loại
    collaborator_type = Column(String(50), default="individual")  # individual, agency, partner
    category = Column(String(50), nullable=True)  # VIP, Standard, Bronze, Silver, Gold

    # Trạng thái
    status = Column(String(20), default="active")  # active, inactive, suspended
    is_active = Column(Boolean, default=True)

    # Thống kê (tự động cập nhật)
    total_leads = Column(Integer, default=0)  # Tổng số lead đã giới thiệu
    successful_leads = Column(Integer, default=0)  # Số lead nhập học thành công
    total_commission_earned = Column(Numeric(15, 2), default=0)  # Tổng hoa hồng đã nhận (VND)
    pending_commission = Column(Numeric(15, 2), default=0)  # Hoa hồng chờ thanh toán (VND)

    # Metadata
    notes = Column(String(1000), nullable=True)  # Ghi chú quản lý
    metadata = Column(JSON, nullable=True)  # Dữ liệu mở rộng (JSON)

    # Audit trail
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    # Relationships
    leads = relationship(
        "Lead",
        back_populates="referrer",
        foreign_keys="[Lead.referrer_id]"
    )
    commissions = relationship(
        "Commission",
        back_populates="collaborator",
        cascade="all, delete-orphan"
    )
    created_by = relationship("User", foreign_keys=[created_by_user_id])

    def __repr__(self):
        return f"<Collaborator {self.code} - {self.full_name}>"
