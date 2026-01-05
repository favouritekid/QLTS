# app/models/admission.py
"""
AdmissionProfile Model - Hồ sơ tuyển sinh (Replacement for Application).

Security Features:
- IDOR Protection: Always check lead.unit_id == current_user.unit_id
- Snapshot Pattern: applied_rules is immutable after creation (from ProgramOffering.admission_rules)
- Unique Constraints: citizen_id, lead_id (prevent duplicate enrollment)
- State Machine: draft -> approved/rejected -> enrolled

Architecture:
- Router: Transaction commit point
- Service: Business logic + IDOR checks
- Model: Data structure + relationships
"""

from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship, Mapped, mapped_column

from .base import Base


class AdmissionProfile(Base):
    """
    Hồ sơ tuyển sinh (Admission Profile).

    Workflow:
    1. CREATE: Officer creates profile -> snapshot admission_rules from ProgramOffering
    2. UPDATE: Officer updates profile (only when status = 'draft')
    3. SUBMIT: System validates against applied_rules -> auto-approve or return errors
    4. ENROLL: System creates Student + StudentDocument (ACID transaction)

    Security:
    - IDOR: Service checks lead.unit_id == current_user.unit_id
    - Snapshot: applied_rules never changes after creation
    - Unique: citizen_id prevents duplicate enrollment
    """
    __tablename__ = "admission_profile"

    # Primary Key
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    # Foreign Key to Lead (One-to-One relationship)
    lead_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("lead.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,  # One lead can only have one admission profile
        index=True,
        comment="Link to Lead (IDOR check point: lead.unit_id)"
    )
    
    # ✅ FK Traceability (Mandatory Requirement #1)
    # Links to source config for audit/debug/report
    offering_admission_config_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("offering_admission_config.id", ondelete="SET NULL"),
        nullable=True,  # Nullable for backward compatibility with existing profiles
        index=True,
        comment="Source config (audit/debug/report)"
    )

    # Applicant Identity (Must be unique across system)
    citizen_id: Mapped[str] = mapped_column(
        String(12),
        nullable=True,  # Can be null during draft, required for submit
        unique=True,  # Prevent duplicate enrollment with same citizen ID
        index=True,
        comment="CCCD/CMND number (12 digits)"
    )

    # Status (State Machine)
    # Allowed values: 'draft', 'approved', 'rejected', 'enrolled'
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="draft",
        index=True,
        comment="State: draft | approved | rejected | enrolled"
    )

    # =========================================================================
    # PERSONAL INFO EXTENSIONS
    # =========================================================================
    
    full_name: Mapped[str] = mapped_column(String(255), nullable=True)
    dob: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    gender: Mapped[str] = mapped_column(String(50), nullable=True, comment="Nam/Nữ/Khác")
    
    email: Mapped[str] = mapped_column(String(255), nullable=True)
    phone: Mapped[str] = mapped_column(String(20), nullable=True)
    
    social_insurance_number: Mapped[str] = mapped_column(String(50), nullable=True)
    
    # Linked to ConfigSystemCategory
    nationality: Mapped[str] = mapped_column(String(100), nullable=True)
    ethnicity: Mapped[str] = mapped_column(String(100), nullable=True)
    religion: Mapped[str] = mapped_column(String(100), nullable=True)
    disability_type: Mapped[str] = mapped_column(String(100), nullable=True)
    
    # Address
    permanent_province: Mapped[str] = mapped_column(String(100), nullable=True)
    permanent_district: Mapped[str] = mapped_column(String(100), nullable=True)
    permanent_ward: Mapped[str] = mapped_column(String(100), nullable=True)
    
    place_of_birth: Mapped[str] = mapped_column(String(255), nullable=True)
    native_place: Mapped[str] = mapped_column(String(255), nullable=True)
    
    # Political
    union_entry_date: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    party_entry_date: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    party_official_entry_date: Mapped[datetime] = mapped_column(DateTime, nullable=True)

    # =========================================================================


    # Optimistic Locking (Prevent Concurrent Modification)
    # Incremented on every update/submit
    # Service must check version matches before modifying
    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        comment="Optimistic locking version (incremented on update)"
    )

    # SNAPSHOT PATTERN (Security: Immutable Rules)
    # This is a snapshot of ProgramOffering.admission_rules AT CREATION TIME
    # NEVER query ProgramOffering during submit/evaluate - use this snapshot only
    applied_rules: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        comment="Snapshot of admission rules: {min_gpa, mandatory_docs[], admission_method}"
    )

    # Family Information (Array of FamilyMember objects)
    # Structure: [{relationship, full_name, occupation, phone}, ...]
    family_info: Mapped[list] = mapped_column(
        JSONB,
        nullable=True,
        default=list,
        comment="Array of family members"
    )

    # Academic History (Array of AcademicRecord objects)
    # Structure: [{school_name, year_from, year_to, gpa}, ...]
    academic_history: Mapped[list] = mapped_column(
        JSONB,
        nullable=True,
        default=list,
        comment="Array of academic records (schools attended)"
    )

    # Admission Scores (Single object)
    # Structure: {gpa, math_score, literature_score, ...}
    admission_scores: Mapped[dict] = mapped_column(
        JSONB,
        nullable=True,
        comment="Scores for admission evaluation"
    )

    # Documents Checklist (Array of DocumentItem objects)
    # Structure: [{code, label, status, file_path, uploaded_at}, ...]
    # Status values: 'missing', 'uploaded', 'verified', 'rejected'
    documents_checklist: Mapped[list] = mapped_column(
        JSONB,
        nullable=True,
        default=list,
        comment="Array of required documents with upload status"
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        comment="Profile creation time (UTC)"
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        comment="Last update time (UTC)"
    )

    # Relationships (Eager Loading to Prevent N+1 Queries)
    lead: Mapped["Lead"] = relationship(
        "Lead",
        back_populates="admission_profile",
        lazy="joined",  # Always load lead (for IDOR checks)
        foreign_keys=[lead_id]
    )

    student: Mapped["Student"] = relationship(
        "Student",
        back_populates="admission_profile",
        uselist=False,  # One-to-one
        cascade="all, delete-orphan"
    )
    
    # ✅ Phase 1: FK Traceability - link to source config
    offering_admission_config: Mapped["OfferingAdmissionConfig"] = relationship(
        "OfferingAdmissionConfig",
        back_populates="admission_profiles"
    )
    
    # ✅ Phase 1: Relational data (replaces JSON fields)
    subject_scores: Mapped[list] = relationship(
        "ProfileSubjectScore",
        back_populates="profile",
        cascade="all, delete-orphan",
        lazy="selectin"
    )
    documents: Mapped[list] = relationship(
        "ProfileDocument",
        back_populates="profile",
        cascade="all, delete-orphan",
        lazy="selectin"
    )

    def __repr__(self):
        return f"<AdmissionProfile {self.id}: Lead {self.lead_id}, Status: {self.status}>"

