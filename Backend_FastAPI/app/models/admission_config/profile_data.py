# app/models/admission_config/profile_data.py
"""
Profile Data Models (Relational user input).

Replaces JSON fields in AdmissionProfile:
- admission_scores → ProfileSubjectScore
- documents_checklist → ProfileDocument
"""

from sqlalchemy import Column, Integer, String, ForeignKey, Numeric, DateTime, UniqueConstraint
from sqlalchemy.orm import relationship
from datetime import datetime, timezone

from app.models.base import Base


class ProfileSubjectScore(Base):
    """
    Điểm môn học do user nhập.
    
    Replaces: AdmissionProfile.admission_scores (JSONB)
    
    Example:
        profile_id: 1, subject_id: math, score: 8.5
        profile_id: 1, subject_id: physics, score: 7.0
    """
    __tablename__ = "profile_subject_score"

    id = Column(Integer, primary_key=True, index=True)
    profile_id = Column(
        Integer,
        ForeignKey("admission_profile.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    subject_id = Column(
        Integer,
        ForeignKey("subject.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    score = Column(
        Numeric(precision=3, scale=1),
        nullable=False,
        comment="Score 0.0 - 10.0"
    )
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
    profile = relationship("AdmissionProfile", back_populates="subject_scores")
    subject = relationship("Subject", back_populates="profile_scores")

    __table_args__ = (
        UniqueConstraint(
            "profile_id", "subject_id",
            name="uq_profile_subject_score"
        ),
    )

    def __repr__(self):
        return f"<ProfileSubjectScore profile={self.profile_id} subject={self.subject_id} score={self.score}>"


class ProfileDocument(Base):
    """
    Hồ sơ do user upload.
    
    Replaces: AdmissionProfile.documents_checklist (JSONB)
    
    Status lifecycle:
    - missing: Document not yet uploaded
    - uploaded: File uploaded, pending verification
    - verified: Document verified by admin
    - rejected: Document rejected (needs re-upload)
    """
    __tablename__ = "profile_document"

    id = Column(Integer, primary_key=True, index=True)
    profile_id = Column(
        Integer,
        ForeignKey("admission_profile.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    document_type_id = Column(
        Integer,
        ForeignKey("config_document_type.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    status = Column(
        String(20),
        nullable=False,
        default="missing",
        index=True,
        comment="missing | uploaded | verified | rejected | paper_submitted"
    )
    file_path = Column(
        String(500),
        nullable=True,
        comment="Path to uploaded file"
    )
    rejection_reason = Column(
        String(500),
        nullable=True,
        comment="Reason if rejected"
    )
    uploaded_at = Column(
        DateTime(timezone=True),
        nullable=True
    )
    verified_at = Column(
        DateTime(timezone=True),
        nullable=True
    )
    # Paper submission tracking (for documents that don't require upload)
    paper_submitted_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="When officer confirmed paper was received"
    )
    paper_submitted_by = Column(
        Integer,
        ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True,
        comment="Officer who confirmed paper receipt"
    )
    # Rejection tracking
    rejected_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="When document was rejected"
    )
    rejected_by = Column(
        Integer,
        ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True,
        comment="Officer who rejected"
    )

    # ✅ Finding 2.3: Document Internal Verification
    verified_format = Column(
        String(50),
        nullable=True,
        comment="original | certified_copy | photo"
    )

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
    profile = relationship("AdmissionProfile", back_populates="documents")
    document_type = relationship("ConfigDocumentType", back_populates="profile_documents")

    __table_args__ = (
        UniqueConstraint(
            "profile_id", "document_type_id",
            name="uq_profile_document"
        ),
    )

    def __repr__(self):
        return f"<ProfileDocument profile={self.profile_id} type={self.document_type_id} status={self.status}>"
