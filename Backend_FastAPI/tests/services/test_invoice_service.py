# tests/services/test_invoice_service.py
"""
Tests for InvoiceService.

Covers:
- Invoice generation (single and installment)
- Auto-issue on generation
- H8: Fee status validation
- Duplicate invoice prevention
- Invoice lifecycle (issue, cancel, penalty)
- Invoice number format
"""

import pytest
import pytest_asyncio
from datetime import datetime, timezone, date, timedelta
from decimal import Decimal
import re

from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.models.finance import (
    Fee, Invoice, PaymentMethod, InstallmentPlan,
    FeeTypeEnum, FeeStatusEnum, InvoiceStatusEnum,
)
from app.services.fee_calculation_service import FeeCalculationService
from app.services.invoice_service import InvoiceService
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
async def invoice_fixtures(db: AsyncSession, seeded_dependencies: dict, admin_user):
    """Create base fixtures for invoice tests: fee + payment methods."""
    cash_method = PaymentMethod(
        code="inv_test_cash",
        name="Cash",
        is_online=False,
        is_active=True,
    )
    db.add(cash_method)

    plan = InstallmentPlan(
        code="INV_TEST_THREE",
        name="3-Part Payment",
        installment_count=3,
        schedule=[
            {"installment_no": 1, "due_days_offset": 0, "percent": 34.0, "description": "Dot 1"},
            {"installment_no": 2, "due_days_offset": 30, "percent": 33.0, "description": "Dot 2"},
            {"installment_no": 3, "due_days_offset": 60, "percent": 33.0, "description": "Dot 3"},
        ],
        is_active=True,
    )
    db.add(plan)
    await db.flush()

    lead = models.Lead(
        full_name="Invoice Test Student",
        phone="0901220001",
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

    # Create a calculated fee via service
    fee_service = FeeCalculationService(db)
    fee, _ = await fee_service.calculate_fee(
        admission_profile_id=profile.id,
        fee_type=FeeTypeEnum.application,
        base_amount=Decimal("900000"),
        academic_year=2025,
        user_id=admin_user.id,
        unit_id=seeded_dependencies["unit_id"],
    )
    await db.commit()

    # Create a second fee with installment plan
    fee_with_plan, _ = await fee_service.calculate_fee(
        admission_profile_id=profile.id,
        fee_type=FeeTypeEnum.enrollment,
        base_amount=Decimal("9000000"),
        academic_year=2025,
        installment_plan_id=plan.id,
        user_id=admin_user.id,
        unit_id=seeded_dependencies["unit_id"],
    )
    await db.commit()

    return {
        "fee": fee,
        "fee_with_plan": fee_with_plan,
        "profile": profile,
        "cash_method": cash_method,
        "installment_plan": plan,
        "unit_id": seeded_dependencies["unit_id"],
    }


# =============================================================================
# INVOICE GENERATION TESTS
# =============================================================================

class TestInvoiceGeneration:
    """Tests for invoice generation."""

    async def test_generate_invoices_single(self, db, invoice_fixtures, admin_user):
        """Single invoice for fee without installment plan."""
        service = InvoiceService(db)
        fee = invoice_fixtures["fee"]
        due = date.today() + timedelta(days=30)

        invoices, _ = await service.generate_invoices_for_fee(
            fee_id=fee.id,
            due_date_base=due,
            user_id=admin_user.id,
            unit_id=invoice_fixtures["unit_id"],
        )
        await db.commit()

        assert len(invoices) == 1
        assert invoices[0].amount == Decimal("900000")
        assert invoices[0].installment_no == 1
        assert invoices[0].status == InvoiceStatusEnum.draft.value
        assert invoices[0].paid_amount == Decimal("0")
        assert invoices[0].due_date == due

    async def test_generate_invoices_installment(self, db, invoice_fixtures, admin_user):
        """Multiple invoices from installment plan, amounts sum to total."""
        service = InvoiceService(db)
        fee = invoice_fixtures["fee_with_plan"]
        due = date.today() + timedelta(days=30)

        invoices, _ = await service.generate_invoices_for_fee(
            fee_id=fee.id,
            due_date_base=due,
            user_id=admin_user.id,
            unit_id=invoice_fixtures["unit_id"],
        )
        await db.commit()

        assert len(invoices) == 3
        total = sum(inv.amount for inv in invoices)
        assert total == fee.final_amount
        assert invoices[0].installment_no == 1
        assert invoices[1].installment_no == 2
        assert invoices[2].installment_no == 3

        # Verify due dates offset correctly
        assert invoices[0].due_date == due
        assert invoices[1].due_date == due + timedelta(days=30)
        assert invoices[2].due_date == due + timedelta(days=60)

    async def test_generate_invoices_auto_issue(self, db, invoice_fixtures, admin_user):
        """Auto-issue sets invoices to issued status directly."""
        service = InvoiceService(db)
        fee = invoice_fixtures["fee"]
        due = date.today() + timedelta(days=30)

        invoices, _ = await service.generate_invoices_for_fee(
            fee_id=fee.id,
            due_date_base=due,
            user_id=admin_user.id,
            unit_id=invoice_fixtures["unit_id"],
            auto_issue=True,
        )
        await db.commit()

        assert invoices[0].status == InvoiceStatusEnum.issued.value
        assert invoices[0].issued_at is not None
        assert invoices[0].issued_by_id == admin_user.id

    async def test_generate_invoices_wrong_status(self, db, invoice_fixtures, admin_user):
        """H8: Cannot generate invoices for cancelled fee."""
        service = InvoiceService(db)
        fee = invoice_fixtures["fee"]

        # Force fee to cancelled status
        fee.status = FeeStatusEnum.cancelled.value
        await db.commit()

        with pytest.raises(BusinessRuleViolation) as exc_info:
            await service.generate_invoices_for_fee(
                fee_id=fee.id,
                due_date_base=date.today() + timedelta(days=30),
                user_id=admin_user.id,
                unit_id=invoice_fixtures["unit_id"],
            )

        assert "status" in str(exc_info.value).lower()

    async def test_generate_invoices_duplicate(self, db, invoice_fixtures, admin_user):
        """Cannot generate invoices if they already exist."""
        service = InvoiceService(db)
        fee = invoice_fixtures["fee"]
        due = date.today() + timedelta(days=30)

        # Generate first batch
        await service.generate_invoices_for_fee(
            fee_id=fee.id,
            due_date_base=due,
            user_id=admin_user.id,
            unit_id=invoice_fixtures["unit_id"],
        )
        await db.commit()

        # Try again
        with pytest.raises(BadRequest) as exc_info:
            await service.generate_invoices_for_fee(
                fee_id=fee.id,
                due_date_base=due,
                user_id=admin_user.id,
                unit_id=invoice_fixtures["unit_id"],
            )

        assert "already exist" in str(exc_info.value).lower()


# =============================================================================
# MANUAL INVOICE CREATION TESTS
# =============================================================================

class TestSingleInvoiceCreation:
    """Tests for create_single_invoice."""

    async def test_create_single_invoice(self, db, invoice_fixtures, admin_user):
        """Manual invoice creation success."""
        service = InvoiceService(db)
        fee = invoice_fixtures["fee"]
        due = date.today() + timedelta(days=30)

        invoice, _ = await service.create_single_invoice(
            fee_id=fee.id,
            amount=Decimal("400000"),
            due_date=due,
            installment_no=1,
            user_id=admin_user.id,
            unit_id=invoice_fixtures["unit_id"],
            notes="Manual invoice",
        )
        await db.commit()

        assert invoice.id is not None
        assert invoice.amount == Decimal("400000")
        assert invoice.installment_no == 1
        assert invoice.notes == "Manual invoice"

    async def test_create_single_invoice_exceeds_remaining(self, db, invoice_fixtures, admin_user):
        """Invoice amount cannot exceed remaining fee balance."""
        service = InvoiceService(db)
        fee = invoice_fixtures["fee"]
        due = date.today() + timedelta(days=30)

        with pytest.raises(BusinessRuleViolation) as exc_info:
            await service.create_single_invoice(
                fee_id=fee.id,
                amount=Decimal("999999999"),
                due_date=due,
                installment_no=1,
                user_id=admin_user.id,
                unit_id=invoice_fixtures["unit_id"],
            )

        assert "exceeds" in str(exc_info.value).lower()


# =============================================================================
# INVOICE LIFECYCLE TESTS
# =============================================================================

class TestInvoiceLifecycle:
    """Tests for invoice issue, cancel, and penalty."""

    async def test_issue_invoice(self, db, invoice_fixtures, admin_user):
        """Issue draft invoice transitions to issued status."""
        service = InvoiceService(db)
        fee = invoice_fixtures["fee"]

        invoices, _ = await service.generate_invoices_for_fee(
            fee_id=fee.id,
            due_date_base=date.today() + timedelta(days=30),
            user_id=admin_user.id,
            unit_id=invoice_fixtures["unit_id"],
        )
        await db.commit()

        issued, _ = await service.issue_invoice(
            invoice_id=invoices[0].id,
            user_id=admin_user.id,
            unit_id=invoice_fixtures["unit_id"],
        )
        await db.commit()

        assert issued.status == InvoiceStatusEnum.issued.value
        assert issued.issued_at is not None
        assert issued.issued_by_id == admin_user.id

    async def test_cancel_invoice_no_payments(self, db, invoice_fixtures, admin_user):
        """Cancel invoice with no payments succeeds."""
        service = InvoiceService(db)
        fee = invoice_fixtures["fee"]

        invoices, _ = await service.generate_invoices_for_fee(
            fee_id=fee.id,
            due_date_base=date.today() + timedelta(days=30),
            user_id=admin_user.id,
            unit_id=invoice_fixtures["unit_id"],
        )
        await db.commit()

        cancelled, _ = await service.cancel_invoice(
            invoice_id=invoices[0].id,
            reason="No longer needed",
            user_id=admin_user.id,
            unit_id=invoice_fixtures["unit_id"],
        )
        await db.commit()

        assert cancelled.status == InvoiceStatusEnum.cancelled.value
        assert cancelled.cancelled_at is not None
        assert cancelled.cancelled_reason == "No longer needed"

    async def test_cancel_invoice_with_payments(self, db, invoice_fixtures, admin_user):
        """Cannot cancel invoice with payments."""
        service = InvoiceService(db)
        fee = invoice_fixtures["fee"]

        invoices, _ = await service.generate_invoices_for_fee(
            fee_id=fee.id,
            due_date_base=date.today() + timedelta(days=30),
            user_id=admin_user.id,
            unit_id=invoice_fixtures["unit_id"],
        )
        await db.commit()

        # Simulate paid_amount > 0
        invoices[0].paid_amount = Decimal("100000")
        await db.commit()

        with pytest.raises(BusinessRuleViolation) as exc_info:
            await service.cancel_invoice(
                invoice_id=invoices[0].id,
                reason="Try cancel",
                user_id=admin_user.id,
                unit_id=invoice_fixtures["unit_id"],
            )

        assert "payments" in str(exc_info.value).lower()

    async def test_cancel_invoice_already_cancelled(self, db, invoice_fixtures, admin_user):
        """Cannot cancel already cancelled invoice."""
        service = InvoiceService(db)
        fee = invoice_fixtures["fee"]

        invoices, _ = await service.generate_invoices_for_fee(
            fee_id=fee.id,
            due_date_base=date.today() + timedelta(days=30),
            user_id=admin_user.id,
            unit_id=invoice_fixtures["unit_id"],
        )
        await db.commit()

        # Cancel once
        await service.cancel_invoice(
            invoice_id=invoices[0].id,
            reason="First cancel",
            user_id=admin_user.id,
            unit_id=invoice_fixtures["unit_id"],
        )
        await db.commit()

        # Try cancel again
        with pytest.raises(BusinessRuleViolation) as exc_info:
            await service.cancel_invoice(
                invoice_id=invoices[0].id,
                reason="Second cancel",
                user_id=admin_user.id,
                unit_id=invoice_fixtures["unit_id"],
            )

        assert "already cancelled" in str(exc_info.value).lower()

    async def test_apply_penalty(self, db, invoice_fixtures, admin_user):
        """Penalty increases penalty_amount."""
        service = InvoiceService(db)
        fee = invoice_fixtures["fee"]

        invoices, _ = await service.generate_invoices_for_fee(
            fee_id=fee.id,
            due_date_base=date.today() + timedelta(days=30),
            user_id=admin_user.id,
            unit_id=invoice_fixtures["unit_id"],
            auto_issue=True,
        )
        await db.commit()

        penalized, _ = await service.apply_penalty(
            invoice_id=invoices[0].id,
            penalty_amount=Decimal("50000"),
            reason="Late payment",
            user_id=admin_user.id,
            unit_id=invoice_fixtures["unit_id"],
        )
        await db.commit()

        assert penalized.penalty_amount == Decimal("50000")
        assert penalized.total_due == Decimal("900000") + Decimal("50000")

    async def test_apply_penalty_on_paid_invoice(self, db, invoice_fixtures, admin_user):
        """Cannot apply penalty to paid invoice."""
        service = InvoiceService(db)
        fee = invoice_fixtures["fee"]

        invoices, _ = await service.generate_invoices_for_fee(
            fee_id=fee.id,
            due_date_base=date.today() + timedelta(days=30),
            user_id=admin_user.id,
            unit_id=invoice_fixtures["unit_id"],
        )
        await db.commit()

        # Force paid status
        invoices[0].status = InvoiceStatusEnum.paid.value
        await db.commit()

        with pytest.raises(BusinessRuleViolation):
            await service.apply_penalty(
                invoice_id=invoices[0].id,
                penalty_amount=Decimal("10000"),
                reason="Try penalty",
                user_id=admin_user.id,
                unit_id=invoice_fixtures["unit_id"],
            )

    async def test_invoice_number_format(self, db, invoice_fixtures, admin_user):
        """Invoice number matches INV-YYYY-XXXXXX format."""
        service = InvoiceService(db)
        fee = invoice_fixtures["fee"]

        invoices, _ = await service.generate_invoices_for_fee(
            fee_id=fee.id,
            due_date_base=date.today() + timedelta(days=30),
            user_id=admin_user.id,
            unit_id=invoice_fixtures["unit_id"],
        )
        await db.commit()

        inv_num = invoices[0].invoice_number
        assert inv_num.startswith("INV-")
        # Format: INV-YYYY-XXXXXX (possibly with timestamp suffix)
        assert re.match(r"INV-\d{4}-\d+", inv_num)
