# app/models/admission_config/criteria.py
"""
Admission Criteria Models.

Tables:
- AdmissionCriteria: Specific criteria under a method (min_score, min_gpa)
- CriteriaSubjectGroup: Join table linking criteria to allowed subject groups
"""

from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, Numeric, Text, UniqueConstraint, CheckConstraint
from sqlalchemy.orm import relationship

from app.models.base import Base


class AdmissionCriteria(Base):
    """
    Tiêu chí xét tuyển cụ thể.
    
    Belongs to an AdmissionMethod.
    
    Examples:
        - code: "HB2026_CQ", method: hoc_ba, min_gpa: 6.0
        - code: "THPTQG2026_CQ", method: thpt_qg, min_score: 15.0
    """
    __tablename__ = "admission_criteria"

    id = Column(Integer, primary_key=True, index=True)
    method_id = Column(
        Integer,
        ForeignKey("admission_method.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    code = Column(
        String(50),
        nullable=False,
        unique=True,
        index=True,
        comment="Criteria code: HB2026_CQ, THPTQG2026_LT"
    )
    name = Column(
        String(255),
        nullable=False,
        comment="Display name: Xét học bạ 2026 - Chính quy"
    )
    min_gpa = Column(
        Numeric(precision=3, scale=1),
        nullable=True,
        comment="Minimum GPA (0.0 - 10.0)"
    )
    min_score = Column(
        Numeric(precision=4, scale=1),
        nullable=True,
        comment="Minimum total score (0.0 - 30.0)"
    )
    conditions = Column(
        Text,
        nullable=True,
        comment="Additional conditions/notes"
    )
    is_active = Column(
        Boolean,
        nullable=False,
        default=True,
        index=True
    )

    # =========================================================================
    # RULE ENGINE FIELDS (Critical fix: Enable 1-2-N subject flexibility)
    # =========================================================================
    
    # Number of subjects required (NULL = use all available)
    required_subject_count = Column(
        Integer,
        nullable=True,
        comment="Số môn bắt buộc: 1, 2, 3, hoặc NULL (flexible/xét tất cả)"
    )
    
    # How to select subjects from the pool
    subject_selection_mode = Column(
        String(20),
        nullable=False,
        default="fixed",
        comment="fixed | best_n | any_n - Cách chọn môn từ pool"
        # fixed: chọn đúng N môn trong tổ hợp đã đăng ký
        # best_n: chọn N môn điểm cao nhất trong pool
        # any_n: chọn bất kỳ N môn trong pool
    )
    
    # How to calculate final score
    scoring_method = Column(
        String(20),
        nullable=False,
        default="sum",
        comment="sum | average | weighted - Cách tính điểm"
    )
    
    # Maximum possible score (for normalization/display)
    max_possible_score = Column(
        Numeric(precision=5, scale=2),
        nullable=True,
        comment="Điểm tối đa: 30.0 (3 môn), 20.0 (2 môn), 10.0 (1 môn)"
    )
    
    # Optional: minimum score per subject (quy chế đặc thù)
    min_subject_score = Column(
        Numeric(precision=3, scale=1),
        nullable=True,
        comment="Điểm tối thiểu mỗi môn (vd: không môn nào dưới 1.0)"
    )

    # Relationships
    method = relationship("AdmissionMethod", back_populates="criteria")
    subject_group_mappings = relationship(
        "CriteriaSubjectGroup",
        back_populates="criteria",
        cascade="all, delete-orphan"
    )
    offering_configs = relationship(
        "OfferingAdmissionConfig",
        back_populates="criteria",
        cascade="all, delete-orphan"
    )

    # =========================================================================
    # CHECK CONSTRAINTS (Enforce ENUM values - prevent typo bugs)
    # =========================================================================
    __table_args__ = (
        CheckConstraint(
            "subject_selection_mode IN ('fixed', 'best_n', 'any_n')",
            name="ck_criteria_selection_mode"
        ),
        CheckConstraint(
            "scoring_method IN ('sum', 'average', 'weighted')",
            name="ck_criteria_scoring_method"
        ),
        # Logic guard: NULL + fixed is invalid (must specify count for fixed mode)
        # Note: This is enforced at service layer for flexibility
        # CheckConstraint(
        #     "NOT (required_subject_count IS NULL AND subject_selection_mode = 'fixed')",
        #     name="ck_criteria_fixed_requires_count"
        # ),
    )

    def __repr__(self):
        return f"<AdmissionCriteria {self.code}: {self.name}>"


class CriteriaSubjectGroup(Base):
    """
    Join table: Criteria uses SubjectGroup.
    
    Links which subject groups are allowed for a criteria.
    
    Example:
        Criteria "HB2026_CQ" allows: A00, A01, D01
    """
    __tablename__ = "criteria_subject_group"

    id = Column(Integer, primary_key=True, index=True)
    criteria_id = Column(
        Integer,
        ForeignKey("admission_criteria.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    subject_group_id = Column(
        Integer,
        ForeignKey("subject_group.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    # Relationships
    criteria = relationship("AdmissionCriteria", back_populates="subject_group_mappings")
    subject_group = relationship("SubjectGroup", back_populates="criteria_mappings")

    __table_args__ = (
        UniqueConstraint(
            "criteria_id", "subject_group_id",
            name="uq_criteria_subject_group"
        ),
    )

    def __repr__(self):
        return f"<CriteriaSubjectGroup criteria={self.criteria_id} group={self.subject_group_id}>"
