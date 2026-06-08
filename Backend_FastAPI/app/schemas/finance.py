# app/schemas/finance.py
"""
Pydantic Schemas for Finance Module (Phase 0+1).

Security Features:
- Input Sanitization: html.escape() for text fields (prevent XSS)
- Amount Validation: Positive amounts, max limit (1 trillion VND)
- Type Safety: Pydantic v2 with strict Decimal handling

Architecture Compliance:
- No HTTPException imports (service layer raises custom exceptions)
- Schemas used for request/response validation only
- Enums imported from models for consistency
"""

from datetime import datetime, date
from decimal import Decimal
from typing import List, Optional, Dict, Any
import html

from pydantic import BaseModel, Field, field_validator, model_validator, ConfigDict

from app.models.finance import (
    FeeTypeEnum,
    FeeStatusEnum,
    InvoiceStatusEnum,
    PaymentStatusEnum,
    PaymentIntentStatusEnum,
    RefundStatusEnum,
    OverpaymentStatusEnum,
    ResolutionTypeEnum,
    TransactionTypeEnum,
)


# ==============================================================================
# CONSTANTS
# ==============================================================================

MAX_AMOUNT = Decimal("999999999999")  # ~1 trillion VND
MIN_AMOUNT = Decimal("0.01")


# ==============================================================================
# INSTALLMENT PLAN SCHEMAS
# ==============================================================================

class InstallmentScheduleItem(BaseModel):
    """Single installment in a payment schedule."""
    installment_no: int = Field(..., ge=1, le=12)
    percent: Decimal = Field(..., ge=0, le=100)
    due_days_offset: int = Field(..., ge=0, le=365)

    model_config = ConfigDict(from_attributes=True)


