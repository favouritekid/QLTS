# app/models/collaborator.py
"""
Collaborator (CTV) System - Phase 1: Core Models

Collaborator = External partner who refers leads to the system.
Two types:
- Independent (managed_by_officer_id=NULL): Leads go through auto-assignment
- Attached to Officer (managed_by_officer_id=X): Leads assigned directly to officer

LeadClaim = Workflow record for CTV submitting/claiming a lead.
"""
import enum
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    JSON,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from .base import Base


class CollaboratorStatusEnum(str, enum.Enum):
    pending = "pending"
    active = "active"
    suspended = "suspended"
    inactive = "inactive"


class Collaborator(Base):
    """External collaborator (CTV) who refers prospective students."""

    __tablename__ = "collaborator"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(20), unique=True, nullable=False, index=True)
    full_name = Column(String(255), nullable=False)
    email = Column(String(255), nullable=True, index=True)
    phone = Column(String(20), nullable=False, index=True)
    status = Column(String(20), nullable=False, default="pending", index=True)

    # Hybrid: Link to User (nullable). If set, CTV can login
    user_id = Column(
        Integer,
        ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True,
        unique=True,
    )

    # Organization scope
    unit_id = Column(
        Integer,
        ForeignKey("organization_unit.id"),
        nullable=False,
        index=True,
    )

    # Metadata
    id_card_number = Column(String(20), nullable=True)
    bank_account = Column(String(50), nullable=True)
    bank_name = Column(String(100), nullable=True)
    address = Column(String(500), nullable=True)
    notes = Column(Text, nullable=True)

    # 2 types: Independent (NULL) vs Attached to Officer
    managed_by_officer_id = Column(
        Integer,
        ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="NULL=independent CTV (auto-assign), officer_id=leads assigned directly to officer",
    )

    # Abuse tracking (Phase 2: Attribution expiry)
    expired_attribution_count = Column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="Count of expired attributions for abuse detection",
    )
    is_flagged = Column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        comment="Flagged for review after 5+ expired attributions",
    )

    # Timestamps & Soft delete
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    deleted_at = Column(DateTime(timezone=True), nullable=True, index=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    approved_by_id = Column(
        Integer,
        ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Relationships
    user = relationship("User", foreign_keys=[user_id])
    approved_by = relationship("User", foreign_keys=[approved_by_id])
    managed_by_officer = relationship("User", foreign_keys=[managed_by_officer_id])
    unit = relationship("OrganizationUnit")
    leads_referred = relationship("Lead", back_populates="referrer")

    def __repr__(self):
        return f"<Collaborator {self.code}: {self.full_name}>"


class LeadClaimStatusEnum(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class LeadClaim(Base):
    """Claim record: CTV submits a lead through claim workflow."""

    __tablename__ = "lead_claim"

    id = Column(Integer, primary_key=True, index=True)
    collaborator_id = Column(
        Integer,
        ForeignKey("collaborator.id"),
        nullable=False,
        index=True,
    )
    lead_id = Column(
        Integer,
        ForeignKey("lead.id"),
        nullable=False,
        index=True,
    )
    status = Column(String(20), nullable=False, default="pending", index=True)

    # Claim data (validated by Pydantic LeadClaimData before storing as JSON)
    claim_data = Column(JSON, nullable=True)

    # Review
    reviewed_by_id = Column(
        Integer,
        ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True,
    )
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    rejection_reason = Column(String(500), nullable=True)

    # Timestamps
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    # Unique: 1 CTV can only claim 1 lead once
    __table_args__ = (
        UniqueConstraint("collaborator_id", "lead_id", name="uq_claim_collaborator_lead"),
    )

    # Relationships
    collaborator = relationship("Collaborator")
    lead = relationship("Lead", back_populates="claims")
    reviewed_by = relationship("User")

    def __repr__(self):
        return f"<LeadClaim {self.id}: CTV={self.collaborator_id} Lead={self.lead_id} Status={self.status}>"
