# app/models/finance/__init__.py
"""
Finance Module Domain Models.

This module contains all SQLAlchemy ORM models for the Finance bounded context.

Tables:
- InstallmentPlan: Payment schedule configurations
- PaymentMethod: Payment method definitions
- AccountingPeriod: Ledger period tracking
- Fee: Main fee record (application, tuition, enrollment, etc.)
- FeeAppliedDiscount: Discount application snapshots
- Invoice: Invoice records with installment support
- PaymentIntent: Online payment intent tracking (2-phase pattern)
- Payment: Confirmed payment records
- PaymentTransaction: Audit trail for all financial transactions
- RefundRequest: Refund request workflow
- OverpaymentRecord: Overpayment liability tracking

Architecture:
- All models follow QLTS patterns (soft delete where applicable, timestamps, version)
- IDOR protection via admission_profile.lead.unit_id relationship
- Security constraints enforced at DB level (CHECK constraints)
"""

from .installment_plan import InstallmentPlan
from .payment_method import PaymentMethod
from .accounting import AccountingPeriod
from .fee import Fee, FeeAppliedDiscount, FeeTypeEnum, FeeStatusEnum
from .invoice import (
    Invoice,
    InvoiceStatusEnum,
    PAYABLE_INVOICE_STATUSES,
    OVERDUE_DERIVED_STATUSES,
)
from .payment_intent import PaymentIntent, PaymentIntentStatusEnum, GatewayStatusEnum
from .payment import Payment, PaymentTransaction, PaymentStatusEnum, TransactionTypeEnum
from .refund import RefundRequest, RefundStatusEnum
from .overpayment import OverpaymentRecord, OverpaymentStatusEnum, ResolutionTypeEnum
from .payment_import import (
    PaymentImportBatch,
    PaymentImportRow,
    PaymentImportBatchStatusEnum,
    PaymentImportRowStatusEnum,
)

__all__ = [
    # Enums - Fee
    "FeeTypeEnum",
    "FeeStatusEnum",
    # Enums - Invoice
    "InvoiceStatusEnum",
    "PAYABLE_INVOICE_STATUSES",
    "OVERDUE_DERIVED_STATUSES",
    # Enums - Payment
    "PaymentIntentStatusEnum",
    "GatewayStatusEnum",
    "PaymentStatusEnum",
    "TransactionTypeEnum",
    # Enums - Refund
    "RefundStatusEnum",
    # Enums - Overpayment
    "OverpaymentStatusEnum",
    "ResolutionTypeEnum",
    # Models - Configuration
    "InstallmentPlan",
    "PaymentMethod",
    # Models - Accounting
    "AccountingPeriod",
    # Models - Core Finance
    "Fee",
    "FeeAppliedDiscount",
    "Invoice",
    # Models - Payment
    "PaymentIntent",
    "Payment",
    "PaymentTransaction",
    # Models - Refund & Overpayment
    "RefundRequest",
    "OverpaymentRecord",
    # Bulk payment import (BV)
    "PaymentImportBatch",
    "PaymentImportRow",
    "PaymentImportBatchStatusEnum",
    "PaymentImportRowStatusEnum",
]
