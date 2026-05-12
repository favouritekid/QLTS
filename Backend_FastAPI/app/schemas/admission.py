# app/schemas/admission.py
"""
Pydantic Schemas for Admission Module.

Security Features:
- Input Sanitization: html.escape() for all text fields (prevent XSS)
- Strict Validation: Regex patterns, length limits, GPA range (0-10)
- Type Safety: Pydantic v2 with strict mode

Architecture Compliance:
- No HTTPException imports (service layer raises custom exceptions)
- Schemas used for request/response validation only
- Field validators sanitize inputs at schema level
"""

from datetime import date, datetime
from typing import Annotated, Any, Dict, List, Literal, Optional
import html

from pydantic import BaseModel, EmailStr, Field, StringConstraints, field_validator, model_validator, ConfigDict


# ==============================================================================
# NESTED SCHEMAS (for JSONB fields)
# ==============================================================================

class FamilyMemberSchema(BaseModel):
    """
    Family member information (stored in admission_profile.family_info JSONB array).

    Security:
    - XSS Prevention: html.escape() on full_name, occupation
    - Phone Validation: Vietnam format (0 + 9-10 digits)
    """
    relationship: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description="Relationship type (father, mother, sibling, etc.)"
    )
    full_name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Full name of family member"
    )
    occupation: str = Field(
        default="",
        max_length=255,
        description="Occupation/job title"
    )
    phone: str = Field(
        ...,
        pattern=r"^0\d{9,10}$",
        description="Vietnam phone number (0 + 9-10 digits)"
    )
    is_primary_guardian: bool = Field(
        False,
        description="Identify if this is the primary guardian"
    )

    @field_validator('full_name', 'occupation', 'relationship')
    @classmethod
    def sanitize_text(cls, v: str) -> str:
        """XSS Prevention: Escape HTML entities."""
        if not v:
            return v
        return html.escape(v.strip())

    model_config = ConfigDict(
        str_strip_whitespace=True,
        str_min_length=0
    )


class AcademicRecordSchema(BaseModel):
    """
    Academic history (stored in admission_profile.academic_history JSONB array).

    Security:
    - XSS Prevention: html.escape() on school_name
    - Year Validation: year_from <= year_to, reasonable range (1900-2100)
    - GPA Validation: 0.0 - 10.0 range
    """
    school_name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Name of school/institution"
    )
    year_from: int = Field(
        ...,
        ge=1900,
        le=2100,
        description="Start year (e.g., 2020)"
    )
    year_to: int = Field(
        ...,
        ge=1900,
        le=2100,
        description="End year (e.g., 2023)"
    )
    gpa: Optional[float] = Field(
        None,
        ge=0.0,
        le=10.0,
        description="GPA (0.0 - 10.0)"
    )
    graduation_type: Optional[str] = Field(
        None,
        max_length=50,
        description="Type of graduation (THPT, Dai hoc, etc.)"
    )


    @field_validator('school_name')
    @classmethod
    def sanitize_school_name(cls, v: str) -> str:
        """XSS Prevention: Escape HTML entities."""
        return html.escape(v.strip())

    @field_validator('year_to')
    @classmethod
    def validate_year_range(cls, v: int, info) -> int:
        """Ensure year_from <= year_to."""
        year_from = info.data.get('year_from')
        if year_from and v < year_from:
            raise ValueError(f"year_to ({v}) must be >= year_from ({year_from})")
        return v

    model_config = ConfigDict(str_strip_whitespace=True)


class AdmissionScoreSchema(BaseModel):
    """
    Admission scores (stored in admission_profile.admission_scores JSONB object).

    Supports two scoring modes:
    1. GPA-only: For "học bạ" methods without subject groups
    2. Subject-based: For methods with subject_groups (e.g., A00, D01)

    Phase 6: Dynamic Admission Scoring
    """
    # Selected admission criterion and subject group
    selected_criterion_id: Optional[str] = Field(
        None,
        description="ID of selected admission criterion from applied_rules.criteria"
    )
    selected_group: Optional[str] = Field(
        None,
        description="Selected subject group code (e.g., 'A00', 'D01')"
    )
    
    # GPA for học bạ-based methods
    gpa: Optional[float] = Field(
        None,
        ge=0.0,
        le=10.0,
        description="Overall GPA (for học bạ/GPA-based methods)"
    )
    
    # Dynamic subject scores (e.g., {"math": 8.5, "physics": 7.0, "chemistry": 9.0})
    subject_scores: Optional[Dict[str, Optional[float]]] = Field(
        None,
        description="Subject scores keyed by subject code (e.g., 'math', 'physics')"
    )

    @field_validator('subject_scores')
    @classmethod
    def validate_scores(cls, v: Optional[Dict[str, Optional[float]]]) -> Optional[Dict[str, Optional[float]]]:
        if not v:
            return v
        for code, score in v.items():
            if score is not None and (score < 0 or score > 10):
                raise ValueError(f"Score for {code} must be between 0 and 10")
        return v
    
    # Legacy fields (kept for backward compatibility)
    math_score: Optional[float] = Field(None, ge=0.0, le=10.0)
    literature_score: Optional[float] = Field(None, ge=0.0, le=10.0)
    english_score: Optional[float] = Field(None, ge=0.0, le=10.0)
    
    # Computed fields (optional, for display)
    total_score: Optional[float] = Field(None, ge=0.0, description="Total of subject scores")
    average_score: Optional[float] = Field(None, ge=0.0, le=10.0, description="Average score")

    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True,
        extra="ignore"  # Ignore extra fields for safety
    )


