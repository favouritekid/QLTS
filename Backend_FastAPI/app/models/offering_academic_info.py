# app/models/offering_academic_info.py
"""
Offering Academic Info Model - Level 3 in the 3-tier hierarchy.

This model stores year-versioned academic information (tuition, quotas, etc.)
that changes annually for each program offering.

Hierarchy:
    MajorProgram (Level 1) -> ProgramOffering (Level 2) -> OfferingAcademicInfo (Level 3)

Key Features:
- One record per offering per academic year
- Immutable historical data (never update past years)
- Supports multi-year planning and historical queries
- Rich academic metadata with JSON support

Example:
    - academic_year: 2025
    - tuition_fee_per_year: 15000000.00
    - annual_admission_quota: 100
    - is_published: True
"""
from datetime import datetime

from sqlalchemy import (
    Boolean, Column, ForeignKey, Integer, Numeric, String,
    UniqueConstraint, JSON, DateTime, Index
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from .base import Base


class OfferingAcademicInfo(Base):
    """
    CẤP 3: Thông tin tuyển sinh (Động theo năm).
    """
    __tablename__ = "offering_academic_info"

    id = Column(Integer, primary_key=True, index=True)
    academic_year = Column(Integer, nullable=False, index=True)
    tuition_fee_per_year = Column(Numeric(precision=12, scale=2), nullable=True)
    annual_admission_quota = Column(Integer, nullable=True)
    is_published = Column(
        Boolean,
        nullable=False,
        default=False,
        index=True,
        comment="Đã công bố thông tin ra public chưa?"
    )
    is_deleted = Column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        index=True,
        comment="Soft delete flag - NEVER hard delete academic info (financial/historical data)"
    )
    admission_criteria = Column(
        JSON,
        nullable=True,
        comment="Tiêu chí tuyển sinh (JSON)"
    )

    # Tuition discount policies
    applied_discount_policy_ids = Column(
        JSON,
        nullable=True,
        comment="Danh sách ID chính sách ưu đãi áp dụng (JSON array of integers)"
    )

    # Additional fields for compatibility with old system
    target_audience = Column(
        String(1000),
        nullable=True,
        comment="Đối tượng phù hợp với ngành học này"
    )
    cutoff_score_previous_year = Column(
        Numeric(precision=5, scale=2),
        nullable=True,
        comment="Điểm chuẩn năm trước"
    )

    # Liên kết Nhiều-1 đến Cấp 2
    offering_id = Column(
        Integer,
        ForeignKey("program_offering.id", ondelete="CASCADE"),
        nullable=False
    )
    offering = relationship("ProgramOffering", back_populates="academic_info_history")

    # Audit Trail
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False
    )
    created_by_user_id = Column(
        Integer,
        ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True
    )
    updated_by_user_id = Column(
        Integer,
        ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True
    )

    # ✅ TASK 6.1: Updated to use back_populates (explicit bidirectional relationship)
    created_by = relationship(
        "User",
        foreign_keys=[created_by_user_id],
        back_populates="created_academic_infos"
    )
    updated_by = relationship(
        "User",
        foreign_keys=[updated_by_user_id],
        back_populates="updated_academic_infos"
    )

    __table_args__ = (
        UniqueConstraint('offering_id', 'academic_year', name='uq_offering_academic_year'),
    )

    def __repr__(self):
        status = "published" if self.is_published else "draft"
        return (
            f"<OfferingAcademicInfo offering_id={self.offering_id} "
            f"year={self.academic_year} {status}>"
        )

    @property
    def tuition_fee_display(self) -> str:
        """Format tuition fee for display (Vietnamese currency)."""
        if self.tuition_fee_per_year:
            amount = float(self.tuition_fee_per_year)
            return f"{amount:,.0f} VNĐ"
        return "Chưa công bố"

    @property
    def is_current_year(self) -> bool:
        """Check if this is the current academic year."""
        current_year = datetime.now().year
        return self.academic_year == current_year
