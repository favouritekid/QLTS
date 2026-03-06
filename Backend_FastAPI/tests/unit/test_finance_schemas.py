"""
Unit tests for Finance Module Schemas (Phase 0+1).

Tests cover:
- Validation rules (amount limits, required fields)
- XSS sanitization
- Pydantic model behavior

Coverage Target: Schema validation logic
"""

import pytest
from decimal import Decimal
from datetime import date, datetime

from pydantic import ValidationError

from app.schemas.finance import (
    # Fee schemas
    FeeCreate,
    FeeCalculateRequest,
    FeeWaiveRequest,
    # Invoice schemas
    InvoiceCreate,
    # Payment schemas
    PaymentCreate,
    PaymentVerifyRequest,
    PaymentIntentCreate,
    # Refund schemas
    RefundRequestCreate,
    RefundApproveRequest,
    # Overpayment schemas
    OverpaymentApplyRequest,
    OverpaymentWriteOffRequest,
    # Constants
    MAX_AMOUNT,
)
from app.models.finance import FeeTypeEnum


class TestFeeCreateSchema:
    """Test FeeCreate schema validation."""

    def test_valid_fee_create(self):
        """Test valid fee creation."""
        fee = FeeCreate(
            admission_profile_id=1,
            fee_type=FeeTypeEnum.tuition,
            academic_year=2024,
            base_amount=Decimal("10000000"),
        )
        assert fee.admission_profile_id == 1
        assert fee.fee_type == FeeTypeEnum.tuition
        assert fee.base_amount == Decimal("10000000")

    def test_academic_year_valid_int(self):
        """Test valid academic year as integer."""
        fee = FeeCreate(
            admission_profile_id=1,
            fee_type=FeeTypeEnum.tuition,
            academic_year=2024,
            base_amount=Decimal("1000"),
        )
        assert fee.academic_year == 2024

    def test_academic_year_out_of_range_rejected(self):
        """Test academic year out of range raises error."""
        with pytest.raises(ValidationError) as exc_info:
            FeeCreate(
                admission_profile_id=1,
                fee_type=FeeTypeEnum.tuition,
                academic_year=2019,  # Below minimum 2020
                base_amount=Decimal("1000"),
            )
        assert "academic_year" in str(exc_info.value)

    def test_base_amount_negative_rejected(self):
        """Test negative base amount is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            FeeCreate(
                admission_profile_id=1,
                fee_type=FeeTypeEnum.tuition,
                academic_year=2024,
                base_amount=Decimal("-1000"),
            )
        assert "base_amount" in str(exc_info.value)

    def test_base_amount_exceeds_max_rejected(self):
        """Test amount exceeding MAX_AMOUNT is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            FeeCreate(
                admission_profile_id=1,
                fee_type=FeeTypeEnum.tuition,
                academic_year=2024,
                base_amount=MAX_AMOUNT + 1,
            )
        assert "base_amount" in str(exc_info.value)

    def test_notes_xss_sanitized(self):
        """Test notes field is XSS sanitized."""
        fee = FeeCreate(
            admission_profile_id=1,
            fee_type=FeeTypeEnum.tuition,
            academic_year=2024,
            base_amount=Decimal("1000"),
            notes="<script>alert('xss')</script>",
        )
        # HTML entities should be escaped
        assert "<script>" not in fee.notes
        assert "&lt;script&gt;" in fee.notes


class TestFeeWaiveRequestSchema:
    """Test FeeWaiveRequest schema validation."""

    def test_valid_waive_request(self):
        """Test valid waive request."""
        req = FeeWaiveRequest(
            waive_amount=Decimal("50000"),
            reason="Student scholarship",
        )
        assert req.waive_amount == Decimal("50000")
        assert req.reason == "Student scholarship"

    def test_waive_amount_zero_rejected(self):
        """Test zero waive amount is rejected."""
        with pytest.raises(ValidationError):
            FeeWaiveRequest(
                waive_amount=Decimal("0"),
                reason="Test",
            )

    def test_reason_required(self):
        """Test reason is required."""
        with pytest.raises(ValidationError):
            FeeWaiveRequest(
                waive_amount=Decimal("50000"),
                reason="",  # Empty reason
            )

    def test_reason_xss_sanitized(self):
        """Test reason field is XSS sanitized."""
        req = FeeWaiveRequest(
            waive_amount=Decimal("50000"),
            reason="<img src=x onerror=alert('xss')>",
        )
        assert "<img" not in req.reason
        assert "&lt;img" in req.reason


