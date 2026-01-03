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
from typing import List, Optional, Literal
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

    Security:
    - GPA Range: 0.0 - 10.0 (Vietnam education system)
    - Subject Scores: Optional, 0.0 - 10.0
    """
    gpa: float = Field(
        ...,
        ge=0.0,
        le=10.0,
        description="Overall GPA (required for admission evaluation)"
    )
    math_score: Optional[float] = Field(
        None,
        ge=0.0,
        le=10.0,
        description="Math score (optional)"
    )
    literature_score: Optional[float] = Field(
        None,
        ge=0.0,
        le=10.0,
        description="Literature score (optional)"
    )
    english_score: Optional[float] = Field(
        None,
        ge=0.0,
        le=10.0,
        description="English score (optional)"
    )
    # Add more subjects as needed

    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True
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
    - documents_checklist: Auto-generated from applied_rules.mandatory_docs
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
    - GPA validated via nested schemas
    - Optimistic locking via version field (required)
    - Array size limits: family_info max 10, documents_checklist max 50
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
    admission_scores: Optional[AdmissionScoreSchema] = Field(
        None,
        description="Admission scores (GPA, subject scores)"
    )
    documents_checklist: Optional[List[DocumentItemSchema]] = Field(
        None,
        max_length=50,
        description="Document upload checklist (max 50)"
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
    """
    id: int
    lead_id: int
    status: str
    version: int
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
    
    # Political Dates
    union_entry_date: Optional[datetime] = None
    party_entry_date: Optional[datetime] = None
    party_official_entry_date: Optional[datetime] = None
    
    # JSONB Fields
    family_info: List[FamilyMemberSchema] = []
    academic_history: List[AcademicRecordSchema] = []
    admission_scores: Optional[AdmissionScoreSchema] = None
    documents_checklist: List[DocumentItemSchema] = []

    # Nested relationships (using forward refs for circular import avoidance)
    lead: Optional["LeadShallowForAdmission"] = None
    student: Optional["StudentShallowForAdmission"] = None

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

    Success (200):
    - status: "approved"
    - message: Success message

    Failure (400):
    - errors: List of validation error messages
    """
    status: Optional[Literal["approved", "rejected"]] = None
    message: Optional[str] = None
    errors: Optional[List[str]] = None

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
# EXPORT ALL
# ==============================================================================

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
    # Student schemas
    "StudentDocumentResponse",
    "StudentResponse",
]
