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

    async def test_auto_issue_returns_invoice_issued_callback(
        self, db, invoice_fixtures, admin_user
    ):
        """C2 / B4: auto_issue=True returns a non-None, awaitable post_commit
        callback (the INVOICE_ISSUED fanout).

        The router (POST /api/fees/calculate) must CAPTURE and await this
        callback; previously it discarded it (``invoices, _ = ...``) so the
        invoice was issued silently with no notification/sync. This guards the
        callback wiring at the service boundary. The actual dispatch is
        guarded on ``payload['user_id']`` (assigned officer) — this fixture's
        lead has no owner, so no dispatch fires; the end-to-end dispatch is
        asserted at the route level in test_fees_calculate_authorization.py
        where the lead has an assigned officer.
        """
        from unittest.mock import AsyncMock, patch

        service = InvoiceService(db)
        fee = invoice_fixtures["fee"]
        due = date.today() + timedelta(days=30)

        invoices, invoice_cb = await service.generate_invoices_for_fee(
            fee_id=fee.id,
            due_date_base=due,
            user_id=admin_user.id,
            unit_id=invoice_fixtures["unit_id"],
            auto_issue=True,
        )
        await db.commit()

        assert invoices[0].status == InvoiceStatusEnum.issued.value
        # B4: callback must be captured, not None, and awaitable without error.
        assert invoice_cb is not None and callable(invoice_cb)
        with patch(
            "app.services.notification_dispatcher.safe_dispatch",
            new_callable=AsyncMock,
        ):
            await invoice_cb()  # must not raise

    async def test_no_auto_issue_returns_none_callback(
        self, db, invoice_fixtures, admin_user
    ):
        """C2 regression guard: without auto_issue, no callback is returned and
        invoices stay draft → no INVOICE_ISSUED for non-tuition fee types."""
        service = InvoiceService(db)
        fee = invoice_fixtures["fee"]
        due = date.today() + timedelta(days=30)

        invoices, invoice_cb = await service.generate_invoices_for_fee(
            fee_id=fee.id,
            due_date_base=due,
            user_id=admin_user.id,
            unit_id=invoice_fixtures["unit_id"],
            auto_issue=False,
        )
        await db.commit()

        assert invoices[0].status == InvoiceStatusEnum.draft.value
        assert invoice_cb is None

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


# =============================================================================
# PR-A: RE-CREATE INVOICE AFTER CANCEL
# =============================================================================

