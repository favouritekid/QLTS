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
    # OLD 2-TIER: majors = relationship("Major", back_populates="unit") - REMOVED after migration
    major_programs = relationship("MajorProgram", back_populates="unit")  # NEW: 3-tier architecture
    leads = relationship("Lead", back_populates="unit")

    # Configuration
    assignment_config = relationship(
        "OfficerAssignmentConfig", back_populates="unit", uselist=False
    )
    scoring_config = relationship(
        "LeadScoringConfig", back_populates="unit", uselist=False
    )


# ============================================================================
# OLD 2-TIER MODEL - REMOVED AFTER MIGRATION k6l7m8n9o0p1
# ============================================================================
# class Major(Base):
#     """
#     [DEPRECATED] Old 2-tier model - replaced by 3-tier architecture:
#     MajorProgram (Tier 1) -> ProgramOffering (Tier 2) -> OfferingAcademicInfo (Tier 3)
#
#     This model and its table were removed in migration k6l7m8n9o0p1.
#     DO NOT UNCOMMENT - kept for reference only.
#     """
#     __tablename__ = "major"  # Table dropped in migration
#     # ... fields removed ...
# ============================================================================
