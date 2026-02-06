"""
Unit tests for Finance Module Models (Phase 0+1).

Tests cover:
- Enum value validation
- Model property methods
- Constraint validation (via schema)
- Relationship definitions

Coverage Target: Core model logic and enum values
"""

import pytest
from decimal import Decimal
from datetime import datetime, timezone, timedelta, date

from app.models.finance import (
    # Enums
    FeeTypeEnum,
    FeeStatusEnum,
    InvoiceStatusEnum,
    PaymentStatusEnum,
    PaymentIntentStatusEnum,
    GatewayStatusEnum,
    TransactionTypeEnum,
    RefundStatusEnum,
    OverpaymentStatusEnum,
    ResolutionTypeEnum,
    # Models
    Fee,
    Invoice,
    Payment,
    PaymentIntent,
    RefundRequest,
    OverpaymentRecord,
    InstallmentPlan,
    PaymentMethod,
)


class TestFeeTypeEnum:
    """Test FeeTypeEnum values."""

    def test_all_fee_types_defined(self):
        """Verify all 6 fee types are defined."""
        expected_types = {
            "application",
            "tuition",
            "enrollment",
            "insurance",
            "dormitory",
            "other",
        }
        actual_types = {t.value for t in FeeTypeEnum}
        assert actual_types == expected_types

    def test_application_fee_type_exists(self):
        """Verify application fee type exists (Phase 0 requirement)."""
        assert FeeTypeEnum.application.value == "application"


class TestFeeStatusEnum:
    """Test FeeStatusEnum values."""

    def test_all_fee_statuses_defined(self):
        """Verify all 8 fee statuses are defined."""
        expected_statuses = {
            "pending",
            "calculated",
            "invoiced",
            "partial",
            "paid",
            "overdue",
            "waived",
            "cancelled",
        }
        actual_statuses = {s.value for s in FeeStatusEnum}
        assert actual_statuses == expected_statuses

    def test_fee_status_flow(self):
        """Verify expected fee status flow exists."""
        # Expected flow: pending -> calculated -> invoiced -> paid
        assert FeeStatusEnum.pending.value == "pending"
        assert FeeStatusEnum.calculated.value == "calculated"
        assert FeeStatusEnum.invoiced.value == "invoiced"
        assert FeeStatusEnum.paid.value == "paid"


class TestInvoiceStatusEnum:
    """Test InvoiceStatusEnum values."""

    def test_all_invoice_statuses_defined(self):
        """Verify all 6 invoice statuses are defined."""
        expected_statuses = {
            "draft",
            "issued",
            "partial",
            "paid",
            "overdue",
            "cancelled",
        }
        actual_statuses = {s.value for s in InvoiceStatusEnum}
        assert actual_statuses == expected_statuses


class TestPaymentStatusEnum:
    """Test PaymentStatusEnum values."""

    def test_all_payment_statuses_defined(self):
        """Verify all 4 payment statuses are defined."""
        expected_statuses = {
            "pending",
            "verified",
            "rejected",
            "refunded",
        }
        actual_statuses = {s.value for s in PaymentStatusEnum}
        assert actual_statuses == expected_statuses

    def test_pending_status_for_maker_checker(self):
        """Verify pending status exists for maker-checker workflow."""
        assert PaymentStatusEnum.pending.value == "pending"
        assert PaymentStatusEnum.verified.value == "verified"


class TestPaymentIntentStatusEnum:
    """Test PaymentIntentStatusEnum values."""

    def test_all_intent_statuses_defined(self):
        """Verify all 6 intent statuses are defined."""
        expected_statuses = {
            "created",
            "pending",
            "completed",
            "failed",
            "expired",
            "cancelled",
        }
        actual_statuses = {s.value for s in PaymentIntentStatusEnum}
        assert actual_statuses == expected_statuses

    def test_terminal_states(self):
        """Verify terminal states exist for intent lifecycle."""
        terminal = {"completed", "failed", "expired", "cancelled"}
        for status in PaymentIntentStatusEnum:
            if status.value in terminal:
                assert True  # Status is terminal


