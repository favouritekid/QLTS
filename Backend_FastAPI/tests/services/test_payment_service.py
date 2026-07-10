# tests/services/test_payment_service.py
"""
Tests for PaymentService and RefundService.

Covers:
- Manual payment recording and verification (maker-checker)
- C3: Self-approval prevention
- Payment rejection with reason
- Overpayment checks
- Invoice and fee balance updates on verification
- Refund lifecycle: request → approve → process
"""

import pytest
import pytest_asyncio
from datetime import datetime, timezone, date, timedelta
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.models.finance import (
    Fee, Invoice, Payment, PaymentMethod, InstallmentPlan,
    FeeTypeEnum, FeeStatusEnum, InvoiceStatusEnum, PaymentStatusEnum,
    OverpaymentRecord, OverpaymentStatusEnum, ResolutionTypeEnum,
    RefundRequest, RefundStatusEnum,
)
from app.services.fee_calculation_service import FeeCalculationService
from app.services.invoice_service import InvoiceService
from app.services.overpayment_service import OverpaymentService
from app.services.payment_service import PaymentService, RefundService
from app.security import get_password_hash
from app.utils.exceptions import (
    ResourceNotFoundError,
    BadRequest,
    BusinessRuleViolation,
)

pytestmark = pytest.mark.asyncio


# =============================================================================
# FIXTURES
# =============================================================================

@pytest_asyncio.fixture
async def payment_fixtures(db: AsyncSession, seeded_dependencies: dict, admin_user):
    """Create fixtures: fee → issued invoice → ready for payment."""
    cash_method = PaymentMethod(
        code="pay_test_cash",
        name="Cash",
        is_online=False,
        is_active=True,
    )
    db.add(cash_method)

    inactive_method = PaymentMethod(
        code="pay_test_inactive",
        name="Inactive Method",
        is_online=False,
        is_active=False,
    )
    db.add(inactive_method)
    await db.flush()

    lead = models.Lead(
        full_name="Payment Test Student",
        phone="0901330001",
        source="test",
        unit_id=seeded_dependencies["unit_id"],
        consultation_status_id=seeded_dependencies["initial_status_id"],
    )
    db.add(lead)
    await db.flush()

    profile = models.AdmissionProfile(
        lead_id=lead.id,
        status="submitted",
        academic_year=2025,
        applied_rules={},
    )
    db.add(profile)
    await db.flush()
    await db.refresh(profile)

    # Create fee
    fee_service = FeeCalculationService(db)
    fee, _ = await fee_service.calculate_fee(
        admission_profile_id=profile.id,
        fee_type=FeeTypeEnum.application,
        base_amount=Decimal("1000000"),
        academic_year=2025,
        user_id=admin_user.id,
        unit_id=seeded_dependencies["unit_id"],
    )
    await db.commit()

    # Generate and auto-issue invoice
    invoice_service = InvoiceService(db)
    invoices, _ = await invoice_service.generate_invoices_for_fee(
        fee_id=fee.id,
        due_date_base=date.today() + timedelta(days=30),
        user_id=admin_user.id,
        unit_id=seeded_dependencies["unit_id"],
        auto_issue=True,
    )
    await db.commit()

    # Create maker (officer) and checker (manager) users
    maker = models.User(
        username="pay_test_maker",
        email="pay_maker@test.com",
        password_hash=get_password_hash("Maker123!"),
        role="officer",
        status="active",
        full_name="Payment Maker",
        unit_id=seeded_dependencies["unit_id"],
    )
    db.add(maker)

    checker = models.User(
        username="pay_test_checker",
        email="pay_checker@test.com",
        password_hash=get_password_hash("Checker123!"),
        role="manager",
        status="active",
        full_name="Payment Checker",
        unit_id=seeded_dependencies["unit_id"],
    )
    db.add(checker)
    await db.flush()
    await db.refresh(maker)
    await db.refresh(checker)

    return {
        "fee": fee,
        "invoice": invoices[0],
        "cash_method": cash_method,
        "inactive_method": inactive_method,
        "maker": maker,
        "checker": checker,
        "profile": profile,
        "unit_id": seeded_dependencies["unit_id"],
    }


# =============================================================================
# PAYMENT RECORDING TESTS
# =============================================================================