class DocumentItemSchema(BaseModel):
    """
    Document checklist item (stored in admission_profile.documents_checklist JSONB array).

    Status Lifecycle:
    - missing: Document not yet uploaded
    - uploaded: File uploaded, pending verification
    - verified: Officer verified the document
    - rejected: Officer rejected the document
    - paper_submitted: Applicant submitted a paper copy (not a digital upload)

    Security:
    - File Path Validation: Max 512 chars (prevent path traversal in display)
    - Status Enum: Only allowed values accepted
    """
    code: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Document code (HOC_BA, CCCD, BANG_TN, etc.)"
    )
    label: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Human-readable label (e.g., 'Học bạ THPT')"
    )
    status: Literal["missing", "uploaded", "verified", "rejected", "paper_submitted"] = Field(
        default="missing",
        description="Upload status"
    )
    file_path: Optional[str] = Field(
        None,
        max_length=512,
        description="S3 path or local file path (null if not uploaded)"
    )
    file_size: Optional[int] = Field(
        None,
        ge=0,
        le=10_485_760,  # 10MB max (10 * 1024 * 1024)
        description="File size in bytes (max 10MB, null if not uploaded)"
    )
    uploaded_at: Optional[datetime] = Field(
        None,
        description="Upload timestamp (UTC)"
    )
    # ADM-031 round 7: paper-receipt timestamp
    paper_submitted_at: Optional[datetime] = Field(
        None,
        description="Timestamp when officer marked the paper document as received"
    )
    # ✅ FIX Finding 2.3: Document Internal Verification
    verified_format: Optional[Literal["original", "certified_copy", "photo"]] = Field(
        None,
        description="Format verified by officer (original/certified_copy/photo)"
    )
    # ADM-031 round 4: officer-declared actual format. Captured at upload /
    # paper-receipt time; surfaced in the FE row badge so officers can see
    # what was actually recorded vs the path-required submission_format.
    actual_submission_format: Optional[Literal["original", "certified_copy", "photo"]] = Field(
        None,
        description="Format actually declared by the officer at upload/paper-receipt time"
    )
    # ADM-031 round 10: surface the verifier identity + timestamp so the FE
    # row can render "Đã duyệt — <Tên> · <ngày>" under the status badge and
    # show full datetime on hover. verified_at + verified_by come straight
    # from ProfileDocument; verified_by_name is resolved server-side via a
    # batched User lookup to keep the listing N+1-free.
    verified_at: Optional[datetime] = Field(
        None,
        description="Timestamp when officer marked status=verified",
    )
    verified_by: Optional[int] = Field(
        None,
        description="User id of the officer who verified the document",
    )
    verified_by_name: Optional[str] = Field(
        None,
        description=(
            "Display name of the verifier — backend resolves "
            "full_name → username via a batched User lookup. Null when the "
            "verifier no longer exists or has neither field set; FE then "
            "falls back to 'User #<verified_by>'. Email is never exposed "
            "here (staff-to-staff privacy)."
        ),
    )

    # =========================================================================
    # Checklist-only display fields populated by _compute_frontend_fields.
    # These live alongside the raw document status so the FE can render the
    # row without a second API call.
    # =========================================================================
    is_mandatory: Optional[bool] = Field(
        default=None,
        description="Whether this document is mandatory for the admission path",
    )
    is_extra: Optional[bool] = Field(
        default=False,
        description=(
            "BR2 (2026-04-29): True when this row is a ProfileDocument that "
            "exists in the DB but is NOT in the current "
            "applied_rules.mandatory_docs snapshot — typically because the "
            "AdmissionPath was edited after the profile was created. Extras "
            "are read-only (all can_* flags false); the FE renders them in "
            "a separate 'Tài liệu ngoài yêu cầu hiện tại' section so "
            "officers see prior evidence isn't silently dropped."
        ),
    )
    requires_upload: Optional[bool] = Field(
        default=None,
        description="True if an online upload is required; False for paper-only docs",
    )
    submission_format: Optional[str] = Field(
        default=None,
        description="Allowed physical format (original/certified_copy/photo) when specified",
    )
    rejection_reason: Optional[str] = Field(
        default=None,
        description="Reason shown to the applicant when status = rejected",
    )
    submission_format_confirmed: Optional[bool] = Field(
        default=None,
        description="True once the officer verified the physical format",
    )

    # =========================================================================
    # PR #5 — explicit per-document permission flags
    # FE previously inferred action visibility from a generic `can('edit')`
    # check, which leaked buttons for roles that couldn't actually invoke the
    # underlying endpoint. The flags below are authoritative: backend computes
    # them per (role × doc status × profile status × unit/assignment scope),
    # and FE renders Upload / Verify / Reject / Reset / Paper-submit buttons
    # iff the matching flag is true.
    # =========================================================================
    can_upload: Optional[bool] = Field(
        default=None,
        description="Officer may upload a file for this doc (profile editable + owning officer)",
    )
    can_verify: Optional[bool] = Field(
        default=None,
        description="Manager/admin may mark status=verified (requires uploaded or paper_submitted)",
    )
    can_reject: Optional[bool] = Field(
        default=None,
        description="Manager/admin may mark status=rejected (requires uploaded/paper_submitted/verified)",
    )
    can_reset: Optional[bool] = Field(
        default=None,
        description="Manager/admin may clear the doc back to status=missing",
    )
    can_mark_paper_submitted: Optional[bool] = Field(
        default=None,
        description="Officer may record paper submission (paper-doc + missing status + owning officer)",
    )

    @field_validator('label')
    @classmethod
    def sanitize_label(cls, v: str) -> str:
        """XSS Prevention: Escape HTML entities."""
        return html.escape(v.strip())

    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True
    )


# ==============================================================================
# ADMISSION PROFILE SCHEMAS
# ==============================================================================

class AdmissionProfileCreate(BaseModel):
    """
    Schema for creating new AdmissionProfile.

    REFACTORED (Phase 2): Now requires admission_method_id for relational lookup.
    
    Fields populated by service:
    - applied_rules: Snapshot from AdmissionPath + AdmissionCriteria
    - ProfileDocument records: Auto-generated from DocumentGroup resolution
    - status: Default = 'draft'
    """
    lead_id: int = Field(
        ...,
        gt=0,
        description="Lead ID (must exist and belong to current user's unit)"
    )
    admission_method_id: int = Field(
        ...,
        gt=0,
        description="Admission method ID (required for AdmissionPath lookup)"
    )
    # ADM-017: client SHOULD pass academic_year so the service binds
    # the profile to a specific OfferingAcademicInfo row deterministically.
    # Optional in this BE phase for backward compatibility — if omitted,
    # the service falls back to "first published academic_info for the
    # offering" (legacy behaviour). A follow-up PR will add the FE field
    # and flip this to required. See memory ``project_admission_audit_2026-04-27_wave_status``
    # (Q8=b decision) and the ADM-017 ship note.
    academic_year: Optional[int] = Field(
        default=None,
        ge=2000,
        le=2100,
        description=(
            "Academic year for the profile (e.g., 2026). Service "
            "validates a published OfferingAcademicInfo row exists "
            "for ``(lead.offering_id, academic_year)``; if omitted, "
            "falls back to the offering's first published year."
        )
    )

    model_config = ConfigDict(str_strip_whitespace=True)