class TestPaymentCreateSchema:
    """Test PaymentCreate schema validation."""

    def test_valid_payment_create(self):
        """Test valid payment creation."""
        payment = PaymentCreate(
            invoice_id=1,
            method_id=1,
            amount=Decimal("500000"),
        )
        assert payment.invoice_id == 1
        assert payment.method_id == 1
        assert payment.amount == Decimal("500000")

    def test_amount_zero_rejected(self):
        """Test zero amount is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            PaymentCreate(
                invoice_id=1,
                method_id=1,
                amount=Decimal("0"),
            )
        assert "amount" in str(exc_info.value)

    def test_amount_negative_rejected(self):
        """Test negative amount is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            PaymentCreate(
                invoice_id=1,
                method_id=1,
                amount=Decimal("-100"),
            )
        assert "amount" in str(exc_info.value)

    def test_amount_exceeds_max_rejected(self):
        """Test amount exceeding MAX_AMOUNT is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            PaymentCreate(
                invoice_id=1,
                method_id=1,
                amount=MAX_AMOUNT + 1,
            )
        # The custom validator should catch this
        errors = exc_info.value.errors()
        assert any("amount" in str(e) for e in errors)

    def test_payer_name_xss_sanitized(self):
        """Test payer_name field is XSS sanitized."""
        payment = PaymentCreate(
            invoice_id=1,
            method_id=1,
            amount=Decimal("100000"),
            payer_name="<script>alert(1)</script>",
        )
        assert "<script>" not in payment.payer_name
        assert "&lt;script&gt;" in payment.payer_name

    def test_notes_xss_sanitized(self):
        """Test notes field is XSS sanitized."""
        payment = PaymentCreate(
            invoice_id=1,
            method_id=1,
            amount=Decimal("100000"),
            notes="Test <b>bold</b> text",
        )
        assert "<b>" not in payment.notes
        assert "&lt;b&gt;" in payment.notes


class TestPaymentVerifyRequestSchema:
    """Test PaymentVerifyRequest schema validation."""

    def test_approve_no_reason_needed(self):
        """Test approval doesn't require reason."""
        req = PaymentVerifyRequest(
            payment_id=1,
            approve=True,
        )
        assert req.approve is True
        assert req.rejection_reason is None

    def test_reject_requires_reason(self):
        """Test rejection requires reason."""
        with pytest.raises(ValidationError) as exc_info:
            PaymentVerifyRequest(
                payment_id=1,
                approve=False,
                rejection_reason=None,  # Should require reason
            )
        assert "rejection_reason" in str(exc_info.value)

    def test_reject_with_reason_valid(self):
        """Test rejection with reason is valid."""
        req = PaymentVerifyRequest(
            payment_id=1,
            approve=False,
            rejection_reason="Invalid bank reference",
        )
        assert req.approve is False
        assert req.rejection_reason == "Invalid bank reference"

    def test_rejection_reason_xss_sanitized(self):
        """Test rejection_reason is XSS sanitized."""
        req = PaymentVerifyRequest(
            payment_id=1,
            approve=False,
            rejection_reason="<script>hack</script>",
        )
        assert "<script>" not in req.rejection_reason


class TestPaymentIntentCreateSchema:
    """Test PaymentIntentCreate schema validation."""

    def test_valid_intent_create(self):
        """Test valid intent creation."""
        intent = PaymentIntentCreate(
            invoice_id=1,
            method_id=2,
            amount=Decimal("1000000"),
            idempotency_key="uuid-123-456",
        )
        assert intent.invoice_id == 1
        assert intent.idempotency_key == "uuid-123-456"

    def test_idempotency_key_required(self):
        """Test idempotency_key is required."""
        with pytest.raises(ValidationError):
            PaymentIntentCreate(
                invoice_id=1,
                method_id=2,
                amount=Decimal("1000000"),
                idempotency_key="",  # Empty key
            )

    def test_amount_validation(self):
        """Test amount validation."""
        with pytest.raises(ValidationError):
            PaymentIntentCreate(
                invoice_id=1,
                method_id=2,
                amount=Decimal("-100"),  # Negative
                idempotency_key="uuid-123",
            )


