# app/models/major_academic_info.py
"""
Major Academic Info Model - Temporal Academic Data System

This model implements a year-versioned approach to storing major academic information
that changes annually (tuition fees, admission quotas, benefits, etc.).

Key Features:
- One record per major per academic year
- Immutable historical data (never update past years)
- Supports multi-year planning and historical queries
- Rich academic metadata

Use Cases:
- "What was the tuition fee for Computer Science in 2024?"
- "Show admission quota trends for Business major (2020-2025)"
- "Compare benefits offered across years"
"""
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    Index,
    UniqueConstraint
)
from sqlalchemy.orm import relationship

from .base import Base


class MajorAcademicInfo(Base):
    """
    Year-versioned academic information for majors.

    This is the SOURCE OF TRUTH for academic data that changes yearly:
    - Tuition fees
    - Admission quotas
    - Target audience
    - Benefits and promotions

    The `major` table only stores static data (name, code, description).

    Important: Each (major_id, academic_year) combination is UNIQUE.
    """

    __tablename__ = "major_academic_info"

    # Primary Key
    id = Column(Integer, primary_key=True, index=True)

    # Foreign Key
    major_id = Column(
        Integer,
        ForeignKey("major.id", ondelete="CASCADE"),
        nullable=False,
        index=True  # For fast major lookups
    )

    # Temporal Key
    academic_year = Column(
        Integer,
        nullable=False,
        index=True  # For year-based queries
    )

    # Academic Information (Rich Text Fields)
    target_audience = Column(
        Text,
        nullable=True,
        comment="Đối tượng phù hợp với ngành học này (VD: 'Học sinh có năng khiếu toán, logic tốt')"
    )
    detailed_info = Column(
        Text,
        nullable=True,
        comment="Thông tin chi tiết về ngành học (có thể là HTML/Markdown)"
    )
    current_year_benefits = Column(
        Text,
        nullable=True,
        comment="Ưu đãi, học bổng, chính sách đặc biệt cho năm học này"
    )

    # Financial Information
    tuition_fee_per_year = Column(
        Numeric(precision=12, scale=2),  # Support up to 9,999,999,999.99 VND
        nullable=True,
        comment="Học phí một năm (VND)"
    )

    # Admission Information
    annual_admission_quota = Column(
        Integer,
        nullable=True,
        comment="Chỉ tiêu tuyển sinh của năm học"
    )

    # Status
    is_published = Column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        index=True,  # For filtering published info
        comment="Đã công bố thông tin ra public chưa?"
    )

    # Audit Fields
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
        server_default="CURRENT_TIMESTAMP"
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        server_default="CURRENT_TIMESTAMP"
    )
    created_by_user_id = Column(
        Integer,
        ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True
    )

    # Relationships
    major = relationship(
        "Major",
        back_populates="academic_info_history"
    )
    created_by = relationship(
        "User",
        foreign_keys=[created_by_user_id]
    )

    # Constraints and Indexes
    __table_args__ = (
        # Ensure one record per major per year
        UniqueConstraint(
            'major_id',
            'academic_year',
            name='uq_major_academic_year'
        ),

        # Fast lookup: "Get info for major in specific year"
        Index('ix_major_year_published', 'major_id', 'academic_year', 'is_published'),

        # Fast lookup: "Get all published info for a year across all majors"
        Index('ix_year_published', 'academic_year', 'is_published'),
    )

    def __repr__(self) -> str:
        status = "published" if self.is_published else "draft"
        return (
            f"<MajorAcademicInfo major_id={self.major_id} "
            f"year={self.academic_year} {status}>"
        )

    @property
    def tuition_fee_display(self) -> str:
        """Format tuition fee for display (Vietnamese currency)."""
        if self.tuition_fee_per_year:
            # Convert Decimal to float for formatting
            amount = float(self.tuition_fee_per_year)
            # Format with thousands separator
            return f"{amount:,.0f} VNĐ"
        return "Chưa công bố"

    @property
    def is_current_year(self) -> bool:
        """Check if this is the current academic year."""
        current_year = datetime.utcnow().year
        return self.academic_year == current_year

    def calculate_fee_change_percentage(self, previous_year_fee: Decimal) -> float | None:
        """
        Calculate percentage change from previous year.

        Args:
            previous_year_fee: Tuition fee from previous year

        Returns:
            Percentage change (positive = increase, negative = decrease)
        """
        if not self.tuition_fee_per_year or not previous_year_fee:
            return None

        if previous_year_fee == 0:
            return None

        change = (
            (self.tuition_fee_per_year - previous_year_fee) / previous_year_fee
        ) * 100
        return float(change)
