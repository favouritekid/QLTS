# app/models/organization.py
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

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

    # Audit trail timestamps
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        comment="Timestamp when unit was created"
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
        comment="Timestamp when unit was last updated"
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
    distribution_configs = relationship(
        "OfferingDistributionConfig", back_populates="unit", cascade="all, delete-orphan"
    )

    # Database constraints
    __table_args__ = (
        UniqueConstraint(
            'parent_id',
            'name',
            name='uq_unit_parent_name',
            # Note: NULL parent_id values are treated as distinct in PostgreSQL
            # This allows multiple root units with same name (different parent=NULL)
            # but prevents duplicate names within same parent
        ),
    )


class OfferingDistributionConfig(Base):
    """
    Configuration for Weighted Round Robin distribution of Leads across Units
    when a ProgramOffering is shared by multiple Units.

    This model enables fair lead distribution based on configurable weights and priorities,
    preventing territorial conflicts and ensuring optimal resource allocation.

    Features:
    - Weighted Round Robin: Units with higher weights receive more leads
    - Priority levels: Higher priority units are considered first
    - Active/Inactive toggle: Temporarily disable a unit from receiving leads
    - Redis-backed cursor: Atomic increment for concurrent safety

    Example:
        Offering "MBA Program" shared by 3 units:
        - Unit A (weight=3, priority=1) -> Gets 3x more leads than Unit B
        - Unit B (weight=1, priority=1) -> Base allocation
        - Unit C (weight=2, priority=2) -> Only gets leads if A & B at capacity
    """
    __tablename__ = "offering_distribution_config"

    id = Column(Integer, primary_key=True, index=True)

    # Foreign keys
    offering_id = Column(
        Integer,
        ForeignKey("program_offering.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="ProgramOffering being distributed"
    )
    unit_id = Column(
        Integer,
        ForeignKey("organization_unit.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="OrganizationUnit receiving leads"
    )

    # Distribution parameters
    weight = Column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
        comment="Distribution weight (higher = more leads). Range: 1-100"
    )
    priority = Column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
        comment="Priority level (lower number = higher priority). Range: 1-10"
    )
    is_active = Column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
        index=True,
        comment="Toggle to temporarily exclude unit from receiving leads"
    )

    # Audit trail
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        comment="Timestamp when config was created"
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
        comment="Timestamp when config was last updated"
    )

    # Relationships
    offering = relationship("ProgramOffering", back_populates="distribution_configs")
    unit = relationship("OrganizationUnit", back_populates="distribution_configs")

    # Database constraints
    __table_args__ = (
        UniqueConstraint(
            'offering_id',
            'unit_id',
            name='uq_offering_unit_distribution',
        ),
        # Index for fast lookups during lead creation
        # Usage: SELECT * FROM offering_distribution_config
        #        WHERE offering_id = ? AND is_active = true
        #        ORDER BY priority, weight DESC
    )

    def __repr__(self):
        return (
            f"<OfferingDistributionConfig "
            f"offering_id={self.offering_id} "
            f"unit_id={self.unit_id} "
            f"weight={self.weight} "
            f"priority={self.priority}>"
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