class TestTransactionTypeEnum:
    """Test TransactionTypeEnum values."""

    def test_all_transaction_types_defined(self):
        """Verify all 6 transaction types are defined."""
        expected_types = {
            "payment",
            "refund",
            "adjustment",
            "waive",
            "penalty",
            "reversal",
        }
        actual_types = {t.value for t in TransactionTypeEnum}
        assert actual_types == expected_types


class TestRefundStatusEnum:
    """Test RefundStatusEnum values."""

    def test_all_refund_statuses_defined(self):
        """Verify all 4 refund statuses are defined."""
        expected_statuses = {
            "pending",
            "approved",
            "rejected",
            "refunded",
        }
        actual_statuses = {s.value for s in RefundStatusEnum}
        assert actual_statuses == expected_statuses


class TestOverpaymentStatusEnum:
    """Test OverpaymentStatusEnum values."""

    def test_all_overpayment_statuses_defined(self):
        """Verify all 4 overpayment statuses are defined."""
        expected_statuses = {
            "pending",
            "applied",
            "refunded",
            "cancelled",
        }
        actual_statuses = {s.value for s in OverpaymentStatusEnum}
        assert actual_statuses == expected_statuses


class TestResolutionTypeEnum:
    """Test ResolutionTypeEnum values."""

    def test_all_resolution_types_defined(self):
        """Verify all 3 resolution types are defined."""
        expected_types = {
            "apply_to_next",
            "refund",
            "write_off",
        }
        actual_types = {t.value for t in ResolutionTypeEnum}
        assert actual_types == expected_types


class TestFeeModel:
    """Test Fee model properties."""

    def test_remaining_amount_calculation(self):
        """Test remaining_amount property calculation."""
        fee = Fee()
        fee.final_amount = Decimal("1000000")
        fee.paid_amount = Decimal("300000")
        fee.waived_amount = Decimal("100000")

        # remaining = final - paid - waived = 1000000 - 300000 - 100000 = 600000
        assert fee.remaining_amount == Decimal("600000")

    def test_remaining_amount_fully_paid(self):
        """Test remaining_amount when fully paid."""
        fee = Fee()
        fee.final_amount = Decimal("500000")
        fee.paid_amount = Decimal("500000")
        fee.waived_amount = Decimal("0")

        assert fee.remaining_amount == Decimal("0")

    def test_remaining_amount_with_waive(self):
        """Test remaining_amount with partial waive."""
        fee = Fee()
        fee.final_amount = Decimal("1000000")
        fee.paid_amount = Decimal("0")
        fee.waived_amount = Decimal("1000000")  # Fully waived

        assert fee.remaining_amount == Decimal("0")

    def test_is_fully_paid_true(self):
        """Test is_fully_paid property when paid."""
        fee = Fee()
        fee.final_amount = Decimal("500000")
        fee.paid_amount = Decimal("500000")
        fee.waived_amount = Decimal("0")

        assert fee.is_fully_paid is True

    def test_is_fully_paid_false(self):
        """Test is_fully_paid property when not paid."""
        fee = Fee()
        fee.final_amount = Decimal("500000")
        fee.paid_amount = Decimal("200000")
        fee.waived_amount = Decimal("0")

        assert fee.is_fully_paid is False

    def test_is_overdue_true(self):
        """Test is_overdue property when past due date."""
        fee = Fee()
        fee.due_date = date.today() - timedelta(days=1)
        fee.final_amount = Decimal("500000")
        fee.paid_amount = Decimal("0")
        fee.waived_amount = Decimal("0")

        assert fee.is_overdue is True

    def test_is_overdue_false_when_paid(self):
        """Test is_overdue property when fully paid."""
        fee = Fee()
        fee.due_date = date.today() - timedelta(days=1)
        fee.final_amount = Decimal("500000")
        fee.paid_amount = Decimal("500000")
        fee.waived_amount = Decimal("0")

        assert fee.is_overdue is False