class TestRecordPayment:
    """Tests for recording manual payments."""

    async def test_record_payment_success(self, db, payment_fixtures):
        """Record manual payment creates pending payment."""
        service = PaymentService(db)
        pf = payment_fixtures

        payment, _ = await service.record_manual_payment(
            invoice_id=pf["invoice"].id,
            method_id=pf["cash_method"].id,
            amount=Decimal("500000"),
            user_id=pf["maker"].id,
            unit_id=pf["unit_id"],
            reference_code="CASH-001",
            payer_name="Test Student",
        )
        await db.commit()

        assert payment.id is not None
        assert payment.status == PaymentStatusEnum.pending.value
        assert payment.amount == Decimal("500000")
        assert payment.created_by_id == pf["maker"].id
        assert payment.reference_code == "CASH-001"

    async def test_record_payment_invalid_invoice_status(self, db, payment_fixtures):
        """Cannot pay draft invoice."""
        service = PaymentService(db)
        pf = payment_fixtures

        # Force invoice back to draft
        pf["invoice"].status = InvoiceStatusEnum.draft.value
        await db.commit()

        with pytest.raises(BusinessRuleViolation) as exc_info:
            await service.record_manual_payment(
                invoice_id=pf["invoice"].id,
                method_id=pf["cash_method"].id,
                amount=Decimal("100000"),
                user_id=pf["maker"].id,
                unit_id=pf["unit_id"],
            )

        assert "status" in str(exc_info.value).lower()

    async def test_record_payment_exceeds_remaining(self, db, payment_fixtures):
        """Payment amount cannot exceed invoice remaining balance."""
        service = PaymentService(db)
        pf = payment_fixtures

        with pytest.raises(BusinessRuleViolation) as exc_info:
            await service.record_manual_payment(
                invoice_id=pf["invoice"].id,
                method_id=pf["cash_method"].id,
                amount=Decimal("2000000"),  # Exceeds 1000000
                user_id=pf["maker"].id,
                unit_id=pf["unit_id"],
            )

        assert "exceeds" in str(exc_info.value).lower()

    async def test_record_payment_inactive_method(self, db, payment_fixtures):
        """Inactive payment method is rejected."""
        service = PaymentService(db)
        pf = payment_fixtures

        with pytest.raises(BadRequest) as exc_info:
            await service.record_manual_payment(
                invoice_id=pf["invoice"].id,
                method_id=pf["inactive_method"].id,
                amount=Decimal("100000"),
                user_id=pf["maker"].id,
                unit_id=pf["unit_id"],
            )

        assert "not active" in str(exc_info.value).lower()

    @pytest.mark.parametrize("terminal_status", ["withdrawn", "rejected"])
    async def test_record_payment_blocked_when_profile_terminal(
        self, db, payment_fixtures, terminal_status
    ):
        """P0: cannot even stage a pending payment on a withdrawn/rejected
        profile — its invoice can still be `issued` because withdraw does not
        cancel the fee. (``withdrawal_pending`` arrives with PR-B; the CHECK
        constraint rejects it today, so it is covered by the pure-logic unit
        test ``test_assert_payable_target``.)"""
        service = PaymentService(db)
        pf = payment_fixtures

        pf["profile"].status = terminal_status
        await db.commit()

        with pytest.raises(BusinessRuleViolation) as exc:
            await service.record_manual_payment(
                invoice_id=pf["invoice"].id,
                method_id=pf["cash_method"].id,
                amount=Decimal("100000"),
                user_id=pf["maker"].id,
                unit_id=pf["unit_id"],
            )
        assert "hồ sơ" in str(exc.value).lower()


# =============================================================================
# PAYMENT VERIFICATION TESTS
# =============================================================================


class TestVerifyPayment:
    """Tests for payment verification (maker-checker)."""

    async def test_verify_payment_success(self, db, payment_fixtures):
        """Verification updates payment, invoice, and fee balances."""
        service = PaymentService(db)
        pf = payment_fixtures

        # Record payment
        payment, _ = await service.record_manual_payment(
            invoice_id=pf["invoice"].id,
            method_id=pf["cash_method"].id,
            amount=Decimal("1000000"),
            user_id=pf["maker"].id,
            unit_id=pf["unit_id"],
        )
        await db.commit()

        # Verify by different user
        verified, _ = await service.verify_payment(
            payment_id=payment.id,
            verifier_id=pf["checker"].id,
            unit_id=pf["unit_id"],
        )
        await db.commit()

        assert verified.status == PaymentStatusEnum.verified.value
        assert verified.verified_by_id == pf["checker"].id
        assert verified.verified_at is not None

        # Check invoice updated
        await db.refresh(pf["invoice"])
        assert pf["invoice"].paid_amount == Decimal("1000000")
        assert pf["invoice"].status == InvoiceStatusEnum.paid.value

        # Check fee updated
        await db.refresh(pf["fee"])
        assert pf["fee"].paid_amount == Decimal("1000000")
        assert pf["fee"].status == FeeStatusEnum.paid.value

    async def test_verify_payment_blocked_when_fee_cancelled(
        self, db, payment_fixtures
    ):
        """Race guard: fee/invoice cancelled AFTER a pending payment was
        recorded → verify refuses (never write money onto a cancelled target)."""
        service = PaymentService(db)
        pf = payment_fixtures

        payment, _ = await service.record_manual_payment(
            invoice_id=pf["invoice"].id,
            method_id=pf["cash_method"].id,
            amount=Decimal("500000"),
            user_id=pf["maker"].id,
            unit_id=pf["unit_id"],
        )
        await db.commit()

        # Simulate cancel landing AFTER the pending payment (race window).
        pf["fee"].status = FeeStatusEnum.cancelled.value
        pf["invoice"].status = InvoiceStatusEnum.cancelled.value
        await db.commit()

        with pytest.raises(BusinessRuleViolation) as exc:
            await service.verify_payment(
                payment_id=payment.id,
                verifier_id=pf["checker"].id,
                unit_id=pf["unit_id"],
            )
        assert "đã bị huỷ" in str(exc.value)

        await db.refresh(pf["fee"])
        assert pf["fee"].paid_amount == Decimal("0")

    async def test_verify_payment_self_blocked(self, db, payment_fixtures):
        """C3: Maker cannot verify their own payment."""
        service = PaymentService(db)
        pf = payment_fixtures

        payment, _ = await service.record_manual_payment(
            invoice_id=pf["invoice"].id,
            method_id=pf["cash_method"].id,
            amount=Decimal("500000"),
            user_id=pf["maker"].id,
            unit_id=pf["unit_id"],
        )
        await db.commit()

        with pytest.raises(BusinessRuleViolation) as exc_info:
            await service.verify_payment(
                payment_id=payment.id,
                verifier_id=pf["maker"].id,  # Same as creator
                unit_id=pf["unit_id"],
            )

        assert "maker-checker" in str(exc_info.value).lower()

    async def test_verify_payment_non_pending(self, db, payment_fixtures):
        """Cannot verify non-pending payment."""
        service = PaymentService(db)
        pf = payment_fixtures

        payment, _ = await service.record_manual_payment(
            invoice_id=pf["invoice"].id,
            method_id=pf["cash_method"].id,
            amount=Decimal("500000"),
            user_id=pf["maker"].id,
            unit_id=pf["unit_id"],
        )
        await db.commit()

        # Verify first time
        await service.verify_payment(
            payment_id=payment.id,
            verifier_id=pf["checker"].id,
            unit_id=pf["unit_id"],
        )
        await db.commit()

        # Try verify again
        with pytest.raises(BusinessRuleViolation) as exc_info:
            await service.verify_payment(
                payment_id=payment.id,
                verifier_id=pf["checker"].id,
                unit_id=pf["unit_id"],
            )

        assert "pending" in str(exc_info.value).lower()

    async def test_verify_payment_partial_updates_fee_status(self, db, payment_fixtures):
        """Partial payment sets fee to partial status."""
        service = PaymentService(db)
        pf = payment_fixtures

        payment, _ = await service.record_manual_payment(
            invoice_id=pf["invoice"].id,
            method_id=pf["cash_method"].id,
            amount=Decimal("400000"),  # Partial
            user_id=pf["maker"].id,
            unit_id=pf["unit_id"],
        )
        await db.commit()

        await service.verify_payment(
            payment_id=payment.id,
            verifier_id=pf["checker"].id,
            unit_id=pf["unit_id"],
        )
        await db.commit()

        await db.refresh(pf["invoice"])
        assert pf["invoice"].status == InvoiceStatusEnum.partial.value

    async def test_verify_payment_full_updates_fee_paid(self, db, payment_fixtures):
        """Full payment sets fee and invoice to paid."""
        service = PaymentService(db)
        pf = payment_fixtures

        payment, _ = await service.record_manual_payment(
            invoice_id=pf["invoice"].id,
            method_id=pf["cash_method"].id,
            amount=Decimal("1000000"),
            user_id=pf["maker"].id,
            unit_id=pf["unit_id"],
        )
        await db.commit()

        await service.verify_payment(
            payment_id=payment.id,
            verifier_id=pf["checker"].id,
            unit_id=pf["unit_id"],
        )
        await db.commit()

        await db.refresh(pf["fee"])
        assert pf["fee"].status == FeeStatusEnum.paid.value
        assert pf["fee"].paid_amount == Decimal("1000000")

    @pytest.mark.parametrize("terminal_status", ["withdrawn", "rejected"])
    async def test_verify_payment_blocked_when_profile_terminal(
        self, db, payment_fixtures, terminal_status
    ):
        """P0 race guard: a pending payment recorded while the profile was live,
        then the profile is withdrawn/rejected → verify refuses to write money
        (fee.paid_amount stays 0). Mirrors the cancelled-fee race guard."""
        service = PaymentService(db)
        pf = payment_fixtures

        payment, _ = await service.record_manual_payment(
            invoice_id=pf["invoice"].id,
            method_id=pf["cash_method"].id,
            amount=Decimal("500000"),
            user_id=pf["maker"].id,
            unit_id=pf["unit_id"],
        )
        await db.commit()

        pf["profile"].status = terminal_status
        await db.commit()

        with pytest.raises(BusinessRuleViolation) as exc:
            await service.verify_payment(
                payment_id=payment.id,
                verifier_id=pf["checker"].id,
                unit_id=pf["unit_id"],
            )
        assert "hồ sơ" in str(exc.value).lower()

        await db.refresh(pf["fee"])
        assert pf["fee"].paid_amount == Decimal("0")


