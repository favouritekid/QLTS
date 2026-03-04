# app/models/commission.py
"""
Commission System Models - Phase 2: CTV Commission Tracking

CommissionPolicy: Admin-configured rules for automatic commission calculation.
CommissionRecord: Individual commission entries triggered by lead status changes.
"""
import enum
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import relationship

from .base import Base


class CommissionCalculationType(str, enum.Enum):
    fixed = "fixed"
    percentage = "percentage"


class CommissionRecordStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    paid = "paid"
    rejected = "rejected"
    cancelled = "cancelled"


class CommissionPolicy(Base):
    """Admin-configured commission policy — defines when and how commissions are calculated."""

    __tablename__ = "commission_policy"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)

    # Trigger: which consultation_status triggers this policy
    trigger_status_id = Column(
        String(50),
        nullable=False,
        index=True,
        comment="ConsultationStatus.id that triggers commission calculation",
    )

    # Calculation
    calculation_type = Column(
        String(20),
        nullable=False,
        comment="'fixed' or 'percentage'",
    )
    fixed_amount = Column(
        Numeric(12, 0),
        nullable=True,
        comment="VND amount when calculation_type='fixed'",
    )
    percentage = Column(
        Numeric(5, 2),
        nullable=True,
        comment="Percentage when calculation_type='percentage'",
    )

    # Scope (nullable = global policy)
    unit_id = Column(
        Integer,
        ForeignKey("organization_unit.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
        comment="NULL = global policy, otherwise unit-scoped",
    )
    offering_id = Column(
        Integer,
        ForeignKey("program_offering.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
        comment="NULL = all offerings, otherwise offering-scoped",
    )

    # Validity period
    effective_from = Column(Date, nullable=False)
    effective_to = Column(Date, nullable=True, comment="NULL = no end date")
    is_active = Column(Boolean, nullable=False, default=True, server_default="true", index=True)

    # Audit
    created_by_id = Column(
        Integer,
        ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
    )

    # Relationships
    created_by = relationship("User", foreign_keys=[created_by_id])
    unit = relationship("OrganizationUnit")
    offering = relationship("ProgramOffering")

    __table_args__ = (
        CheckConstraint(
            "(calculation_type = 'fixed' AND fixed_amount IS NOT NULL) OR "
            "(calculation_type = 'percentage' AND percentage IS NOT NULL)",
            name="ck_commission_policy_amount",
        ),
    )

    def __repr__(self):
        return f"<CommissionPolicy {self.id}: {self.name} ({self.calculation_type})>"


class CommissionRecord(Base):
    """Individual commission record — created when a lead reaches a trigger status."""

    __tablename__ = "commission_record"

    id = Column(Integer, primary_key=True)

    collaborator_id = Column(
        Integer,
        ForeignKey("collaborator.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    lead_id = Column(
        Integer,
        ForeignKey("lead.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    policy_id = Column(
        Integer,
        ForeignKey("commission_policy.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    # Calculated amount
    amount = Column(Numeric(12, 0), nullable=False, comment="VND")
    calculation_detail = Column(
        JSON,
        nullable=True,
        comment="Snapshot: {type, fixed_amount/percentage, base_amount, policy_name, ...}",
    )

    # Status workflow: pending → approved → paid | cancelled | rejected
    status = Column(
        String(20),
        nullable=False,
        default="pending",
        server_default="pending",
        index=True,
    )

    # Trigger info
    trigger_status_id = Column(
        String(50),
        nullable=False,
        comment="The consultation_status.id that triggered this record",
    )
    triggered_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
    )

    # Approval
    approved_by_id = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)

    # Rejection
    rejected_by_id = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    rejected_at = Column(DateTime(timezone=True), nullable=True)
    rejection_reason = Column(String(500), nullable=True)

    # Cancellation
    cancelled_at = Column(DateTime(timezone=True), nullable=True)
    cancelled_by_id = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    cancellation_reason = Column(String(500), nullable=True)

    # Payment
    paid_at = Column(DateTime(timezone=True), nullable=True)
    paid_by_id = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    payment_reference = Column(String(255), nullable=True)

    # Timestamps
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
    )

    # Relationships
    collaborator = relationship("Collaborator", backref="commissions")
    lead = relationship("Lead", backref="commission_records")
    policy = relationship("CommissionPolicy")
    approved_by = relationship("User", foreign_keys=[approved_by_id])
    rejected_by = relationship("User", foreign_keys=[rejected_by_id])
    cancelled_by = relationship("User", foreign_keys=[cancelled_by_id])
    paid_by = relationship("User", foreign_keys=[paid_by_id])

    __table_args__ = (
        UniqueConstraint("lead_id", "policy_id", name="uq_commission_lead_policy"),
    )

    def __repr__(self):
        return f"<CommissionRecord {self.id}: CTV={self.collaborator_id} Amount={self.amount} Status={self.status}>"