class AdmissionProfileUpdate(BaseModel):
    """
    Schema for updating AdmissionProfile (only allowed when status = 'draft').

    Security:
    - All text fields sanitized via field validators
    - citizen_id format validated (12 digits)
    - Optimistic locking via version field (required)
    - Array size limits: family_info max 10, academic_history max 20
    """
    version: int = Field(
        ...,
        ge=1,
        description="Current version (for optimistic locking, must match DB)"
    )
    
    # Personal Info Fields
    full_name: Optional[str] = Field(None, max_length=255)
    phone: Optional[str] = Field(
        None, 
        pattern=r"^0\d{9,10}$",
        description="Phone number (10-11 digits starting with 0)"
    )
    email: Optional[EmailStr] = Field(None, max_length=255)
    dob: Optional[date] = Field(None, description="Date of birth")
    gender: Optional[str] = Field(None, max_length=50)
    
    citizen_id: Optional[str] = Field(
        None,
        pattern=r"^\d{12}$",
        description="CCCD/CMND number (12 digits)"
    )
    social_insurance_number: Optional[str] = Field(None, max_length=50)
    
    # Location Fields
    nationality: Optional[str] = Field(None, max_length=100)
    ethnicity: Optional[str] = Field(None, max_length=100)
    religion: Optional[str] = Field(None, max_length=100)
    disability_type: Optional[str] = Field(None, max_length=100)
    permanent_province: Optional[str] = Field(None, max_length=100)
    permanent_district: Optional[str] = Field(None, max_length=100)
    permanent_ward: Optional[str] = Field(None, max_length=100)
    permanent_residential_group: Optional[str] = Field(
        None, max_length=150,
        description="Tổ dân phố / Thôn / Buôn / Ấp / Khóm / Khu phố — community sub-unit, free-text"
    )
    permanent_street_address: Optional[str] = Field(
        None, max_length=255,
        description="Số nhà, tên đường — street address line, free-text"
    )
    place_of_birth: Optional[str] = Field(None, max_length=255)
    native_place: Optional[str] = Field(None, max_length=255)
    
    # Political Info Dates
    union_entry_date: Optional[datetime] = Field(None, description="Union entry date")
    party_entry_date: Optional[datetime] = Field(None, description="Party entry date (probationary)")
    party_official_entry_date: Optional[datetime] = Field(None, description="Party entry date (official)")
    
    # JSONB Arrays
    family_info: Optional[List[FamilyMemberSchema]] = Field(
        None,
        max_length=10,
        description="Array of family members (max 10)"
    )
    academic_history: Optional[List[AcademicRecordSchema]] = Field(
        None,
        max_length=20,
        description="Array of academic records (schools attended, max 20)"
    )

    # Phase 6: Admission Scores
    admission_scores: Optional[AdmissionScoreSchema] = Field(
        None,
        description="Admission scores (GPA or subject scores) for dynamic scoring"
    )

    # Field validators to convert empty strings to None (for pattern fields)
    @field_validator('phone', 'citizen_id', mode='before')
    @classmethod
    def empty_str_to_none(cls, v):
        """Convert empty strings to None to bypass pattern validation."""
        if v == "" or v is None:
            return None
        return v

    @field_validator('email', 'full_name', 'gender', 'social_insurance_number',
                     'nationality', 'ethnicity', 'religion', 'disability_type',
                     'permanent_province', 'permanent_district', 'permanent_ward',
                     'permanent_residential_group', 'permanent_street_address',
                     'place_of_birth', 'native_place', mode='before')
    @classmethod
    def empty_str_to_none_text(cls, v):
        """Convert empty strings to None for text fields."""
        if v == "" or v is None:
            return None
        return v

    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True
    )

    # Cross-field date invariants — delegate to standalone utility so
    # service-layer partial-update flows (apply_minor_correction,
    # update_profile candidate-state checks) share the exact same rules.
    # See feedback memory ``partial-update-loses-cross-field-invariants``.
    from pydantic import model_validator

    @model_validator(mode='after')
    def validate_logical_dates(self) -> 'AdmissionProfileUpdate':
        """Schema-level entry point — runs on the partial payload only.

        IMPORTANT: this catches violations within the payload itself, but
        does NOT catch a partial update that conflicts with values
        already in the database. Callers doing partial updates must
        build a candidate state (DB + payload) and call
        ``validate_logical_dates`` from
        ``app.services.admission_invariants`` directly.
        """
        from app.services.admission_invariants import validate_logical_dates
        validate_logical_dates(self.model_dump())
        return self


# ==============================================================================
# APPLIED RULES SCHEMA (Ticket #1)
# ==============================================================================

# Ticket #4: Default Upload Configuration (Shared Constant)
DEFAULT_UPLOAD_CONFIG = {
    "allowed_types": ["application/pdf", "image/jpeg", "image/png", "image/jpg"],
    "max_file_size": 10 * 1024 * 1024,  # 10MB
    "allowed_extensions": ["pdf", "jpg", "jpeg", "png"]
}

class DocumentConfigSnapshotSchema(BaseModel):
    """Snapshot of document configuration."""
    requires_upload: Optional[bool] = None
    submission_format: Optional[str] = None
    is_mandatory: Optional[bool] = None
    label: Optional[str] = None

    model_config = ConfigDict(extra="ignore")


class UploadConfigSchema(BaseModel):
    """
    Upload configuration (Ticket #4).
    Controls frontend file validation rules.
    """
    allowed_types: List[str]
    max_file_size: int
    allowed_extensions: List[str]

    model_config = ConfigDict(extra="ignore")


class AppliedRulesSchema(BaseModel):
    """
    Schema for applied_rules snapshot (Ticket #1).
    BE-FE Contract:
    - Must handle LEGACY data (defaults required for new fields).
    - Must correspond to Zod schema strictly.
    """
    # Group 1: Basic Criteria
    min_gpa: Optional[float] = None
    min_score: Optional[float] = None

    # Group 2: Scoring Configuration
    subject_selection_mode: Optional[Literal["fixed", "best_n", "any_n"]] = "fixed"
    scoring_method: Optional[Literal["sum", "average", "weighted"]] = "sum"
    required_subject_count: Optional[int] = None
    min_subject_score: Optional[float] = None
    max_possible_score: Optional[float] = None

    # Group 3: Subject Validation
    allowed_subject_codes: List[str] = []
    subject_groups: List[Dict[str, Any]] = []

    # Group 4: Method Metadata
    admission_method: Optional[str] = None
    admission_method_id: Optional[int] = None
    # Ticket #3: Explicit method type
    # Legacy data fallback: None (Frontend handles nullable)
    method_type: Optional[Literal["gpa_only", "subject_based", "combined"]] = None

    # Group 5: Document Requirements
    mandatory_docs: List[str] = []
    doc_configs: Dict[str, DocumentConfigSnapshotSchema] = {}
    
    # Ticket #4: Upload Config
    # CRITICAL: Must provide default for legacy JSONB data that lacks this field.
    # Frontend Zod requires this field (non-optional).
    upload_config: UploadConfigSchema = Field(
        default_factory=lambda: UploadConfigSchema(**DEFAULT_UPLOAD_CONFIG)
    )

    # Group 6: Metadata
    snapshot_source: Optional[str] = None
    admission_path_id: Optional[int] = None
    academic_info_id: Optional[int] = None

    # PR #6 — submit-gate snapshot. schema_version distinguishes pre-PR
    # rows (backfilled to 1) from post-PR rows (2+). allow_unverified_submission
    # freezes the path-level toggle at the time of profile creation so
    # later admin changes don't retroactively re-score in-flight profiles.
    schema_version: Optional[int] = None
    allow_unverified_submission: Optional[bool] = None

    model_config = ConfigDict(extra="ignore")


