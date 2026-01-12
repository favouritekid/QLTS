# app/models/admission_config/admission_path.py
"""
Admission Path Model.

FIRST-CLASS ENTITY representing a complete admission pathway:
Year + Major + Offering + Method = AdmissionPath

This is the CENTRAL ENTITY for:
- Wizard configuration
- Matrix display
- Activation control
"""

from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, DateTime, UniqueConstraint
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.offering_academic_info import OfferingAcademicInfo
    from app.models.admission_config.method import AdmissionMethod
    from app.models.admission_config.criteria import AdmissionCriteria
    from app.models.user import User


class AdmissionPath(Base):
    """
    Đường tuyển sinh = Năm học + Ngành + Chương trình + Phương thức.
    
    This is the CENTRAL ENTITY that UI revolves around.
    
    Examples:
        - "CNTT 2026 – Chính quy – Xét học bạ"
        - "CNTT 2026 – Chính quy – THPT Quốc gia"
        - "CNTT 2026 – Chính quy – ĐGNL"
    
    Status Lifecycle:
        draft → active → inactive → archived
    
    Activation Guard:
        Can only activate if:
        - Has criteria (min_gpa OR min_score)
        - Has document config
        - Has quota > 0
    """
    __tablename__ = "admission_path"

    id = Column(Integer, primary_key=True, index=True)
    
    # Context
    academic_info_id = Column(
        Integer,
        ForeignKey("offering_academic_info.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Link to offering per year (Year + Major + Offering)"
    )
    admission_method_id = Column(
        Integer,
        ForeignKey("admission_method.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Link to admission method (hoc_ba, thpt_qg, dgnl)"
    )
    
    # Criteria (for efficient eager loading - avoids N+1)
    criteria_id = Column(
        Integer,
        ForeignKey("admission_criteria.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="Link to admission criteria (nullable for draft paths)"
    )
    
    # State
    status = Column(
        String(20),
        nullable=False,
        default="draft",
        index=True,
        comment="Status: draft | active | inactive | archived"
    )
    
    # Metadata
    display_name = Column(
        String(255),
        nullable=True,
        comment="Human-readable name: 'CNTT 2026 – CQ – Học bạ'"
    )
    display_order = Column(
        Integer,
        nullable=False,
        default=0,
        comment="Display order in UI"
    )
    visibility = Column(
        String(20),
        nullable=False,
        default="internal",
        comment="Visibility: internal | public (for future portal)"
    )
    
    # Activation Audit
    activated_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="When was this path activated"
    )
    activated_by = Column(
        Integer,
        ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True,
        comment="Who activated this path"
    )
    
    # Timestamps
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc)
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    academic_info = relationship(
        "OfferingAcademicInfo",
        back_populates="admission_paths"
    )
    admission_method = relationship(
        "AdmissionMethod",
        back_populates="admission_paths"
    )
    criteria = relationship(
        "AdmissionCriteria",
        foreign_keys="[AdmissionPath.criteria_id]"
    )
    activator = relationship(
        "User",
        foreign_keys=[activated_by]
    )

    # UNIQUE constraint: Only 1 path per (offering + method)
    __table_args__ = (
        UniqueConstraint(
            "academic_info_id", "admission_method_id",
            name="uq_admission_path_offering_method"
        ),
    )

    def __repr__(self):
        return f"<AdmissionPath {self.id}: {self.display_name or 'unnamed'} ({self.status})>"
