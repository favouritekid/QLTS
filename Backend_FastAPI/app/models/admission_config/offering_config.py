# app/models/admission_config/offering_config.py
"""
Offering Admission Config Model.

PURE JUNCTION TABLE - Links AdmissionCriteria to OfferingAcademicInfo per year.

❌ NO business logic
❌ NO overrides
❌ NO JSON
"""

from sqlalchemy import Column, Integer, Boolean, ForeignKey, DateTime, UniqueConstraint
from sqlalchemy.orm import relationship
from datetime import datetime, timezone

from app.models.base import Base


class OfferingAdmissionConfig(Base):
    """
    Junction table: Links AdmissionCriteria to OfferingAcademicInfo.
    
    PURE JUNCTION - No business logic here.
    
    Example:
        OfferingAcademicInfo (CNTT 2026) uses AdmissionCriteria (HB2026_CQ)
    """
    __tablename__ = "offering_admission_config"

    id = Column(Integer, primary_key=True, index=True)
    academic_info_id = Column(
        Integer,
        ForeignKey("offering_academic_info.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Link to offering per year"
    )
    criteria_id = Column(
        Integer,
        ForeignKey("admission_criteria.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Link to admission criteria"
    )
    valid_from = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="Config valid from (optional)"
    )
    valid_to = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="Config valid until (optional)"
    )
    is_active = Column(
        Boolean,
        nullable=False,
        default=True,
        index=True
    )
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    academic_info = relationship(
        "OfferingAcademicInfo",
        back_populates="admission_configs"
    )
    criteria = relationship(
        "AdmissionCriteria",
        back_populates="offering_configs"
    )
    # AdmissionProfiles created from this config
    admission_profiles = relationship(
        "AdmissionProfile",
        back_populates="offering_admission_config"
    )

    # ✅ UNIQUE constraint: Prevent duplicate config links
    __table_args__ = (
        UniqueConstraint(
            "academic_info_id", "criteria_id",
            name="uq_offering_admission_config"
        ),
    )

    def __repr__(self):
        return f"<OfferingAdmissionConfig info={self.academic_info_id} criteria={self.criteria_id}>"

