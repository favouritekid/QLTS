# app/schemas/collaborator.py
"""
Collaborator (CTV) System - Phase 1: Pydantic Schemas

Includes:
- Collaborator CRUD schemas
- LeadClaim workflow schemas
- LeadForCTV (masked view for CTV)
"""
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from .organization import OrganizationUnitShallow


# ============================================================================
# SHALLOW / NESTED SCHEMAS
# ============================================================================


class UserShallow(BaseModel):
    """Minimal user info for embedding in Collaborator responses."""
    id: int
    full_name: Optional[str] = None
    username: str

    model_config = ConfigDict(from_attributes=True)


class CollaboratorShallow(BaseModel):
    """Minimal collaborator info for embedding in Lead response."""
    id: int
    code: str
    full_name: str
    phone: str

    model_config = ConfigDict(from_attributes=True)


# ============================================================================
# COLLABORATOR CRUD SCHEMAS
# ============================================================================


class CollaboratorCreate(BaseModel):
    full_name: str = Field(..., min_length=1, max_length=255, strip_whitespace=True)
    phone: str = Field(..., min_length=1, max_length=20, strip_whitespace=True)
    email: Optional[EmailStr] = None
    unit_id: int
    user_id: Optional[int] = None
    managed_by_officer_id: Optional[int] = None
    id_card_number: Optional[str] = Field(None, max_length=20, strip_whitespace=True)
    bank_account: Optional[str] = Field(None, max_length=50, strip_whitespace=True)
    bank_name: Optional[str] = Field(None, max_length=100, strip_whitespace=True)
    address: Optional[str] = Field(None, max_length=500, strip_whitespace=True)
    notes: Optional[str] = None

    @field_validator("email", mode="before")
    @classmethod
    def empty_string_to_none(cls, v):
        if v == "" or (isinstance(v, str) and v.strip() == ""):
            return None
        return v

    @field_validator("phone", mode="before")
    @classmethod
    def normalize_phone(cls, v):
        from app.utils.phone_helpers import normalize_vietnam_phone, validate_vietnam_phone
        if v is None:
            return v
        if isinstance(v, str) and v.strip() == "":
            return v
        normalized = normalize_vietnam_phone(v)
        if normalized is None:
            return v
        if not validate_vietnam_phone(normalized, normalize=False):
            raise ValueError(
                "Số điện thoại không hợp lệ. Vui lòng nhập số điện thoại Việt Nam "
                "(VD: 0901234567, +84901234567)"
            )
        return normalized


class CollaboratorUpdate(BaseModel):
    full_name: Optional[str] = Field(None, min_length=1, max_length=255, strip_whitespace=True)
    phone: Optional[str] = Field(None, max_length=20, strip_whitespace=True)
    email: Optional[EmailStr] = None
    managed_by_officer_id: Optional[int] = None
    id_card_number: Optional[str] = Field(None, max_length=20, strip_whitespace=True)
    bank_account: Optional[str] = Field(None, max_length=50, strip_whitespace=True)
    bank_name: Optional[str] = Field(None, max_length=100, strip_whitespace=True)
    address: Optional[str] = Field(None, max_length=500, strip_whitespace=True)
    notes: Optional[str] = None

    @field_validator("email", mode="before")
    @classmethod
    def empty_string_to_none(cls, v):
        if v == "" or (isinstance(v, str) and v.strip() == ""):
            return None
        return v

    @field_validator("phone", mode="before")
    @classmethod
    def normalize_phone(cls, v):
        from app.utils.phone_helpers import normalize_vietnam_phone, validate_vietnam_phone
        if v is None:
            return v
        if isinstance(v, str) and v.strip() == "":
            return None
        normalized = normalize_vietnam_phone(v)
        if normalized is None:
            return None
        if not validate_vietnam_phone(normalized, normalize=False):
            raise ValueError(
                "Số điện thoại không hợp lệ. Vui lòng nhập số điện thoại Việt Nam "
                "(VD: 0901234567, +84901234567)"
            )
        return normalized


class CollaboratorResponse(BaseModel):
    """Full collaborator detail."""
    id: int
    code: str
    full_name: str
    phone: str
    email: Optional[str] = None
    status: str
    unit_id: int
    user_id: Optional[int] = None
    managed_by_officer_id: Optional[int] = None
    id_card_number: Optional[str] = None
    bank_account: Optional[str] = None
    bank_name: Optional[str] = None
    address: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    approved_at: Optional[datetime] = None
    approved_by_id: Optional[int] = None
    # Nested relationships
    unit: Optional[OrganizationUnitShallow] = None
    managed_by_officer: Optional[UserShallow] = None

    model_config = ConfigDict(from_attributes=True)


class CollaboratorApproveResponse(BaseModel):
    """Response for approve endpoint — includes temp credentials if account was created."""
    collaborator: CollaboratorResponse
    account_created: bool = False
    username: Optional[str] = None
    temp_password: Optional[str] = None  # Shown to admin once, not stored
    message: str


class CollaboratorListItem(BaseModel):
    """Collaborator summary for list view — excludes sensitive financial data."""
    id: int
    code: str
    full_name: str
    phone: str
    email: Optional[str] = None
    status: str
    unit_id: int
    managed_by_officer_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime
    approved_at: Optional[datetime] = None
    # Nested relationships
    unit: Optional[OrganizationUnitShallow] = None
    managed_by_officer: Optional[UserShallow] = None

    model_config = ConfigDict(from_attributes=True)


