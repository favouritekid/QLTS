# app/models/admission.py
"""
AdmissionProfile Model - Hồ sơ tuyển sinh (Replacement for Application).

Security Features:
- IDOR Protection: Always check lead.unit_id == current_user.unit_id
- Snapshot Pattern: applied_rules is immutable after creation (from AdmissionPath + DocumentGroup)
- Unique Constraints: citizen_id, lead_id (prevent duplicate enrollment)
- State Machine: draft -> approved/rejected -> enrolled

Architecture:
- Router: Transaction commit point
- Service: Business logic + IDOR checks
- Model: Data structure + relationships
"""

from datetime import datetime, timezone
from typing import List, Optional
from sqlalchemy import Boolean, Column, Integer, String, Text, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship, Mapped, mapped_column

from .base import Base


class AdmissionProfile(Base):
    """
    Hồ sơ tuyển sinh (Admission Profile).

    Workflow:
    1. CREATE: Officer creates profile -> snapshot rules from AdmissionPath + DocumentGroup
    2. UPDATE: Officer updates profile (only when status = 'draft')
    3. SUBMIT: System validates against applied_rules -> auto-approve or return errors
    4. ENROLL: System creates Student + StudentDocument (ACID transaction)

    Security:
    - IDOR: Service checks lead.unit_id == current_user.unit_id
    - Snapshot: applied_rules never changes after creation
    - Unique: (citizen_id, academic_year) prevents duplicate enrollment per year
    """
    __tablename__ = "admission_profile"
    
    # ✅ Composite Unique Constraints
    __table_args__ = (
        UniqueConstraint('citizen_id', 'academic_year', name='uq_citizen_academic_year'),
    )

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

    # ✅ Academic Year (for multi-year admission support)
    # Allows same citizen to apply in different years
    # Copied from OfferingAcademicInfo at profile creation time (snapshot pattern)
    academic_year: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        index=True,
        comment="Academic year (e.g., 2025, 2026) - snapshotted at creation"
    )

    # Applicant Identity (Unique per academic year)
    # ✅ CHANGED: From UNIQUE(citizen_id) to UNIQUE(citizen_id, academic_year)
    # This allows same person to apply in different years
    citizen_id: Mapped[str] = mapped_column(
        String(12),
        nullable=True,  # Can be null during draft, required for submit
        index=True,  # Removed unique=True, composite constraint in __table_args__
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
    # This is a snapshot of AdmissionPath + DocumentGroup rules AT CREATION TIME
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

    # =========================================================================
    # ANALYTICS FIELDS (State Transition Tracking)
    # =========================================================================

    # ✅ FIX #6: Approval tracking (for audit trail)
    approved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
        comment="Timestamp when profile was approved by Manager/Admin"
    )
    approved_by_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True,
        comment="User ID who approved the profile (Manager/Admin)"
    )
    approval_notes: Mapped[str] = mapped_column(
        String(1000),
        nullable=True,
        comment="Optional approval notes from Manager/Admin"
    )

    # ✅ FIX #6: Rejection tracking (for audit trail)
    rejected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
        comment="Timestamp when profile was rejected by Manager/Admin"
    )
    rejected_by_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True,
        comment="User ID who rejected the profile (Manager/Admin)"
    )
    rejection_reason: Mapped[str] = mapped_column(
        String(1000),
        nullable=True,
        comment="Rejection reason (required when rejecting)"
    )

    # Revision request tracking (REVISION_REQUESTED state - separate from rejection)
    revision_requested_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
        comment="Timestamp when revision was requested"
    )
    revision_requested_by_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True,
        comment="User ID who requested revision (Manager/Admin)"
    )
    revision_reason: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True,
        comment="Reason/instructions for revision request"
    )

    # ✅ Resubmit audit fields (REJECTED → RESUBMITTED tracking)
    resubmitted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Timestamp when profile was resubmitted by Officer"
    )
    resubmitted_by_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True,
        comment="User ID who resubmitted the profile (Officer)"
    )
    resubmit_notes: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Notes about what was fixed before resubmit"
    )

    # ✅ Override audit fields (Admin override tracking)
    overridden_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Timestamp when profile was overridden by Admin"
    )
    overridden_by_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True,
        comment="Admin ID who overrode the profile"
    )
    override_reason: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Reason for admin override"
    )

    # ✅ Confirmation tracking - who confirmed
    confirmed_by_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True,
        comment="User ID who confirmed enrollment (applicant or admin)"
    )

    # ✅ FIX #8: Assignment Workflow (Reviewer Assignment)
    # Allows tracking "Who is reviewing this profile?"
    # Prevents multiple managers from reviewing the same profile simultaneously
    assigned_reviewer_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="Assigned Manager/Reviewer ID"
    )
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Timestamp when profile was assigned/claimed"
    )

    # Confirmation tracking for statistics/reporting
    confirmed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,  # Index for fast date range queries
        comment="Timestamp when lead confirmed enrollment"
    )
    confirmed_via: Mapped[str] = mapped_column(
        String(20),
        nullable=True,
        comment="Confirmation method: 'magic_link', 'admin_override', 'officer'"
    )

    # Drop-out tracking (side-channel, status stays "enrolled")
    is_dropped: Mapped[Optional[bool]] = mapped_column(
        Boolean, default=False, server_default="false",
        comment="Whether enrolled student has dropped out"
    )
    dropped_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
        comment="Timestamp when student dropped out"
    )
    dropped_by_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True,
        comment="User ID who marked student as dropped"
    )
    dropped_reason: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True,
        comment="Reason for dropping out"
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
        cascade="all, delete-orphan",
        lazy="selectin",  # ✅ FIX: Eager load to prevent MissingGreenlet in async
    )

    # ✅ FIX #6: Audit trail relationships
    approved_by: Mapped["User"] = relationship(
        "User",
        foreign_keys=[approved_by_id],
        lazy="select",
        uselist=False
    )
    rejected_by: Mapped["User"] = relationship(
        "User",
        foreign_keys=[rejected_by_id],
        lazy="select",
        uselist=False
    )
    # ✅ Revision request audit relationship
    revision_requested_by: Mapped[Optional["User"]] = relationship(
        "User",
        foreign_keys=[revision_requested_by_id],
        lazy="select",
        uselist=False
    )
    # ✅ Resubmit audit relationship
    resubmitted_by: Mapped[Optional["User"]] = relationship(
        "User",
        foreign_keys=[resubmitted_by_id],
        lazy="select",
        uselist=False
    )
    # ✅ Override audit relationship
    overridden_by: Mapped[Optional["User"]] = relationship(
        "User",
        foreign_keys=[overridden_by_id],
        lazy="select",
        uselist=False
    )
    # ✅ Confirmed by relationship
    confirmed_by: Mapped[Optional["User"]] = relationship(
        "User",
        foreign_keys=[confirmed_by_id],
        lazy="select",
        uselist=False
    )
    # ✅ Drop-out audit relationship
    dropped_by: Mapped[Optional["User"]] = relationship(
        "User",
        foreign_keys=[dropped_by_id],
        lazy="select",
        uselist=False
    )
    # ✅ FIX #8: Assignment relationship
    assigned_reviewer: Mapped["User"] = relationship(
        "User",
        foreign_keys=[assigned_reviewer_id],
        lazy="select",
        uselist=False
    )

    # ✅ Phase 1: FK Traceability - link to source config
    offering_admission_config: Mapped["OfferingAdmissionConfig"] = relationship(
        "OfferingAdmissionConfig",
        back_populates="admission_profiles"
    )
    
    # ✅ Phase 1: Relational data (replaces JSON fields)
    subject_scores: Mapped[List["ProfileSubjectScore"]] = relationship(
        "ProfileSubjectScore",
        back_populates="profile",
        cascade="all, delete-orphan",
        lazy="selectin"
    )
    documents: Mapped[List["ProfileDocument"]] = relationship(
        "ProfileDocument",
        back_populates="profile",
        cascade="all, delete-orphan",
        lazy="selectin"
    )
    
    # Magic Link Confirmation Token
    confirmation_token: Mapped["AdmissionConfirmationToken"] = relationship(
        "AdmissionConfirmationToken",
        back_populates="profile",
        uselist=False,
        cascade="all, delete-orphan"
    )

    # Finance Module: Fee relationship (Phase 0+1)
    fees: Mapped[List["Fee"]] = relationship(
        "Fee",
        back_populates="admission_profile",
        cascade="all, delete-orphan",
        lazy="selectin"  # Eager load for fee summary calculations
    )

    def __repr__(self):
        return f"<AdmissionProfile {self.id}: Lead {self.lead_id}, Status: {self.status}>"