# =============================================================================
# PAYMENT REJECTION TESTS
# =============================================================================


class TestRejectPayment:
    """Tests for payment rejection."""

    async def test_reject_payment_success(self, db, payment_fixtures):
        """Reject payment with reason succeeds."""
        service = PaymentService(db)
        pf = payment_fixtures

        payment, _ = await service.record_manual_payment(
            invoice_id=pf["invoice"].id,
            method_id=pf["cash_method"].id,
            amount=Decimal("500000"),
            user_id=pf["maker"].id,
            unit_id=pf["unit_id"],
        )
        await db.commit()

        rejected, _ = await service.reject_payment(
            payment_id=payment.id,
            reason="Invalid bank reference",
            rejector_id=pf["checker"].id,
            unit_id=pf["unit_id"],
        )
        await db.commit()

        assert rejected.status == PaymentStatusEnum.rejected.value
        assert rejected.rejection_reason == "Invalid bank reference"

        # Invoice should not be affected
        await db.refresh(pf["invoice"])
        assert pf["invoice"].paid_amount == Decimal("0")

    async def test_reject_payment_empty_reason(self, db, payment_fixtures):
        """Rejection requires a non-empty reason."""
        service = PaymentService(db)
        pf = payment_fixtures

        payment, _ = await service.record_manual_payment(
            invoice_id=pf["invoice"].id,
            method_id=pf["cash_method"].id,
            amount=Decimal("500000"),
            user_id=pf["maker"].id,
            unit_id=pf["unit_id"],
        )
        await db.commit()

        with pytest.raises(BadRequest):
            await service.reject_payment(
                payment_id=payment.id,
                reason="",
                rejector_id=pf["checker"].id,
                unit_id=pf["unit_id"],
            )


# =============================================================================
# OVERPAYMENT CHECK TESTS
# =============================================================================

class TestOverpaymentCheck:
    """Tests for overpayment detection."""

    async def test_check_overpayment_no_excess(self, db, payment_fixtures):
        """No overpayment when amount within remaining."""
        service = PaymentService(db)
        pf = payment_fixtures

        is_over, excess = await service.check_overpayment(
            invoice_id=pf["invoice"].id,
            payment_amount=Decimal("1000000"),
            unit_id=pf["unit_id"],
        )

        assert is_over is False
        assert excess == Decimal("0")

    async def test_check_overpayment_excess(self, db, payment_fixtures):
        """Overpayment detected when amount exceeds remaining."""
        service = PaymentService(db)
        pf = payment_fixtures

        is_over, excess = await service.check_overpayment(
            invoice_id=pf["invoice"].id,
            payment_amount=Decimal("1500000"),
            unit_id=pf["unit_id"],
        )

        assert is_over is True
        assert excess == Decimal("500000")


