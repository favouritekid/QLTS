# app/models/admission_config/profile_data.py
"""
Profile Data Models (Relational user input).

Replaces JSON fields in AdmissionProfile:
- admission_scores → ProfileSubjectScore
- documents_checklist → ProfileDocument
"""

from sqlalchemy import CheckConstraint, Column, Index, Integer, String, ForeignKey, Numeric, DateTime, UniqueConstraint, Text, BigInteger, text
from sqlalchemy.orm import backref, relationship
from sqlalchemy.dialects.postgresql import JSONB
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
        # Phase 2 v8.2 PR-2E — widened cho V-ACT/DGNL methods (max 1200).
        Numeric(precision=8, scale=2),
        nullable=False,
        comment="Score 0.0 - 1200.0 (V-ACT/DGNL); trad THPT 0-10"
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
    subject = relationship("Subject", back_populates="profile_scores", lazy="selectin")

    __table_args__ = (
        UniqueConstraint(
            "profile_id", "subject_id",
            name="uq_profile_subject_score"
        ),
        # Phase 2 v8.2 PR-2E — relaxed cho V-ACT/DGNL.
        CheckConstraint(
            "score >= 0",
            name="ck_profile_subject_score_non_negative"
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
        nullable=True,
        index=True,
        comment="FK ConfigDocumentType — required cho category='path', NULL cho category='priority_evidence'"
    )
    # Phase E.4 — phân biệt path documents vs priority_evidence (UT) documents
    category = Column(
        String(40),
        nullable=False,
        default="path",
        server_default="path",
        comment="path | priority_evidence"
    )
    # Phase E.4 — UT sub_code khi category='priority_evidence', NULL otherwise
    priority_sub_code = Column(
        String(2),
        nullable=True,
        comment="UT sub_code (e.g. '04','07') — chỉ set khi category='priority_evidence'"
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
    verified_by = Column(
        Integer,
        ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True,
        comment="Officer who verified the document"
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

    # ✅ Submission Format Tracking
    # User declares what type of document they are submitting
    actual_submission_format = Column(
        String(50),
        nullable=True,
        comment="Declared by user/officer at submission: original | certified_copy | photo"
    )

    # ✅ Finding 2.3: Document Internal Verification
    # Officer verifies the actual physical format (may differ from declared)
    verified_format = Column(
        String(50),
        nullable=True,
        comment="Verified by officer after inspection: original | certified_copy | photo"
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
        # Phase E.4 — partial unique indexes thay thế full uq_profile_document
        # vì priority_evidence rows có document_type_id=NULL (không apply unique
        # cho (profile_id, document_type_id) full table)
        Index(
            "uq_profile_document_path",
            "profile_id",
            "document_type_id",
            unique=True,
            postgresql_where=text("category = 'path'"),
        ),
        Index(
            "uq_profile_document_priority",
            "profile_id",
            "priority_sub_code",
            unique=True,
            postgresql_where=text("category = 'priority_evidence'"),
        ),
        CheckConstraint(
            "status IN ('missing','uploaded','verified','rejected','paper_submitted')",
            name="ck_profile_document_status"
        ),
        CheckConstraint(
            "category IN ('path','priority_evidence')",
            name="ck_profile_document_category"
        ),
        CheckConstraint(
            "(category = 'priority_evidence' AND priority_sub_code IS NOT NULL) "
            "OR (category <> 'priority_evidence' AND priority_sub_code IS NULL)",
            name="ck_priority_evidence_sub_code"
        ),
        # Phase E.4 q9_07_e4c — enforce legacy invariant cho path documents
        # post-relax document_type_id NOT NULL. priority_evidence rows
        # acceptable với document_type_id=NULL (no FK target).
        CheckConstraint(
            "category <> 'path' OR document_type_id IS NOT NULL",
            name="ck_path_requires_doc_type"
        ),
    )

    def __repr__(self):
        return f"<ProfileDocument profile={self.profile_id} type={self.document_type_id} status={self.status}>"


class DocumentAuditLog(Base):
    """
    Audit log for all document operations.

    Tracks:
    - Upload: who uploaded, original filename, file size
    - Verify: who verified, format confirmed
    - Reject: who rejected, reason
    - Reset: who reset, old status
    - Re-upload: old file path preserved

    Compliance: Maintains full history for regulatory requirements.
    """
    __tablename__ = "document_audit_log"

    id = Column(Integer, primary_key=True, index=True)

    # Link to document
    profile_document_id = Column(
        Integer,
        ForeignKey("profile_document.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    # Action details
    action = Column(
        String(50),
        nullable=False,
        index=True,
        comment="uploaded | verified | rejected | reset | paper_submitted | deleted | downloaded"
    )

    # Actor
    actor_user_id = Column(
        Integer,
        ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="User who performed the action"
    )

    # Status change
    old_status = Column(
        String(20),
        nullable=True,
        comment="Status before action"
    )
    new_status = Column(
        String(20),
        nullable=True,
        comment="Status after action"
    )

    # File tracking
    old_file_path = Column(
        String(500),
        nullable=True,
        comment="Previous file path (for re-uploads)"
    )
    new_file_path = Column(
        String(500),
        nullable=True,
        comment="New file path (for uploads)"
    )

    # Upload metadata
    original_filename = Column(
        String(255),
        nullable=True,
        comment="Original filename from user"
    )
    file_size_bytes = Column(
        BigInteger,
        nullable=True,
        comment="File size in bytes"
    )
    content_type = Column(
        String(100),
        nullable=True,
        comment="MIME type of uploaded file"
    )

    # Action details
    reason = Column(
        Text,
        nullable=True,
        comment="Reason for rejection/reset"
    )

    # Format tracking
    declared_format = Column(
        String(50),
        nullable=True,
        comment="User declared: original | certified_copy | photo"
    )
    verified_format = Column(
        String(50),
        nullable=True,
        comment="Officer verified: original | certified_copy | photo"
    )

    # Extra data (JSON)
    extra_data = Column(
        JSONB,
        nullable=True,
        default=dict,
        comment="Additional context data"
    )

    # Timestamp
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True
    )

    # Client context (for security audit)
    ip_address = Column(
        String(45),
        nullable=True,
        comment="Client IP address"
    )
    user_agent = Column(
        String(500),
        nullable=True,
        comment="Client user agent"
    )

    # Relationships
    # passive_deletes=True: let the DB-level ondelete="CASCADE" on the FK
    # handle deletion. Without this, SQLAlchemy walks the backref and tries
    # UPDATE SET NULL on profile_document_id — which violates the NOT NULL
    # constraint and crashes with IntegrityError. See Issue #108.
    profile_document = relationship(
        "ProfileDocument",
        backref=backref("audit_logs", passive_deletes=True),
    )
    actor = relationship("User", foreign_keys=[actor_user_id])

    __table_args__ = (
        CheckConstraint(
            "action IN ('uploaded','verified','rejected','reset','paper_submitted','deleted','downloaded')",
            name="ck_document_audit_log_action"
        ),
    )

    def __repr__(self):
        return f"<DocumentAuditLog doc={self.profile_document_id} action={self.action} at={self.created_at}>"
