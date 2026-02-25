# app/schemas/commission.py
"""
Commission System Schemas - Pydantic validation models.
"""
from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .collaborator import CollaboratorShallow
from .organization import OrganizationUnitShallow


# ============================================================================
# COMMISSION POLICY SCHEMAS
# ============================================================================


class CommissionPolicyCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255, strip_whitespace=True)
    description: Optional[str] = None
    trigger_status_id: str = Field(..., min_length=1, max_length=50)
    calculation_type: Literal["fixed", "percentage"]
    fixed_amount: Optional[Decimal] = Field(None, ge=0, decimal_places=0)
    percentage: Optional[Decimal] = Field(None, ge=0, le=100, decimal_places=2)
    unit_id: Optional[int] = None
    offering_id: Optional[int] = None
    effective_from: date
    effective_to: Optional[date] = None
    is_active: bool = True

    @model_validator(mode="after")
    def validate_calculation_fields(self):
        if self.calculation_type == "fixed":
            if self.fixed_amount is None:
                raise ValueError("fixed_amount is required when calculation_type is 'fixed'")
        elif self.calculation_type == "percentage":
            if self.percentage is None:
                raise ValueError("percentage is required when calculation_type is 'percentage'")
        return self


class CommissionPolicyUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255, strip_whitespace=True)
    description: Optional[str] = None
    trigger_status_id: Optional[str] = Field(None, min_length=1, max_length=50)
    calculation_type: Optional[Literal["fixed", "percentage"]] = None
    fixed_amount: Optional[Decimal] = Field(None, ge=0, decimal_places=0)
    percentage: Optional[Decimal] = Field(None, ge=0, le=100, decimal_places=2)
    unit_id: Optional[int] = None
    offering_id: Optional[int] = None
    effective_from: Optional[date] = None
    effective_to: Optional[date] = None
    is_active: Optional[bool] = None


class CommissionPolicyResponse(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    trigger_status_id: str
    calculation_type: str
    fixed_amount: Optional[Decimal] = None
    percentage: Optional[Decimal] = None
    unit_id: Optional[int] = None
    offering_id: Optional[int] = None
    effective_from: date
    effective_to: Optional[date] = None
    is_active: bool
    created_by_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime
    unit: Optional[OrganizationUnitShallow] = None

    model_config = ConfigDict(from_attributes=True)


class CommissionPoliciesPage(BaseModel):
    total_count: int
    policies: list[CommissionPolicyResponse]


# ============================================================================
# COMMISSION RECORD SCHEMAS
# ============================================================================


class LeadShallow(BaseModel):
    """Minimal lead info for embedding in commission responses."""
    id: int
    full_name: Optional[str] = None
    phone: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class CommissionPolicyShallow(BaseModel):
    id: int
    name: str
    calculation_type: str

    model_config = ConfigDict(from_attributes=True)


class CommissionRecordResponse(BaseModel):
    id: int
    collaborator_id: int
    lead_id: int
    policy_id: int
    amount: Decimal
    calculation_detail: Optional[dict] = None
    status: str
    trigger_status_id: str
    triggered_at: datetime
    approved_by_id: Optional[int] = None
    approved_at: Optional[datetime] = None
    rejected_by_id: Optional[int] = None
    rejected_at: Optional[datetime] = None
    rejection_reason: Optional[str] = None
    cancelled_at: Optional[datetime] = None
    cancelled_by_id: Optional[int] = None
    cancellation_reason: Optional[str] = None
    paid_at: Optional[datetime] = None
    paid_by_id: Optional[int] = None
    payment_reference: Optional[str] = None
    created_at: datetime
    # Nested
    collaborator: Optional[CollaboratorShallow] = None
    lead: Optional[LeadShallow] = None
    policy: Optional[CommissionPolicyShallow] = None

    model_config = ConfigDict(from_attributes=True)


class CommissionRecordsPage(BaseModel):
    total_count: int
    records: list[CommissionRecordResponse]


class CommissionReject(BaseModel):
    rejection_reason: str = Field(..., min_length=1, max_length=500)


class CommissionPay(BaseModel):
    payment_reference: Optional[str] = Field(None, max_length=255)


# ============================================================================
# COMMISSION STATS (for CTV dashboard)
# ============================================================================


class CommissionStats(BaseModel):
    total_earned: Decimal = Decimal("0")
    total_pending: Decimal = Decimal("0")
    total_paid: Decimal = Decimal("0")
    total_rejected: Decimal = Decimal("0")
    record_count: int = 0
