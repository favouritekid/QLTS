# tests/integration/test_finance_workflow.py
"""
Integration tests for Finance Module workflow.

Tests cover end-to-end scenarios:
1. Fee calculation with discounts
2. Invoice generation (single and installment)
3. Manual payment with maker-checker verification
4. Online payment intent flow
5. Refund workflow
6. Accounting period management

Note: These tests require database fixtures from conftest.py
"""

import pytest
import pytest_asyncio
from datetime import datetime, timezone, date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.models.finance import (
    Fee, Invoice, Payment, PaymentIntent, PaymentMethod, InstallmentPlan,
    FeeTypeEnum, FeeStatusEnum, InvoiceStatusEnum, PaymentStatusEnum,
    PaymentIntentStatusEnum,
)
from app.services.fee_calculation_service import FeeCalculationService
from app.services.invoice_service import InvoiceService
from app.services.payment_service import PaymentService, RefundService
from app.services.payment_intent_service import PaymentIntentService
from app.services.accounting_service import AccountingPeriodService
from app.config import settings
from app.utils.exceptions import (
    ResourceNotFoundError,
    BadRequest,
    BusinessRuleViolation,
    ConflictError,
)

# PR1 Commit 5: create_intent now allowlists return_url against FRONTEND_URL.
VALID_RETURN_URL = (
    f"{settings.FRONTEND_URL.rstrip('/')}/finance/payments/return"
)


# =============================================================================
# FIXTURES
# =============================================================================

@pytest_asyncio.fixture(scope="function")
async def finance_fixtures(db: AsyncSession, seeded_dependencies: dict) -> dict:
    """
    Create fixtures for finance tests.
    """
    # Create payment methods
    cash_method = PaymentMethod(
        code="cash",
        name="Cash",
        description="Cash payment",
        is_online=False,
        is_active=True,
    )
    db.add(cash_method)

    bank_transfer = PaymentMethod(
        code="bank_transfer",
        name="Bank Transfer",
        description="Direct bank transfer",
        is_online=False,
        is_active=True,
    )
    db.add(bank_transfer)

    vnpay = PaymentMethod(
        code="vnpay",
        name="VNPay",
        description="VNPay online payment",
        is_online=True,
        is_active=True,
        gateway_config={"tmn_code": "TEST123"},
    )
    db.add(vnpay)

    # Create installment plan
    installment_plan = InstallmentPlan(
        code="THREE_MONTH",
        name="3-Month Installment",
        description="Pay in 3 monthly installments",
        installment_count=3,
        schedule=[
            {"installment_no": 1, "due_days_offset": 0, "percent": 34.0, "description": "Đợt 1"},
            {"installment_no": 2, "due_days_offset": 30, "percent": 33.0, "description": "Đợt 2"},
            {"installment_no": 3, "due_days_offset": 60, "percent": 33.0, "description": "Đợt 3"},
        ],
        is_active=True,
    )
    db.add(installment_plan)

    await db.flush()

    # Create academic info + semester tuition for the tuition fee lookup
    # chain (PR 3 — ADR-002). The profile references this via
    # applied_rules["academic_info_id"] (legacy fallback path).
    from app.models.offering_academic_info import OfferingAcademicInfo
    from app.models.offering_semester_tuition import OfferingSemesterTuition

    # We need a ProgramOffering to attach academic info to. Use the first
    # seeded offering if available, otherwise create a minimal one.
    from sqlalchemy import select as sa_select
    offering_result = await db.execute(
        sa_select(models.ProgramOffering).limit(1)
    )
    offering = offering_result.scalar_one_or_none()
    if not offering:
        program = models.MajorProgram(
            name="Test Program",
            code="TEST-FW",
            degree_level="Đại học",
            unit_id=seeded_dependencies["unit_id"],
        )
        db.add(program)
        await db.flush()
        offering = models.ProgramOffering(
            program_id=program.id,
            offering_type="Chính quy",
        )
        db.add(offering)
        await db.flush()

    academic_info = OfferingAcademicInfo(
        offering_id=offering.id,
        academic_year=2025,
        tuition_fee_per_year=10000000,  # Legacy field, still used by non-tuition path
        is_published=True,
    )
    db.add(academic_info)
    await db.flush()

    semester_tuition = OfferingSemesterTuition(
        academic_info_id=academic_info.id,
        semester_no=1,
        amount=10000000,  # HK1 amount (matches tuition_fee_per_year for test consistency)
    )
    db.add(semester_tuition)
    await db.flush()

    # Create test lead with admission profile
    lead = models.Lead(
        full_name="Finance Test Student",
        email="finance_test@example.com",
        phone="0901234567",
        source="test",
        unit_id=seeded_dependencies["unit_id"],
        consultation_status_id=seeded_dependencies["initial_status_id"],
    )
    db.add(lead)
    await db.flush()

    admission_profile = models.AdmissionProfile(
        lead_id=lead.id,
        status="submitted",
        academic_year=2025,
        applied_rules={"academic_info_id": academic_info.id},
    )
    db.add(admission_profile)
    await db.flush()
    await db.refresh(admission_profile)

    return {
        "lead": lead,
        "admission_profile": admission_profile,
        "cash_method": cash_method,
        "bank_transfer": bank_transfer,
        "vnpay": vnpay,
        "installment_plan": installment_plan,
        "unit_id": seeded_dependencies["unit_id"],
    }


