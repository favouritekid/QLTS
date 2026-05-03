# app/models/major_program.py
"""
Major Program Model - Level 1 in the 3-tier hierarchy.

This model represents a major/program at a specific degree level,
uniquely identified by its admission code.

Hierarchy:
    MajorProgram (Level 1) -> ProgramOffering (Level 2) -> OfferingAcademicInfo (Level 3)

Example:
    - name: "Cao đẳng Công nghệ thông tin"
    - degree_level: "Cao đẳng"
    - code: "6480201"
"""
from sqlalchemy import (
    Boolean, Column, ForeignKey, Integer, String,
)
from sqlalchemy.orm import relationship
from .base import Base


class MajorProgram(Base):
    """
    CẤP 1: Ngành/Trình độ.
    Định danh duy nhất bằng Mã ngành (code).
    """
    __tablename__ = "major_program"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(
        String(255),
        nullable=False,
        comment="Tên hiển thị (vd: 'Cao đẳng Công nghệ thông tin')"
    )
    degree_level = Column(
        String(50),
        nullable=False,
        comment="Trình độ (vd: 'Cao đẳng', 'Đại học'). LEGACY text column "
                "— stays for Phase 4 retire. New code paths use "
                "degree_level_id FK below."
    )
    # phase1_01 (#184 Wave 1) — FK to config_degree_level. Canonical
    # lookup for new code paths; legacy ``degree_level`` text column
    # stays in parallel for Phase 4 retire.
    degree_level_id = Column(
        Integer,
        ForeignKey("config_degree_level.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="FK to config_degree_level. Canonical lookup; "
                "backfilled from legacy degree_level text column."
    )
    code = Column(
        String(50),
        unique=True,
        nullable=False,
        index=True,
        comment="Mã ngành tuyển sinh (vd: '6480201')"
    )
    is_active = Column(
        Boolean,
        nullable=False,
        default=True,
        index=True,
        comment="Cờ Soft Delete"
    )
    is_heavy = Column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        index=True,
        comment="Ngành nghề nặng nhọc, độc hại, nguy hiểm (được hưởng chính sách đặc biệt)"
    )

    # Liên kết với Khoa/Đơn vị
    unit_id = Column(Integer, ForeignKey("organization_unit.id"), nullable=False, index=True)  # ✅ FIX: Added index
    unit = relationship("OrganizationUnit", back_populates="major_programs")

    # Liên kết 1-Nhiều đến Cấp 2 (Loại hình)
    offerings = relationship(
        "ProgramOffering",
        back_populates="program",
        cascade="all, delete-orphan"  # Xóa Cấp 1 -> Xóa Cấp 2
    )

    def __repr__(self):
        return f"<MajorProgram {self.id}: {self.name} ({self.code})>"
