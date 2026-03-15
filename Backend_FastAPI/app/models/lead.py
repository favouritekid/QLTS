# app/models/lead.py
import enum
from datetime import datetime, timezone

from sqlalchemy import BigInteger, CheckConstraint, Index, JSON, Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import relationship

from .base import Base


class LeadValidityEnum(str, enum.Enum):
    """Lead validity/quality status — separate from lifecycle status."""
    raw = "raw"
    duplicate = "duplicate"
    invalid = "invalid"
    valid = "valid"
    qualified = "qualified"


class LeadCreatedViaEnum(str, enum.Enum):
    """How the lead was created."""
    manual = "manual"
    claim = "claim"
    import_ = "import"


class ConsultationMethodEnum(str, enum.Enum):
    """Method of consultation contact."""
    phone = "phone"
    email = "email"
    sms = "sms"
    video_call = "video_call"
    in_person = "in_person"


class LeadStatusEnum(str, enum.Enum):
    """Lead lifecycle status."""
    new = "new"
    assigned = "assigned"
    contacted = "contacted"
    qualified = "qualified"
    unqualified = "unqualified"
    converted = "converted"
    rejected = "rejected"


class LeadSourceEnum(str, enum.Enum):
    """Source where the lead came from."""
    website = "website"
    referral = "referral"
    social_media = "social_media"
    walk_in = "walk_in"
    email = "email"
    phone = "phone"
    event = "event"
    other = "other"


class EducationLevelEnum(str, enum.Enum):
    """Education level of the lead."""
    high_school = "high_school"
    diploma = "diploma"
    bachelor = "bachelor"
    master = "master"
    phd = "phd"
    other = "other"