class TestOverpaymentService:
    """Tests for overpayment list and resolution workflows."""

    async def _create_pending_overpayment(self, db, pf):
        """Helper: create a pending overpayment record with valid relations."""
        payment_service = PaymentService(db)
        payment, _ = await payment_service.record_manual_payment(
            invoice_id=pf["invoice"].id,
            method_id=pf["cash_method"].id,
            amount=Decimal("100000"),
            user_id=pf["maker"].id,
            unit_id=pf["unit_id"],
        )
        await db.commit()

        payment, _ = await payment_service.verify_payment(
            payment_id=payment.id,
            verifier_id=pf["checker"].id,
            unit_id=pf["unit_id"],
        )
        await db.commit()

        overpayment = OverpaymentRecord(
            payment_id=payment.id,
            invoice_id=pf["invoice"].id,
            admission_profile_id=pf["profile"].id,
            overpayment_amount=Decimal("50000"),
            status=OverpaymentStatusEnum.pending.value,
        )
        db.add(overpayment)
        await db.commit()
        await db.refresh(overpayment)
        return overpayment

    async def test_list_overpayments_filters_and_write_off(
        self, db, payment_fixtures
    ):
        """List/count overpayments and write-off pending liability."""
        pf = payment_fixtures
        overpayment = await self._create_pending_overpayment(db, pf)
        service = OverpaymentService(db)

        items, total = await service.list_overpayments(
            unit_id=pf["unit_id"],
            statuses=["pending"],
            profile_id=pf["profile"].id,
        )
        assert total == 1
        assert [item.id for item in items] == [overpayment.id]

        resolved, _ = await service.write_off(
            overpayment_id=overpayment.id,
            reason="Small balance write-off",
            user_id=pf["checker"].id,
            unit_id=pf["unit_id"],
        )
        await db.commit()

        assert resolved.status == OverpaymentStatusEnum.cancelled.value
        assert resolved.resolution_type == ResolutionTypeEnum.write_off.value
        assert resolved.resolved_by_id == pf["checker"].id
        assert resolved.resolved_at is not None

    async def test_apply_overpayment_to_target_invoice(self, db, payment_fixtures):
        """Apply moves the full overpayment onto another invoice of the same profile."""
        pf = payment_fixtures
        overpayment = await self._create_pending_overpayment(db, pf)

        # Target invoice on the SAME fee/profile, with enough remaining balance.
        target_invoice = Invoice(
            fee_id=pf["fee"].id,
            invoice_number="INV-TEST-APPLY-0001",
            installment_no=2,
            amount=Decimal("500000"),
            paid_amount=Decimal("0"),
            penalty_amount=Decimal("0"),
            status=InvoiceStatusEnum.issued.value,
            due_date=date.today() + timedelta(days=30),
        )
        db.add(target_invoice)
        await db.flush()
        await db.refresh(target_invoice)

        await db.refresh(pf["fee"])
        fee_paid_before = pf["fee"].paid_amount

        service = OverpaymentService(db)
        resolved, callback = await service.apply_to_invoice(
            overpayment_id=overpayment.id,
            target_invoice_id=target_invoice.id,
            user_id=pf["checker"].id,
            unit_id=pf["unit_id"],
        )
        await db.commit()
        assert callback is None

        assert resolved.status == OverpaymentStatusEnum.applied.value
        assert resolved.resolution_type == ResolutionTypeEnum.apply_to_next.value
        assert resolved.applied_to_invoice_id == target_invoice.id
        assert resolved.applied_amount == Decimal("50000")
        assert resolved.resolved_by_id == pf["checker"].id

        await db.refresh(target_invoice)
        await db.refresh(pf["fee"])
        assert target_invoice.paid_amount == Decimal("50000")
        assert pf["fee"].paid_amount == fee_paid_before + Decimal("50000")

    async def test_apply_overpayment_rejects_other_profile_invoice(
        self, db, payment_fixtures
    ):
        """Overpayment cannot be applied to an invoice on a different profile."""
        pf = payment_fixtures
        overpayment = await self._create_pending_overpayment(db, pf)

        other_lead = models.Lead(
            full_name="Other Student",
            phone="0901330099",
            source="test",
            unit_id=pf["unit_id"],
        )
        db.add(other_lead)
        await db.flush()
        other_profile = models.AdmissionProfile(
            lead_id=other_lead.id,
            status="submitted",
            academic_year=2025,
            applied_rules={},
        )
        db.add(other_profile)
        await db.flush()

        fee_service = FeeCalculationService(db)
        other_fee, _ = await fee_service.calculate_fee(
            admission_profile_id=other_profile.id,
            fee_type=FeeTypeEnum.application,
            base_amount=Decimal("1000000"),
            academic_year=2025,
            user_id=pf["checker"].id,
            unit_id=pf["unit_id"],
        )
        await db.flush()
        other_invoice = Invoice(
            fee_id=other_fee.id,
            invoice_number="INV-TEST-OTHER-0001",
            installment_no=1,
            amount=Decimal("500000"),
            status=InvoiceStatusEnum.issued.value,
            due_date=date.today() + timedelta(days=30),
        )
        db.add(other_invoice)
        await db.flush()

        service = OverpaymentService(db)
        with pytest.raises(BusinessRuleViolation):
            await service.apply_to_invoice(
                overpayment_id=overpayment.id,
                target_invoice_id=other_invoice.id,
                user_id=pf["checker"].id,
                unit_id=pf["unit_id"],
            )

    async def test_refund_overpayment_keeps_pending_until_processed(
        self, db, payment_fixtures
    ):
        """F4: refund resolution links a RefundRequest but keeps overpayment pending."""
        pf = payment_fixtures
        overpayment = await self._create_pending_overpayment(db, pf)

        service = OverpaymentService(db)
        resolved, callback = await service.refund_overpayment(
            overpayment_id=overpayment.id,
            notes="Student requested refund",
            user_id=pf["maker"].id,
            unit_id=pf["unit_id"],
        )
        await db.commit()
        assert callback is None

        # Liability stays pending; only linked to the (still-open) refund request.
        assert resolved.status == OverpaymentStatusEnum.pending.value
        assert resolved.refund_request_id is not None

        refund = await db.get(RefundRequest, resolved.refund_request_id)
        assert refund is not None
        assert refund.payment_id == overpayment.payment_id
        assert refund.amount == Decimal("50000")
        assert refund.status == RefundStatusEnum.pending.value

    async def test_refund_overpayment_blocks_second_resolution(
        self, db, payment_fixtures
    ):
        """F4: an open linked refund blocks any other resolution of the same record."""
        pf = payment_fixtures
        overpayment = await self._create_pending_overpayment(db, pf)
        service = OverpaymentService(db)

        await service.refund_overpayment(
            overpayment_id=overpayment.id,
            notes="Refund first",
            user_id=pf["maker"].id,
            unit_id=pf["unit_id"],
        )
        await db.commit()

        with pytest.raises(BusinessRuleViolation) as exc:
            await service.write_off(
                overpayment_id=overpayment.id,
                reason="cannot write off while refund open",
                user_id=pf["checker"].id,
                unit_id=pf["unit_id"],
            )
        assert "open refund" in str(exc.value).lower()

    async def test_process_refund_closes_linked_overpayment(
        self, db, payment_fixtures
    ):
        """F4: processing the refund finally marks the linked overpayment refunded."""
        pf = payment_fixtures
        overpayment = await self._create_pending_overpayment(db, pf)
        op_service = OverpaymentService(db)
        refund_service = RefundService(db)

        resolved, _ = await op_service.refund_overpayment(
            overpayment_id=overpayment.id,
            notes="Refund",
            user_id=pf["maker"].id,
            unit_id=pf["unit_id"],
        )
        await db.commit()
        refund_id = resolved.refund_request_id

        await refund_service.approve_refund(
            refund_id=refund_id,
            approver_id=pf["checker"].id,
            unit_id=pf["unit_id"],
        )
        await db.commit()

        await refund_service.process_approved_refund(
            refund_id=refund_id,
            processor_id=pf["checker"].id,
            refund_reference="BANK-OP-001",
            unit_id=pf["unit_id"],
        )
        await db.commit()

        await db.refresh(overpayment)
        assert overpayment.status == OverpaymentStatusEnum.refunded.value
        assert overpayment.resolution_type == ResolutionTypeEnum.refund.value
        assert overpayment.resolved_by_id == pf["checker"].id

    async def test_apply_overpayment_rejects_non_payable_invoice(
        self, db, payment_fixtures
    ):
        """F5: cannot apply an overpayment onto a cancelled/draft invoice."""
        pf = payment_fixtures
        overpayment = await self._create_pending_overpayment(db, pf)

        cancelled_invoice = Invoice(
            fee_id=pf["fee"].id,
            invoice_number="INV-TEST-CANCELLED-1",
            installment_no=3,
            amount=Decimal("500000"),
            status=InvoiceStatusEnum.cancelled.value,
            due_date=date.today() + timedelta(days=30),
        )
        db.add(cancelled_invoice)
        await db.flush()

        service = OverpaymentService(db)
        with pytest.raises(BusinessRuleViolation) as exc:
            await service.apply_to_invoice(
                overpayment_id=overpayment.id,
                target_invoice_id=cancelled_invoice.id,
                user_id=pf["checker"].id,
                unit_id=pf["unit_id"],
            )
        assert "status" in str(exc.value).lower()

    @pytest.mark.parametrize("terminal_status", ["withdrawn", "rejected"])
    async def test_apply_overpayment_blocked_when_profile_terminal(
        self, db, payment_fixtures, terminal_status
    ):
        """P0: overpayment credit must not be applied onto a withdrawn/rejected
        profile's invoice. The overpayment-apply path writes money but does NOT
        run through ``assert_payable_target``, so it carries its own inline
        profile guard."""
        pf = payment_fixtures
        overpayment = await self._create_pending_overpayment(db, pf)

        target_invoice = Invoice(
            fee_id=pf["fee"].id,
            invoice_number="INV-TEST-TERMGUARD-0001",
            installment_no=2,
            amount=Decimal("500000"),
            paid_amount=Decimal("0"),
            penalty_amount=Decimal("0"),
            status=InvoiceStatusEnum.issued.value,
            due_date=date.today() + timedelta(days=30),
        )
        db.add(target_invoice)
        await db.flush()
        await db.refresh(target_invoice)

        pf["profile"].status = terminal_status
        await db.commit()

        service = OverpaymentService(db)
        with pytest.raises(BusinessRuleViolation) as exc:
            await service.apply_to_invoice(
                overpayment_id=overpayment.id,
                target_invoice_id=target_invoice.id,
                user_id=pf["checker"].id,
                unit_id=pf["unit_id"],
            )
        assert "hồ sơ" in str(exc.value).lower()


