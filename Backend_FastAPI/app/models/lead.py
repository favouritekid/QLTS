# app/models/lead.py
import enum
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from .base import Base


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
    # Quick Disposition: Next activity timestamp for bubble-up sorting
    next_activity_at = Column(DateTime(timezone=True), nullable=True, index=True)
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

    def __repr__(self):
        return f"<Lead {self.id}: {self.full_name}>"


class Consultation(Base):
    """Model cho các buổi tư vấn."""

    __tablename__ = "consultation"

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
    officer_id = Column(Integer, ForeignKey("user.id"), nullable=False, index=True)  # ✅ FIX: Added index
    consultation_status_id = Column(
        String(50), ForeignKey("consultation_status.id"), nullable=True, index=True  # ✅ FIX: Added index
    )

    consultation_status = relationship("ConsultationStatus")
    officer = relationship(
        "User", back_populates="consultations_handled", foreign_keys=[officer_id]
    )
    lead = relationship("Lead", back_populates="consultations")


class Application(Base):
    """Model cho hồ sơ nhập học (Admission Profile).

    Lưu trữ thông tin hồ sơ tuyển sinh của thí sinh, bao gồm:
    - Ngành đào tạo, loại hình, phương thức xét tuyển
    - Điểm xét tuyển và checklist hồ sơ (JSON)
    - Trạng thái xử lý hồ sơ
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