class Lead(Base):
    """Model cho học viên tiềm năng (Lead)."""

    __tablename__ = "lead"
    __table_args__ = (
        CheckConstraint(
            "assignment_status IN ('pending', 'assigned', 'failed', 'reassign_pending')",
            name="ck_lead_assignment_status",
        ),
        # Composite performance indexes (created by perf20260126001, opt20260125002)
        Index('ix_lead_unit_status', 'unit_id', 'status'),
        Index('ix_lead_unit_officer', 'unit_id', 'assigned_officer_id'),
        Index('ix_lead_unit_stage', 'unit_id', 'pipeline_stage_id'),
        Index('ix_lead_unit_consultation_status', 'unit_id', 'consultation_status_id'),
        Index('ix_lead_unit_updated', 'unit_id', 'updated_at'),
        Index('ix_lead_unit_status_deleted', 'unit_id', 'status', 'deleted_at'),
        Index('ix_lead_deleted_score', 'deleted_at', 'lead_score'),
        Index('ix_lead_officer_deleted_updated', 'assigned_officer_id', 'deleted_at', 'updated_at'),
        Index('ix_lead_officer_status_deleted_activity', 'assigned_officer_id', 'status', 'deleted_at', 'next_activity_at', 'created_at'),
        Index('ix_lead_officer_hot_deleted_lastconsult', 'assigned_officer_id', 'is_hot_lead', 'deleted_at', 'last_consultation_at'),
        # Partial unique index (created by zj9p0q1r2s3t4)
        Index('uq_lead_email_unit_active', text('lower(email)'), 'unit_id', unique=True, postgresql_where=text('email IS NOT NULL AND deleted_at IS NULL')),
    )

    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String(255), nullable=False)
    email = Column(String(255), nullable=True, index=True)  # Email is optional
    phone = Column(String(20), nullable=False, index=True)
    phone2 = Column(String(20), nullable=True, index=True)  # Số điện thoại phụ
    source = Column(String(50), nullable=False)
    status = Column(String(50), nullable=False, default="new", index=True)
    # Assignment workflow status: pending, assigned, failed, reassign_pending
    assignment_status = Column(
        String(20),
        nullable=False,
        default="pending",
        index=True,
        comment="Assignment workflow: pending, assigned, failed, reassign_pending"
    )
    lead_score = Column(Integer, default=0, nullable=False)
    education_level = Column(String(100), nullable=True)
    gpa = Column(Float, nullable=True)
    location = Column(String(255), nullable=True)
    officer_rating = Column(Integer, nullable=True)
    officer_summary = Column(Text, nullable=True)
    # Fit Score fields
    birth_year = Column(Integer, nullable=True, comment="Năm sinh (VD: 2000)")
    location_proximity = Column(
        Integer,
        nullable=False,
        default=0,
        comment="Officer đánh giá: 0=Xa, 1=Lân cận, 2=Gần"
    )
    occupation_relevance = Column(
        Integer,
        nullable=False,
        default=0,
        comment="Officer đánh giá: 0=Không liên quan, 1=Gián tiếp, 2=Trực tiếp"
    )
    academic_performance = Column(
        Integer,
        nullable=False,
        default=0,
        comment="Học lực: 0=Yếu/Chưa xác định, 1=Trung bình, 2=Khá, 3=Giỏi"
    )
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
    assigned_at = Column(DateTime(timezone=True), nullable=True)
    # Soft delete support
    deleted_at = Column(DateTime(timezone=True), nullable=True, index=True)
    # Optimistic locking version
    version = Column(
        Integer,
        nullable=False,
        default=1,
        comment="Optimistic locking version - incremented on each update"
    )
    # Quick Disposition: Next activity timestamp for bubble-up sorting
    next_activity_at = Column(DateTime(timezone=True), nullable=True, index=True)
    
    # =========================================================================
    # CACHED METRICS (Lead Insights Upgrade)
    # Updated by LeadCacheService after consultation changes
    # =========================================================================
    last_consultation_at = Column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
        comment="Ngày tư vấn cuối cùng (auto-updated)"
    )
    consultation_count = Column(
        Integer,
        nullable=False,
        default=0,
        comment="Số lần tư vấn (auto-updated)"
    )
    cached_urgency_score = Column(
        Integer,
        nullable=False,
        default=50,
        index=True,
        comment="Điểm khẩn cấp 0-100 (auto-calculated)"
    )
    is_hot_lead = Column(
        Boolean,
        nullable=False,
        default=False,
        index=True,
        comment="Lead score >= 70"
    )
    is_overdue = Column(
        Boolean,
        nullable=False,
        default=False,
        index=True,
        comment="next_activity_at đã quá hạn"
    )
    # =========================================================================
    
    # NEW 3-TIER ARCHITECTURE: Link to ProgramOffering instead of Major
    offering_id = Column(Integer, ForeignKey("program_offering.id", ondelete="SET NULL"), nullable=True, index=True)
    unit_id = Column(Integer, ForeignKey("organization_unit.id"), nullable=False, index=True)  # ✅ FIX: Added index
    assigned_officer_id = Column(
        Integer, ForeignKey("user.id"), nullable=True, index=True
    )
    consultation_status_id = Column(
        String(50), ForeignKey("consultation_status.id"), nullable=True, index=True
    )
    pipeline_stage_id = Column(
        String(50), ForeignKey("pipeline_stage.id"), nullable=True, index=True
    )
    # Blacklist: Officers who have reassigned this lead (cannot receive it again)
    rejected_by_officer_ids = Column(
        JSON,
        nullable=True,
        default=list,
        comment="List of officer IDs who reassigned this lead - prevents reassignment back to them"
    )

    # =========================================================================
    # COLLABORATOR SYSTEM (Phase 1)
    # =========================================================================
    referrer_id = Column(
        Integer,
        ForeignKey("collaborator.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="CTV who referred this lead",
    )
    validity_status = Column(
        String(20),
        nullable=False,
        default="raw",
        server_default="raw",
        index=True,
        comment="Lead quality status: raw, duplicate, invalid, valid, qualified",
    )
    created_via = Column(
        String(20),
        nullable=False,
        default="manual",
        server_default="manual",
        comment="How lead was created: manual, claim, import",
    )

    pipeline_stage = relationship("PipelineStage", back_populates="leads")

    assigned_officer = relationship(
        "User", back_populates="leads_assigned", foreign_keys=[assigned_officer_id]
    )
    consultations = relationship(
        "Consultation", back_populates="lead", cascade="all, delete-orphan"
    )
    application = relationship(
        "Application",
        back_populates="lead",
        uselist=False,
        cascade="all, delete-orphan",
    )
    # NEW: AdmissionProfile (Replacement for Application)
    admission_profile = relationship(
        "AdmissionProfile",
        back_populates="lead",
        uselist=False,
        cascade="all, delete-orphan",
    )
    interactions = relationship(
        "CRMInteraction", back_populates="lead", cascade="all, delete-orphan"
    )
    assignment_logs = relationship(
        "AssignmentLog", back_populates="lead", cascade="all, delete-orphan"
    )
    # NEW 3-TIER ARCHITECTURE: Link to ProgramOffering instead of Major
    offering = relationship("ProgramOffering", back_populates="leads")
    unit = relationship("OrganizationUnit", back_populates="leads")
    consultation_status = relationship("ConsultationStatus", back_populates="leads")
    # Collaborator system
    referrer = relationship("Collaborator", back_populates="leads_referred")
    claims = relationship("LeadClaim", back_populates="lead", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Lead {self.id}: {self.full_name}>"


class Consultation(Base):
    """Model cho các buổi tư vấn."""

    __tablename__ = "consultation"
    __table_args__ = (
        # Composite performance indexes (created by opt20260125002, perf20260126001)
        Index('ix_consultation_lead_date', 'lead_id', 'consultation_date'),
        Index('ix_consultation_officer_date', 'officer_id', 'consultation_date'),
        Index('ix_consultation_officer_deleted', 'officer_id', 'deleted_at'),
        Index('ix_consultation_lead_status_deleted_scheduled', 'lead_id', 'consultation_status_id', 'deleted_at', 'scheduled_at'),
    )

    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(Integer, ForeignKey("lead.id"), nullable=False, index=True)
    consultation_date = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
    # Quick Disposition: Scheduled follow-up time
    scheduled_at = Column(DateTime(timezone=True), nullable=True, index=True)
    # Reminder notification sent flag (prevents duplicate reminders)
    reminder_sent = Column(Boolean, default=False, nullable=False, index=True)
    method = Column(String(50))
    notes = Column(Text)
    duration_minutes = Column(Integer, nullable=True)
    officer_id = Column(Integer, ForeignKey("user.id"), nullable=False, index=True)
    consultation_status_id = Column(
        String(50), ForeignKey("consultation_status.id"), nullable=True, index=True
    )
    # Record creation timestamp (for 24h edit window calculation)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    # Soft delete support - when parent lead is deleted, consultations are also soft-deleted
    deleted_at = Column(DateTime(timezone=True), nullable=True, index=True)

    consultation_status = relationship("ConsultationStatus")
    officer = relationship(
        "User", back_populates="consultations_handled", foreign_keys=[officer_id]
    )
    lead = relationship("Lead", back_populates="consultations")


class Application(Base):
    """
    DEPRECATED: Legacy admission model — do NOT use for new code.
    Use AdmissionProfile (app/models/admission.py) instead.
    This model maps to the 'application' table which may be dropped in a future migration.
    """

    __tablename__ = "application"

    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(Integer, ForeignKey("lead.id"), nullable=False, unique=True, index=True)

    # Foreign Keys liên kết đến 3-Tier Architecture
    major_program_id = Column(Integer, ForeignKey("major_program.id", ondelete="SET NULL"), nullable=True, index=True)
    program_offering_id = Column(Integer, ForeignKey("program_offering.id", ondelete="SET NULL"), nullable=True, index=True)
    criterion_id = Column(String(100), nullable=True, index=True)  # AdmissionCriterion.id (stored in JSON)

    # Trường JSON để lưu dữ liệu động
    # Structure: {"scores": {"Toan": 8.5, "Van": 7.0}, "checklist": [{code, label, status, submission_type, notes}]}
    documents = Column(JSON, nullable=True)

    # Trạng thái hồ sơ
    # Allowed values: pending, missing_documents, completed, passed, failed
    status = Column(String(50), nullable=False, default="pending", index=True)

    # Legacy field
    officer_id = Column(Integer, ForeignKey("user.id"), nullable=True, index=True)  # ✅ FIX: Added index

    # Timestamps
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

    # Soft delete support
    deleted_at = Column(DateTime(timezone=True), nullable=True, index=True)

    # Relationships
    officer = relationship(
        "User", back_populates="applications_handled", foreign_keys=[officer_id]
    )
    lead = relationship("Lead", back_populates="application")
    major_program = relationship("MajorProgram")
    program_offering = relationship("ProgramOffering")


class CRMInteraction(Base):
    """Model cho các tương tác CRM tự động."""

    __tablename__ = "crm_interaction"

    id = Column(Integer, primary_key=True)
    lead_id = Column(Integer, ForeignKey("lead.id"), nullable=False, index=True)  # ✅ FIX: Added index
    type = Column(String(50))
    details = Column(JSON)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    lead = relationship("Lead", back_populates="interactions")


class AssignmentLog(Base):
    """Model để ghi lại lịch sử phân công lead."""

    __tablename__ = "assignment_log"

    id = Column(Integer, primary_key=True)
    lead_id = Column(Integer, ForeignKey("lead.id"), nullable=False, index=True)  # ✅ FIX: Added index
    method = Column(String(50))
    timestamp = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    reason = Column(Text, nullable=True)
    officer_id = Column(Integer, ForeignKey("user.id"), nullable=False, index=True)  # ✅ FIX: Added index

    officer = relationship(
        "User", back_populates="assignment_logs_involved", foreign_keys=[officer_id]
    )
    lead = relationship("Lead", back_populates="assignment_logs")


class AssignmentDecisionLog(Base):
    """Assignment decision log for fairness analysis (v2.1 prep)."""
    __tablename__ = "assignment_decision_log"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    lead_id = Column(Integer, ForeignKey("lead.id", ondelete="CASCADE"), nullable=False, index=True)
    assigned_officer_id = Column(Integer, ForeignKey("user.id"), nullable=True, index=True)
    decision_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)

    # Context snapshot
    eligible_officer_ids = Column(ARRAY(Integer), nullable=False)
    channel = Column(String(50), nullable=True)
    unit_id = Column(Integer, ForeignKey("organization_unit.id"), nullable=True)

    # Scoring factors (snapshot, no FK)
    scores_snapshot = Column(JSONB, nullable=True)
    capacity_snapshot = Column(JSONB, nullable=True)

    # Result
    reason = Column(String(200), nullable=True)

    # Relationships
    lead = relationship("Lead", foreign_keys=[lead_id])
    assigned_officer = relationship("User", foreign_keys=[assigned_officer_id])

    def __repr__(self):
        return f"<AssignmentDecisionLog lead={self.lead_id} officer={self.assigned_officer_id}>"