class CollaboratorsPage(BaseModel):
    total_count: int
    collaborators: list[CollaboratorListItem]


# ============================================================================
# LEAD CLAIM SCHEMAS
# ============================================================================


class LeadForCTV(BaseModel):
    """Limited lead view for CTV — masked phone, no email, no sensitive data."""
    id: int
    full_name: str
    phone_masked: str  # "0912***456" — masked by service layer
    status: str
    validity_status: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class LeadClaimData(BaseModel):
    """Structured data validated before storing as JSON."""
    full_name: str = Field(..., min_length=1, max_length=255, strip_whitespace=True)
    phone: str = Field(..., min_length=1, max_length=20, strip_whitespace=True)
    email: Optional[EmailStr] = None
    notes: Optional[str] = Field(None, max_length=500)

    @field_validator("email", mode="before")
    @classmethod
    def empty_string_to_none(cls, v):
        if v == "" or (isinstance(v, str) and v.strip() == ""):
            return None
        return v

    @field_validator("phone", mode="before")
    @classmethod
    def normalize_phone(cls, v):
        from app.utils.phone_helpers import normalize_vietnam_phone, validate_vietnam_phone
        if v is None:
            return v
        if isinstance(v, str) and v.strip() == "":
            return v
        normalized = normalize_vietnam_phone(v)
        if normalized is None:
            return v
        if not validate_vietnam_phone(normalized, normalize=False):
            raise ValueError(
                "Số điện thoại không hợp lệ. Vui lòng nhập số điện thoại Việt Nam "
                "(VD: 0901234567, +84901234567)"
            )
        return normalized


class LeadClaimCreate(BaseModel):
    """CTV submits this to claim a lead."""
    lead_data: LeadClaimData


class LeadClaimReview(BaseModel):
    status: Literal["approved", "rejected"]
    rejection_reason: Optional[str] = Field(None, max_length=500)


class LeadClaimResponse(BaseModel):
    id: int
    collaborator_id: int
    lead_id: int
    status: str
    claim_data: Optional[dict] = None
    reviewed_by_id: Optional[int] = None
    reviewed_at: Optional[datetime] = None
    rejection_reason: Optional[str] = None
    created_at: datetime
    # Nested info
    lead: Optional[LeadForCTV] = None
    collaborator: Optional[CollaboratorShallow] = None

    model_config = ConfigDict(from_attributes=True)


class LeadClaimsPage(BaseModel):
    total_count: int
    claims: list[LeadClaimResponse]


class LeadForCTVPage(BaseModel):
    total_count: int
    leads: list[LeadForCTV]


# ============================================================================
# LEAD VALIDITY SCHEMA
# ============================================================================


class LeadValidityUpdate(BaseModel):
    """Admin/Manager endpoint to set lead validity status."""
    validity_status: Literal["raw", "duplicate", "invalid", "valid", "qualified"]


# ============================================================================
# COLLABORATOR STATS
# ============================================================================


class CollaboratorStats(BaseModel):
    total_leads: int = 0
    valid_leads: int = 0
    qualified_leads: int = 0
    converted_leads: int = 0
    pending_claims: int = 0


# ============================================================================
# PHONE CHECK
# ============================================================================


class PhoneCheckResponse(BaseModel):
    available: bool
    message: Optional[str] = None


# ============================================================================
# CTV SELF-REGISTRATION (Phase 2)
# ============================================================================


class CTVSelfRegistration(BaseModel):
    """Public CTV self-registration form."""
    full_name: str = Field(..., min_length=1, max_length=255, strip_whitespace=True)
    phone: str = Field(..., min_length=1, max_length=20, strip_whitespace=True)
    email: Optional[EmailStr] = None
    id_card_number: Optional[str] = Field(None, max_length=20, strip_whitespace=True)
    address: Optional[str] = Field(None, max_length=500, strip_whitespace=True)
    notes: Optional[str] = Field(None, max_length=1000)
    unit_id: int

    @field_validator("email", mode="before")
    @classmethod
    def empty_string_to_none(cls, v):
        if v == "" or (isinstance(v, str) and v.strip() == ""):
            return None
        return v

    @field_validator("phone", mode="before")
    @classmethod
    def normalize_phone(cls, v):
        from app.utils.phone_helpers import normalize_vietnam_phone, validate_vietnam_phone
        if v is None:
            return v
        if isinstance(v, str) and v.strip() == "":
            return v
        normalized = normalize_vietnam_phone(v)
        if normalized is None:
            return v
        if not validate_vietnam_phone(normalized, normalize=False):
            raise ValueError(
                "Số điện thoại không hợp lệ. Vui lòng nhập số điện thoại Việt Nam "
                "(VD: 0901234567, +84901234567)"
            )
        return normalized


class CTVRegistrationResponse(BaseModel):
    """Safe response for public CTV registration — no PII leak."""
    code: str
    status: str
    message: str


class CTVRegistrationStatus(BaseModel):
    """Response for CTV registration status check."""
    status: str
    message: str
