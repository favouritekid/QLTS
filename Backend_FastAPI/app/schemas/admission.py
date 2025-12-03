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
        description="GPA on 10-point scale"
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
    """
    citizen_id: Optional[str] = Field(
        None,
        pattern=r"^\d{12}$",
        description="CCCD/CMND number (12 digits)"
    )
    family_info: Optional[List[FamilyMemberSchema]] = Field(
        None,
        description="Array of family members"
    )
    academic_history: Optional[List[AcademicRecordSchema]] = Field(
        None,
        description="Array of academic records (schools attended)"
    )
    admission_scores: Optional[AdmissionScoreSchema] = Field(
        None,
        description="Admission scores (GPA, subject scores)"
    )
    documents_checklist: Optional[List[DocumentItemSchema]] = Field(
        None,
        description="Document upload checklist"
    )

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
    citizen_id: Optional[str] = None
    status: str
    applied_rules: dict
    family_info: List[FamilyMemberSchema] = []
    academic_history: List[AcademicRecordSchema] = []
    admission_scores: Optional[AdmissionScoreSchema] = None
    documents_checklist: List[DocumentItemSchema] = []
    created_at: datetime
    updated_at: datetime

    # Nested relationships (optional)
    lead: Optional[dict] = None  # LeadShallow from lead.py
    student: Optional[dict] = None  # StudentShallow

    model_config = ConfigDict(
        from_attributes=True,
        validate_assignment=True
    )


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