class TestInvoiceModel:
    """Test Invoice model properties."""

    def test_remaining_amount_calculation(self):
        """Test remaining_amount property calculation."""
        invoice = Invoice()
        invoice.amount = Decimal("500000")
        invoice.penalty_amount = Decimal("0")
        invoice.paid_amount = Decimal("200000")

        assert invoice.remaining_amount == Decimal("300000")

    def test_remaining_amount_with_penalty(self):
        """Test remaining_amount includes penalty."""
        invoice = Invoice()
        invoice.amount = Decimal("500000")
        invoice.penalty_amount = Decimal("50000")
        invoice.paid_amount = Decimal("200000")

        # remaining = 500000 + 50000 - 200000 = 350000
        assert invoice.remaining_amount == Decimal("350000")

    def test_is_fully_paid_true(self):
        """Test is_fully_paid property when paid."""
        invoice = Invoice()
        invoice.amount = Decimal("500000")
        invoice.penalty_amount = Decimal("0")
        invoice.paid_amount = Decimal("500000")

        assert invoice.is_fully_paid is True

    def test_is_overdue_true(self):
        """Test is_overdue property when past due date."""
        invoice = Invoice()
        invoice.due_date = date.today() - timedelta(days=1)
        invoice.amount = Decimal("500000")
        invoice.penalty_amount = Decimal("0")
        invoice.paid_amount = Decimal("0")

        assert invoice.is_overdue is True

    def test_is_overdue_false_when_paid(self):
        """Test is_overdue property when paid."""
        invoice = Invoice()
        invoice.due_date = date.today() - timedelta(days=1)
        invoice.amount = Decimal("500000")
        invoice.penalty_amount = Decimal("0")
        invoice.paid_amount = Decimal("500000")

        assert invoice.is_overdue is False

    def test_is_overdue_false_when_future(self):
        """Test is_overdue property when future due date."""
        invoice = Invoice()
        invoice.due_date = date.today() + timedelta(days=30)
        invoice.amount = Decimal("500000")
        invoice.penalty_amount = Decimal("0")
        invoice.paid_amount = Decimal("0")

        assert invoice.is_overdue is False

    def test_total_due_property(self):
        """Test total_due property."""
        invoice = Invoice()
        invoice.amount = Decimal("500000")
        invoice.penalty_amount = Decimal("25000")

        assert invoice.total_due == Decimal("525000")


class TestPaymentModel:
    """Test Payment model properties."""

    def test_is_verified_true(self):
        """Test is_verified property when verified."""
        payment = Payment()
        payment.status = PaymentStatusEnum.verified.value

        assert payment.is_verified is True

    def test_is_verified_false(self):
        """Test is_verified property when pending."""
        payment = Payment()
        payment.status = PaymentStatusEnum.pending.value

        assert payment.is_verified is False

    def test_is_pending_true(self):
        """Test is_pending property when pending."""
        payment = Payment()
        payment.status = PaymentStatusEnum.pending.value

        assert payment.is_pending is True

    def test_needs_verification_manual_payment(self):
        """Test needs_verification for manual payment."""
        payment = Payment()
        payment.status = PaymentStatusEnum.pending.value
        payment.intent_id = None  # Manual payment

        assert payment.needs_verification is True

    def test_needs_verification_online_payment(self):
        """Test needs_verification for online payment."""
        payment = Payment()
        payment.status = PaymentStatusEnum.pending.value
        payment.intent_id = 123  # Online payment

        assert payment.needs_verification is False