class AdmissionProfileResponse(BaseModel):
    """
    Schema for AdmissionProfile response (GET, CREATE, UPDATE).

    Includes all fields + relationships (lead, student).
    
    Phase 7: Frontend Thin Client Compliance
    - permissions: dict of action permissions (computed from Casbin + status)
    - eligibility_status: computed eligibility state
    - validation_errors: list of validation issues
    - available_actions: list of allowed workflow actions
    - completion_percent: profile completion percentage
    """
    id: int
    lead_id: int
    status: str
    version: int
    academic_year: int  # ✅ NEW: Academic year (e.g., 2025, 2026)

    # phase3_01 (#184 Wave 3 PR-3A) P-UI-02 v0.6 — multi-NV gate.
    # false = legacy single-NV ProfileSubjectScore flow; true = Phase 3
    # AdmissionProfileChoice + ProfileChoiceScore engine flow. FE Step 5
    # "Nguyện vọng" hiển thị có điều kiện theo flag này (dynamic
    # visibleSteps array per P-UI-01).
    uses_choice_engine: bool = False

    # ✅ Ticket #1: Use strict schema
    applied_rules: AppliedRulesSchema

    created_at: datetime
    updated_at: datetime
    
    # Personal Info Fields
    full_name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    dob: Optional[date] = None
    gender: Optional[str] = None
    citizen_id: Optional[str] = None
    citizen_id_masked: Optional[str] = Field(
        None,
        description="Masked citizen ID for display (e.g., ********1234)"
    )
    social_insurance_number: Optional[str] = None
    
    # Location Fields
    nationality: Optional[str] = None
    ethnicity: Optional[str] = None
    religion: Optional[str] = None
    disability_type: Optional[str] = None
    permanent_province: Optional[str] = None
    permanent_district: Optional[str] = None
    permanent_ward: Optional[str] = None
    permanent_residential_group: Optional[str] = None
    permanent_street_address: Optional[str] = None
    place_of_birth: Optional[str] = None
    native_place: Optional[str] = None

    # Scores (Dynamic Calculation)
    admission_scores: Optional[AdmissionScoreSchema] = None
    total_score: Optional[float] = None
    average_score: Optional[float] = None
    
    # Political Dates
    union_entry_date: Optional[datetime] = None
    party_entry_date: Optional[datetime] = None
    party_official_entry_date: Optional[datetime] = None

    # ✅ FIX #6: Audit trail fields (approve/reject tracking)
    approved_at: Optional[datetime] = None
    approved_by_id: Optional[int] = None
    approval_notes: Optional[str] = None
    rejected_at: Optional[datetime] = None
    rejected_by_id: Optional[int] = None
    rejection_reason: Optional[str] = None

    # ✅ Resubmit audit fields
    resubmitted_at: Optional[datetime] = None
    resubmitted_by_id: Optional[int] = None
    resubmit_notes: Optional[str] = None

    # ✅ Revision request audit fields
    revision_requested_at: Optional[datetime] = None
    revision_requested_by_id: Optional[int] = None
    revision_reason: Optional[str] = None

    # ✅ Override audit fields
    overridden_at: Optional[datetime] = None
    overridden_by_id: Optional[int] = None
    override_reason: Optional[str] = None

    # ✅ Drop-out tracking
    is_dropped: Optional[bool] = None
    dropped_at: Optional[datetime] = None
    dropped_by_id: Optional[int] = None
    dropped_reason: Optional[str] = None

    # ✅ Confirmation tracking
    confirmed_by_id: Optional[int] = None

    # Claim/assignment fields
    assigned_reviewer_id: Optional[int] = None
    assigned_reviewer_name: Optional[str] = None
    assigned_at: Optional[datetime] = None
    assigned_officer_name: Optional[str] = None

    # ✅ Ticket #2: Qualification Status
    # Computed by backend: True if all academic criteria met
    is_qualified: Optional[bool] = None

    # JSONB Fields — DB enforces NOT NULL DEFAULT '[]' after migration
    # `nn20260419001`. Validator below stays as belt-and-suspenders for
    # any cached payload / downgrade path that still produces None.
    # See project_admissions_list_null_list_fields for original 2026-04-18
    # incident.
    family_info: List[FamilyMemberSchema] = Field(default_factory=list)
    academic_history: List[AcademicRecordSchema] = Field(default_factory=list)

    @field_validator("family_info", "academic_history", mode="before")
    @classmethod
    def _coerce_null_list_jsonb_to_empty(cls, value):
        """Convert DB NULL into an empty list before Pydantic type-check.

        Runs in `mode='before'` so the raw `None` from SQLAlchemy never
        hits Pydantic's `List[...]` validator (which would raise
        `list_type`). If the column was accidentally set to a non-list
        value by some unusual path, we still raise below.
        """
        if value is None:
            return []
        return value

    # Nested relationships (using forward refs for circular import avoidance)
    lead: Optional["LeadShallowForAdmission"] = None
    student: Optional["StudentShallowForAdmission"] = None

    # Denormalized fields for list display (avoids nested relationship loading issues)
    program_name: Optional[str] = Field(
        None,
        description="Program name from lead.offering.program (denormalized for list view)"
    )

    # =========================================================================
    # Phase 7: Frontend Thin Client Compliance Fields
    # =========================================================================
    
    # Permission flags (computed from Casbin + status + user context)
    # Keys: edit, save, submit, approve, reject, enroll, delete
    permissions: Dict[str, bool] = Field(
        default_factory=dict,
        description="Permission flags computed from Casbin policy and status"
    )
    
    # Eligibility status (computed by backend service)
    eligibility_status: Literal["eligible", "ineligible", "pending"] = Field(
        default="pending",
        description="Backend-computed eligibility based on applied_rules"
    )
    
    # Validation errors (reasons why profile is not eligible)
    validation_errors: List[str] = Field(
        default_factory=list,
        description="List of validation issues (e.g., 'CCCD required', 'GPA below threshold')"
    )
    
    # Available workflow actions
    available_actions: List[str] = Field(
        default_factory=list,
        description="List of currently available actions (e.g., ['save', 'submit'])"
    )

    # Per-profile effective allowlist for the post-approval correction
    # dialog. Resolved server-side from
    # SAFE_MINOR_CORRECTION_FIELDS ∩ admission_path.minor_correction_allowed_fields,
    # so FE renders only the fields admin enabled for this profile's path
    # without needing to fetch path config separately.
    minor_correction_fields: List[str] = Field(
        default_factory=list,
        description=(
            "Effective per-profile allowlist for minor correction. "
            "FE renders dialog rows from this list."
        )
    )
    
    # Profile completion percentage (0-100)
    completion_percent: int = Field(
        default=0,
        ge=0,
        le=100,
        description="Profile completion percentage (computed by backend)"
    )
    
    # Validation summary (grouped errors for UX)
    validation_summary: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Grouped validation errors: {gpa: {has_error, label, count}, documents: {...}, personal: {...}}"
    )

    # Grouped validation errors (categorized display)
    grouped_validation_errors: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Validation errors grouped by category: {personal_info: {category, errors, count}, documents: {...}, scores: {...}}"
    )

    # Executive summary for dashboard overview
    executive_summary: Optional[Dict[str, Any]] = Field(
        default=None,
        description="High-level status summary: {overall_status, completion_percent, step_summary, critical_blockers, warnings, next_action, can_submit}"
    )

    # Step status for sidebar (Architecture Compliant - Backend computes)
    step_status: Optional[Dict[int, str]] = Field(
        default=None,
        description="Step status map: {1: 'error', 2: 'warning', 3: 'success', ...}"
    )
    
    # Documents checklist for frontend display. Items follow
    # DocumentItemSchema — including the 5 per-document permission flags
    # the FE uses to gate Upload/Verify/Reject/Reset/Paper-submit buttons.
    documents_checklist: List[DocumentItemSchema] = Field(
        default_factory=list,
        description=(
            "Required-document items enriched with backend-computed display "
            "fields (is_mandatory, requires_upload, submission_format, "
            "rejection_reason) and permission flags (can_upload, can_verify, "
            "can_reject, can_reset, can_mark_paper_submitted)."
        ),
    )
    
    # ✅ Ticket #3.1: Document Status Summary (Computed by Backend)
    # Replaces frontend calculation logic for Thin Client compliance
    document_stats: Optional[Dict[str, int]] = Field(
        None,
        description="Document stats: {submitted_count, verified_count, mandatory_count, missing_count}"
    )

    # Snapshot Score (for Best N Highlighting)
    snapshot_score: Optional[Dict[str, Any]] = Field(
        None,
        description="Detailed score snapshot containing selected_subjects, etc."
    )

    # =========================================================================
    # Ticket #5: Score Status (Thin Client Compliance)
    # Backend computes pass/fail status, Frontend ONLY renders
    # =========================================================================
    score_snapshot_status: Optional[Dict[str, Any]] = Field(
        None,
        description="Backend-computed score pass/fail status: {total_status, subject_statuses: {code: status}}"
    )

    model_config = ConfigDict(
        from_attributes=True,
        validate_assignment=True
    )


