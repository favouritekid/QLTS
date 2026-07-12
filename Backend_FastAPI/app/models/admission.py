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

from datetime import date, datetime, timezone
from typing import Any, List, Optional
from sqlalchemy import Boolean, CheckConstraint, Column, Date, Index, Integer, Numeric, SmallInteger, String, Text, DateTime, ForeignKey, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import ENUM, JSONB
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
        Index('ix_admission_profile_citizen_year', 'citizen_id', 'academic_year'),
        # Wave 3-E (M-1-15a) replaces the legacy single-profile-per-lead
        # UNIQUE on ``lead_id`` with a composite ``(lead_id, academic_year)``
        # UNIQUE so a lead can apply for multiple academic years (one
        # profile per year per lead). Migration owner:
        # ``alembic/versions/phase1_15a_drop_lead_id_unique_to_composite.py``.
        # Test DB (``Base.metadata.create_all``) reads this declaration —
        # keeping it in sync với migration prevents drift symptom per
        # memory ``test-db-schema-source``.
        UniqueConstraint('lead_id', 'academic_year', name='uq_admission_profile_lead_year'),
        # Wave 3-A (M-1-11) extended 10-state CHECK to 14-state, adding the
        # 4 choice-engine milestone states (reviewing / result_published /
        # admitted / waitlisted). PR-B extends it to 15-state, adding the
        # intermediate ``withdrawal_pending`` ("Chờ hoàn để rút") state.
        # Migration owners:
        # ``alembic/versions/phase1_11_extend_profile_status_check_constraint.py``
        # (14-state) and ``alembic/versions/wpend20260710_*.py`` (15-state).
        # Test DB (``Base.metadata.create_all()``) reads this declaration —
        # keeping it in sync with the migration prevents test-vs-prod drift.
        CheckConstraint(
            "status IN ('draft','submitted','approved','rejected','confirmed','enrolled','resubmitted','overridden','revision_requested','withdrawn','reviewing','result_published','admitted','waitlisted','withdrawal_pending')",
            name="ck_admission_profile_status"
        ),
        CheckConstraint(
            "confirmed_via IN ('magic_link','admin_override','officer') OR confirmed_via IS NULL",
            name="ck_admission_profile_confirmed_via"
        ),
        # Q9 #07 PR1 — area_resolution_basis enum CHECK (mirror of phase1_08b).
        # Catches typo 'highschool' vs 'high_school' at DB layer.
        CheckConstraint(
            "area_resolution_basis IS NULL OR area_resolution_basis IN "
            "('high_school', 'permanent_address_special', 'manual_override')",
            name="ck_admission_profile_area_resolution_basis"
        ),
        # Q9 #07 PR5 v1.3 (phase1_09) — Trình độ văn hóa enum CHECK.
        # Mirror migration constraint for Base.metadata.create_all() test DB.
        CheckConstraint(
            "cultural_education_level IS NULL OR cultural_education_level IN "
            "('completed_thcs', 'graduated_thcs', "
            "'completed_thpt', 'graduated_thpt', 'graduated_gdtx')",
            name="ck_admission_profile_cultural_education_level"
        ),
        # Q9 #07 PR5 v1.3 — Trình độ chuyên môn enum CHECK.
        CheckConstraint(
            "vocational_qualification IN "
            "('none', 'so_cap', 'trung_cap', 'cao_dang')",
            name="ck_admission_profile_vocational_qualification"
        ),
    )

    # Primary Key
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    # Foreign Key to Lead (One-to-One relationship)
    # Wave 3-E (M-1-15a) DROPPED the single-profile-per-lead UNIQUE
    # in favor of composite ``uq_admission_profile_lead_year`` declared
    # above. Lead can now hold one profile PER academic_year. Wave 4
    # Wave 4 PR #15b (M-1-15-model) flipped ``Lead.admission_profile``
    # (singular ``uselist=False``) to ``Lead.admission_profiles``
    # (plural list) — leads now hold one profile PER academic_year via
    # the composite UNIQUE ``uq_admission_profile_lead_year`` declared
    # in ``__table_args__`` above. The application contract is
    # multi-year per lead.
    lead_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("lead.id", ondelete="CASCADE"),
        nullable=False,
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

    # Phase 0 (M-P0a) — single owner of the DDL for this column.
    # Persisted forward-only at submit time so Phase 3 backfill of
    # `AdmissionProfileChoice` does not have to re-derive the chosen group.
    # Phase 1 #13 (`phase1_12_backfill_selected_subject_group_id`) fills
    # historical rows via the 3-rule decision tree and writes ambiguous
    # cases into `_admission_backfill_exceptions`. ``ondelete="SET NULL"``
    # mirrors `offering_admission_config_id` (FK-traceability convention)
    # — `subject_group` is catalog data with `is_active`; soft-retire is
    # the expected lifecycle, and hard delete should not erase submitted
    # profiles.
    selected_subject_group_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("subject_group.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment=(
            "Subject group chosen by candidate at submit time. "
            "Phase 0 owner; Phase 1 #13 backfills historical rows."
        ),
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
        server_default="'draft'",
        index=True,
        comment="State: draft | approved | rejected | enrolled"
    )

    # =========================================================================
    # PERSONAL INFO EXTENSIONS
    # =========================================================================
    
    full_name: Mapped[str] = mapped_column(String(255), nullable=True)
    dob: Mapped[date] = mapped_column(Date, nullable=True)
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
    # Sub-ward + street address — free-text. There is no national database
    # of sub-ward units (tổ dân phố / thôn / buôn / ấp / khóm / khu phố...);
    # naming varies by region (north/south/highland/Khmer areas) and tổ
    # numbers are renumbered as populations shift, so a structured lookup
    # is impractical for the QLTS scope. The CCCD form (mẫu CC01) uses
    # the same two-line free-text pattern.
    permanent_residential_group: Mapped[str] = mapped_column(
        String(150), nullable=True,
        comment="Tổ dân phố / Thôn / Buôn / Ấp / Khóm / Khu phố — community sub-unit, free-text"
    )
    permanent_street_address: Mapped[str] = mapped_column(
        String(255), nullable=True,
        comment="Số nhà, tên đường — street address line, free-text"
    )

    # =========================================================================
    # Q9 #07 Priority Bonus demographics
    # PR1 phase1_08b: initial cols (some dropped in phase1_09 — see below)
    # PR5 phase1_09: 2-field parallel (cultural + vocational) + snapshot
    # See Documents/Q9_07_PR5_REDESIGN.md v1.3 cho design rationale
    # =========================================================================

    # --- Trình độ văn hóa + chuyên môn (2-field parallel, v1.3 phase1_09) ---
    cultural_education_level: Mapped[Optional[str]] = mapped_column(
        String(30), nullable=True,
        comment=(
            "Trình độ văn hóa (phổ thông): completed_thcs | graduated_thcs | "
            "completed_thpt | graduated_thpt | graduated_gdtx. Nullable cho "
            "draft state; required tại submit T1."
        )
    )
    vocational_qualification: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="none",
        server_default=text("'none'"),
        comment=(
            "Trình độ chuyên môn (nghề nghiệp): none | so_cap | trung_cap | "
            "cao_dang. NOT NULL DEFAULT 'none' — auto fill legacy + new."
        )
    )
    # --- Permanent address resolution (BACKUP basis cho 4 special cases) ---
    permanent_commune_code: Mapped[Optional[str]] = mapped_column(
        String(20), nullable=True,
        comment="Loose ref to vn_commune_area_map.commune_code (no DB FK)"
    )
    area_resolution_basis: Mapped[Optional[str]] = mapped_column(
        String(40), nullable=True,
        comment="'high_school' | 'permanent_address_special' | 'manual_override'"
    )
    # NOTE: high_school_id + high_school_kv_resolved + area_resolution_reason
    # DROPPED trong phase1_09. KV result giờ live in priority_resolution_snapshot;
    # multi-school history live in academic_history JSONB.

    # --- UT đối tượng codes + evidence (TT 05/2021 Phụ lục 01 nhóm 01-07) ---
    priority_object_codes: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
        comment="Array of UT sub_codes thí sinh khai: ['04','06']"
    )
    priority_object_evidence: Mapped[dict[str, dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
        comment="{'04': {'document_id': 123, 'status': 'pending|verified|rejected', 'verified_by': 45, 'verified_at': '...', 'reject_reason': null}}"
    )
    # --- Priority resolution snapshot (v1.3 phase1_09 — Q-P3-11 pattern) ---
    priority_resolution_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
        comment=(
            "Frozen KV resolution at submit T1 + re-frozen at engine T6. "
            "Engine-set keys: {kv_resolved, rule_applied, pathway, breakdown, "
            "frozen_at, frozen_at_status, resolved_by, requires_manual_override, "
            "reason}. "
            "Phase E.2 manual override extends với: {manual_override_by, "
            "manual_override_at, manual_override_reason, evidence_file_id} — "
            "OVERWRITTEN with LAST override per chain-of-override semantics "
            "(Decision D1). Audit log preserves full chain history via "
            "priority_audit_log table. "
            "Empty {} = draft state (service computes real-time preview)."
        )
    )

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
        server_default="1",
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

    # Document debt (nợ giấy tờ) — fast-track prepay/giữ chỗ (C1).
    #
    # Snapshot captured ONCE when an officer submits a profile that is
    # otherwise eligible but still missing mandatory documents (the
    # "Nộp kèm nợ giấy tờ" flow). Shape:
    #   {"codes": [...], "reason": str, "by_user_id": int, "at": iso8601}
    #
    # ⚠️ DELIBERATELY a SEPARATE mutable column, NOT a key inside
    # ``applied_rules``. The ``prevent_applied_rules_update`` trigger
    # (ardockeys01) whitelists only 7 keys; any new applied_rules key
    # RAISEs on UPDATE. A standalone column has no such guard.
    #
    # The badge/count the FE renders is the COMPUTED
    # ``outstanding_debt_codes`` (this snapshot's codes ∩ docs still
    # missing now) — so once the officer uploads the owed docs the debt
    # self-resolves; this snapshot is retained only as an audit record of
    # "was once owed + why".
    document_debt: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        nullable=True,
        comment=(
            "Nợ giấy tờ snapshot {codes, reason, by_user_id, at} captured "
            "at staff submit-with-debt. NULL = no debt ever recorded. "
            "Separate column (NOT applied_rules) to dodge the immutability "
            "trigger."
        ),
    )

    # Family Information (Array of FamilyMember objects)
    # Structure: [{relationship, full_name, occupation, phone}, ...]
    family_info: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default="[]",
        comment="Array of family members"
    )

    # Academic History (Array of AcademicRecord objects)
    # Structure: [{school_name, year_from, year_to, gpa}, ...]
    academic_history: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default="[]",
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
        Text,
        nullable=True,
        comment="Optional approval notes from Manager/Admin"
    )

    # Phase E — post-approval survey (ZNS 426903) dedupe cursor.
    # survey_sent_at: set once when APPLICATION_SURVEY_DUE is dispatched,
    # primary filter for the daily scheduler (WHERE survey_sent_at IS NULL).
    # survey_tracking_id: UUID echoed back by Zalo user_feedback webhook to
    # correlate responses to the originating profile.
    survey_sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    survey_tracking_id: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
        unique=True,
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
        Text,
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

    # phase1_09a (#184 Wave 2 PR-2A) — eligibility scalars. 4
    # nullable columns. gpa_overall + graduation_year backfilled
    # from academic_history JSON via LATERAL + range guard;
    # conduct + health_category STAY NULL (no JSON source — admin
    # reviews qua UI Phase 1+2 per PLAN line 2813-2814).
    # Lock-after-draft trigger (phase1_09b) is DEFERRED Q1/2027
    # per Q9 chốt 2026-05-01; service guard provides basic
    # protection in 2026 cutover.
    gpa_overall: Mapped[Optional[float]] = mapped_column(
        Numeric(precision=4, scale=2),
        nullable=True,
        comment="Overall GPA (0.00..10.00). Backfilled from academic_history.",
    )
    conduct: Mapped[Optional[str]] = mapped_column(
        ENUM(
            "TB", "KHA", "TOT",
            name="conduct_grade",
            create_type=False,
        ),
        nullable=True,
        comment="Đạo đức (TB/KHA/TOT). NULL post-migration; admin UI Phase 1+2.",
    )
    health_category: Mapped[Optional[int]] = mapped_column(
        SmallInteger,
        nullable=True,
        comment="Phân loại sức khỏe (1..4 — 1 tốt nhất). NULL post-migration.",
    )
    graduation_year: Mapped[Optional[int]] = mapped_column(
        SmallInteger,
        nullable=True,
        comment="Năm tốt nghiệp (1900..2100). Backfilled from MAX(year_to).",
    )

    # phase1_08 (#184 Wave 1 PR-1D) — multi-NV gate. Determines
    # whether this profile flows through the legacy single-NV
    # ProfileSubjectScore engine (false) or the Phase 3 multi-NV
    # AdmissionProfileChoice + ProfileChoiceScore engine (true).
    # PLAN line 821-826: must be an explicit flag (not inferred
    # from count(choices)) because Phase 3 backfill creates one
    # choice per existing profile, after which count >= 1 for
    # every row and can no longer distinguish legacy from new.
    uses_choice_engine: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        comment=(
            "Phase 3 multi-NV gate. false = legacy single-NV "
            "ProfileSubjectScore flow; true = AdmissionProfileChoice "
            "+ ProfileChoiceScore flow."
        ),
    )

    # Relationships (Eager Loading to Prevent N+1 Queries)
    lead: Mapped["Lead"] = relationship(
        "Lead",
        back_populates="admission_profiles",
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

    # phase3_01 (#184 Wave 3 PR-3A) — multi-NV Phase 3.
    # Active khi uses_choice_engine=true (legacy profiles có 0 choices,
    # KHÔNG flow qua engine xét tuyển này). Cascade delete-orphan đảm bảo
    # cleanup choices + scores khi profile xoá (matches FK ON DELETE
    # CASCADE migration).
    choices: Mapped[list["AdmissionProfileChoice"]] = relationship(
        "AdmissionProfileChoice",
        back_populates="profile",
        cascade="all, delete-orphan",
        order_by="AdmissionProfileChoice.display_order",
        lazy="select",  # Engine query via selectinload explicit (GAP-22)
    )

    # ✅ FIX #6: Audit trail relationships
    approved_by: Mapped["User"] = relationship(
        "User",
        foreign_keys=[approved_by_id],
        lazy="selectin",
        uselist=False
    )
    rejected_by: Mapped["User"] = relationship(
        "User",
        foreign_keys=[rejected_by_id],
        lazy="selectin",
        uselist=False
    )
    # ✅ Revision request audit relationship
    revision_requested_by: Mapped[Optional["User"]] = relationship(
        "User",
        foreign_keys=[revision_requested_by_id],
        lazy="selectin",
        uselist=False
    )
    # ✅ Resubmit audit relationship
    resubmitted_by: Mapped[Optional["User"]] = relationship(
        "User",
        foreign_keys=[resubmitted_by_id],
        lazy="selectin",
        uselist=False
    )
    # ✅ Override audit relationship
    overridden_by: Mapped[Optional["User"]] = relationship(
        "User",
        foreign_keys=[overridden_by_id],
        lazy="selectin",
        uselist=False
    )
    # ✅ Confirmed by relationship
    confirmed_by: Mapped[Optional["User"]] = relationship(
        "User",
        foreign_keys=[confirmed_by_id],
        lazy="selectin",
        uselist=False
    )
    # ✅ Drop-out audit relationship
    dropped_by: Mapped[Optional["User"]] = relationship(
        "User",
        foreign_keys=[dropped_by_id],
        lazy="selectin",
        uselist=False
    )
    # ✅ FIX #8: Assignment relationship
    assigned_reviewer: Mapped["User"] = relationship(
        "User",
        foreign_keys=[assigned_reviewer_id],
        lazy="selectin",
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

    # Wave 3-D (M-1-18) extends single-action token to multi-action.
    # Migration owner:
    # ``alembic/versions/phase1_18_extend_confirmation_token_for_multi_action.py``.
    # CheckConstraint locks the 4-action enum at the test DB layer
    # (Base.metadata.create_all) so test rows that fail the contract
    # surface here just like prod. Partial UNIQUE index keeps audit
    # trail rows (already-confirmed) free from contention with newly-
    # issued tokens for the same (profile_id, action_type) pair.
    __table_args__ = (
        CheckConstraint(
            "action_type IN ('submit','resubmit','confirm','withdraw')",
            name="ck_token_action_type",
        ),
        Index(
            "uq_active_token_per_profile_action",
            "profile_id",
            "action_type",
            unique=True,
            postgresql_where=text("confirmed_at IS NULL"),
        ),
        Index("ix_token_action_type", "token", "action_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # Link to AdmissionProfile. Wave 3-D (PR Wave 3-D) DROPPED the
    # single-token-per-profile UNIQUE in favor of the partial UNIQUE
    # ``uq_active_token_per_profile_action`` declared above — every
    # profile may now hold ONE active token PER action_type.
    profile_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("admission_profile.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Wave 3-D (M-1-18) — multi-action token. 4 values locked by the
    # ``ck_token_action_type`` CHECK declared in ``__table_args__``
    # above. Default ``'confirm'`` preserves legacy single-action
    # behavior on legacy rows; new code paths set ``submit`` /
    # ``resubmit`` / ``withdraw`` explicitly.
    action_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="confirm",
        server_default=text("'confirm'"),
        comment="Token action: submit | resubmit | confirm | withdraw",
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

    # ADM-023 (2026-04-29): hybrid cooldown ladder.
    # ``locked_at`` is the HARD lock (≥30 fails — admin must reset).
    # ``lock_until`` is the SLIDING cooldown end set on every failed
    # attempt — request retry rejected with retry_at while NOW() <
    # lock_until. Cooldown duration scales with attempt_count per the
    # ladder in ``admission_confirmation_cooldown.cooldown_minutes_for``.
    lock_until: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Sliding cooldown end. NULL when no cooldown active.",
    )
    lock_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="How many times this token has been hard-locked (≥1 = require admin reset).",
    )

    # ADM-028 (2026-04-29): reminder beat dedupe markers. Beat task
    # scans for tokens approaching expiry and emits ``ADMISSION_
    # CONFIRMATION_REMINDER_*`` notifications; these timestamps stop
    # double-sends if the beat tick overruns or the task retries.
    reminder_24h_sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Set when the 24h-before-expiry reminder has been dispatched.",
    )
    reminder_6h_sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Set when the 6h-before-expiry reminder has been dispatched.",
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
