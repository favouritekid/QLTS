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
)
from app.services.fee_calculation_service import FeeCalculationService
from app.services.invoice_service import InvoiceService
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
            unit_id=pf["unit_id"],
        )
        await db.commit()
        assert refund.status == "refunded"
        assert refund.refunded_at is not None

        # Verify balances decreased
        await db.refresh(pf["fee"])
        assert pf["fee"].paid_amount == Decimal("700000")  # 1M - 300K

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