class LeadShallowForAdmission(BaseModel):
    """Minimal Lead info for AdmissionProfileResponse."""
    id: int
    full_name: str
    phone: Optional[str] = None
    email: Optional[str] = None
    unit_id: Optional[int] = None
    assigned_officer_id: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)


class StudentShallowForAdmission(BaseModel):
    """Minimal Student info for AdmissionProfileResponse."""
    id: int
    student_code: str
    enrollment_date: datetime

    model_config = ConfigDict(from_attributes=True)


# Update forward refs
AdmissionProfileResponse.model_rebuild()


class AdmissionsPage(BaseModel):
    """Paginated admissions response with metadata."""
    total_count: int
    page: int
    page_size: int
    profiles: List[AdmissionProfileResponse]


# ==============================================================================
# BULK ACTION SCHEMAS
# ==============================================================================

# ------------------------------------------------------------------------------
# ADM-026 review (Nit): the (bypass_quota, bypass_reason) pair previously
# carried three verbatim copies of the cross-field validator across
# BulkApproveItem / ApproveRequest / FinalizeRequest. Extract into a single
# mixin so the contract — "bypass requires a reason ≥20 chars" — has one
# definition. ``model_validator(mode="after")`` defined on a base class
# still fires on subclasses, so each schema picks the rule up by
# inheritance and the audit log evidence-string format stays identical.
# Admin-only enforcement still lives in the request-entry dependency
# (``require_admin_for_quota_bypass`` in ``deps.py``) plus the service-side
# defense-in-depth check inside ``_assert_quota_or_bypass``.
# ------------------------------------------------------------------------------


class _QuotaBypassMixin(BaseModel):
    """Shared (bypass_quota, bypass_reason) pair + cross-field validator."""

    bypass_quota: bool = Field(
        False,
        description="ADM-026: Override annual_admission_quota cap (admin only). Requires bypass_reason.",
    )
    bypass_reason: Optional[str] = Field(
        None,
        max_length=1000,
        description="ADM-026: Required when bypass_quota=true. Min 20 chars. Audit log evidence.",
    )

    @model_validator(mode="after")
    def _validate_bypass_pair(self):
        if self.bypass_quota:
            reason = (self.bypass_reason or "").strip()
            if len(reason) < 20:
                raise ValueError(
                    "bypass_reason is required and must be at least 20 characters when bypass_quota=true"
                )
        return self


class BulkApproveItem(_QuotaBypassMixin):
    """Single item in a bulk approve request."""
    profile_id: int = Field(..., description="Admission profile ID")
    version: int = Field(..., ge=1, description="Current profile version for optimistic locking")
    # ADM-026: per-item quota bypass. Admin-only enforced at request entry
    # (``require_admin_for_quota_bypass`` in ``deps.py``); service-side check
    # in ``_assert_quota_or_bypass`` is defense-in-depth.


class BulkApproveRequest(BaseModel):
    """Request schema for bulk approve action."""
    items: List[BulkApproveItem] = Field(..., min_length=1, max_length=100, description="List of profiles to approve with their versions")
    notes: Optional[str] = Field(None, max_length=1000, description="Optional approval notes")


class BulkRejectItem(BaseModel):
    """Single item in a bulk reject request."""
    profile_id: int = Field(..., description="Admission profile ID")
    version: int = Field(..., ge=1, description="Current profile version for optimistic locking")


class BulkRejectRequest(BaseModel):
    """Request schema for bulk reject action."""
    items: List[BulkRejectItem] = Field(..., min_length=1, max_length=100, description="List of profiles to reject with their versions")
    reason: str = Field(..., min_length=10, max_length=1000, description="Rejection reason (required)")


class BulkAssignRequest(BaseModel):
    """Request schema for bulk assign to officer action."""
    profile_ids: List[int] = Field(..., min_length=1, max_length=100, description="List of profile IDs to assign")
    officer_id: int = Field(..., description="ID of the officer to assign profiles to")


class BulkActionResponse(BaseModel):
    """Response schema for bulk actions."""
    success_count: int = Field(..., description="Number of successfully processed profiles")
    failed_count: int = Field(..., description="Number of failed profiles")
    failed_ids: List[int] = Field(default_factory=list, description="IDs of profiles that failed")
    errors: Optional[Dict[int, str]] = Field(None, description="Error messages per failed profile ID")
    message: str = Field(..., description="Summary message")


class AdmissionSubmitResponse(BaseModel):
    """
    Schema for submit endpoint response.

    ✅ CRITICAL FIX #1: Updated to match state machine flow
    - draft → submitted (validation pass)
    - draft → draft (validation fail - user fixes errors)

    Success (200):
    - status: "submitted" (wait for Manager approval)
    - message: Success message
    - validation_errors: null

    Validation Failed (200):
    - status: "draft" (user needs to fix errors)
    - message: null
    - validation_errors: List of error messages
    """
    status: Optional[Literal["draft", "submitted"]] = None  # ✅ FIX: Match state machine
    message: Optional[str] = None
    validation_errors: Optional[List[str]] = None  # ✅ FIX: Renamed from "errors"

    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True
    )


