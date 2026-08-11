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
from .refund import RefundRequest, RefundSourceEnum, RefundStatusEnum
from .overpayment import OverpaymentRecord, OverpaymentStatusEnum, ResolutionTypeEnum
from .payment_import import (
    PaymentImportBatch,
    PaymentImportRow,
    PaymentImportBatchStatusEnum,
    PaymentImportRowStatusEnum,
    PaymentImportCommitStatusEnum,
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
    "RefundSourceEnum",
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
    "PaymentImportCommitStatusEnum",
]

# Nhập vì TÁC DỤNG PHỤ: module này gắn trigger `duplicate_guard_version` vào
# `after_create` của metadata, thứ `Base.metadata.create_all()` cần để cơ sở dữ
# liệu TEST có cùng hàng rào với cơ sở dữ liệu thật. Đặt ở cuối tệp vì nó phải
# chạy sau khi mọi bảng đã được khai báo. Không có dòng này, các ca kiểm
# "ghi phiếu phải làm version tăng" chạy trên một DB không có trigger — xanh vì
# không có gì để hỏng.
from app.models.finance import duplicate_guard_ddl  # noqa: E402,F401