# =============================================================================
# REFUND SERVICE TESTS
# =============================================================================


class TestRefundService:
    """Tests for refund request lifecycle."""

    async def _create_verified_payment(self, db, pf):
        """Helper: create and verify a payment."""
        pay_service = PaymentService(db)

        payment, _ = await pay_service.record_manual_payment(
            invoice_id=pf["invoice"].id,
            method_id=pf["cash_method"].id,
            amount=Decimal("1000000"),
            user_id=pf["maker"].id,
            unit_id=pf["unit_id"],
        )
        await db.commit()

        verified, _ = await pay_service.verify_payment(
            payment_id=payment.id,
            verifier_id=pf["checker"].id,
            unit_id=pf["unit_id"],
        )
        await db.commit()

        return verified

    async def test_request_refund_success(self, db, payment_fixtures):
        """Request refund for verified payment succeeds."""
        pf = payment_fixtures
        payment = await self._create_verified_payment(db, pf)

        refund_service = RefundService(db)
        refund, _ = await refund_service.request_refund(
            payment_id=payment.id,
            amount=Decimal("500000"),
            reason="Student withdrawal",
            user_id=pf["maker"].id,
            unit_id=pf["unit_id"],
        )
        await db.commit()

        assert refund.id is not None
        assert refund.status == "pending"
        assert refund.amount == Decimal("500000")
        assert refund.reason == "Student withdrawal"

    async def test_request_refund_reserves_open_requests(self, db, payment_fixtures):
        """F2: open (pending/approved) refunds are reserved against the payment."""
        pf = payment_fixtures
        payment = await self._create_verified_payment(db, pf)  # amount 1,000,000
        refund_service = RefundService(db)

        # First open request reserves 700,000.
        await refund_service.request_refund(
            payment_id=payment.id,
            amount=Decimal("700000"),
            reason="First refund",
            user_id=pf["maker"].id,
            unit_id=pf["unit_id"],
        )
        await db.commit()

        # Second request of 400,000 would over-commit (700k + 400k > 1,000k).
        with pytest.raises(BusinessRuleViolation) as exc:
            await refund_service.request_refund(
                payment_id=payment.id,
                amount=Decimal("400000"),
                reason="Second refund",
                user_id=pf["maker"].id,
                unit_id=pf["unit_id"],
            )
        assert "exceeds available" in str(exc.value).lower()

        # A second request within the remaining 300,000 still succeeds.
        ok, _ = await refund_service.request_refund(
            payment_id=payment.id,
            amount=Decimal("300000"),
            reason="Second refund within budget",
            user_id=pf["maker"].id,
            unit_id=pf["unit_id"],
        )
        await db.commit()
        assert ok.status == "pending"

    async def test_double_process_same_refund_rejected_balance_unchanged(
        self, db, payment_fixtures
    ):
        """Race regression (sequential proxy): processing an already-processed
        refund a second time must be rejected (status re-checked under the row
        lock) and must NOT change balances again. Also covers full-refund →
        invoice 'issued' (#7)."""
        pf = payment_fixtures
        payment = await self._create_verified_payment(db, pf)  # 1,000,000
        refund_service = RefundService(db)

        refund, _ = await refund_service.request_refund(
            payment_id=payment.id,
            amount=Decimal("1000000"),
            reason="Full refund",
            user_id=pf["maker"].id,
            unit_id=pf["unit_id"],
        )
        await db.commit()
        await refund_service.approve_refund(
            refund_id=refund.id,
            approver_id=pf["checker"].id,
            unit_id=pf["unit_id"],
        )
        await db.commit()

        await refund_service.process_approved_refund(
            refund_id=refund.id,
            processor_id=pf["checker"].id,
            refund_reference="REF-1",
            unit_id=pf["unit_id"],
        )
        await db.commit()

        await db.refresh(pf["invoice"])
        await db.refresh(pf["fee"])
        assert pf["invoice"].paid_amount == Decimal("0")
        # #7: a full refund returns the invoice to 'issued', not 'partial'.
        assert pf["invoice"].status == InvoiceStatusEnum.issued.value
        fee_paid_after_first = pf["fee"].paid_amount

        # Second process of the SAME refund → rejected (status now 'refunded').
        with pytest.raises(BusinessRuleViolation):
            await refund_service.process_approved_refund(
                refund_id=refund.id,
                processor_id=pf["checker"].id,
                refund_reference="REF-2",
                unit_id=pf["unit_id"],
            )
        await db.rollback()

        await db.refresh(pf["invoice"])
        await db.refresh(pf["fee"])
        assert pf["invoice"].paid_amount == Decimal("0")
        assert pf["fee"].paid_amount == fee_paid_after_first

    async def test_list_refunds_filters_by_payment_and_status(
        self, db, payment_fixtures
    ):
        """List refunds returns refund rows, not payment rows."""
        pf = payment_fixtures
        payment = await self._create_verified_payment(db, pf)

        refund_service = RefundService(db)
        refund, _ = await refund_service.request_refund(
            payment_id=payment.id,
            amount=Decimal("100000"),
            reason="Need refund",
            user_id=pf["maker"].id,
            unit_id=pf["unit_id"],
        )
        await db.commit()

        items, total = await refund_service.list_refunds(
            unit_id=pf["unit_id"],
            statuses=["pending"],
            payment_id=payment.id,
        )
        assert total == 1
        assert [item.id for item in items] == [refund.id]

        items, total = await refund_service.list_refunds(
            unit_id=pf["unit_id"],
            statuses=["approved"],
            payment_id=payment.id,
        )
        assert total == 0
        assert items == []

    async def test_request_refund_non_verified_payment(self, db, payment_fixtures):
        """Cannot refund non-verified payment."""
        pf = payment_fixtures
        pay_service = PaymentService(db)

        payment, _ = await pay_service.record_manual_payment(
            invoice_id=pf["invoice"].id,
            method_id=pf["cash_method"].id,
            amount=Decimal("500000"),
            user_id=pf["maker"].id,
            unit_id=pf["unit_id"],
        )
        await db.commit()
        # payment still pending, not verified

        refund_service = RefundService(db)
        with pytest.raises(BusinessRuleViolation) as exc_info:
            await refund_service.request_refund(
                payment_id=payment.id,
                amount=Decimal("100000"),
                reason="Try refund",
                user_id=pf["maker"].id,
                unit_id=pf["unit_id"],
            )

        assert "verified" in str(exc_info.value).lower()

    async def test_request_refund_exceeds_available(self, db, payment_fixtures):
        """Refund amount cannot exceed payment amount."""
        pf = payment_fixtures
        payment = await self._create_verified_payment(db, pf)

        refund_service = RefundService(db)
        with pytest.raises(BusinessRuleViolation) as exc_info:
            await refund_service.request_refund(
                payment_id=payment.id,
                amount=Decimal("2000000"),  # Exceeds 1000000
                reason="Too much refund",
                user_id=pf["maker"].id,
                unit_id=pf["unit_id"],
            )

        assert "exceeds" in str(exc_info.value).lower()

    async def test_approve_and_process_refund(self, db, payment_fixtures):
        """Full refund lifecycle: request → approve → process."""
        pf = payment_fixtures
        payment = await self._create_verified_payment(db, pf)

        refund_service = RefundService(db)

        # Request
        refund, _ = await refund_service.request_refund(
            payment_id=payment.id,
            amount=Decimal("300000"),
            reason="Partial refund",
            user_id=pf["maker"].id,
            unit_id=pf["unit_id"],
        )
        await db.commit()
        assert refund.status == "pending"

        # Approve
        refund, _ = await refund_service.approve_refund(
            refund_id=refund.id,
            approver_id=pf["checker"].id,
            unit_id=pf["unit_id"],
        )
        await db.commit()
        assert refund.status == "approved"

        # Process
        refund, _ = await refund_service.process_approved_refund(
            refund_id=refund.id,
            processor_id=pf["checker"].id,
            refund_reference="BANK-REF-001",
            unit_id=pf["unit_id"],
        )
        await db.commit()
        assert refund.status == "refunded"
        assert refund.refunded_at is not None
        assert refund.refund_reference == "BANK-REF-001"

        # Verify balances decreased
        await db.refresh(pf["fee"])
        assert pf["fee"].paid_amount == Decimal("700000")  # 1M - 300K

    async def test_process_refund_blocked_when_payment_reversed(
        self, db, payment_fixtures
    ):
        # BV-3.5 P1: payment đã bị ĐẢO (void lô import → status='refunded') KHÔNG được
        # process refund (chống double-subtract sau void). Guard re-check sau khóa fee.
        pf = payment_fixtures
        payment = await self._create_verified_payment(db, pf)
        refund_service = RefundService(db)
        refund, _ = await refund_service.request_refund(
            payment_id=payment.id, amount=Decimal("300000"), reason="x",
            user_id=pf["maker"].id, unit_id=pf["unit_id"],
        )
        await db.commit()
        refund, _ = await refund_service.approve_refund(
            refund_id=refund.id, approver_id=pf["checker"].id, unit_id=pf["unit_id"],
        )
        await db.commit()
        # mô phỏng void: payment → 'refunded' SAU khi refund đã approved
        payment.status = "refunded"
        await db.commit()
        with pytest.raises(BusinessRuleViolation):
            await refund_service.process_approved_refund(
                refund_id=refund.id, processor_id=pf["checker"].id,
                refund_reference="X", unit_id=pf["unit_id"],
            )

    async def test_reject_refund(self, db, payment_fixtures):
        """Reject refund request with reason."""
        pf = payment_fixtures
        payment = await self._create_verified_payment(db, pf)

        refund_service = RefundService(db)
        refund, _ = await refund_service.request_refund(
            payment_id=payment.id,
            amount=Decimal("100000"),
            reason="Need refund",
            user_id=pf["maker"].id,
            unit_id=pf["unit_id"],
        )
        await db.commit()

        rejected, _ = await refund_service.reject_refund(
            refund_id=refund.id,
            reason="Policy does not allow",
            rejector_id=pf["checker"].id,
            unit_id=pf["unit_id"],
        )
        await db.commit()

        assert rejected.status == "rejected"
        assert rejected.rejection_reason == "Policy does not allow"
        assert rejected.rejected_by_id == pf["checker"].id
        assert rejected.rejected_at is not None

    async def test_approve_refund_blocks_self_approval(self, db, payment_fixtures):
        """Refund approval enforces maker-checker."""
        pf = payment_fixtures
        payment = await self._create_verified_payment(db, pf)

        refund_service = RefundService(db)
        refund, _ = await refund_service.request_refund(
            payment_id=payment.id,
            amount=Decimal("100000"),
            reason="Need refund",
            user_id=pf["maker"].id,
            unit_id=pf["unit_id"],
        )
        await db.commit()

        with pytest.raises(BusinessRuleViolation) as exc_info:
            await refund_service.approve_refund(
                refund_id=refund.id,
                approver_id=pf["maker"].id,
                unit_id=pf["unit_id"],
            )

        assert "maker-checker" in str(exc_info.value).lower()