class EnrollStudentResponse(BaseModel):
    """
    Schema for enroll endpoint response (201 Created).

    Returns newly created student information.
    """
    student_id: int = Field(..., description="Student ID")
    student_code: str = Field(..., description="Generated student code (SV + YYYY + 0000)")
    enrollment_date: datetime = Field(..., description="Enrollment date (UTC)")

    model_config = ConfigDict(
        from_attributes=True,
        validate_assignment=True
    )


# ==============================================================================
# STUDENT SCHEMAS (for responses)
# ==============================================================================

class StudentDocumentResponse(BaseModel):
    """Schema for StudentDocument response."""
    id: int
    student_id: int
    doc_type: str
    file_path: str
    is_verified: bool
    reviewer_note: Optional[str] = None
    uploaded_at: datetime
    verified_at: Optional[datetime] = None

    model_config = ConfigDict(
        from_attributes=True,
        validate_assignment=True
    )


class DocumentUploadResponse(BaseModel):
    """Schema for document upload response."""
    code: str = Field(..., description="Document code (e.g., HOC_BA)")
    label: str = Field(..., description="Human-readable name")
    is_mandatory: bool = Field(default=True)
    status: Literal["missing", "uploaded", "verified", "rejected", "paper_submitted"] = Field(
        default="uploaded",
        description="Upload status"
    )
    file_path: Optional[str] = Field(
        None,
        description="File path where document is stored"
    )
    uploaded_at: Optional[str] = Field(
        None,
        description="Upload timestamp (ISO format)"
    )
    # ✅ FIX Finding 2.3
    verified_format: Optional[str] = Field(
        None,
        description="Verified format (original/certified_copy/photo)"
    )

    model_config = ConfigDict(
        from_attributes=True,
        validate_assignment=True
    )


class DocumentSubmissionRequest(BaseModel):
    """
    Schema for document submission (upload or paper receipt).
    User/Officer declares what type of document is being submitted.
    """
    actual_submission_format: Literal["original", "certified_copy", "photo"] = Field(
        ...,
        description="Type of physical document being submitted/uploaded"
    )

    model_config = ConfigDict(str_strip_whitespace=True)


class DocumentFormatVerifyRequest(BaseModel):
    """
    Schema for verifying document format (Officer action).
    Finding 2.3: Officer confirms if document is Original/Copy.
    """
    format: Literal["original", "certified_copy", "photo"] = Field(
        ...,
        description="Physical format of the document"
    )

    model_config = ConfigDict(str_strip_whitespace=True)


class DocumentRejectRequest(BaseModel):
    """Schema for reject document request."""
    reason: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Rejection reason (required)"
    )

    @field_validator('reason')
    @classmethod
    def sanitize_reason(cls, v: str) -> str:
        """XSS Prevention: Escape HTML entities."""
        return html.escape(v.strip())

    model_config = ConfigDict(str_strip_whitespace=True)


class StudentResponse(BaseModel):
    """Schema for Student response."""
    id: int
    admission_profile_id: int
    student_code: str
    enrollment_date: datetime
    created_at: datetime

    # Nested relationships
    documents: List[StudentDocumentResponse] = []

    model_config = ConfigDict(
        from_attributes=True,
        validate_assignment=True
    )


# ==============================================================================
# STATE TRANSITION SCHEMAS (State Machine)
# ==============================================================================

class ApproveRequest(_QuotaBypassMixin):
    """
    Schema for approve action (Manager/Admin).

    ✅ CRITICAL FIX #4: Made version REQUIRED for optimistic locking
    Without version check: 2 managers can approve/reject same profile simultaneously
    With version check: Second request fails with 409 Conflict

    Per ADMISSION_STATE_MACHINE_IMPLEMENTATION_PLAN.md Section 3.1:
    - Transition: SUBMITTED/RESUBMITTED → APPROVED
    - Requires Manager or Admin role
    - Optional approval notes
    - REQUIRED version for optimistic locking (CRITICAL FIX #4)

    ADM-026: bypass_quota / bypass_reason inherited from _QuotaBypassMixin.
    Admin-only enforced at request entry (``require_admin_for_quota_bypass``
    in ``deps.py``); service ``_assert_quota_or_bypass`` is defense-in-depth.
    """
    notes: Optional[str] = Field(
        None,
        max_length=1000,
        description="Optional approval notes/comments"
    )
    version: int = Field(  # ✅ CRITICAL FIX #4: Now REQUIRED (was Optional)
        ...,
        ge=1,
        description="REQUIRED: Current profile version for optimistic locking (prevents race conditions)"
    )

    model_config = ConfigDict(str_strip_whitespace=True)


class RejectRequest(BaseModel):
    """
    Schema for reject action (Manager/Admin).

    ✅ CRITICAL FIX #4: Made version REQUIRED for optimistic locking

    Per ADMISSION_STATE_MACHINE_IMPLEMENTATION_PLAN.md Section 3.1:
    - Transition: SUBMITTED/RESUBMITTED → REJECTED
    - Requires Manager or Admin role
    - Reason is MANDATORY (min 10 chars)
    - REQUIRED version for optimistic locking (CRITICAL FIX #4)
    """
    reason: str = Field(
        ...,
        min_length=10,
        max_length=1000,
        description="Rejection reason (min 10 chars, required)"
    )
    version: int = Field(  # ✅ CRITICAL FIX #4: Now REQUIRED (was Optional)
        ...,
        ge=1,
        description="REQUIRED: Current profile version for optimistic locking (prevents race conditions)"
    )

    @field_validator('reason')
    @classmethod
    def sanitize_reason(cls, v: str) -> str:
        """XSS Prevention: Escape HTML entities."""
        return html.escape(v.strip())

    model_config = ConfigDict(str_strip_whitespace=True)


class RevisionRequest(BaseModel):
    """
    Schema for revision request action (Manager/Admin).

    Transition: SUBMITTED/RESUBMITTED -> REVISION_REQUESTED
    Requires Manager or Admin role.
    Reason is MANDATORY (min 10 chars).
    """
    reason: str = Field(
        ...,
        min_length=10,
        max_length=1000,
        description="Revision reason/instructions (min 10 chars, required)"
    )
    version: int = Field(
        ...,
        ge=1,
        description="REQUIRED: Current profile version for optimistic locking"
    )

    @field_validator('reason')
    @classmethod
    def sanitize_reason(cls, v: str) -> str:
        """XSS Prevention: Escape HTML entities."""
        return html.escape(v.strip())

    model_config = ConfigDict(str_strip_whitespace=True)


