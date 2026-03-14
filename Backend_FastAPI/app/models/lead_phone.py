# app/models/lead_phone.py
"""
Phase 2 — True Phone Identity Model

Canonical phone identity for active leads.
Each normalized phone number can belong to at most 1 active lead.

The real uniqueness guarantee is a partial unique index:
    CREATE UNIQUE INDEX uq_lead_phone_active
    ON lead_phone_identity (phone_normalized)
    WHERE deleted_at IS NULL

When a lead is soft-deleted, its phone identity rows are also soft-deleted.
When a lead is restored, phone identities are restored (with conflict check).
"""

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from .base import Base


class LeadPhoneIdentity(Base):
    """Canonical phone identity for active leads.

    Each normalized phone number can belong to at most 1 active lead.
    When a lead is soft-deleted, its phone identity rows are also soft-deleted.
    When a lead is restored, phone identities are restored (with conflict check).
    """

    __tablename__ = "lead_phone_identity"
    __table_args__ = (
        # Partial unique index created in migration: WHERE deleted_at IS NULL
        # See: alembic/versions/zl1r2s3t4u5v6_phase2_phone_identity.py
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    lead_id = Column(
        Integer,
        ForeignKey("lead.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    phone_normalized = Column(String(20), nullable=False, index=True)
    slot = Column(String(10), nullable=False, comment="'phone' or 'phone2'")
    deleted_at = Column(DateTime(timezone=True), nullable=True, index=True)

    lead = relationship("Lead", backref="phone_identities")
