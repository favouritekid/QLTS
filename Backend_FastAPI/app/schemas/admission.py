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

from datetime import datetime
from typing import List, Optional, Literal, Dict
import html

from pydantic import BaseModel, Field, field_validator, ConfigDict


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
        extra="allow"  # Allow extra fields for flexibility
    )


class DocumentItemSchema(BaseModel):
    """
    Document checklist item (stored in admission_profile.documents_checklist JSONB array).

    Status Lifecycle:
    - missing: Document not yet uploaded
    - uploaded: File uploaded, pending verification
    - verified: Officer verified the document
    - rejected: Officer rejected the document

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
    status: Literal["missing", "uploaded", "verified", "rejected"] = Field(
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

    Only requires lead_id. All other fields are populated by service:
    - applied_rules: Snapshot from ProgramOffering.admission_rules
    - ProfileDocument records: Auto-generated from applied_rules.mandatory_docs
    - status: Default = 'draft'
    """
    lead_id: int = Field(
        ...,
        gt=0,
        description="Lead ID (must exist and belong to current user's unit)"
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
    email: Optional[str] = Field(None, max_length=255)
    dob: Optional[datetime] = Field(None, description="Date of birth")
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
    applied_rules: dict
    created_at: datetime
    updated_at: datetime
    
    # Personal Info Fields
    full_name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    dob: Optional[datetime] = None
    gender: Optional[str] = None
    citizen_id: Optional[str] = None
    social_insurance_number: Optional[str] = None
    
    # Location Fields
    nationality: Optional[str] = None
    ethnicity: Optional[str] = None
    religion: Optional[str] = None
    disability_type: Optional[str] = None
    permanent_province: Optional[str] = None
    permanent_district: Optional[str] = None
    permanent_ward: Optional[str] = None
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

    # JSONB Fields
    family_info: List[FamilyMemberSchema] = []
    academic_history: List[AcademicRecordSchema] = []

    # Nested relationships (using forward refs for circular import avoidance)
    lead: Optional["LeadShallowForAdmission"] = None
    student: Optional["StudentShallowForAdmission"] = None

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
    
    # Profile completion percentage (0-100)
    completion_percent: int = Field(
        default=0,
        ge=0,
        le=100,
        description="Profile completion percentage (computed by backend)"
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

    model_config = ConfigDict(from_attributes=True)


class StudentShallowForAdmission(BaseModel):
    """Minimal Student info for AdmissionProfileResponse."""
    id: int
    student_code: str
    enrollment_date: datetime

    model_config = ConfigDict(from_attributes=True)


# Update forward refs
AdmissionProfileResponse.model_rebuild()


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
    status: Literal["missing", "uploaded", "verified", "rejected"] = Field(
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

    model_config = ConfigDict(
        from_attributes=True,
        validate_assignment=True
    )


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

class ApproveRequest(BaseModel):
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


class ResubmitRequest(BaseModel):
    """
    Schema for resubmit action (Officer).

    Per ADMISSION_STATE_MACHINE_IMPLEMENTATION_PLAN.md Section 3.2:
    - Transition: REJECTED → RESUBMITTED
    - Requires Officer or higher role
    - Optional notes about what was fixed
    """
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


class OverrideRequest(BaseModel):
    """
    Schema for override action (Admin only).

    Per ADMISSION_STATE_MACHINE_IMPLEMENTATION_PLAN.md Section 3.4:
    - Transition: APPROVED → OVERRIDDEN
    - Admin only
    - Reason MANDATORY (audit requirement)
    - Full audit logging required
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

    @field_validator('reason')
    @classmethod
    def sanitize_reason(cls, v: str) -> str:
        """XSS Prevention: Escape HTML entities."""
        return html.escape(v.strip())

    model_config = ConfigDict(str_strip_whitespace=True)


class FinalizeRequest(BaseModel):
    """
    Schema for finalize action (Admin only).

    Per ADMISSION_STATE_MACHINE_IMPLEMENTATION_PLAN.md Section 3.4:
    - Transition: OVERRIDDEN/CONFIRMED → ENROLLED
    - Admin only
    - Creates Student record
    """
    # No fields required - triggers enrollment
    pass

    model_config = ConfigDict(str_strip_whitespace=True)


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
    sent_to_phone: Optional[str] = None


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
    "ApproveRequest",
    "RejectRequest",
    "ResubmitRequest",
    "ConfirmRequest",
    "OverrideRequest",
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
]
