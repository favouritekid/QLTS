# app/models/admission_config/method.py
"""
Admission Method Model.

Represents admission methods like:
- hoc_ba: Xét học bạ THPT
- thpt_qg: Xét điểm thi THPT Quốc gia
- dgnl: Xét đánh giá năng lực
"""

from sqlalchemy import Column, Integer, String, Boolean, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from app.models.base import Base


class AdmissionMethod(Base):
    """
    Phương thức tuyển sinh.
    
    Examples:
        - code: "hoc_ba", name: "Xét học bạ THPT"
        - code: "thpt_qg", name: "Xét điểm thi THPT Quốc gia"
        - code: "dgnl", name: "Xét đánh giá năng lực"
    """
    __tablename__ = "admission_method"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(
        String(50),
        nullable=False,
        unique=True,
        index=True,
        comment="Method code: hoc_ba, thpt_qg, dgnl"
    )
    name = Column(
        String(255),
        nullable=False,
        comment="Method name: Xét học bạ THPT"
    )
    description = Column(
        Text,
        nullable=True,
        comment="Detailed description of method"
    )
    requires_gpa = Column(
        Boolean,
        nullable=False,
        default=False,
        comment="Does this method require GPA input?"
    )
    requires_subject_scores = Column(
        Boolean,
        nullable=False,
        default=True,
        comment="Does this method require subject scores?"
    )
    display_order = Column(
        Integer,
        nullable=False,
        default=0,
        comment="Display order in UI"
    )
    is_active = Column(
        Boolean,
        nullable=False,
        default=True,
        index=True
    )

    # phase1_02 (#184 Wave 1) — method-level default bonus rule.
    # Schema: {"apply_area_bonus": bool, "apply_object_bonus": bool,
    # "max_total_bonus": float}. NULL = bonus disabled fallback.
    # (apply_subject_bonus renamed -> apply_object_bonus in phase1_08a / Q9 #07 PR1.)
    # Path-level override via AdmissionPath.bonus_rule_override.
    # Resolution rule (PLAN line 787-789):
    #   effective = path.bonus_rule_override
    #               ?? method.default_bonus_rule
    #               ?? {"apply_area_bonus": false, "apply_object_bonus": false}
    default_bonus_rule = Column(
        JSONB,
        nullable=True,
        comment="Method-level default bonus rule (JSONB). NULL = bonus "
                "disabled fallback. Path-level override via "
                "AdmissionPath.bonus_rule_override."
    )

    # Relationships
    criteria = relationship(
        "AdmissionCriteria",
        back_populates="method",
        cascade="all, delete-orphan",
        order_by="AdmissionCriteria.id"
    )
    # NEW: Document groups that are method-specific
    document_groups = relationship(
        "DocumentGroup",
        back_populates="admission_method"
    )
    # NEW: Admission paths using this method
    admission_paths = relationship(
        "AdmissionPath",
        back_populates="admission_method"
    )

    def __repr__(self):
        return f"<AdmissionMethod {self.code}: {self.name}>"
