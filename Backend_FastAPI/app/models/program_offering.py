# app/models/program_offering.py
"""
Program Offering Model - Level 2 in the 3-tier hierarchy.

This model represents a specific training type/format for a major program.

Hierarchy:
    MajorProgram (Level 1) -> ProgramOffering (Level 2) -> OfferingAcademicInfo (Level 3)

Example:
    - offering_type: "Chính quy"
    - offering_type: "Liên thông"
    - offering_type: "Vừa làm vừa học"
"""
from sqlalchemy import (
    Boolean, Column, ForeignKey, Integer, String, Text,
    UniqueConstraint
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from .base import Base


class ProgramOffering(Base):
    """
    CẤP 2: Loại hình đào tạo (Tĩnh).
    Ví dụ: 'Chính quy', 'Liên thông'
    """
    __tablename__ = "program_offering"

    id = Column(Integer, primary_key=True, index=True)
    offering_type = Column(
        String(100),
        nullable=False,
        comment="Tên loại hình (vd: 'Chính quy', 'Liên thông')"
    )
    duration_semesters = Column(Integer, nullable=True)
    total_credits = Column(Integer, nullable=True)
    is_active = Column(
        Boolean,
        nullable=False,
        default=True,
        index=True,
        comment="Cờ Soft Delete"
    )

    # Admission Rules (for AdmissionProfile snapshot)
    admission_rules = Column(
        JSONB,
        nullable=True,
        comment="Admission rules JSON: {min_gpa, mandatory_docs[], admission_method}"
    )

    # Liên kết Nhiều-1 đến Cấp 1
    program_id = Column(
        Integer,
        ForeignKey("major_program.id", ondelete="CASCADE"),
        nullable=False
    )
    program = relationship("MajorProgram", back_populates="offerings")

    # Liên kết 1-Nhiều đến Cấp 3
    academic_info_history = relationship(
        "OfferingAcademicInfo",
        back_populates="offering",
        cascade="all, delete-orphan",  # Xóa Cấp 2 -> Xóa Cấp 3
        order_by="OfferingAcademicInfo.academic_year.desc()"
    )

    # Leads sẽ liên kết vào đây
    leads = relationship("Lead", back_populates="offering")

    # Distribution configurations for multi-unit offerings
    distribution_configs = relationship(
        "OfferingDistributionConfig",
        back_populates="offering",
        cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint('program_id', 'offering_type', name='uq_program_offering_type'),
    )

    def __repr__(self):
        return f"<ProgramOffering {self.id}: {self.offering_type}>"