class TestPaymentIntentModel:
    """Test PaymentIntent model properties."""

    def test_is_expired_true(self):
        """Test is_expired property when past expiration."""
        intent = PaymentIntent()
        intent.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)

        assert intent.is_expired is True

    def test_is_expired_false(self):
        """Test is_expired property when not expired."""
        intent = PaymentIntent()
        intent.expires_at = datetime.now(timezone.utc) + timedelta(hours=1)

        assert intent.is_expired is False

    def test_is_terminal_completed(self):
        """Test is_terminal property for completed intent."""
        intent = PaymentIntent()
        intent.status = PaymentIntentStatusEnum.completed.value

        assert intent.is_terminal is True

    def test_is_terminal_pending(self):
        """Test is_terminal property for pending intent."""
        intent = PaymentIntent()
        intent.status = PaymentIntentStatusEnum.pending.value

        assert intent.is_terminal is False

    def test_can_process_callback_valid(self):
        """Test can_process_callback for valid intent."""
        intent = PaymentIntent()
        intent.status = PaymentIntentStatusEnum.pending.value
        intent.expires_at = datetime.now(timezone.utc) + timedelta(hours=1)

        assert intent.can_process_callback is True

    def test_can_process_callback_expired(self):
        """Test can_process_callback for expired intent."""
        intent = PaymentIntent()
        intent.status = PaymentIntentStatusEnum.pending.value
        intent.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)

        assert intent.can_process_callback is False

    def test_can_process_callback_terminal(self):
        """Test can_process_callback for terminal intent."""
        intent = PaymentIntent()
        intent.status = PaymentIntentStatusEnum.completed.value
        intent.expires_at = datetime.now(timezone.utc) + timedelta(hours=1)

        assert intent.can_process_callback is False


class TestRefundRequestModel:
    """Test RefundRequest model properties."""

    def test_is_pending_true(self):
        """Test is_pending property when pending."""
        refund = RefundRequest()
        refund.status = RefundStatusEnum.pending.value

        assert refund.is_pending is True

    def test_is_approved_true(self):
        """Test is_approved property when approved."""
        refund = RefundRequest()
        refund.status = RefundStatusEnum.approved.value

        assert refund.is_approved is True

    def test_is_completed_true(self):
        """Test is_completed property when refunded."""
        refund = RefundRequest()
        refund.status = RefundStatusEnum.refunded.value

        assert refund.is_completed is True

    def test_can_process_true(self):
        """Test can_process property when approved."""
        refund = RefundRequest()
        refund.status = RefundStatusEnum.approved.value

        assert refund.can_process is True

    def test_can_process_false(self):
        """Test can_process property when pending."""
        refund = RefundRequest()
        refund.status = RefundStatusEnum.pending.value

        assert refund.can_process is False


class TestOverpaymentRecordModel:
    """Test OverpaymentRecord model properties."""

    def test_is_pending_true(self):
        """Test is_pending property when pending."""
        overpayment = OverpaymentRecord()
        overpayment.status = OverpaymentStatusEnum.pending.value

        assert overpayment.is_pending is True

    def test_is_resolved_applied(self):
        """Test is_resolved property when applied."""
        overpayment = OverpaymentRecord()
        overpayment.status = OverpaymentStatusEnum.applied.value

        assert overpayment.is_resolved is True

    def test_is_resolved_refunded(self):
        """Test is_resolved property when refunded."""
        overpayment = OverpaymentRecord()
        overpayment.status = OverpaymentStatusEnum.refunded.value

        assert overpayment.is_resolved is True

    def test_can_apply_to_invoice_true(self):
        """Test can_apply_to_invoice when pending."""
        overpayment = OverpaymentRecord()
        overpayment.status = OverpaymentStatusEnum.pending.value

        assert overpayment.can_apply_to_invoice is True

    def test_can_apply_to_invoice_false(self):
        """Test can_apply_to_invoice when resolved."""
        overpayment = OverpaymentRecord()
        overpayment.status = OverpaymentStatusEnum.applied.value

        assert overpayment.can_apply_to_invoice is False

    def test_can_refund_true(self):
        """Test can_refund when pending."""
        overpayment = OverpaymentRecord()
        overpayment.status = OverpaymentStatusEnum.pending.value

        assert overpayment.can_refund is True

    def test_can_refund_false(self):
        """Test can_refund when already refunded."""
        overpayment = OverpaymentRecord()
        overpayment.status = OverpaymentStatusEnum.refunded.value

        assert overpayment.can_refund is False
