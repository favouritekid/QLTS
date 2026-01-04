# app/models/admission_config/method.py
"""
Admission Method Model.

Represents admission methods like:
- hoc_ba: Xét học bạ THPT
- thpt_qg: Xét điểm thi THPT Quốc gia
- dgnl: Xét đánh giá năng lực
"""

from sqlalchemy import Column, Integer, String, Boolean, Text
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

    # Relationships
    criteria = relationship(
        "AdmissionCriteria",
        back_populates="method",
        cascade="all, delete-orphan",
        order_by="AdmissionCriteria.id"
    )

    def __repr__(self):
        return f"<AdmissionMethod {self.code}: {self.name}>"