class TestInvoiceRecreateAfterCancelPRA:
    """PR-A: a cancelled invoice no longer reserves the (fee_id, installment_no)
    slot, so an installment can be re-created after cancellation. The DB partial
    unique index still forbids two ACTIVE invoices on the same installment.
    """

    async def test_regenerate_after_all_cancelled(self, db, invoice_fixtures, admin_user):
        """Cancel every invoice → generate_invoices_for_fee runs again instead of
        raising BadRequest('Invoices already exist')."""
        service = InvoiceService(db)
        fee = invoice_fixtures["fee_with_plan"]
        unit_id = invoice_fixtures["unit_id"]
        due = date.today() + timedelta(days=30)

        invoices, _ = await service.generate_invoices_for_fee(
            fee_id=fee.id, due_date_base=due, user_id=admin_user.id, unit_id=unit_id,
        )
        await db.commit()
        assert len(invoices) == 3

        for inv in invoices:
            await service.cancel_invoice(
                invoice_id=inv.id, reason="test recreate",
                user_id=admin_user.id, unit_id=unit_id,
            )
        await db.commit()

        regenerated, _ = await service.generate_invoices_for_fee(
            fee_id=fee.id, due_date_base=due, user_id=admin_user.id, unit_id=unit_id,
        )
        await db.commit()

        assert len(regenerated) == 3
        # New rows are distinct from the cancelled ones (no slot collision).
        assert {inv.id for inv in invoices}.isdisjoint({inv.id for inv in regenerated})

    async def test_recreate_single_installment_after_cancel(
        self, db, invoice_fixtures, admin_user
    ):
        """Cancel one installment → create_single_invoice with the SAME
        installment_no succeeds (partial index frees the slot)."""
        service = InvoiceService(db)
        fee = invoice_fixtures["fee_with_plan"]
        unit_id = invoice_fixtures["unit_id"]
        due = date.today() + timedelta(days=30)

        invoices, _ = await service.generate_invoices_for_fee(
            fee_id=fee.id, due_date_base=due, user_id=admin_user.id, unit_id=unit_id,
        )
        await db.commit()
        target = next(inv for inv in invoices if inv.installment_no == 2)

        await service.cancel_invoice(
            invoice_id=target.id, reason="wrong amount",
            user_id=admin_user.id, unit_id=unit_id,
        )
        await db.commit()

        new_inv, _ = await service.create_single_invoice(
            fee_id=fee.id, amount=target.amount, due_date=due,
            installment_no=2, user_id=admin_user.id, unit_id=unit_id,
        )
        await db.commit()

        assert new_inv.installment_no == 2
        assert new_inv.id != target.id
        assert new_inv.status == InvoiceStatusEnum.draft.value

    async def test_duplicate_active_installment_still_blocked(
        self, db, invoice_fixtures, admin_user
    ):
        """create_single_invoice on an installment that still has an ACTIVE
        invoice is rejected — active_only guard sees the live row."""
        service = InvoiceService(db)
        fee = invoice_fixtures["fee_with_plan"]
        unit_id = invoice_fixtures["unit_id"]
        due = date.today() + timedelta(days=30)

        await service.generate_invoices_for_fee(
            fee_id=fee.id, due_date_base=due, user_id=admin_user.id, unit_id=unit_id,
        )
        await db.commit()

        with pytest.raises(BadRequest):
            await service.create_single_invoice(
                fee_id=fee.id, amount=Decimal("100000"), due_date=due,
                installment_no=1, user_id=admin_user.id, unit_id=unit_id,
            )

    async def test_total_invoiced_excludes_cancelled(
        self, db, invoice_fixtures, admin_user
    ):
        """Hidden-bug guard: create_single_invoice's remaining-to-invoice must
        ignore cancelled amounts, else re-invoicing a cancelled installment
        wrongly trips 'exceeds remaining balance'."""
        service = InvoiceService(db)
        fee = invoice_fixtures["fee"]  # single 900000, no plan
        unit_id = invoice_fixtures["unit_id"]
        due = date.today() + timedelta(days=30)

        invoices, _ = await service.generate_invoices_for_fee(
            fee_id=fee.id, due_date_base=due, user_id=admin_user.id, unit_id=unit_id,
        )
        await db.commit()
        await service.cancel_invoice(
            invoice_id=invoices[0].id, reason="redo",
            user_id=admin_user.id, unit_id=unit_id,
        )
        await db.commit()

        # The full 900000 is invoiceable again (cancelled amount not counted).
        new_inv, _ = await service.create_single_invoice(
            fee_id=fee.id, amount=Decimal("900000"), due_date=due,
            installment_no=1, user_id=admin_user.id, unit_id=unit_id,
        )
        await db.commit()
        assert new_inv.amount == Decimal("900000")

    async def test_db_partial_unique_blocks_two_active(
        self, db, invoice_fixtures, admin_user
    ):
        """DB-level: two ACTIVE invoices on the same (fee_id, installment_no)
        violate uq_invoice_fee_installment_active."""
        from sqlalchemy.exc import IntegrityError

        service = InvoiceService(db)
        fee = invoice_fixtures["fee"]
        unit_id = invoice_fixtures["unit_id"]
        due = date.today() + timedelta(days=30)

        await service.generate_invoices_for_fee(
            fee_id=fee.id, due_date_base=due, user_id=admin_user.id, unit_id=unit_id,
        )
        await db.commit()

        dup = Invoice(
            fee_id=fee.id,
            invoice_number="INV-TEST-DUP-0001",
            installment_no=1,
            amount=Decimal("900000"),
            paid_amount=Decimal("0"),
            penalty_amount=Decimal("0"),
            status=InvoiceStatusEnum.draft.value,
            due_date=due,
        )
        db.add(dup)
        with pytest.raises(IntegrityError):
            await db.flush()
        await db.rollback()

    async def test_race_integrity_error_maps_to_duplicate(
        self, db, invoice_fixtures, admin_user, monkeypatch
    ):
        """Race backstop: when a concurrent INSERT wins between the active_only
        pre-check and the flush, create_single_invoice maps the partial-unique
        IntegrityError to a domain DuplicateResourceError (→ 409 at the router),
        not a raw 500.

        Simulated by stubbing the duplicate pre-check to 'see nothing' while a
        real ACTIVE invoice for the same installment already exists.
        """
        from app.utils.exceptions import DuplicateResourceError

        service = InvoiceService(db)
        fee = invoice_fixtures["fee"]
        unit_id = invoice_fixtures["unit_id"]
        due = date.today() + timedelta(days=30)

        await service.generate_invoices_for_fee(
            fee_id=fee.id, due_date_base=due, user_id=admin_user.id, unit_id=unit_id,
        )
        await db.commit()

        async def _no_existing(*args, **kwargs):
            return []

        # Pre-check now "sees nothing", so create proceeds to the flush where the
        # real active installment #1 trips the partial unique index.
        monkeypatch.setattr(service.invoice_repo, "get_by_fee_id", _no_existing)

        with pytest.raises(DuplicateResourceError):
            await service.create_single_invoice(
                fee_id=fee.id, amount=Decimal("100000"), due_date=due,
                installment_no=1, user_id=admin_user.id, unit_id=unit_id,
            )