# =============================================================================
# PAYMENT_VERIFIED NOTIFICATION BRIDGE TESTS (Task 0.1)
# =============================================================================

class TestPaymentVerifiedNotificationBridge:
    """
    Tests for Task 0.1: verify_payment() dispatches PAYMENT_VERIFIED
    notification with correct payload and transaction contract.
    """

    async def test_verify_dispatches_payment_verified_event(
        self, db, payment_fixtures
    ):
        """
        post_commit callback must dispatch PAYMENT_VERIFIED via safe_dispatch,
        and the notification must be created for the verifier (user_id in payload).
        """
        from unittest.mock import AsyncMock, patch
        from app.core.events import SystemEvents

        service = PaymentService(db)
        pf = payment_fixtures

        # Record payment first
        payment, _ = await service.record_manual_payment(
            invoice_id=pf["invoice"].id,
            method_id=pf["cash_method"].id,
            amount=Decimal("500000"),
            user_id=pf["maker"].id,
            unit_id=pf["unit_id"],
        )
        await db.commit()

        # Verify payment — returns (payment, post_commit)
        verified, post_commit = await service.verify_payment(
            payment_id=payment.id,
            verifier_id=pf["checker"].id,
            unit_id=pf["unit_id"],
        )
        await db.commit()

        # Assert post_commit callback exists
        assert post_commit is not None

        # Patch safe_dispatch to capture the call
        with patch(
            "app.services.notification_dispatcher.safe_dispatch",
            new_callable=AsyncMock,
            return_value=[],
        ) as mock_safe_dispatch:
            await post_commit()

            # Verify safe_dispatch was called exactly once
            mock_safe_dispatch.assert_awaited_once()
            call_kwargs = mock_safe_dispatch.call_args
            assert call_kwargs[1]["event"] == SystemEvents.PAYMENT_VERIFIED

            # Verify payload contains all required fields
            payload = call_kwargs[1]["payload"]
            assert payload["payment_id"] == payment.id
            assert payload["invoice_id"] == pf["invoice"].id
            assert payload["fee_id"] == pf["fee"].id
            assert Decimal(payload["amount"]) == Decimal("500000")
            assert payload["verified_by_id"] == pf["checker"].id
            assert payload["verified_at"] is not None
            assert payload["admission_profile_id"] == pf["profile"].id
            assert payload["unit_id"] == pf["unit_id"]

            # user_id = officer_id (preferred) or verifier_id (fallback)
            # In this fixture, lead has no assigned_officer_id → fallback to verifier
            assert payload["user_id"] == pf["checker"].id

    async def test_verify_notifies_officer_when_assigned(self, db, payment_fixtures):
        """
        When lead has assigned_officer_id, notification should target the officer,
        not the verifier.
        """
        from unittest.mock import AsyncMock, patch
        from app.core.events import SystemEvents

        service = PaymentService(db)
        pf = payment_fixtures

        # Assign an officer to the lead
        from sqlalchemy import select
        lead_result = await db.execute(
            select(models.Lead).where(models.Lead.id == pf["profile"].lead_id)
        )
        lead = lead_result.scalar()
        lead.assigned_officer_id = pf["maker"].id  # maker is the officer
        await db.flush()

        payment, _ = await service.record_manual_payment(
            invoice_id=pf["invoice"].id,
            method_id=pf["cash_method"].id,
            amount=Decimal("500000"),
            user_id=pf["maker"].id,
            unit_id=pf["unit_id"],
        )
        await db.commit()

        verified, post_commit = await service.verify_payment(
            payment_id=payment.id,
            verifier_id=pf["checker"].id,
            unit_id=pf["unit_id"],
        )
        await db.commit()

        with patch(
            "app.services.notification_dispatcher.safe_dispatch",
            new_callable=AsyncMock,
            return_value=[],
        ) as mock_safe_dispatch:
            await post_commit()

            payload = mock_safe_dispatch.call_args[1]["payload"]
            # Should notify the officer (maker), not the verifier (checker)
            assert payload["user_id"] == pf["maker"].id, (
                f"Expected officer {pf['maker'].id}, got {payload['user_id']}"
            )

    async def test_verify_payload_has_lead_id(self, db, payment_fixtures):
        """
        Payload must include lead_id resolved from admission profile.
        """
        from unittest.mock import AsyncMock, patch
        from app.core.events import SystemEvents

        service = PaymentService(db)
        pf = payment_fixtures

        payment, _ = await service.record_manual_payment(
            invoice_id=pf["invoice"].id,
            method_id=pf["cash_method"].id,
            amount=Decimal("500000"),
            user_id=pf["maker"].id,
            unit_id=pf["unit_id"],
        )
        await db.commit()

        verified, post_commit = await service.verify_payment(
            payment_id=payment.id,
            verifier_id=pf["checker"].id,
            unit_id=pf["unit_id"],
        )
        await db.commit()

        with patch(
            "app.services.notification_dispatcher.safe_dispatch",
            new_callable=AsyncMock,
            return_value=[],
        ) as mock_safe_dispatch:
            await post_commit()

            payload = mock_safe_dispatch.call_args[1]["payload"]
            # lead_id must be resolved from fee -> profile -> lead
            assert payload["lead_id"] is not None
            assert isinstance(payload["lead_id"], int)

    async def test_payment_received_not_used_for_external_zalo(self):
        """
        PAYMENT_RECEIVED must NOT be configured for external Zalo.
        Only PAYMENT_VERIFIED should be used for external ZNS.
        """
        from app.core.events import SystemEvents
        from app.core.event_catalog import get_event

        # PR3: Validate against catalog (runtime source of truth), not deprecated registry
        pr_defn = get_event(SystemEvents.PAYMENT_RECEIVED)
        assert pr_defn is not None, "PAYMENT_RECEIVED must exist in catalog"
        assert pr_defn.notification_class == "user"

        pv_defn = get_event(SystemEvents.PAYMENT_VERIFIED)
        assert pv_defn is not None, "PAYMENT_VERIFIED must exist in catalog"
        assert pv_defn.notification_class == "user"

        # Both should exist as separate events
        assert (
            SystemEvents.PAYMENT_RECEIVED.value != SystemEvents.PAYMENT_VERIFIED.value
        )

    async def test_payment_verified_event_metadata_exists(self):
        """
        PAYMENT_VERIFIED must have a catalog entry with correct payload
        variables. Wave 2 migration: source switched from
        EVENT_METADATA_REGISTRY to EVENT_CATALOG.
        """
        from app.core.events import SystemEvents
        from app.core.event_catalog import EVENT_CATALOG

        metadata = EVENT_CATALOG.get(SystemEvents.PAYMENT_VERIFIED)
        assert metadata is not None
        assert metadata.category == "finance"

        var_names = [v.name for v in metadata.variables]
        assert "payment_id" in var_names
        assert "invoice_id" in var_names
        assert "fee_id" in var_names
        assert "amount" in var_names
        assert "verified_by_id" in var_names
        assert "verified_at" in var_names
        assert "admission_profile_id" in var_names
        assert "lead_id" in var_names
        assert "unit_id" in var_names

    async def test_payment_verified_in_finance_event_group(self):
        """
        PAYMENT_VERIFIED must be mapped to FINANCE event group.
        """
        from app.core.events import SystemEvents
        from app.core.event_groups import (
            EVENT_GROUP_MAPPING,
            NotificationEventGroup,
        )

        assert (
            EVENT_GROUP_MAPPING[SystemEvents.PAYMENT_VERIFIED]
            == NotificationEventGroup.FINANCE
        )