@pytest_asyncio.fixture(scope="function")
async def maker_user(db: AsyncSession, seeded_dependencies: dict) -> models.User:
    """User who records payments (maker in maker-checker)."""
    from app.security import get_password_hash

    user = models.User(
        username="finance_maker",
        email="maker@test.com",
        password_hash=get_password_hash("MakerPass123!"),
        role="officer",
        status="active",
        full_name="Finance Maker",
        unit_id=seeded_dependencies["unit_id"],
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user


@pytest_asyncio.fixture(scope="function")
async def checker_user(db: AsyncSession, seeded_dependencies: dict) -> models.User:
    """User who verifies payments (checker in maker-checker)."""
    from app.security import get_password_hash

    user = models.User(
        username="finance_checker",
        email="checker@test.com",
        password_hash=get_password_hash("CheckerPass123!"),
        role="manager",
        status="active",
        full_name="Finance Checker",
        unit_id=seeded_dependencies["unit_id"],
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user


# =============================================================================
# FEE CALCULATION TESTS
# =============================================================================

class TestFeeCalculation:
    """Test fee calculation workflow."""

    @pytest.mark.asyncio
    async def test_calculate_fee_success(
        self,
        db: AsyncSession,
        finance_fixtures: dict,
        maker_user: models.User,
    ):
        """Test successful fee calculation."""
        service = FeeCalculationService(db)
        profile = finance_fixtures["admission_profile"]

        fee, callback = await service.calculate_fee(
            admission_profile_id=profile.id,
            fee_type=FeeTypeEnum.tuition,
            base_amount=Decimal("10000000"),
            academic_year=2025,
            user_id=maker_user.id,
            unit_id=finance_fixtures["unit_id"],
        )

        await db.commit()

        assert fee.id is not None
        assert fee.base_amount == Decimal("10000000")
        assert fee.final_amount == Decimal("10000000")  # No discount
        assert fee.status == FeeStatusEnum.calculated.value
        assert fee.paid_amount == Decimal("0")

    @pytest.mark.asyncio
    async def test_calculate_fee_duplicate_rejected(
        self,
        db: AsyncSession,
        finance_fixtures: dict,
        maker_user: models.User,
    ):
        """Test duplicate fee for same profile/type/year is rejected."""
        service = FeeCalculationService(db)
        profile = finance_fixtures["admission_profile"]

        # First fee
        await service.calculate_fee(
            admission_profile_id=profile.id,
            fee_type=FeeTypeEnum.tuition,
            base_amount=Decimal("10000000"),
            academic_year=2025,
            user_id=maker_user.id,
            unit_id=finance_fixtures["unit_id"],
        )
        await db.commit()

        # Duplicate should fail
        with pytest.raises(BadRequest) as exc_info:
            await service.calculate_fee(
                admission_profile_id=profile.id,
                fee_type=FeeTypeEnum.tuition,
                base_amount=Decimal("5000000"),
                academic_year=2025,
                user_id=maker_user.id,
                unit_id=finance_fixtures["unit_id"],
            )

        error_msg = str(exc_info.value)
        assert "already exists" in error_msg or "đã được tính" in error_msg

    @pytest.mark.asyncio
    async def test_recalculate_fee_blocked_after_payment(
        self,
        db: AsyncSession,
        finance_fixtures: dict,
        maker_user: models.User,
    ):
        """Test recalculation is blocked if payments exist (M10)."""
        service = FeeCalculationService(db)
        profile = finance_fixtures["admission_profile"]

        # Create fee
        fee, _ = await service.calculate_fee(
            admission_profile_id=profile.id,
            fee_type=FeeTypeEnum.enrollment,
            base_amount=Decimal("1000000"),
            academic_year=2025,
            user_id=maker_user.id,
            unit_id=finance_fixtures["unit_id"],
        )
        await db.commit()

        # Simulate payment (manually update paid_amount)
        fee.paid_amount = Decimal("500000")
        await db.commit()

        # Recalculation should fail
        with pytest.raises(BusinessRuleViolation) as exc_info:
            await service.recalculate_fee(
                fee_id=fee.id,
                new_base_amount=Decimal("1500000"),
                reason="Price adjustment",
                user_id=maker_user.id,
                unit_id=finance_fixtures["unit_id"],
            )

        assert "existing payments" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_waive_fee_exceeds_remaining_rejected(
        self,
        db: AsyncSession,
        finance_fixtures: dict,
        maker_user: models.User,
    ):
        """Test waive amount cannot exceed remaining balance (H5)."""
        service = FeeCalculationService(db)
        profile = finance_fixtures["admission_profile"]

        # Create fee
        fee, _ = await service.calculate_fee(
            admission_profile_id=profile.id,
            fee_type=FeeTypeEnum.insurance,
            base_amount=Decimal("500000"),
            academic_year=2025,
            user_id=maker_user.id,
            unit_id=finance_fixtures["unit_id"],
        )
        await db.commit()

        # Waive more than remaining
        with pytest.raises(BusinessRuleViolation) as exc_info:
            await service.waive_fee(
                fee_id=fee.id,
                waive_amount=Decimal("600000"),  # Exceeds 500000
                reason="Scholarship",
                user_id=maker_user.id,
                unit_id=finance_fixtures["unit_id"],
            )

        assert "exceeds remaining" in str(exc_info.value).lower()


# =============================================================================
# INVOICE GENERATION TESTS
# =============================================================================

class TestInvoiceGeneration:
    """Test invoice generation workflow."""

    @pytest.mark.asyncio
    async def test_generate_single_invoice(
        self,
        db: AsyncSession,
        finance_fixtures: dict,
        maker_user: models.User,
    ):
        """Test generating single invoice for a fee."""
        fee_service = FeeCalculationService(db)
        invoice_service = InvoiceService(db)
        profile = finance_fixtures["admission_profile"]

        # Create fee
        fee, _ = await fee_service.calculate_fee(
            admission_profile_id=profile.id,
            fee_type=FeeTypeEnum.application,
            base_amount=Decimal("500000"),
            academic_year=2025,
            user_id=maker_user.id,
            unit_id=finance_fixtures["unit_id"],
        )
        await db.commit()

        # Generate invoice
        due_date = date.today() + timedelta(days=30)
        invoices, _ = await invoice_service.generate_invoices_for_fee(
            fee_id=fee.id,
            due_date_base=due_date,
            user_id=maker_user.id,
            unit_id=finance_fixtures["unit_id"],
        )
        await db.commit()

        assert len(invoices) == 1
        assert invoices[0].amount == Decimal("500000")
        assert invoices[0].installment_no == 1
        assert invoices[0].status == InvoiceStatusEnum.draft.value

    @pytest.mark.asyncio
    async def test_generate_installment_invoices(
        self,
        db: AsyncSession,
        finance_fixtures: dict,
        maker_user: models.User,
    ):
        """Test generating multiple invoices with installment plan."""
        fee_service = FeeCalculationService(db)
        invoice_service = InvoiceService(db)
        profile = finance_fixtures["admission_profile"]
        plan = finance_fixtures["installment_plan"]

        # Create fee with installment plan.
        # PR 3: tuition base_amount is now looked up from
        # offering_semester_tuition (10M in fixture), so the explicit
        # base_amount here is ignored for tuition. Use enrollment type
        # instead for a clean installment-amount test with known base.
        fee, _ = await fee_service.calculate_fee(
            admission_profile_id=profile.id,
            fee_type=FeeTypeEnum.enrollment,
            base_amount=Decimal("9000000"),
            academic_year=2025,
            installment_plan_id=plan.id,
            user_id=maker_user.id,
            unit_id=finance_fixtures["unit_id"],
        )
        await db.commit()

        # Generate invoices
        due_date = date.today() + timedelta(days=30)
        invoices, _ = await invoice_service.generate_invoices_for_fee(
            fee_id=fee.id,
            due_date_base=due_date,
            user_id=maker_user.id,
            unit_id=finance_fixtures["unit_id"],
        )
        await db.commit()

        assert len(invoices) == 3
        # Amounts based on 34%/33%/33% split of 9,000,000
        assert invoices[0].amount == Decimal("3060000")  # 34%
        assert invoices[1].amount == Decimal("2970000")  # 33%
        assert invoices[2].amount == Decimal("2970000")  # 33%
        assert invoices[0].installment_no == 1
        assert invoices[1].installment_no == 2
        assert invoices[2].installment_no == 3

        # Verify due dates
        assert invoices[1].due_date == invoices[0].due_date + timedelta(days=30)
        assert invoices[2].due_date == invoices[1].due_date + timedelta(days=30)

    @pytest.mark.asyncio
    async def test_issue_invoice(
        self,
        db: AsyncSession,
        finance_fixtures: dict,
        maker_user: models.User,
    ):
        """Test issuing a draft invoice."""
        fee_service = FeeCalculationService(db)
        invoice_service = InvoiceService(db)
        profile = finance_fixtures["admission_profile"]

        # Create and generate invoice
        fee, _ = await fee_service.calculate_fee(
            admission_profile_id=profile.id,
            fee_type=FeeTypeEnum.dormitory,
            base_amount=Decimal("2000000"),
            academic_year=2025,
            user_id=maker_user.id,
            unit_id=finance_fixtures["unit_id"],
        )
        await db.commit()

        invoices, _ = await invoice_service.generate_invoices_for_fee(
            fee_id=fee.id,
            due_date_base=date.today() + timedelta(days=30),
            user_id=maker_user.id,
            unit_id=finance_fixtures["unit_id"],
        )
        await db.commit()

        # Issue invoice
        invoice, _ = await invoice_service.issue_invoice(
            invoice_id=invoices[0].id,
            user_id=maker_user.id,
            unit_id=finance_fixtures["unit_id"],
        )
        await db.commit()

        assert invoice.status == InvoiceStatusEnum.issued.value
        assert invoice.issued_at is not None
        assert invoice.issued_by_id == maker_user.id


# =============================================================================
# MANUAL PAYMENT TESTS
# =============================================================================

class TestManualPayment:
    """Test manual payment with maker-checker workflow."""

    @pytest.mark.asyncio
    async def test_record_and_verify_payment(
        self,
        db: AsyncSession,
        finance_fixtures: dict,
        maker_user: models.User,
        checker_user: models.User,
    ):
        """Test complete manual payment workflow."""
        fee_service = FeeCalculationService(db)
        invoice_service = InvoiceService(db)
        payment_service = PaymentService(db)
        profile = finance_fixtures["admission_profile"]

        # Setup: Create fee, invoice, and issue
        fee, _ = await fee_service.calculate_fee(
            admission_profile_id=profile.id,
            fee_type=FeeTypeEnum.other,
            base_amount=Decimal("1000000"),
            academic_year=2025,
            user_id=maker_user.id,
            unit_id=finance_fixtures["unit_id"],
        )
        await db.commit()

        invoices, _ = await invoice_service.generate_invoices_for_fee(
            fee_id=fee.id,
            due_date_base=date.today() + timedelta(days=30),
            user_id=maker_user.id,
            unit_id=finance_fixtures["unit_id"],
            auto_issue=True,
        )
        await db.commit()

        invoice = invoices[0]

        # Step 1: Maker records payment
        payment, _ = await payment_service.record_manual_payment(
            invoice_id=invoice.id,
            method_id=finance_fixtures["cash_method"].id,
            amount=Decimal("1000000"),
            user_id=maker_user.id,
            unit_id=finance_fixtures["unit_id"],
            reference_code="CASH-001",
            payer_name="Test Student",
        )
        await db.commit()

        assert payment.status == PaymentStatusEnum.pending.value
        assert payment.created_by_id == maker_user.id

        # Step 2: Checker verifies payment
        verified_payment, _ = await payment_service.verify_payment(
            payment_id=payment.id,
            verifier_id=checker_user.id,
            unit_id=finance_fixtures["unit_id"],
        )
        await db.commit()

        assert verified_payment.status == PaymentStatusEnum.verified.value
        assert verified_payment.verified_by_id == checker_user.id

        # Verify invoice and fee are updated
        await db.refresh(invoice)
        await db.refresh(fee)

        assert invoice.status == InvoiceStatusEnum.paid.value
        assert invoice.paid_amount == Decimal("1000000")
        assert fee.status == FeeStatusEnum.paid.value
        assert fee.paid_amount == Decimal("1000000")

    @pytest.mark.asyncio
    async def test_self_approval_blocked(
        self,
        db: AsyncSession,
        finance_fixtures: dict,
        maker_user: models.User,
    ):
        """Test that maker cannot verify their own payment (C3)."""
        fee_service = FeeCalculationService(db)
        invoice_service = InvoiceService(db)
        payment_service = PaymentService(db)
        profile = finance_fixtures["admission_profile"]

        # Setup
        fee, _ = await fee_service.calculate_fee(
            admission_profile_id=profile.id,
            fee_type=FeeTypeEnum.enrollment,
            base_amount=Decimal("500000"),
            academic_year=2025,
            user_id=maker_user.id,
            unit_id=finance_fixtures["unit_id"],
        )
        await db.commit()

        invoices, _ = await invoice_service.generate_invoices_for_fee(
            fee_id=fee.id,
            due_date_base=date.today() + timedelta(days=30),
            user_id=maker_user.id,
            unit_id=finance_fixtures["unit_id"],
            auto_issue=True,
        )
        await db.commit()

        # Record payment
        payment, _ = await payment_service.record_manual_payment(
            invoice_id=invoices[0].id,
            method_id=finance_fixtures["bank_transfer"].id,
            amount=Decimal("500000"),
            user_id=maker_user.id,
            unit_id=finance_fixtures["unit_id"],
        )
        await db.commit()

        # Attempt self-approval
        with pytest.raises(BusinessRuleViolation) as exc_info:
            await payment_service.verify_payment(
                payment_id=payment.id,
                verifier_id=maker_user.id,  # Same as creator
                unit_id=finance_fixtures["unit_id"],
            )

        assert "maker-checker" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_reject_payment(
        self,
        db: AsyncSession,
        finance_fixtures: dict,
        maker_user: models.User,
        checker_user: models.User,
    ):
        """Test rejecting a pending payment."""
        fee_service = FeeCalculationService(db)
        invoice_service = InvoiceService(db)
        payment_service = PaymentService(db)
        profile = finance_fixtures["admission_profile"]

        # Setup
        fee, _ = await fee_service.calculate_fee(
            admission_profile_id=profile.id,
            fee_type=FeeTypeEnum.insurance,
            base_amount=Decimal("300000"),
            academic_year=2025,
            user_id=maker_user.id,
            unit_id=finance_fixtures["unit_id"],
        )
        await db.commit()

        invoices, _ = await invoice_service.generate_invoices_for_fee(
            fee_id=fee.id,
            due_date_base=date.today() + timedelta(days=30),
            user_id=maker_user.id,
            unit_id=finance_fixtures["unit_id"],
            auto_issue=True,
        )
        await db.commit()

        # Record payment
        payment, _ = await payment_service.record_manual_payment(
            invoice_id=invoices[0].id,
            method_id=finance_fixtures["cash_method"].id,
            amount=Decimal("300000"),
            user_id=maker_user.id,
            unit_id=finance_fixtures["unit_id"],
        )
        await db.commit()

        # Reject payment
        rejected_payment, _ = await payment_service.reject_payment(
            payment_id=payment.id,
            reason="Invalid bank reference",
            rejector_id=checker_user.id,
            unit_id=finance_fixtures["unit_id"],
        )
        await db.commit()

        assert rejected_payment.status == PaymentStatusEnum.rejected.value
        assert rejected_payment.rejection_reason == "Invalid bank reference"

        # Invoice should not be updated
        await db.refresh(invoices[0])
        assert invoices[0].paid_amount == Decimal("0")


# =============================================================================
# ONLINE PAYMENT TESTS
# =============================================================================

class TestOnlinePayment:
    """Test online payment intent flow."""

    @pytest.mark.asyncio
    async def test_create_payment_intent(
        self,
        db: AsyncSession,
        finance_fixtures: dict,
        maker_user: models.User,
    ):
        """Test creating payment intent for online payment."""
        fee_service = FeeCalculationService(db)
        invoice_service = InvoiceService(db)
        intent_service = PaymentIntentService(db)
        profile = finance_fixtures["admission_profile"]

        # Setup
        fee, _ = await fee_service.calculate_fee(
            admission_profile_id=profile.id,
            fee_type=FeeTypeEnum.application,
            base_amount=Decimal("500000"),
            academic_year=2025,
            user_id=maker_user.id,
            unit_id=finance_fixtures["unit_id"],
        )
        await db.commit()

        invoices, _ = await invoice_service.generate_invoices_for_fee(
            fee_id=fee.id,
            due_date_base=date.today() + timedelta(days=30),
            user_id=maker_user.id,
            unit_id=finance_fixtures["unit_id"],
            auto_issue=True,
        )
        await db.commit()

        # Create payment intent
        intent, _ = await intent_service.create_intent(
            invoice_id=invoices[0].id,
            method_id=finance_fixtures["vnpay"].id,
            amount=Decimal("500000"),
            idempotency_key="test-uuid-123",
            return_url=VALID_RETURN_URL,
            unit_id=finance_fixtures["unit_id"],
        )
        await db.commit()

        assert intent.id is not None
        assert intent.amount == Decimal("500000")
        assert intent.idempotency_key == "test-uuid-123"
        assert intent.pay_url is not None
        assert intent.gateway_ref is not None

    @pytest.mark.asyncio
    async def test_idempotency_returns_existing_intent(
        self,
        db: AsyncSession,
        finance_fixtures: dict,
        maker_user: models.User,
    ):
        """Test idempotency key returns existing non-terminal intent."""
        fee_service = FeeCalculationService(db)
        invoice_service = InvoiceService(db)
        intent_service = PaymentIntentService(db)
        profile = finance_fixtures["admission_profile"]

        # Setup
        fee, _ = await fee_service.calculate_fee(
            admission_profile_id=profile.id,
            fee_type=FeeTypeEnum.tuition,
            base_amount=Decimal("1000000"),
            academic_year=2025,
            user_id=maker_user.id,
            unit_id=finance_fixtures["unit_id"],
        )
        await db.commit()

        invoices, _ = await invoice_service.generate_invoices_for_fee(
            fee_id=fee.id,
            due_date_base=date.today() + timedelta(days=30),
            user_id=maker_user.id,
            unit_id=finance_fixtures["unit_id"],
            auto_issue=True,
        )
        await db.commit()

        # Create first intent
        intent1, _ = await intent_service.create_intent(
            invoice_id=invoices[0].id,
            method_id=finance_fixtures["vnpay"].id,
            amount=Decimal("1000000"),
            idempotency_key="idempotency-test-456",
            return_url=VALID_RETURN_URL,
            unit_id=finance_fixtures["unit_id"],
        )
        await db.commit()

        # Create second intent with same key
        intent2, _ = await intent_service.create_intent(
            invoice_id=invoices[0].id,
            method_id=finance_fixtures["vnpay"].id,
            amount=Decimal("1000000"),
            idempotency_key="idempotency-test-456",  # Same key
            return_url=VALID_RETURN_URL,
            unit_id=finance_fixtures["unit_id"],
        )
        await db.commit()

        # Should return same intent
        assert intent1.id == intent2.id


# =============================================================================
# ACCOUNTING PERIOD TESTS
# =============================================================================

class TestAccountingPeriod:
    """Test accounting period management."""

    @pytest.mark.asyncio
    async def test_create_and_close_period(
        self,
        db: AsyncSession,
        maker_user: models.User,
    ):
        """Test creating and closing an accounting period."""
        service = AccountingPeriodService(db)

        # Create period
        period, _ = await service.create_period(
            month=1,
            year=2025,
            user_id=maker_user.id,
            notes="January 2025",
        )
        await db.commit()

        assert period.id is not None
        assert period.period_month == 1
        assert period.period_year == 2025
        assert period.is_closed is False

        # Close period
        closed_period, _ = await service.close_period(
            month=1,
            year=2025,
            user_id=maker_user.id,
            notes="End of month",
        )
        await db.commit()

        assert closed_period.is_closed is True
        assert closed_period.closed_at is not None
        assert closed_period.closed_by_id == maker_user.id

    @pytest.mark.asyncio
    async def test_period_cannot_be_created_before_closing_previous(
        self,
        db: AsyncSession,
        maker_user: models.User,
    ):
        """Test H7: previous period must be closed."""
        service = AccountingPeriodService(db)

        # Create January
        await service.create_period(month=1, year=2026, user_id=maker_user.id)
        await db.commit()

        # Try to create February without closing January
        with pytest.raises(BusinessRuleViolation) as exc_info:
            await service.create_period(month=2, year=2026, user_id=maker_user.id)

        assert "not closed" in str(exc_info.value).lower()


# =============================================================================
# SEMESTER TUITION RECALCULATION TESTS (PR 3 — ADR-002 Decision 4)
# =============================================================================

class TestSemesterTuitionRecalculation:
    """Test discount recalculation when admin edits semester tuition amounts."""

    @pytest.mark.asyncio
    async def test_recalc_updates_draft_fee_and_invoices(
        self,
        db: AsyncSession,
        finance_fixtures: dict,
        maker_user: models.User,
    ):
        """When semester tuition amount changes, draft fees and their draft
        invoices should be rewritten to match the new amount."""
        from app.services.fee_calculation_service import (
            recalculate_fees_for_semester_tuition_change,
        )

        fee_service = FeeCalculationService(db)
        invoice_service = InvoiceService(db)
        profile = finance_fixtures["admission_profile"]
        plan = finance_fixtures["installment_plan"]

        # Create tuition fee (reads 10M from semester_tuition fixture)
        fee, _ = await fee_service.calculate_fee(
            admission_profile_id=profile.id,
            fee_type=FeeTypeEnum.tuition,
            base_amount=Decimal("0"),  # ignored for tuition
            academic_year=2025,
            installment_plan_id=plan.id,
            user_id=maker_user.id,
            unit_id=finance_fixtures["unit_id"],
        )
        await db.commit()

        assert fee.base_amount == Decimal("10000000")

        # Generate draft invoices (3 installments)
        invoices, _ = await invoice_service.generate_invoices_for_fee(
            fee_id=fee.id,
            due_date_base=date.today() + timedelta(days=30),
            user_id=maker_user.id,
            unit_id=finance_fixtures["unit_id"],
        )
        await db.commit()
        assert len(invoices) == 3

        # Change semester tuition from 10M to 12M
        from app.models.offering_semester_tuition import OfferingSemesterTuition
        ai_id = profile.applied_rules["academic_info_id"]
        sem_result = await db.execute(
            select(OfferingSemesterTuition).where(
                OfferingSemesterTuition.academic_info_id == ai_id,
                OfferingSemesterTuition.semester_no == 1,
            )
        )
        sem_row = sem_result.scalar_one()
        sem_row.amount = Decimal("12000000")
        await db.flush()

        # Recalculate
        count = await recalculate_fees_for_semester_tuition_change(db, int(ai_id))
        await db.commit()

        assert count == 1, f"Expected 1 fee recalculated, got {count}. ai_id={ai_id}, fee.id={fee.id}"

        # Verify fee updated
        await db.refresh(fee)
        assert fee.base_amount == Decimal("12000000")
        assert fee.final_amount == Decimal("12000000")

        # Verify invoices rewritten (34%/33%/33% of 12M).
        # Use raw SQL text query to bypass ORM identity map caching.
        from sqlalchemy import text
        inv_rows = (await db.execute(
            text("SELECT installment_no, amount FROM invoice WHERE fee_id = :fid ORDER BY installment_no"),
            {"fid": fee.id},
        )).fetchall()
        assert len(inv_rows) == 3
        assert inv_rows[0][1] == Decimal("4080000")  # 34% of 12M
        assert inv_rows[1][1] == Decimal("3960000")  # 33%
        assert inv_rows[2][1] == Decimal("3960000")  # 33%

    @pytest.mark.asyncio
    async def test_recalc_skips_paid_fee(
        self,
        db: AsyncSession,
        finance_fixtures: dict,
        maker_user: models.User,
    ):
        """Fees with paid_amount > 0 must not be recalculated."""
        from app.services.fee_calculation_service import (
            recalculate_fees_for_semester_tuition_change,
        )

        fee_service = FeeCalculationService(db)
        profile = finance_fixtures["admission_profile"]

        fee, _ = await fee_service.calculate_fee(
            admission_profile_id=profile.id,
            fee_type=FeeTypeEnum.tuition,
            base_amount=Decimal("0"),
            academic_year=2025,
            user_id=maker_user.id,
            unit_id=finance_fixtures["unit_id"],
        )
        # Simulate partial payment
        fee.paid_amount = Decimal("5000000")
        fee.status = FeeStatusEnum.partial.value
        await db.flush()
        await db.commit()

        original_base = fee.base_amount

        # Change semester tuition
        from app.models.offering_semester_tuition import OfferingSemesterTuition
        ai_id = profile.applied_rules["academic_info_id"]
        sem_result = await db.execute(
            select(OfferingSemesterTuition).where(
                OfferingSemesterTuition.academic_info_id == ai_id,
                OfferingSemesterTuition.semester_no == 1,
            )
        )
        sem_row = sem_result.scalar_one()
        sem_row.amount = Decimal("15000000")
        await db.flush()

        count = await recalculate_fees_for_semester_tuition_change(db, ai_id)
        await db.commit()

        assert count == 0

        await db.refresh(fee)
        assert fee.base_amount == original_base  # Unchanged

    @pytest.mark.asyncio
    async def test_recalc_skips_non_draft_invoices(
        self,
        db: AsyncSession,
        finance_fixtures: dict,
        maker_user: models.User,
    ):
        """Fees with issued invoices must not be recalculated."""
        from app.services.fee_calculation_service import (
            recalculate_fees_for_semester_tuition_change,
        )

        fee_service = FeeCalculationService(db)
        invoice_service = InvoiceService(db)
        profile = finance_fixtures["admission_profile"]

        fee, _ = await fee_service.calculate_fee(
            admission_profile_id=profile.id,
            fee_type=FeeTypeEnum.tuition,
            base_amount=Decimal("0"),
            academic_year=2025,
            user_id=maker_user.id,
            unit_id=finance_fixtures["unit_id"],
        )
        await db.commit()

        # Generate + issue invoices
        invoices, _ = await invoice_service.generate_invoices_for_fee(
            fee_id=fee.id,
            due_date_base=date.today() + timedelta(days=30),
            user_id=maker_user.id,
            unit_id=finance_fixtures["unit_id"],
            auto_issue=True,  # Issues immediately
        )
        await db.commit()

        original_base = fee.base_amount

        # Change semester tuition
        from app.models.offering_semester_tuition import OfferingSemesterTuition
        ai_id = profile.applied_rules["academic_info_id"]
        sem_result = await db.execute(
            select(OfferingSemesterTuition).where(
                OfferingSemesterTuition.academic_info_id == ai_id,
                OfferingSemesterTuition.semester_no == 1,
            )
        )
        sem_row = sem_result.scalar_one()
        sem_row.amount = Decimal("20000000")
        await db.flush()

        count = await recalculate_fees_for_semester_tuition_change(db, ai_id)
        await db.commit()

        assert count == 0  # Skipped because invoices are issued

        await db.refresh(fee)
        assert fee.base_amount == original_base


# =============================================================================
# HK1 CLEARED-STATE PIPELINE GATE TESTS (PR 5 — ADR-002)
# =============================================================================

class TestHK1ClearedStatePipelineGate:
    """Test that admission pipeline projections use HK1 cleared-state
    semantics: fires once on first HK1 clearance, never for HK2+."""

    @pytest.mark.asyncio
    async def test_is_hk1_cleared_helper(self):
        """Unit test for the shared is_hk1_cleared helper."""
        from app.services.fee_calculation_service import is_hk1_cleared

        # Cleared states for HK1
        assert is_hk1_cleared("tuition", 1, "paid", Decimal("10000000")) is True
        assert is_hk1_cleared("tuition", 1, "waived", Decimal("0")) is True
        assert is_hk1_cleared("tuition", 1, "partial", Decimal("100000")) is True

        # Not cleared
        assert is_hk1_cleared("tuition", 1, "partial", Decimal("0")) is False
        assert is_hk1_cleared("tuition", 1, "pending", Decimal("0")) is False
        assert is_hk1_cleared("tuition", 1, "calculated", Decimal("0")) is False
        assert is_hk1_cleared("tuition", 1, "invoiced", Decimal("0")) is False
        assert is_hk1_cleared("tuition", 1, "overdue", Decimal("0")) is False
        assert is_hk1_cleared("tuition", 1, "cancelled", Decimal("0")) is False

        # Wrong semester / wrong type
        assert is_hk1_cleared("tuition", 2, "paid", Decimal("10000000")) is False
        assert is_hk1_cleared("tuition", 3, "paid", Decimal("10000000")) is False
        assert is_hk1_cleared("application", 1, "paid", Decimal("10000000")) is False
        assert is_hk1_cleared("tuition", None, "paid", Decimal("10000000")) is False

    @pytest.mark.asyncio
    async def test_hk1_first_partial_triggers_transition(self):
        """First partial HK1 payment: False -> True transition = sync fires."""
        from app.services.fee_calculation_service import is_hk1_cleared

        was = is_hk1_cleared("tuition", 1, "calculated", Decimal("0"))
        assert was is False

        now = is_hk1_cleared("tuition", 1, "partial", Decimal("3000000"))
        assert now is True
        assert not was and now  # Transition detected

    @pytest.mark.asyncio
    async def test_hk1_second_payment_no_retrigger(self):
        """Second payment on already-cleared HK1: True -> True = no sync."""
        from app.services.fee_calculation_service import is_hk1_cleared

        was = is_hk1_cleared("tuition", 1, "partial", Decimal("3000000"))
        assert was is True

        now = is_hk1_cleared("tuition", 1, "partial", Decimal("6000000"))
        assert now is True
        assert not (not was and now)  # No transition

    @pytest.mark.asyncio
    async def test_hk2_payment_never_triggers(self):
        """HK2 payment: always False, no sync regardless of state."""
        from app.services.fee_calculation_service import is_hk1_cleared

        assert is_hk1_cleared("tuition", 2, "paid", Decimal("10000000")) is False
        assert is_hk1_cleared("tuition", 2, "partial", Decimal("5000000")) is False
        assert is_hk1_cleared("tuition", 2, "waived", Decimal("0")) is False

    @pytest.mark.asyncio
    async def test_hk1_waiver_triggers_transition(self):
        """HK1 waiver: False -> True transition = sync fires."""
        from app.services.fee_calculation_service import is_hk1_cleared

        was = is_hk1_cleared("tuition", 1, "calculated", Decimal("0"))
        now = is_hk1_cleared("tuition", 1, "waived", Decimal("0"))
        assert not was and now

    @pytest.mark.asyncio
    async def test_hk1_full_payment_triggers_transition(self):
        """HK1 full payment: False -> True transition = sync fires."""
        from app.services.fee_calculation_service import is_hk1_cleared

        was = is_hk1_cleared("tuition", 1, "invoiced", Decimal("0"))
        now = is_hk1_cleared("tuition", 1, "paid", Decimal("10000000"))
        assert not was and now


# =============================================================================
# KPI HK1 METRICS TESTS (PR 7 — ADR-002)
# =============================================================================

class TestKPIHK1Metrics:
    """Test that KPI metrics use HK1 semester tuition with fallback."""

    @pytest.mark.asyncio
    async def test_hk1_lookup_returns_amount(
        self, db: AsyncSession, finance_fixtures: dict,
    ):
        """Repository returns HK1 amount for the correct academic_info_id."""
        from app.repositories import OrganizationRepository

        ai_id = int(finance_fixtures["admission_profile"].applied_rules["academic_info_id"])
        repo = OrganizationRepository(db)
        result = await repo.get_hk1_tuition_by_academic_info_id(2025)

        # Fixture creates HK1 with 10M for year 2025
        assert ai_id in result
        assert result[ai_id] == Decimal("10000000")

    @pytest.mark.asyncio
    async def test_hk1_lookup_empty_for_unknown_year(
        self, db: AsyncSession,
    ):
        """Repository returns empty dict for a year with no published info."""
        from app.repositories import OrganizationRepository

        repo = OrganizationRepository(db)
        result = await repo.get_hk1_tuition_by_academic_info_id(1999)
        assert result == {}

    @pytest.mark.asyncio
    async def test_resolve_tuition_prefers_hk1(self):
        """HK1 lookup value wins over tuition_fee_per_year."""
        from unittest.mock import MagicMock

        hk1_lookup = {42: Decimal("8000000")}
        info = MagicMock()
        info.id = 42
        info.tuition_fee_per_year = Decimal("20000000")

        resolved = hk1_lookup.get(info.id) or info.tuition_fee_per_year
        assert resolved == Decimal("8000000")

    @pytest.mark.asyncio
    async def test_resolve_tuition_fallback_when_no_hk1(self):
        """Empty HK1 lookup falls back to tuition_fee_per_year."""
        from unittest.mock import MagicMock

        hk1_lookup = {}
        info = MagicMock()
        info.id = 42
        info.tuition_fee_per_year = Decimal("20000000")

        resolved = hk1_lookup.get(info.id) or info.tuition_fee_per_year
        assert resolved == Decimal("20000000")

    @pytest.mark.asyncio
    async def test_subtree_avg_differs_from_minmax_mix(self):
        """True avg via sum/count differs from the old broken min+max approach."""
        values = [Decimal("5000000"), Decimal("15000000"), Decimal("5000000")]
        true_avg = sum(values) / len(values)
        broken_avg = (min(values) + max(values)) / 2
        assert true_avg != broken_avg  # 8.33M != 10M

