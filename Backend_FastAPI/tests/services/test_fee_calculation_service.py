# tests/services/test_fee_calculation_service.py
"""
Tests for FeeCalculationService.

Covers:
- Fee calculation with/without discounts
- Discount stacking (H4) and capping
- Fee recalculation (M10 block)
- Fee waiving (H5 validation)
- Fee cancellation
- Fee summary aggregation
- Installment amount calculation
"""

import pytest
import pytest_asyncio
from datetime import datetime, timezone, timedelta, date
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.models.finance import (
    Fee, Invoice, Payment, PaymentMethod, InstallmentPlan, PaymentIntent,
    FeeTypeEnum, FeeStatusEnum, InvoiceStatusEnum,
    PaymentStatusEnum, PaymentIntentStatusEnum,
)
from app.models.tuition_discount_policy import TuitionDiscountPolicy
from app.services.fee_calculation_service import (
    FeeCalculationService,
    calculate_installment_amounts,
)
from app.services.lead_admission_sync import (
    TUITION_CALCULATED_STATUS,
    TUITION_PAID_STATUS,
)
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
async def fee_fixtures(db: AsyncSession, seeded_dependencies: dict, admin_user):
    """Create base fixtures for fee calculation tests."""
    # Payment method
    cash_method = PaymentMethod(
        code="fee_test_cash",
        name="Cash",
        is_online=False,
        is_active=True,
    )
    db.add(cash_method)

    # Installment plan (2-part: 50%/50%)
    plan = InstallmentPlan(
        code="FEE_TEST_TWO",
        name="2-Part Payment",
        installment_count=2,
        schedule=[
            {"installment_no": 1, "due_days_offset": 0, "percent": 50.0, "description": "Dot 1"},
            {"installment_no": 2, "due_days_offset": 30, "percent": 50.0, "description": "Dot 2"},
        ],
        is_active=True,
    )
    db.add(plan)

    # Discount policy - fixed 50K
    discount_50k = TuitionDiscountPolicy(
        code="FEE_TEST_50K",
        name="Fixed 50K Discount",
        discount_type="amount",
        discount_value=Decimal("50000"),
        is_active=True,
        applicable_scope={},
        target_criteria={},
    )
    db.add(discount_50k)

    # Discount policy - fixed 30K
    discount_30k = TuitionDiscountPolicy(
        code="FEE_TEST_30K",
        name="Fixed 30K Discount",
        discount_type="amount",
        discount_value=Decimal("30000"),
        is_active=True,
        applicable_scope={},
        target_criteria={},
    )
    db.add(discount_30k)

    # Large discount for capping tests
    discount_large = TuitionDiscountPolicy(
        code="FEE_TEST_LARGE",
        name="Large Discount 800K",
        discount_type="amount",
        discount_value=Decimal("800000"),
        is_active=True,
        applicable_scope={},
        target_criteria={},
    )
    db.add(discount_large)

    await db.flush()

    # Lead + Admission Profile
    lead = models.Lead(
        full_name="Fee Test Student",
        phone="0901110001",
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

    return {
        "profile": profile,
        "lead": lead,
        "cash_method": cash_method,
        "installment_plan": plan,
        "discount_50k": discount_50k,
        "discount_30k": discount_30k,
        "discount_large": discount_large,
        "unit_id": seeded_dependencies["unit_id"],
    }


# =============================================================================
# FEE CALCULATION TESTS
# =============================================================================

class TestFeeCalculation:
    """Tests for fee calculation and creation."""

    async def test_calculate_fee_basic(self, db, fee_fixtures, admin_user):
        """Basic fee creation without discounts."""
        service = FeeCalculationService(db)
        profile = fee_fixtures["profile"]

        fee, callback = await service.calculate_fee(
            admission_profile_id=profile.id,
            fee_type=FeeTypeEnum.application,
            base_amount=Decimal("500000"),
            academic_year=2025,
            user_id=admin_user.id,
            unit_id=fee_fixtures["unit_id"],
        )
        await db.commit()

        assert fee.id is not None
        assert fee.base_amount == Decimal("500000")
        assert fee.total_discount == Decimal("0")
        assert fee.final_amount == Decimal("500000")
        assert fee.paid_amount == Decimal("0")
        assert fee.waived_amount == Decimal("0")
        assert fee.status == FeeStatusEnum.calculated.value
        assert fee.version == 1
        assert fee.calculated_by_id == admin_user.id

    async def test_calculate_fee_with_single_discount(self, db, fee_fixtures, admin_user):
        """Fee with a single fixed discount applied."""
        service = FeeCalculationService(db)
        profile = fee_fixtures["profile"]

        fee, _ = await service.calculate_fee(
            admission_profile_id=profile.id,
            fee_type=FeeTypeEnum.enrollment,
            base_amount=Decimal("1000000"),
            academic_year=2025,
            discount_policy_ids=[fee_fixtures["discount_50k"].id],
            user_id=admin_user.id,
            unit_id=fee_fixtures["unit_id"],
        )
        await db.commit()

        assert fee.total_discount == Decimal("50000")
        assert fee.final_amount == Decimal("950000")

    async def test_calculate_fee_with_stacked_discounts(self, db, fee_fixtures, admin_user):
        """H4: Additive stacking of multiple fixed discounts."""
        service = FeeCalculationService(db)
        profile = fee_fixtures["profile"]

        fee, _ = await service.calculate_fee(
            admission_profile_id=profile.id,
            fee_type=FeeTypeEnum.insurance,
            base_amount=Decimal("1000000"),
            academic_year=2025,
            discount_policy_ids=[
                fee_fixtures["discount_50k"].id,
                fee_fixtures["discount_30k"].id,
            ],
            user_id=admin_user.id,
            unit_id=fee_fixtures["unit_id"],
        )
        await db.commit()

        # 50K + 30K = 80K total discount
        assert fee.total_discount == Decimal("80000")
        assert fee.final_amount == Decimal("920000")

    async def test_calculate_fee_discount_capped_at_base(self, db, fee_fixtures, admin_user):
        """H4: Total discount capped at base_amount."""
        service = FeeCalculationService(db)
        profile = fee_fixtures["profile"]

        fee, _ = await service.calculate_fee(
            admission_profile_id=profile.id,
            fee_type=FeeTypeEnum.dormitory,
            base_amount=Decimal("100000"),
            academic_year=2025,
            discount_policy_ids=[
                fee_fixtures["discount_50k"].id,
                fee_fixtures["discount_large"].id,
            ],
            user_id=admin_user.id,
            unit_id=fee_fixtures["unit_id"],
        )
        await db.commit()

        # 50K + 800K = 850K > 100K base → capped at 100K
        assert fee.total_discount == Decimal("100000")
        assert fee.final_amount == Decimal("0")

    async def test_calculate_fee_with_installment_plan(self, db, fee_fixtures, admin_user):
        """Fee with installment plan attached."""
        service = FeeCalculationService(db)
        profile = fee_fixtures["profile"]

        fee, _ = await service.calculate_fee(
            admission_profile_id=profile.id,
            fee_type=FeeTypeEnum.other,
            base_amount=Decimal("2000000"),
            academic_year=2025,
            installment_plan_id=fee_fixtures["installment_plan"].id,
            user_id=admin_user.id,
            unit_id=fee_fixtures["unit_id"],
        )
        await db.commit()

        assert fee.installment_plan_id == fee_fixtures["installment_plan"].id
        assert fee.final_amount == Decimal("2000000")

    async def test_calculate_fee_duplicate_rejected(self, db, fee_fixtures, admin_user):
        """Duplicate fee for same profile/type/year is rejected."""
        service = FeeCalculationService(db)
        profile = fee_fixtures["profile"]

        await service.calculate_fee(
            admission_profile_id=profile.id,
            fee_type=FeeTypeEnum.application,
            base_amount=Decimal("500000"),
            academic_year=2025,
            user_id=admin_user.id,
            unit_id=fee_fixtures["unit_id"],
        )
        await db.commit()

        with pytest.raises(BadRequest) as exc_info:
            await service.calculate_fee(
                admission_profile_id=profile.id,
                fee_type=FeeTypeEnum.application,
                base_amount=Decimal("300000"),
                academic_year=2025,
                user_id=admin_user.id,
                unit_id=fee_fixtures["unit_id"],
            )

        assert "already exists" in str(exc_info.value)

    async def test_calculate_fee_profile_not_found(self, db, fee_fixtures, admin_user):
        """Non-existent profile raises ResourceNotFoundError."""
        service = FeeCalculationService(db)

        with pytest.raises(ResourceNotFoundError):
            await service.calculate_fee(
                admission_profile_id=999999,
                fee_type=FeeTypeEnum.application,
                base_amount=Decimal("500000"),
                academic_year=2025,
                user_id=admin_user.id,
            )

    async def test_calculate_fee_unit_id_idor(self, db, fee_fixtures, admin_user):
        """Profile in different unit returns 404 (IDOR protection)."""
        service = FeeCalculationService(db)
        profile = fee_fixtures["profile"]

        with pytest.raises(ResourceNotFoundError):
            await service.calculate_fee(
                admission_profile_id=profile.id,
                fee_type=FeeTypeEnum.application,
                base_amount=Decimal("500000"),
                academic_year=2025,
                user_id=admin_user.id,
                unit_id=9999,  # Wrong unit
            )


# =============================================================================
# FEE RECALCULATION TESTS
# =============================================================================

class TestFeeRecalculation:
    """Tests for fee recalculation."""

    async def test_recalculate_fee_success(self, db, fee_fixtures, admin_user):
        """Recalculate updates amount and version."""
        service = FeeCalculationService(db)
        profile = fee_fixtures["profile"]

        fee, _ = await service.calculate_fee(
            admission_profile_id=profile.id,
            fee_type=FeeTypeEnum.application,
            base_amount=Decimal("500000"),
            academic_year=2025,
            user_id=admin_user.id,
            unit_id=fee_fixtures["unit_id"],
        )
        await db.commit()
        assert fee.version == 1

        recalc_fee, _ = await service.recalculate_fee(
            fee_id=fee.id,
            new_base_amount=Decimal("600000"),
            reason="Price adjustment",
            user_id=admin_user.id,
            unit_id=fee_fixtures["unit_id"],
        )
        await db.commit()

        assert recalc_fee.base_amount == Decimal("600000")
        assert recalc_fee.final_amount == Decimal("600000")
        assert recalc_fee.version == 2

    async def test_recalculate_fee_blocked_with_payments(self, db, fee_fixtures, admin_user):
        """M10: Cannot recalculate if paid_amount > 0."""
        service = FeeCalculationService(db)
        profile = fee_fixtures["profile"]

        fee, _ = await service.calculate_fee(
            admission_profile_id=profile.id,
            fee_type=FeeTypeEnum.enrollment,
            base_amount=Decimal("1000000"),
            academic_year=2025,
            user_id=admin_user.id,
            unit_id=fee_fixtures["unit_id"],
        )
        await db.commit()

        # Simulate payment
        fee.paid_amount = Decimal("100000")
        await db.commit()

        with pytest.raises(BusinessRuleViolation) as exc_info:
            await service.recalculate_fee(
                fee_id=fee.id,
                new_base_amount=Decimal("1200000"),
                reason="Adjustment",
                user_id=admin_user.id,
                unit_id=fee_fixtures["unit_id"],
            )

        assert "existing payments" in str(exc_info.value).lower()


# =============================================================================
# FEE WAIVER TESTS
# =============================================================================

class TestFeeWaiver:
    """Tests for fee waiving."""

    async def test_waive_fee_partial(self, db, fee_fixtures, admin_user):
        """Partial waive increases waived_amount."""
        service = FeeCalculationService(db)
        profile = fee_fixtures["profile"]

        fee, _ = await service.calculate_fee(
            admission_profile_id=profile.id,
            fee_type=FeeTypeEnum.application,
            base_amount=Decimal("500000"),
            academic_year=2025,
            user_id=admin_user.id,
            unit_id=fee_fixtures["unit_id"],
        )
        await db.commit()

        waived_fee, _ = await service.waive_fee(
            fee_id=fee.id,
            waive_amount=Decimal("200000"),
            reason="Scholarship",
            user_id=admin_user.id,
            unit_id=fee_fixtures["unit_id"],
        )
        await db.commit()

        assert waived_fee.waived_amount == Decimal("200000")
        assert waived_fee.remaining_amount == Decimal("300000")
        assert waived_fee.version == 2

    async def test_waive_fee_full_triggers_paid_status(self, db, fee_fixtures, admin_user):
        """Full waive sets status to paid."""
        service = FeeCalculationService(db)
        profile = fee_fixtures["profile"]

        fee, _ = await service.calculate_fee(
            admission_profile_id=profile.id,
            fee_type=FeeTypeEnum.enrollment,
            base_amount=Decimal("300000"),
            academic_year=2025,
            user_id=admin_user.id,
            unit_id=fee_fixtures["unit_id"],
        )
        await db.commit()

        waived_fee, _ = await service.waive_fee(
            fee_id=fee.id,
            waive_amount=Decimal("300000"),
            reason="Full scholarship",
            user_id=admin_user.id,
            unit_id=fee_fixtures["unit_id"],
        )
        await db.commit()

        assert waived_fee.waived_amount == Decimal("300000")
        assert waived_fee.remaining_amount <= Decimal("0")
        assert waived_fee.status == FeeStatusEnum.paid.value

    async def test_waive_exceeds_remaining(self, db, fee_fixtures, admin_user):
        """H5: Waive amount cannot exceed remaining balance."""
        service = FeeCalculationService(db)
        profile = fee_fixtures["profile"]

        fee, _ = await service.calculate_fee(
            admission_profile_id=profile.id,
            fee_type=FeeTypeEnum.insurance,
            base_amount=Decimal("500000"),
            academic_year=2025,
            user_id=admin_user.id,
            unit_id=fee_fixtures["unit_id"],
        )
        await db.commit()

        with pytest.raises(BusinessRuleViolation) as exc_info:
            await service.waive_fee(
                fee_id=fee.id,
                waive_amount=Decimal("600000"),
                reason="Too much",
                user_id=admin_user.id,
                unit_id=fee_fixtures["unit_id"],
            )

        assert "exceeds remaining" in str(exc_info.value).lower()


# =============================================================================
# FEE CANCELLATION TESTS
# =============================================================================

class TestFeeCancellation:
    """Tests for fee cancellation."""

    async def test_cancel_fee_success(self, db, fee_fixtures, admin_user):
        """Cancel fee sets status to cancelled."""
        service = FeeCalculationService(db)
        profile = fee_fixtures["profile"]

        fee, _ = await service.calculate_fee(
            admission_profile_id=profile.id,
            fee_type=FeeTypeEnum.application,
            base_amount=Decimal("500000"),
            academic_year=2025,
            user_id=admin_user.id,
            unit_id=fee_fixtures["unit_id"],
        )
        await db.commit()

        cancelled_fee, _ = await service.cancel_fee(
            fee_id=fee.id,
            reason="No longer needed",
            user_id=admin_user.id,
            unit_id=fee_fixtures["unit_id"],
        )
        await db.commit()

        assert cancelled_fee.status == FeeStatusEnum.cancelled.value
        assert cancelled_fee.version == 2

    async def test_cancel_fee_blocked_with_payments(self, db, fee_fixtures, admin_user):
        """Cannot cancel fee with existing payments."""
        service = FeeCalculationService(db)
        profile = fee_fixtures["profile"]

        fee, _ = await service.calculate_fee(
            admission_profile_id=profile.id,
            fee_type=FeeTypeEnum.enrollment,
            base_amount=Decimal("1000000"),
            academic_year=2025,
            user_id=admin_user.id,
            unit_id=fee_fixtures["unit_id"],
        )
        await db.commit()

        # Simulate payment
        fee.paid_amount = Decimal("500000")
        await db.commit()

        with pytest.raises(BusinessRuleViolation) as exc_info:
            await service.cancel_fee(
                fee_id=fee.id,
                reason="Cancel attempt",
                user_id=admin_user.id,
                unit_id=fee_fixtures["unit_id"],
            )

        assert "existing payments" in str(exc_info.value).lower()

    # ---- PR-2 hardening: cascade invoices, guards, lead revert ------------

    async def _mk_tuition_hk1(
        self, db, profile, *, final="10000000", invoices=(), status="invoiced"
    ):
        """Create an HK1 tuition fee (+ optional invoices) directly."""
        fee = Fee(
            admission_profile_id=profile.id,
            fee_type="tuition",
            academic_year=2025,
            semester_no=1,
            base_amount=Decimal(final),
            final_amount=Decimal(final),
            status=status,
        )
        db.add(fee)
        await db.flush()
        inv_objs = []
        for i, (amount, st) in enumerate(invoices, start=1):
            inv = Invoice(
                fee_id=fee.id,
                invoice_number=f"INV-CF-{fee.id}-{i}",
                installment_no=i,
                amount=Decimal(str(amount)),
                paid_amount=Decimal("0"),
                penalty_amount=Decimal("0"),
                status=st,
                due_date=date(2025, 9, 5),
            )
            db.add(inv)
            inv_objs.append(inv)
        await db.flush()
        return fee, inv_objs

    async def _seed_consult(self, db, status_id, stage_id="stg01"):
        if await db.get(models.ConsultationStatus, status_id) is None:
            db.add(models.ConsultationStatus(
                id=status_id, name=status_id, color_code="#888888",
                stage_id=stage_id,
            ))
            await db.flush()

    async def _put_lead_at_sts14(self, db, lead):
        """Move lead to sts14 + forward LeadStatusHistory row (old = current)."""
        await self._seed_consult(db, TUITION_CALCULATED_STATUS)
        orig_cs = lead.consultation_status_id
        orig_stage = lead.pipeline_stage_id
        db.add(models.LeadStatusHistory(
            lead_id=lead.id,
            old_status=lead.status,
            new_status=lead.status,
            old_consultation_status_id=orig_cs,
            new_consultation_status_id=TUITION_CALCULATED_STATUS,
            old_pipeline_stage_id=orig_stage,
            new_pipeline_stage_id="stg01",
            changed_by_user_id=None,
            reason="test setup: forward to sts14",
        ))
        lead.consultation_status_id = TUITION_CALCULATED_STATUS
        lead.pipeline_stage_id = "stg01"
        await db.flush()
        return orig_cs

    async def test_cancel_fee_cascades_active_invoices(
        self, db, fee_fixtures, admin_user
    ):
        """cancel_fee huỷ MỌI invoice non-cancelled (gồm cả draft)."""
        service = FeeCalculationService(db)
        fee, invs = await self._mk_tuition_hk1(
            db, fee_fixtures["profile"],
            invoices=[("6000000", InvoiceStatusEnum.issued.value),
                      ("4000000", InvoiceStatusEnum.draft.value)],
        )
        await db.commit()

        await service.cancel_fee(
            fee_id=fee.id, reason="tính nhầm", user_id=admin_user.id,
            unit_id=fee_fixtures["unit_id"],
        )
        await db.commit()

        for inv in invs:
            await db.refresh(inv)
            assert inv.status == InvoiceStatusEnum.cancelled.value
            assert inv.cancelled_by_id == admin_user.id
            assert inv.cancelled_reason == "tính nhầm"
        await db.refresh(fee)
        assert fee.status == FeeStatusEnum.cancelled.value

    async def test_cancel_fee_blocked_pending_payment(
        self, db, fee_fixtures, admin_user
    ):
        """Có payment pending trên invoice của fee → chặn huỷ."""
        service = FeeCalculationService(db)
        fee, invs = await self._mk_tuition_hk1(
            db, fee_fixtures["profile"],
            invoices=[("10000000", InvoiceStatusEnum.issued.value)],
        )
        db.add(Payment(
            invoice_id=invs[0].id,
            method_id=fee_fixtures["cash_method"].id,
            amount=Decimal("1000000"),
            status=PaymentStatusEnum.pending.value,
            payment_date=datetime.now(timezone.utc),
            created_by_id=admin_user.id,
        ))
        await db.commit()

        with pytest.raises(BusinessRuleViolation) as exc:
            await service.cancel_fee(
                fee_id=fee.id, reason="x", user_id=admin_user.id,
                unit_id=fee_fixtures["unit_id"],
            )
        assert "chờ xác minh" in str(exc.value)

    async def test_cancel_fee_blocked_active_intent(
        self, db, fee_fixtures, admin_user
    ):
        """Có PaymentIntent created/pending chưa hết hạn → chặn huỷ."""
        service = FeeCalculationService(db)
        fee, invs = await self._mk_tuition_hk1(
            db, fee_fixtures["profile"],
            invoices=[("10000000", InvoiceStatusEnum.issued.value)],
        )
        db.add(PaymentIntent(
            invoice_id=invs[0].id,
            method_id=fee_fixtures["cash_method"].id,
            amount=Decimal("10000000"),
            idempotency_key="cf-intent-1",
            status=PaymentIntentStatusEnum.pending.value,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        ))
        await db.commit()

        with pytest.raises(BusinessRuleViolation) as exc:
            await service.cancel_fee(
                fee_id=fee.id, reason="x", user_id=admin_user.id,
                unit_id=fee_fixtures["unit_id"],
            )
        assert "giao dịch online" in str(exc.value)

    async def test_cancel_fee_allows_when_intent_expired(
        self, db, fee_fixtures, admin_user
    ):
        """Intent đã hết hạn (can_process_callback=False) → KHÔNG chặn huỷ."""
        service = FeeCalculationService(db)
        fee, invs = await self._mk_tuition_hk1(
            db, fee_fixtures["profile"],
            invoices=[("10000000", InvoiceStatusEnum.issued.value)],
        )
        db.add(PaymentIntent(
            invoice_id=invs[0].id,
            method_id=fee_fixtures["cash_method"].id,
            amount=Decimal("10000000"),
            idempotency_key="cf-intent-exp",
            status=PaymentIntentStatusEnum.pending.value,
            expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
        ))
        await db.commit()

        cancelled, _ = await service.cancel_fee(
            fee_id=fee.id, reason="x", user_id=admin_user.id,
            unit_id=fee_fixtures["unit_id"],
        )
        await db.commit()
        assert cancelled.status == FeeStatusEnum.cancelled.value

    async def test_cancel_fee_reverts_hk1_lead_from_sts14(
        self, db, fee_fixtures, admin_user
    ):
        """HK1 tuition + lead đang sts14 → huỷ fee lùi lead về status TRƯỚC."""
        service = FeeCalculationService(db)
        lead = fee_fixtures["lead"]
        orig_cs = await self._put_lead_at_sts14(db, lead)
        fee, _ = await self._mk_tuition_hk1(db, fee_fixtures["profile"])
        await db.commit()

        await service.cancel_fee(
            fee_id=fee.id, reason="tính nhầm", user_id=admin_user.id,
            unit_id=fee_fixtures["unit_id"],
        )
        await db.commit()

        await db.refresh(lead)
        assert lead.consultation_status_id == orig_cs

    async def test_cancel_fee_no_revert_for_non_tuition(
        self, db, fee_fixtures, admin_user
    ):
        """Phí KHÔNG phải HK1 tuition → KHÔNG đụng lead dù lead ở sts14."""
        service = FeeCalculationService(db)
        lead = fee_fixtures["lead"]
        await self._put_lead_at_sts14(db, lead)
        fee, _ = await service.calculate_fee(
            admission_profile_id=fee_fixtures["profile"].id,
            fee_type=FeeTypeEnum.application,
            base_amount=Decimal("70000"),
            academic_year=2025,
            user_id=admin_user.id,
            unit_id=fee_fixtures["unit_id"],
        )
        await db.commit()

        await service.cancel_fee(
            fee_id=fee.id, reason="x", user_id=admin_user.id,
            unit_id=fee_fixtures["unit_id"],
        )
        await db.commit()

        await db.refresh(lead)
        assert lead.consultation_status_id == TUITION_CALCULATED_STATUS

    async def test_cancel_fee_no_revert_when_lead_advanced(
        self, db, fee_fixtures, admin_user
    ):
        """Lead đã tiến tiếp khỏi sts14 (sts10) → huỷ fee KHÔNG kéo lùi."""
        service = FeeCalculationService(db)
        lead = fee_fixtures["lead"]
        await self._seed_consult(db, TUITION_PAID_STATUS)
        lead.consultation_status_id = TUITION_PAID_STATUS
        await db.flush()
        fee, _ = await self._mk_tuition_hk1(db, fee_fixtures["profile"])
        await db.commit()

        await service.cancel_fee(
            fee_id=fee.id, reason="x", user_id=admin_user.id,
            unit_id=fee_fixtures["unit_id"],
        )
        await db.commit()

        await db.refresh(lead)
        assert lead.consultation_status_id == TUITION_PAID_STATUS

    async def test_check_duplicate_excludes_cancelled_tuition(
        self, db, fee_fixtures, admin_user
    ):
        """Fee HK1 đã huỷ KHÔNG tính là trùng → cho phép tính lại."""
        service = FeeCalculationService(db)
        fee, _ = await self._mk_tuition_hk1(db, fee_fixtures["profile"])
        await db.commit()
        pid = fee_fixtures["profile"].id

        # Còn active → là trùng.
        assert await service.fee_repo.check_duplicate(
            pid, "tuition", 2025, semester_no=1
        ) is True

        await service.cancel_fee(
            fee_id=fee.id, reason="x", user_id=admin_user.id,
            unit_id=fee_fixtures["unit_id"],
        )
        await db.commit()

        # Đã huỷ → KHÔNG còn trùng.
        assert await service.fee_repo.check_duplicate(
            pid, "tuition", 2025, semester_no=1
        ) is False

    async def test_recalc_nontuition_after_cancel(
        self, db, fee_fixtures, admin_user
    ):
        """Huỷ fee non-tuition rồi tính lại cùng năm → KHÔNG raise trùng."""
        service = FeeCalculationService(db)
        pid = fee_fixtures["profile"].id
        fee1, _ = await service.calculate_fee(
            admission_profile_id=pid, fee_type=FeeTypeEnum.enrollment,
            base_amount=Decimal("1000000"), academic_year=2025,
            user_id=admin_user.id, unit_id=fee_fixtures["unit_id"],
        )
        await db.commit()
        await service.cancel_fee(
            fee_id=fee1.id, reason="x", user_id=admin_user.id,
            unit_id=fee_fixtures["unit_id"],
        )
        await db.commit()

        fee2, _ = await service.calculate_fee(
            admission_profile_id=pid, fee_type=FeeTypeEnum.enrollment,
            base_amount=Decimal("1000000"), academic_year=2025,
            user_id=admin_user.id, unit_id=fee_fixtures["unit_id"],
        )
        await db.commit()
        assert fee2.id != fee1.id
        assert fee2.status == FeeStatusEnum.calculated.value


# =============================================================================
# FEE SUMMARY TESTS
# =============================================================================

class TestFeeSummary:
    """Tests for fee summary aggregation."""

    async def test_get_fee_summary(self, db, fee_fixtures, admin_user):
        """Fee summary aggregates correctly across multiple fees."""
        service = FeeCalculationService(db)
        profile = fee_fixtures["profile"]

        # Create two fees
        fee1, _ = await service.calculate_fee(
            admission_profile_id=profile.id,
            fee_type=FeeTypeEnum.application,
            base_amount=Decimal("500000"),
            academic_year=2025,
            user_id=admin_user.id,
            unit_id=fee_fixtures["unit_id"],
        )
        fee2, _ = await service.calculate_fee(
            admission_profile_id=profile.id,
            fee_type=FeeTypeEnum.enrollment,
            base_amount=Decimal("300000"),
            academic_year=2025,
            user_id=admin_user.id,
            unit_id=fee_fixtures["unit_id"],
        )
        await db.commit()

        summary = await service.get_fee_summary(
            profile_id=profile.id,
            unit_id=fee_fixtures["unit_id"],
        )

        assert summary["profile_id"] == profile.id
        assert summary["total_fees"] == Decimal("800000")
        assert summary["total_paid"] == Decimal("0")
        assert summary["total_remaining"] == Decimal("800000")
        assert summary["fee_count"] == 2


# =============================================================================
# INSTALLMENT AMOUNT CALCULATION TESTS
# =============================================================================

class TestInstallmentAmounts:
    """Tests for calculate_installment_amounts helper."""

    def test_single_installment(self):
        """Single installment returns full amount."""
        amounts = calculate_installment_amounts(Decimal("1000000"), 1)
        assert amounts == [Decimal("1000000")]

    def test_equal_split(self):
        """Amounts split evenly with remainder in last."""
        amounts = calculate_installment_amounts(Decimal("1000000"), 3)
        assert len(amounts) == 3
        # Sum must equal total
        assert sum(amounts) == Decimal("1000000")

    def test_indivisible_amount(self):
        """Indivisible amount has correct sum invariant."""
        amounts = calculate_installment_amounts(Decimal("100"), 3)
        assert len(amounts) == 3
        assert sum(amounts) == Decimal("100")

    def test_invalid_count_raises(self):
        """Zero or negative count raises ValueError."""
        with pytest.raises(ValueError):
            calculate_installment_amounts(Decimal("1000"), 0)