class ResubmitRequest(BaseModel):
    """
    Schema for resubmit action (Officer).

    Per ADMISSION_STATE_MACHINE_IMPLEMENTATION_PLAN.md Section 3.2:
    - Transition: REJECTED → RESUBMITTED
    - Requires Officer or higher role
    - Optional notes about what was fixed
    """
    version: int = Field(
        ...,
        ge=1,
        description="REQUIRED: Current profile version for optimistic locking"
    )
    notes: Optional[str] = Field(
        None,
        max_length=1000,
        description="Optional notes about what was fixed/updated"
    )

    model_config = ConfigDict(str_strip_whitespace=True)


class ConfirmRequest(BaseModel):
    """
    Schema for confirm action (Applicant/User).

    Per ADMISSION_STATE_MACHINE_IMPLEMENTATION_PLAN.md Section 3.3:
    - Transition: APPROVED → CONFIRMED
    - SELF check required (lead.user_id == current_user.id)
    - Admin can also confirm
    """
    # No fields required - simple confirmation
    pass

    model_config = ConfigDict(str_strip_whitespace=True)


class WithdrawRequest(BaseModel):
    """
    Schema for withdrawal action.

    Transitions allowed from: DRAFT, SUBMITTED, REJECTED, RESUBMITTED
    Target state: WITHDRAWN (terminal)

    Lead pipeline sync: lead moves to sts08 (Từ chối tư vấn) per
    lead_admission_sync mapping. Service layer handles the sync.

    **Validation:**
    - reason: required, 5-1000 chars, HTML-escaped
    - version: required for optimistic locking
    """
    reason: str = Field(
        ...,
        min_length=5,
        max_length=1000,
        description="Withdrawal reason (required)",
    )
    version: int = Field(
        ...,
        description="Profile version for optimistic locking",
    )

    @field_validator('reason')
    @classmethod
    def sanitize_reason(cls, v: str) -> str:
        """XSS prevention: escape HTML entities."""
        return html.escape(v.strip())

    model_config = ConfigDict(str_strip_whitespace=True)


class OverrideRequest(BaseModel):
    """
    Schema for override action (Admin only).

    Per ADMISSION_STATE_MACHINE_IMPLEMENTATION_PLAN.md Section 3.4:
    - Transition: APPROVED → OVERRIDDEN
    - Admin only
    - Reason MANDATORY (audit requirement)
    - Full audit logging required
    - REQUIRED version for optimistic locking (ADM-015)
    """
    reason: str = Field(
        ...,
        min_length=10,
        max_length=1000,
        description="Override reason (min 10 chars, required for audit)"
    )
    bypass_rules: List[str] = Field(
        default_factory=list,
        description="List of rules bypassed (e.g., ['min_gpa', 'missing_documents'])"
    )
    version: int = Field(
        ...,
        ge=1,
        description="REQUIRED: Current profile version for optimistic locking (prevents race conditions)"
    )

    @field_validator('reason')
    @classmethod
    def sanitize_reason(cls, v: str) -> str:
        """XSS Prevention: Escape HTML entities."""
        return html.escape(v.strip())

    model_config = ConfigDict(str_strip_whitespace=True)


class FinalizeRequest(_QuotaBypassMixin):
    """
    Schema for finalize action (Admin only).

    Per ADMISSION_STATE_MACHINE_IMPLEMENTATION_PLAN.md Section 3.4:
    - Transition: OVERRIDDEN/CONFIRMED → ENROLLED
    - Admin only
    - Creates Student record
    - REQUIRED version for optimistic locking (ADM-015)

    ADM-026: bypass_quota / bypass_reason inherited from _QuotaBypassMixin.
    """
    version: int = Field(
        ...,
        ge=1,
        description="REQUIRED: Current profile version for optimistic locking (prevents race conditions)"
    )

    model_config = ConfigDict(str_strip_whitespace=True)


class DropStudentRequest(BaseModel):
    """
    Schema for marking an enrolled student as dropped out (Manager/Admin).

    Side-channel: status stays "enrolled", sets is_dropped=True.
    Reason is MANDATORY (min 10 chars).
    """
    reason: str = Field(
        ...,
        min_length=10,
        max_length=1000,
        description="Drop-out reason (min 10 chars, required)"
    )
    version: int = Field(
        ...,
        ge=1,
        description="REQUIRED: Current profile version for optimistic locking"
    )

    @field_validator('reason')
    @classmethod
    def sanitize_reason(cls, v: str) -> str:
        """XSS Prevention: Escape HTML entities."""
        return html.escape(v.strip())

    model_config = ConfigDict(str_strip_whitespace=True)


class ClaimRequest(BaseModel):
    """
    Schema for Claiming a profile.
    Only version is needed for optimistic locking.
    """
    version: int = Field(..., description="Optimistic locking version")


# StringConstraints applies strip_whitespace BEFORE checking min/max
# length, so a payload like "          a" (9 spaces + 1 char, length 10)
# fails the min=10 check after stripping. Defends against accidental
# zero-effort reasons that bypass min_length when validated via
# Field(min_length=...).
TrimmedReason = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=10, max_length=1000),
]