class InstallmentPlanBase(BaseModel):
    """Base schema for installment plans."""
    code: str = Field(..., min_length=1, max_length=50)
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=500)
    installment_count: int = Field(..., ge=1, le=12)
    schedule: List[InstallmentScheduleItem]
    penalty_type: str = Field(default="percentage", pattern=r"^(percentage|fixed)$")
    penalty_rate: Decimal = Field(default=Decimal("0"), ge=0, le=100)
    grace_period_days: int = Field(default=7, ge=0, le=365)
    is_active: bool = True

    @field_validator('name')
    @classmethod
    def sanitize_name(cls, v: str) -> str:
        return html.escape(v.strip())

    @field_validator('description')
    @classmethod
    def sanitize_description(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        return html.escape(v.strip())

    model_config = ConfigDict(from_attributes=True)


class InstallmentPlanCreate(BaseModel):
    """Schema for creating a new installment plan."""
    code: str = Field(..., min_length=1, max_length=50, pattern=r"^[A-Z0-9_]+$")
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=500)
    installment_count: int = Field(..., ge=1, le=12)
    schedule: List[InstallmentScheduleItem]
    penalty_type: str = Field(default="percentage", pattern=r"^(percentage|fixed)$")
    penalty_rate: Decimal = Field(default=Decimal("0"), ge=0, le=100)
    grace_period_days: int = Field(default=7, ge=0, le=365)
    is_active: bool = True

    @field_validator('name')
    @classmethod
    def sanitize_name(cls, v: str) -> str:
        return html.escape(v.strip())

    @field_validator('description')
    @classmethod
    def sanitize_description(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        return html.escape(v.strip())

    @field_validator('schedule')
    @classmethod
    def validate_schedule(cls, v: List[InstallmentScheduleItem], info) -> List[InstallmentScheduleItem]:
        installment_count = info.data.get('installment_count')
        if installment_count is not None and len(v) != installment_count:
            raise ValueError(f"Schedule must have exactly {installment_count} items, got {len(v)}")
        total_percent = sum(item.percent for item in v)
        if total_percent != Decimal("100"):
            raise ValueError(f"Schedule percentages must sum to 100, got {total_percent}")
        nos = [item.installment_no for item in v]
        if len(set(nos)) != len(nos):
            raise ValueError("Duplicate installment_no in schedule")
        return v

    model_config = ConfigDict(from_attributes=True)


class InstallmentPlanUpdate(BaseModel):
    """Schema for updating an installment plan (all fields optional)."""
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=500)
    installment_count: Optional[int] = Field(None, ge=1, le=12)
    schedule: Optional[List[InstallmentScheduleItem]] = None
    penalty_type: Optional[str] = Field(None, pattern=r"^(percentage|fixed)$")
    penalty_rate: Optional[Decimal] = Field(None, ge=0, le=100)
    grace_period_days: Optional[int] = Field(None, ge=0, le=365)
    is_active: Optional[bool] = None

    @field_validator('name')
    @classmethod
    def sanitize_name(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        return html.escape(v.strip())

    @field_validator('description')
    @classmethod
    def sanitize_description(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        return html.escape(v.strip())

    @field_validator('schedule')
    @classmethod
    def validate_schedule(cls, v: Optional[List[InstallmentScheduleItem]], info) -> Optional[List[InstallmentScheduleItem]]:
        if v is None:
            return v
        installment_count = info.data.get('installment_count')
        if installment_count is not None and len(v) != installment_count:
            raise ValueError(f"Schedule must have exactly {installment_count} items, got {len(v)}")
        total_percent = sum(item.percent for item in v)
        if total_percent != Decimal("100"):
            raise ValueError(f"Schedule percentages must sum to 100, got {total_percent}")
        nos = [item.installment_no for item in v]
        if len(set(nos)) != len(nos):
            raise ValueError("Duplicate installment_no in schedule")
        return v

    model_config = ConfigDict(from_attributes=True)


class InstallmentPlanResponse(InstallmentPlanBase):
    """Response schema for installment plan."""
    id: int
    created_at: datetime
    updated_at: Optional[datetime] = None


# ==============================================================================
# PAYMENT METHOD SCHEMAS
# ==============================================================================

class PaymentMethodBase(BaseModel):
    """Base schema for payment methods."""
    code: str = Field(..., min_length=1, max_length=50)
    name: str = Field(..., min_length=1, max_length=100)
    is_online: bool = False
    requires_verification: bool = True
    gateway_code: Optional[str] = None
    display_order: int = Field(default=0, ge=0)
    is_active: bool = True

    @field_validator('name')
    @classmethod
    def sanitize_name(cls, v: str) -> str:
        return html.escape(v.strip())

    model_config = ConfigDict(from_attributes=True)


class PaymentMethodResponse(PaymentMethodBase):
    """Response schema for payment method."""
    id: int
    created_at: datetime


# ==============================================================================
# FEE SCHEMAS
# ==============================================================================

class FeeAppliedDiscountResponse(BaseModel):
    """Response schema for applied discount snapshot.

    Note: policy_name, discount_type, discount_value are extracted from
    the model's calculation_snapshot JSONB field by the router, not from
    direct ORM attributes. Do NOT use model_validate() with ORM objects.
    """
    id: int
    policy_id: int
    policy_name: str  # From calculation_snapshot
    discount_type: str  # From calculation_snapshot
    discount_value: Decimal  # From calculation_snapshot
    discount_amount: Decimal  # Direct model field
    application_order: int  # Direct model field


class FeeBase(BaseModel):
    """Base schema for fees."""
    fee_type: FeeTypeEnum = FeeTypeEnum.tuition

    model_config = ConfigDict(from_attributes=True)


class FeeCreate(FeeBase):
    """Schema for creating a new fee."""
    admission_profile_id: int
    academic_year: int = Field(..., ge=2020, le=2100)
    installment_plan_id: Optional[int] = None
    base_amount: Decimal = Field(..., ge=0, le=MAX_AMOUNT)
    notes: Optional[str] = Field(None, max_length=500)

    @field_validator('notes')
    @classmethod
    def sanitize_notes(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        return html.escape(v.strip())


class FeeCalculateRequest(BaseModel):
    """Request schema for fee calculation.

    For tuition fees, `semester_no` defaults to 1 (HK1) if not provided.
    The service looks up the canonical amount from `offering_semester_tuition`.
    For non-tuition fees, `semester_no` must be None (the service ignores it).
    """
    admission_profile_id: int
    fee_type: FeeTypeEnum = FeeTypeEnum.tuition
    installment_plan_code: str = Field(default="FULL", max_length=50)
    semester_no: Optional[int] = Field(
        None, ge=1,
        description="Số học kỳ (HK1=1). Mặc định 1 cho tuition, None cho non-tuition."
    )

    @model_validator(mode="after")
    def default_semester_for_tuition(self):
        if self.fee_type == FeeTypeEnum.tuition and self.semester_no is None:
            self.semester_no = 1
        return self

    model_config = ConfigDict(from_attributes=True)


class FeeResponse(FeeBase):
    """Response schema for fee."""
    id: int
    admission_profile_id: int
    installment_plan_id: Optional[int]
    academic_year: str  # Formatted as "YYYY-YYYY" by router

    # Semester (PR 3 — ADR-002)
    semester_no: Optional[int] = None

    # Amounts
    base_amount: Decimal
    total_discount: Decimal
    final_amount: Decimal
    paid_amount: Decimal
    waived_amount: Decimal
    remaining_amount: Decimal  # Computed property

    # Status
    status: FeeStatusEnum

    # Metadata
    notes: Optional[str]
    version: int
    created_at: datetime
    updated_at: datetime

    # Nested data
    applied_discounts: List[FeeAppliedDiscountResponse] = []

    # P1: Permission flags - computed in router based on status and amounts
    can_waive: bool = False
    can_cancel: bool = False
    can_recalculate: bool = False

    # P3: First invoice due date for quick reference
    due_date: Optional[date] = None

    model_config = ConfigDict(from_attributes=True)


class FeeSummaryResponse(BaseModel):
    """Summary response for fee list."""
    id: int
    fee_type: FeeTypeEnum
    academic_year: str
    semester_no: Optional[int] = None
    final_amount: Decimal
    paid_amount: Decimal
    remaining_amount: Decimal
    status: FeeStatusEnum

    model_config = ConfigDict(from_attributes=True)


class FeeWaiveRequest(BaseModel):
    """Request schema for waiving fee amount."""
    waive_amount: Decimal = Field(..., gt=0, le=MAX_AMOUNT)
    reason: str = Field(..., min_length=1, max_length=500)

    @field_validator('reason')
    @classmethod
    def sanitize_reason(cls, v: str) -> str:
        return html.escape(v.strip())


# ==============================================================================
# INVOICE SCHEMAS
# ==============================================================================

class InvoiceBase(BaseModel):
    """Base schema for invoices."""
    amount: Decimal = Field(..., gt=0, le=MAX_AMOUNT)
    due_date: date

    model_config = ConfigDict(from_attributes=True)


class InvoiceCreate(InvoiceBase):
    """Schema for creating invoice."""
    fee_id: int
    installment_no: int = Field(default=1, ge=1, le=12)


class InvoiceResponse(InvoiceBase):
    """Response schema for invoice."""
    id: int
    fee_id: int
    invoice_number: str
    installment_no: int
    status: InvoiceStatusEnum
    paid_amount: Decimal
    remaining_amount: Decimal  # Computed property
    issued_at: Optional[datetime]
    paid_at: Optional[datetime]
    cancelled_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    # P1: Permission flags - computed in router based on status and amounts
    # can_issue: status == 'draft'
    # can_cancel: status not in ['paid', 'cancelled'] AND paid_amount == 0
    # can_record_payment: status == 'issued' AND remaining_amount > 0
    # can_apply_penalty: status == 'overdue'
    can_issue: bool = False
    can_cancel: bool = False
    can_record_payment: bool = False
    can_apply_penalty: bool = False

    model_config = ConfigDict(from_attributes=True)


class InvoiceSummaryResponse(BaseModel):
    """Summary response for invoice list."""
    id: int
    invoice_number: str
    installment_no: int
    amount: Decimal
    paid_amount: Decimal
    remaining_amount: Decimal
    due_date: date
    status: InvoiceStatusEnum

    model_config = ConfigDict(from_attributes=True)


# ==============================================================================
# PAYMENT INTENT SCHEMAS (Online Payments)
# ==============================================================================

class PaymentIntentCreate(BaseModel):
    """Schema for creating payment intent."""
    invoice_id: int
    method_id: int
    amount: Decimal = Field(..., gt=0, le=MAX_AMOUNT)
    idempotency_key: str = Field(..., min_length=1, max_length=100)
    return_url: Optional[str] = Field(None, max_length=500)

    @field_validator('amount')
    @classmethod
    def validate_amount(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("Payment amount must be positive")
        if v > MAX_AMOUNT:
            raise ValueError("Payment amount exceeds maximum")
        return v

    model_config = ConfigDict(from_attributes=True)


class PaymentIntentResponse(BaseModel):
    """Response schema for payment intent."""
    id: int
    invoice_id: int
    method_id: int
    amount: Decimal
    currency: str
    status: PaymentIntentStatusEnum
    gateway_ref: Optional[str]
    gateway_status: Optional[str]
    pay_url: Optional[str]
    expires_at: datetime
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class GatewayCallbackData(BaseModel):
    """Schema for gateway callback data."""
    gateway_ref: str
    status: str
    amount: Decimal
    signature: str
    raw_data: Dict[str, Any] = {}

    model_config = ConfigDict(from_attributes=True)


# ==============================================================================
# PAYMENT SCHEMAS (Manual Payments)
# ==============================================================================

class PaymentCreate(BaseModel):
    """Schema for creating manual payment."""
    invoice_id: int
    method_id: int
    amount: Decimal = Field(..., gt=0, le=MAX_AMOUNT)
    payment_date: Optional[datetime] = None
    reference_code: Optional[str] = Field(None, max_length=100)
    payer_name: Optional[str] = Field(None, max_length=200)
    payer_account: Optional[str] = Field(None, max_length=100)
    notes: Optional[str] = Field(None, max_length=500)

    @field_validator('amount')
    @classmethod
    def validate_amount(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("Payment amount must be positive")
        if v > MAX_AMOUNT:
            raise ValueError("Payment amount exceeds maximum")
        return v

    @field_validator('payer_name', 'notes')
    @classmethod
    def sanitize_text(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        return html.escape(v.strip())

    model_config = ConfigDict(from_attributes=True)


class PaymentVerifyRequest(BaseModel):
    """Schema for verifying manual payment (maker-checker)."""
    payment_id: int
    approve: bool = True
    rejection_reason: Optional[str] = Field(None, max_length=500)

    @field_validator('rejection_reason')
    @classmethod
    def validate_rejection_reason(cls, v: Optional[str], info) -> Optional[str]:
        # Rejection reason required if rejecting
        approve = info.data.get('approve', True)
        if not approve and not v:
            raise ValueError("Rejection reason is required when rejecting")
        if v:
            return html.escape(v.strip())
        return v

    model_config = ConfigDict(from_attributes=True)


class PaymentResponse(BaseModel):
    """Response schema for payment."""
    id: int
    invoice_id: int
    method_id: int
    intent_id: Optional[int]
    amount: Decimal
    status: PaymentStatusEnum
    reference_code: Optional[str]
    payer_name: Optional[str]
    payment_date: Optional[datetime]
    verified_at: Optional[datetime]
    rejected_at: Optional[datetime]
    created_by_id: int
    verified_by_id: Optional[int]
    rejection_reason: Optional[str]
    notes: Optional[str]
    created_at: datetime
    updated_at: datetime

    # P1: Permission flags (Maker-Checker enforcement)
    # Computed in router based on current user context
    can_verify: bool = False
    can_reject: bool = False

    # P2: Denormalized user display names
    created_by_name: Optional[str] = None
    verified_by_name: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class PaymentSummaryResponse(BaseModel):
    """Summary response for payment list."""
    id: int
    invoice_id: int
    amount: Decimal
    status: PaymentStatusEnum
    payment_date: Optional[datetime]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ==============================================================================
# PAYMENT TRANSACTION SCHEMAS (Audit Trail)
# ==============================================================================

class PaymentTransactionResponse(BaseModel):
    """Response schema for payment transaction (audit trail)."""
    id: int
    payment_id: Optional[int]
    fee_id: int
    period_id: Optional[int]
    transaction_type: TransactionTypeEnum
    amount: Decimal
    balance_before: Decimal
    balance_after: Decimal
    external_reference: Optional[str]
    performed_by_id: Optional[int]
    notes: Optional[str]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ==============================================================================
# REFUND SCHEMAS
# ==============================================================================

class RefundRequestCreate(BaseModel):
    """Schema for creating refund request."""
    payment_id: int
    amount: Decimal = Field(..., gt=0, le=MAX_AMOUNT)
    reason: str = Field(..., min_length=1, max_length=1000)

    @field_validator('amount')
    @classmethod
    def validate_amount(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("Refund amount must be positive")
        return v

    @field_validator('reason')
    @classmethod
    def sanitize_reason(cls, v: str) -> str:
        return html.escape(v.strip())

    model_config = ConfigDict(from_attributes=True)


class RefundApproveRequest(BaseModel):
    """Schema for approving/rejecting refund."""
    refund_id: int
    approve: bool = True
    rejection_reason: Optional[str] = Field(None, max_length=500)

    @field_validator('rejection_reason')
    @classmethod
    def validate_rejection_reason(cls, v: Optional[str], info) -> Optional[str]:
        approve = info.data.get('approve', True)
        if not approve and not v:
            raise ValueError("Rejection reason is required when rejecting")
        if v:
            return html.escape(v.strip())
        return v


class RefundProcessRequest(BaseModel):
    """Schema for processing approved refund."""
    refund_id: int
    refund_reference: str = Field(..., min_length=1, max_length=100)


class RefundRejectRequest(BaseModel):
    """Schema for rejecting a refund request."""
    rejection_reason: str = Field(..., min_length=1, max_length=500)

    @field_validator('rejection_reason')
    @classmethod
    def sanitize_rejection_reason(cls, v: str) -> str:
        return html.escape(v.strip())


class RefundRequestResponse(BaseModel):
    """Response schema for refund request."""
    id: int
    payment_id: int
    amount: Decimal
    reason: str
    status: RefundStatusEnum
    requested_at: datetime
    requested_by_id: int
    approved_at: Optional[datetime]
    approved_by_id: Optional[int]
    rejected_at: Optional[datetime]
    rejected_by_id: Optional[int]
    rejection_reason: Optional[str]
    refunded_at: Optional[datetime]
    refund_reference: Optional[str]
    created_at: datetime
    updated_at: datetime
    can_approve: bool = False
    can_reject: bool = False
    can_process: bool = False

    model_config = ConfigDict(from_attributes=True)


# ==============================================================================
# OVERPAYMENT SCHEMAS
# ==============================================================================

class OverpaymentApplyRequest(BaseModel):
    """Schema for applying overpayment to another invoice."""
    overpayment_id: int
    target_invoice_id: int
    amount: Optional[Decimal] = Field(None, gt=0, le=MAX_AMOUNT)
    notes: Optional[str] = Field(None, max_length=500)

    @field_validator('notes')
    @classmethod
    def sanitize_notes(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        return html.escape(v.strip())


class OverpaymentRefundRequest(BaseModel):
    """Schema for refunding overpayment."""
    overpayment_id: int
    notes: Optional[str] = Field(None, max_length=500)

    @field_validator('notes')
    @classmethod
    def sanitize_notes(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        return html.escape(v.strip())


class OverpaymentWriteOffRequest(BaseModel):
    """Schema for writing off overpayment (requires manager approval)."""
    overpayment_id: int
    reason: str = Field(..., min_length=1, max_length=500)

    @field_validator('reason')
    @classmethod
    def sanitize_reason(cls, v: str) -> str:
        return html.escape(v.strip())


class OverpaymentRecordResponse(BaseModel):
    """Response schema for overpayment record."""
    id: int
    payment_id: int
    invoice_id: int
    admission_profile_id: int
    overpayment_amount: Decimal
    currency: str
    status: OverpaymentStatusEnum
    resolution_type: Optional[ResolutionTypeEnum]
    resolved_at: Optional[datetime]
    resolved_by_id: Optional[int]
    resolution_notes: Optional[str]
    applied_to_invoice_id: Optional[int]
    applied_amount: Optional[Decimal]
    refund_request_id: Optional[int]
    created_at: datetime
    updated_at: datetime
    can_resolve: bool = False
    # Granular maker-checker flags (mirror Casbin): apply/refund are accountant
    # finance actions; write-off is a manager action. ``can_resolve`` stays as
    # the coarse "row has any action for me" flag.
    can_apply: bool = False
    can_refund: bool = False
    can_write_off: bool = False

    model_config = ConfigDict(from_attributes=True)


# ==============================================================================
# ACCOUNTING PERIOD SCHEMAS
# ==============================================================================

class AccountingPeriodBase(BaseModel):
    """Base schema for accounting period."""
    month: int = Field(..., ge=1, le=12, validation_alias="period_month")
    year: int = Field(..., ge=2020, le=2100, validation_alias="period_year")

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class AccountingPeriodCreate(AccountingPeriodBase):
    """Schema for creating accounting period."""
    pass


class AccountingPeriodResponse(AccountingPeriodBase):
    """Response schema for accounting period."""
    id: int
    is_closed: bool
    closed_at: Optional[datetime]
    closed_by_id: Optional[int]
    total_payments: Decimal
    total_refunds: Decimal
    net_revenue: Decimal
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AccountingPeriodCloseRequest(BaseModel):
    """Schema for closing accounting period."""
    period_id: int
    notes: Optional[str] = Field(None, max_length=500)

    @field_validator('notes')
    @classmethod
    def sanitize_notes(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        return html.escape(v.strip())


# ==============================================================================
# COMPOSITE RESPONSE SCHEMAS
# ==============================================================================

class FeeDetailResponse(FeeResponse):
    """Detailed fee response with invoices."""
    invoices: List[InvoiceSummaryResponse] = []
    installment_plan: Optional[InstallmentPlanResponse] = None

    model_config = ConfigDict(from_attributes=True)


class InvoiceDetailResponse(InvoiceResponse):
    """Detailed invoice response with payments."""
    payments: List[PaymentSummaryResponse] = []
    fee: Optional[FeeSummaryResponse] = None

    model_config = ConfigDict(from_attributes=True)


class ProfileFinanceSummary(BaseModel):
    """Financial summary for an admission profile."""
    admission_profile_id: int
    total_fees: Decimal
    total_paid: Decimal
    total_remaining: Decimal
    fees: List[FeeSummaryResponse] = []
    pending_invoices: int = 0
    overdue_invoices: int = 0

    model_config = ConfigDict(from_attributes=True)


# ==============================================================================
# PAGINATION RESPONSE SCHEMAS
# ==============================================================================

class FeeListItem(FeeSummaryResponse):
    """Fee item for list view with additional profile info."""
    profile_name: Optional[str] = None
    due_date: Optional[date] = None

    model_config = ConfigDict(from_attributes=True)


class FeesPage(BaseModel):
    """Paginated fees response."""
    items: List[FeeListItem]
    total: int
    page: int
    page_size: int

    model_config = ConfigDict(from_attributes=True)


class InvoiceListItem(InvoiceSummaryResponse):
    """Invoice item for list view with additional info."""
    profile_name: Optional[str] = None
    fee_type: Optional[FeeTypeEnum] = None

    model_config = ConfigDict(from_attributes=True)


class InvoicesPage(BaseModel):
    """Paginated invoices response."""
    items: List[InvoiceListItem]
    total: int
    page: int
    page_size: int

    model_config = ConfigDict(from_attributes=True)


class PaymentListItem(PaymentSummaryResponse):
    """Payment item for list view with additional info."""
    profile_name: Optional[str] = None
    method_name: Optional[str] = None
    created_by_name: Optional[str] = None
    can_verify: bool = False
    can_reject: bool = False

    model_config = ConfigDict(from_attributes=True)


class PaymentsPage(BaseModel):
    """Paginated payments response."""
    items: List[PaymentListItem]
    total: int
    page: int
    page_size: int

    model_config = ConfigDict(from_attributes=True)


class RefundsPage(BaseModel):
    """Paginated refunds response."""
    items: List[RefundRequestResponse]
    total: int
    page: int
    page_size: int
    # Page-level capability: only officer/accountant/admin may create a refund
    # request (mirror Casbin POST /api/refunds). Manager is approver-only.
    can_create: bool = False

    model_config = ConfigDict(from_attributes=True)


class OverpaymentsPage(BaseModel):
    """Paginated overpayments response."""
    items: List[OverpaymentRecordResponse]
    total: int
    page: int
    page_size: int

    model_config = ConfigDict(from_attributes=True)


class VietQRBankAccount(BaseModel):
    """Public bank collection account shown beside a VietQR code."""
    bank_bin: str
    account_number: str
    account_name: str


class VietQRResponse(BaseModel):
    """VietQR payload and rendered image for an invoice transfer."""
    qr_payload: str
    qr_image_base64: str
    bank_account: VietQRBankAccount
    amount: Decimal
    content: str


class DebtReportRow(BaseModel):
    """Single debtor row aggregated by admission profile."""
    admission_profile_id: int
    profile_code: str
    profile_name: str
    unit_id: Optional[int] = None
    unit_name: Optional[str] = None
    academic_year: int
    admission_round_id: Optional[int] = None
    fee_types: List[str] = []
    invoice_count: int
    total_expected: Decimal
    total_paid: Decimal
    total_outstanding: Decimal
    days_overdue: int
    aging_bucket: str


class DebtReportSummary(BaseModel):
    """Debt report totals and bucket totals."""
    debtor_count: int
    total_expected: Decimal
    total_paid: Decimal
    total_outstanding: Decimal
    bucket_0_30: Decimal = Decimal("0")
    bucket_31_60: Decimal = Decimal("0")
    bucket_over_60: Decimal = Decimal("0")


class DebtReportResponse(BaseModel):
    """Debt report response grouped by admission profile."""
    items: List[DebtReportRow]
    summary: DebtReportSummary


# ==============================================================================
# DASHBOARD STATS SCHEMA
# ==============================================================================

class FinanceDashboardStats(BaseModel):
    """Finance dashboard statistics."""
    pending_fees_count: int = 0
    pending_fees_amount: Decimal = Decimal("0")
    pending_payments_count: int = 0
    overdue_invoices_count: int = 0
    overdue_amount: Decimal = Decimal("0")
    today_collections: Decimal = Decimal("0")
    monthly_collections: Decimal = Decimal("0")
    period_collections: Decimal = Decimal("0")
    period_start: Optional[date] = None
    period_end: Optional[date] = None
    pending_overpayments_count: int = 0
    pending_refunds_count: int = 0

    model_config = ConfigDict(from_attributes=True)