class TestRefundRequestCreateSchema:
    """Test RefundRequestCreate schema validation."""

    def test_valid_refund_request(self):
        """Test valid refund request."""
        req = RefundRequestCreate(
            payment_id=1,
            amount=Decimal("50000"),
            reason="Customer requested refund",
        )
        assert req.payment_id == 1
        assert req.amount == Decimal("50000")
        assert req.reason == "Customer requested refund"

    def test_amount_zero_rejected(self):
        """Test zero amount is rejected."""
        with pytest.raises(ValidationError):
            RefundRequestCreate(
                payment_id=1,
                amount=Decimal("0"),
                reason="Test",
            )

    def test_reason_required(self):
        """Test reason is required."""
        with pytest.raises(ValidationError):
            RefundRequestCreate(
                payment_id=1,
                amount=Decimal("50000"),
                reason="",  # Empty reason
            )

    def test_reason_xss_sanitized(self):
        """Test reason is XSS sanitized."""
        req = RefundRequestCreate(
            payment_id=1,
            amount=Decimal("50000"),
            reason="<div onclick='hack()'>Click</div>",
        )
        assert "<div" not in req.reason


class TestRefundApproveRequestSchema:
    """Test RefundApproveRequest schema validation."""

    def test_approve_no_reason(self):
        """Test approval without reason."""
        req = RefundApproveRequest(
            refund_id=1,
            approve=True,
        )
        assert req.approve is True

    def test_reject_requires_reason(self):
        """Test rejection requires reason."""
        with pytest.raises(ValidationError):
            RefundApproveRequest(
                refund_id=1,
                approve=False,
                rejection_reason=None,
            )

    def test_reject_with_reason(self):
        """Test rejection with reason."""
        req = RefundApproveRequest(
            refund_id=1,
            approve=False,
            rejection_reason="Refund period expired",
        )
        assert req.approve is False
        assert "expired" in req.rejection_reason


class TestOverpaymentApplyRequestSchema:
    """Test OverpaymentApplyRequest schema validation."""

    def test_valid_apply_request(self):
        """Test valid apply request."""
        req = OverpaymentApplyRequest(
            overpayment_id=1,
            target_invoice_id=2,
        )
        assert req.overpayment_id == 1
        assert req.target_invoice_id == 2

    def test_partial_amount_valid(self):
        """Test partial amount is valid."""
        req = OverpaymentApplyRequest(
            overpayment_id=1,
            target_invoice_id=2,
            amount=Decimal("50000"),
        )
        assert req.amount == Decimal("50000")

    def test_notes_xss_sanitized(self):
        """Test notes are XSS sanitized."""
        req = OverpaymentApplyRequest(
            overpayment_id=1,
            target_invoice_id=2,
            notes="<iframe src='evil'>",
        )
        if req.notes:
            assert "<iframe" not in req.notes


class TestOverpaymentWriteOffRequestSchema:
    """Test OverpaymentWriteOffRequest schema validation."""

    def test_valid_write_off_request(self):
        """Test valid write-off request."""
        req = OverpaymentWriteOffRequest(
            overpayment_id=1,
            reason="Amount too small to process refund",
        )
        assert req.overpayment_id == 1
        assert "small" in req.reason

    def test_reason_required(self):
        """Test reason is required."""
        with pytest.raises(ValidationError):
            OverpaymentWriteOffRequest(
                overpayment_id=1,
                reason="",  # Empty reason
            )

    def test_reason_xss_sanitized(self):
        """Test reason is XSS sanitized."""
        req = OverpaymentWriteOffRequest(
            overpayment_id=1,
            reason="<script>document.cookie</script>",
        )
        assert "<script>" not in req.reason