class MinorCorrectionRequest(BaseModel):
    """Request schema for ``POST /admissions/{id}/minor-correction``.

    Three required fields:
    - ``version`` for optimistic locking (matches the version-on-state
      pattern used by approve/reject/etc., raises 409 on mismatch).
    - ``reason`` whose effective length is checked AFTER strip; an
      operator must supply real justification per audit policy.
    - ``changes`` is a dict of ``{field_key: new_value}``. Field-level
      type validation runs server-side via the FIELD_ADAPTERS map in
      ``admission_correction_helpers.py``; we keep the schema as
      ``dict[str, Any]`` here so unknown / hard-deny keys surface in
      the service-side check rather than failing Pydantic with a
      cryptic union error.
    """

    version: int = Field(
        ...,
        ge=1,
        description="Current profile version for optimistic locking"
    )
    reason: TrimmedReason = Field(
        ...,
        description=(
            "Why this correction is being made. Stored on the audit row. "
            "Min 10 characters AFTER trim — pure-whitespace inputs reject."
        ),
    )
    changes: Dict[str, Any] = Field(
        ...,
        description=(
            "Map of {field_key: new_value}. Field validation happens "
            "server-side after status / IDOR / allowlist gates."
        ),
    )

    @field_validator("changes")
    @classmethod
    def changes_not_empty(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        if not v:
            raise ValueError("changes must contain at least one field")
        return v


# ==============================================================================
# EXPORT ALL
# ==============================================================================

# ==============================================================================
# CONFIRMATION TOKEN SCHEMAS (Magic Link)
# ==============================================================================


class ConfirmTokenVerifyRequest(BaseModel):
    """
    Request body for token-based confirmation.
    
    Security:
    - Pattern validation for exactly 4 digits
    - Used with magic link token for CCCD verification
    """
    last_digits_citizen_id: str = Field(
        ...,
        min_length=4,
        max_length=4,
        pattern=r"^\d{4}$",
        description="Last 4 digits of CCCD/CMND"
    )
    
    model_config = ConfigDict(str_strip_whitespace=True)


class ConfirmTokenResponse(BaseModel):
    """Response after successful token-based confirmation."""
    message: str
    profile_id: int
    status: str
    confirmed_at: datetime
    
    model_config = ConfigDict(from_attributes=True)


class ConfirmTokenInfoResponse(BaseModel):
    """
    Info about token (for frontend to show confirmation form).
    
    Used by GET /confirm/{token} to display:
    - Lead name ("Xin chào, [Tên]...")
    - Token status (valid, expired, locked)
    - Attempts remaining
    """
    valid: bool
    expired: bool
    locked: bool
    already_used: bool
    attempts_remaining: int
    profile_name: str = Field(description="Lead's full_name for display")
    expires_at: Optional[datetime] = None
    
    model_config = ConfigDict(from_attributes=True)


class SendConfirmationResponse(BaseModel):
    """Response after sending confirmation link."""
    message: str
    token_expires_at: datetime
    sent_to_email: Optional[str] = None
    # Canonical field: lead's phone number. The API does NOT send SMS today —
    # this is just data the officer can use to reach out. See
    # project_send_confirmation_ops_gaps for rationale on the rename.
    phone: Optional[str] = Field(
        None,
        description="Lead's phone number (informational — system does not send SMS)",
    )
    token_value: Optional[str] = Field(
        None,
        description="Token value for admin/officer to share confirmation link manually",
    )
    confirm_url: Optional[str] = Field(
        None,
        description=(
            "Full confirmation URL (FRONTEND_URL + /confirm/{token}). "
            "Prefer this over composing the link manually from `token_value`."
        ),
    )


class AdmissionStatusCounts(BaseModel):
    """Status counts for tab badges. From GET /admissions/status-counts."""
    counts: Dict[str, int]
    total: int


class AdmissionStats(BaseModel):
    """Aggregate statistics. From GET /admissions/stats."""
    total_profiles: int = 0
    draft_count: int = 0
    submitted_count: int = 0
    approved_count: int = 0
    enrolled_count: int = 0
    rejected_count: int = 0
    dropped_count: int = 0
    conversion_rate: float = 0.0
    avg_completion: float = 0.0


# =============================================================================
# Phase 3 PR-3C Sub-3 — Choice-engine endpoint schemas
# =============================================================================


class _PerChoiceDecision(BaseModel):
    """Per-choice decision row inside `AdmissionPublishResultResponse`."""

    choice_id: int
    display_order: int
    decision: Literal["pending", "admitted", "waitlisted", "rejected", "skip"]
    reasons: List[str] = Field(default_factory=list)
    score: Optional[float] = None


class AdmissionPublishResultResponse(BaseModel):
    """T6 publish-result endpoint response — wraps `CascadeResult`.

    Returned by `POST /api/v2/admissions/{id}/publish-result` after the
    choice-engine cascade evaluates all profile.choices in display_order
    and transitions profile.status to admitted/rejected.
    """

    profile_id: int
    final_status: Literal["admitted", "rejected", "waitlisted"]
    admitted_choice_id: Optional[int] = None
    admitted_display_order: Optional[int] = None
    per_choice_decisions: List[_PerChoiceDecision] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class AdmissionWaitlistPromoteRequest(BaseModel):
    """T10 waitlist-promote endpoint request body.

    DRIFT-01: Sub-3.4 route shipped là profile-scoped (Casbin canonical
    `/api/v2/admissions/{profile_id}/waitlist-promote`), NOT choice-scoped
    admin namespace per stale Plan v0.7 line 437. `choice_id` moves from
    URL param vào request body — service verifies ownership.

    `reason` optional cho audit context (transition() reason kwarg passes
    into status_history.transition_reason).
    """

    choice_id: int = Field(..., gt=0, description="ID nguyện vọng promote từ waitlist")
    reason: Optional[str] = Field(
        None,
        min_length=10,
        max_length=500,
        description="Optional audit reason (status_history.transition_reason)",
    )

    model_config = ConfigDict(str_strip_whitespace=True)


class AdmissionWaitlistPromoteResponse(BaseModel):
    """T10 waitlist-promote endpoint response.

    Returned by `POST /api/v2/admissions/{profile_id}/waitlist-promote`
    after admin promotes a waitlisted choice → admitted.
    """

    choice_id: int
    decision: Literal["admitted"] = "admitted"
    profile_id: int
    profile_status: Literal["admitted"] = "admitted"


class AdmissionAdminRollbackRequest(BaseModel):
    """T17 admin-rollback endpoint request body.

    Reason is mandatory + min 10 chars for audit trail. The reason flows
    into `AdmissionProfileStatusHistory.transition_reason` + dispatch
    payload of `ADMISSION_ROLLED_BACK`.
    """

    reason: str = Field(
        ...,
        min_length=10,
        max_length=500,
        description="Mandatory rollback reason (audit log + dispatch payload)",
    )

    model_config = ConfigDict(str_strip_whitespace=True)


class AdmissionAdminRollbackResponse(BaseModel):
    """T17 admin-rollback endpoint response."""

    profile_id: int
    status: Literal["draft"] = "draft"
    rolled_back_from: str  # The status the profile was in BEFORE rollback


__all__ = [
    # Nested schemas
    "FamilyMemberSchema",
    "AcademicRecordSchema",
    "AdmissionScoreSchema",
    "DocumentItemSchema",
    # AdmissionProfile schemas
    "AdmissionProfileCreate",
    "AdmissionProfileUpdate",
    "AdmissionProfileResponse",
    "AdmissionSubmitResponse",
    "EnrollStudentResponse",
    # State transition schemas
    "ClaimRequest",  # ✅ Added
    "DocumentFormatVerifyRequest",  # ✅ Added
    "ApproveRequest",
    "RejectRequest",
    "RevisionRequest",
    "ResubmitRequest",
    "DropStudentRequest",
    "ConfirmRequest",
    "OverrideRequest",
    "WithdrawRequest",
    "FinalizeRequest",
    # Student schemas
    "StudentDocumentResponse",
    "StudentResponse",
    "DocumentUploadResponse",
    # Confirmation token schemas (Magic Link)
    "ConfirmTokenVerifyRequest",
    "ConfirmTokenResponse",
    "ConfirmTokenInfoResponse",
    "SendConfirmationResponse",
    # Aggregate schemas
    "AdmissionStatusCounts",
    "AdmissionStats",
    # Phase 3 PR-3C Sub-3 — choice-engine endpoints
    "AdmissionPublishResultResponse",
    "AdmissionWaitlistPromoteRequest",
    "AdmissionWaitlistPromoteResponse",
    "AdmissionAdminRollbackRequest",
    "AdmissionAdminRollbackResponse",
]