# =============================================================================
# PR-B: FEE.STATUS RECOMPUTE ON CANCEL (Nhóm A balance)
# =============================================================================

class TestFeeRecomputeOnCancelPRB:
    """PR-B: cancelling an invoice recomputes the parent Fee.status from the
    remaining ACTIVE invoices (+ paid_amount), WITHOUT touching final_amount."""

    async def test_cancel_one_of_many_keeps_invoiced(
        self, db, invoice_fixtures, admin_user
    ):
        """Cancel one of several unpaid installments → Fee stays 'invoiced'
        (still has active invoices, paid=0); final_amount NOT auto-reduced."""
        service = InvoiceService(db)
        fee = invoice_fixtures["fee_with_plan"]
        unit_id = invoice_fixtures["unit_id"]
        original_final = fee.final_amount
        invs, _ = await service.generate_invoices_for_fee(
            fee_id=fee.id, due_date_base=date.today() + timedelta(days=30),
            user_id=admin_user.id, unit_id=unit_id,
        )
        await db.commit()

        await service.cancel_invoice(invs[1].id, "drop one", admin_user.id, unit_id)
        await db.commit()
        await db.refresh(fee)

        assert fee.status == FeeStatusEnum.invoiced.value
        assert fee.final_amount == original_final

    async def test_cancel_all_returns_calculated(
        self, db, invoice_fixtures, admin_user
    ):
        """Cancel every invoice (paid=0) → Fee back to 'calculated'; final_amount
        unchanged (real reduction is a separate audited flow)."""
        service = InvoiceService(db)
        fee = invoice_fixtures["fee_with_plan"]
        unit_id = invoice_fixtures["unit_id"]
        original_final = fee.final_amount
        invs, _ = await service.generate_invoices_for_fee(
            fee_id=fee.id, due_date_base=date.today() + timedelta(days=30),
            user_id=admin_user.id, unit_id=unit_id,
        )
        await db.commit()

        for inv in invs:
            await service.cancel_invoice(inv.id, "drop all", admin_user.id, unit_id)
        await db.commit()
        await db.refresh(fee)

        assert fee.status == FeeStatusEnum.calculated.value
        assert fee.final_amount == original_final

    async def test_recompute_status_paid_branches(
        self, db, invoice_fixtures, admin_user
    ):
        """paid_amount > 0 → 'partial'; paid >= billable → 'paid'. Never overload
        'partial' with "đã lập một phần"."""
        service = InvoiceService(db)
        fee = invoice_fixtures["fee_with_plan"]
        unit_id = invoice_fixtures["unit_id"]
        await service.generate_invoices_for_fee(
            fee_id=fee.id, due_date_base=date.today() + timedelta(days=30),
            user_id=admin_user.id, unit_id=unit_id,
        )
        await db.commit()

        fee.paid_amount = Decimal("100000")  # > 0, < billable
        await db.flush()
        await service.recompute_fee_from_invoices(fee.id, unit_id)
        await db.refresh(fee)
        assert fee.status == FeeStatusEnum.partial.value

        fee.paid_amount = fee.final_amount - fee.waived_amount  # >= billable
        await db.flush()
        await service.recompute_fee_from_invoices(fee.id, unit_id)
        await db.refresh(fee)
        assert fee.status == FeeStatusEnum.paid.value

    async def test_cancel_after_post_issue_waive_not_blocked(
        self, db, invoice_fixtures, admin_user
    ):
        """F1 (review 06-24): a post-issue waiver can make Σ active >
        (final - waived). Cancelling to clean up must NOT be blocked — recompute
        no longer enforces an over-bill invariant (that guard lives at creation)."""
        service = InvoiceService(db)
        fee = invoice_fixtures["fee_with_plan"]  # final 9_000_000, 3 installments
        unit_id = invoice_fixtures["unit_id"]
        invs, _ = await service.generate_invoices_for_fee(
            fee_id=fee.id, due_date_base=date.today() + timedelta(days=30),
            user_id=admin_user.id, unit_id=unit_id,
        )
        await db.commit()

        # Post-issue waiver shrinking billable below Σ active (still un-paid).
        fee.waived_amount = Decimal("6000000")  # billable 3M < Σ active 9M
        await db.flush()

        # Must succeed (no over-bill BusinessRuleViolation).
        await service.cancel_invoice(
            invs[0].id, "cleanup over-billed", admin_user.id, unit_id
        )
        await db.commit()
        await db.refresh(fee)

        # remaining = 9M - 6M - 0 = 3M > 0, paid=0, active>0 → invoiced
        assert fee.status == FeeStatusEnum.invoiced.value

    async def test_full_waive_then_cancel_stays_paid(
        self, db, invoice_fixtures, admin_user
    ):
        """F2 (review 06-24): a fully-waived fee (settled, paid_amount 0) must NOT
        be reopened to 'calculated' when its invoice is cancelled."""
        service = InvoiceService(db)
        fee = invoice_fixtures["fee"]  # single application fee 900_000
        unit_id = invoice_fixtures["unit_id"]
        invs, _ = await service.generate_invoices_for_fee(
            fee_id=fee.id, due_date_base=date.today() + timedelta(days=30),
            user_id=admin_user.id, unit_id=unit_id,
        )
        await db.commit()

        # Full waiver: settled by waiver, status 'paid', paid_amount 0.
        fee.waived_amount = fee.final_amount
        fee.status = FeeStatusEnum.paid.value
        await db.flush()

        await service.cancel_invoice(invs[0].id, "redo billing", admin_user.id, unit_id)
        await db.commit()
        await db.refresh(fee)

        assert fee.status == FeeStatusEnum.paid.value  # stays settled, not reopened

    async def test_recompute_bumps_version_on_status_change(
        self, db, invoice_fixtures, admin_user
    ):
        """F3 (review 06-24): recompute bumps fee.version when it changes status,
        so the optimistic-lock token can't be silently stale."""
        service = InvoiceService(db)
        fee = invoice_fixtures["fee_with_plan"]
        unit_id = invoice_fixtures["unit_id"]
        invs, _ = await service.generate_invoices_for_fee(
            fee_id=fee.id, due_date_base=date.today() + timedelta(days=30),
            user_id=admin_user.id, unit_id=unit_id,
        )
        await db.commit()
        await db.refresh(fee)
        v0 = fee.version

        for inv in invs:
            await service.cancel_invoice(inv.id, "all", admin_user.id, unit_id)
        await db.commit()
        await db.refresh(fee)

        assert fee.status == FeeStatusEnum.calculated.value
        assert fee.version > v0  # invoiced→calculated bumped the token

    async def test_cancel_blocked_when_invoice_paid(
        self, db, invoice_fixtures, admin_user
    ):
        """Existing guard preserved: an invoice with paid_amount > 0 cannot be
        cancelled (recompute never runs on a paid installment)."""
        service = InvoiceService(db)
        fee = invoice_fixtures["fee_with_plan"]
        unit_id = invoice_fixtures["unit_id"]
        invs, _ = await service.generate_invoices_for_fee(
            fee_id=fee.id, due_date_base=date.today() + timedelta(days=30),
            user_id=admin_user.id, unit_id=unit_id,
        )
        await db.commit()
        invs[0].paid_amount = Decimal("1")
        await db.flush()

        with pytest.raises(BusinessRuleViolation):
            await service.cancel_invoice(invs[0].id, "x", admin_user.id, unit_id)
