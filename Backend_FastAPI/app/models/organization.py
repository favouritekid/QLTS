# app/models/organization.py
from sqlalchemy import Boolean, Column, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from .base import Base


class OrganizationUnit(Base):
    """
    Organizational Unit Model with Soft Delete.

    Represents hierarchical structure of the institution (departments, faculties, etc.).
    Uses soft delete - never physically delete units to preserve historical data.
    """
    __tablename__ = "organization_unit"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    type = Column(String(50), nullable=False)
    description = Column(Text, nullable=True)
    parent_id = Column(Integer, ForeignKey("organization_unit.id"), nullable=True)

    # NEW: Soft delete support
    is_active = Column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
        index=True,
        comment="Soft delete flag - never hard delete organizational units"
    )

    # === Hierarchical structure ===
    parent = relationship(
        "OrganizationUnit", back_populates="children", remote_side=[id]
    )
    children = relationship("OrganizationUnit", back_populates="parent")

    # === User relationships ===
    # Direct users (cached - may become stale)
    users = relationship("User", back_populates="unit")

    # NEW: User assignments (source of truth)
    user_assignments = relationship(
        "UserUnitAssignment",
        back_populates="unit",
        cascade="all, delete-orphan"
    )

    # === Other relationships ===
    majors = relationship("Major", back_populates="unit")  # Legacy - to be removed
    major_programs = relationship("MajorProgram", back_populates="unit")  # NEW: 3-tier architecture
    leads = relationship("Lead", back_populates="unit")

    # Configuration
    assignment_config = relationship(
        "OfficerAssignmentConfig", back_populates="unit", uselist=False
    )
    scoring_config = relationship(
        "LeadScoringConfig", back_populates="unit", uselist=False
    )


class Major(Base):
    """
    Major/Program Model with Soft Delete and Year-versioned Academic Info.

    Static fields (name, code) are stored here.
    Dynamic fields (tuition fees, admission quotas) are in MajorAcademicInfo.
    """

    __tablename__ = "major"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    code = Column(String(50), unique=True, nullable=False)
    description = Column(Text, nullable=True, comment="General description (static)")

    unit_id = Column(Integer, ForeignKey("organization_unit.id"), nullable=False)

    # NEW: Soft delete support
    is_active = Column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
        index=True,
        comment="Soft delete flag - preserve historical major data"
    )

    # Relationships
    unit = relationship("OrganizationUnit", back_populates="majors")
    leads = relationship("Lead", back_populates="major")

    # NEW: Year-versioned academic information
    academic_info_history = relationship(
        "MajorAcademicInfo",
        back_populates="major",
        cascade="all, delete-orphan",
        order_by="MajorAcademicInfo.academic_year.desc()"
    )