class AdmissionConfirmationToken(Base):
    """
    Magic link token for admission confirmation.
    
    Security Features:
    - Token is URL-safe random string (256-bit entropy)
    - One-time use (confirmed_at marks as used)
    - Expires after configurable days (default: 7)
    - CCCD verification required (last 4 digits)
    - Max attempts before lockout (default: 5)
    
    Workflow:
    1. Profile approved → Generate token → Send email with link
    2. Lead clicks link → Enter last 4 CCCD digits
    3. If correct → Confirm profile, mark token used
    4. If wrong → Increment attempts, lock if exceeded
    """
    __tablename__ = "admission_confirmation_token"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    
    # Link to AdmissionProfile (one token per profile)
    profile_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("admission_profile.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,  # One active token per profile
        index=True
    )
    
    # The actual token value (sent in email link)
    token: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        unique=True,
        index=True,
        comment="URL-safe random token (256-bit)"
    )
    
    # Token expiration
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="Token expiration timestamp"
    )
    
    # Confirmation timestamp (null = not used yet)
    confirmed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="When confirmation was completed"
    )
    
    # CCCD verification attempts
    attempt_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="Failed CCCD verification attempts"
    )
    
    # Lock timestamp (null = not locked)
    locked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Locked after max failed attempts"
    )
    
    # Creation timestamp
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc)
    )

    # Relationship back to profile
    profile: Mapped["AdmissionProfile"] = relationship(
        "AdmissionProfile",
        back_populates="confirmation_token"
    )

    def __repr__(self):
        return f"<AdmissionConfirmationToken {self.id}: Profile {self.profile_id}, Used: {self.confirmed_at is not None}>"
