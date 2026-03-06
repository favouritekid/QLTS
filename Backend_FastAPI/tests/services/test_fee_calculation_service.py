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
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.models.finance import (
    Fee, PaymentMethod, InstallmentPlan,
    FeeTypeEnum, FeeStatusEnum,
)
from app.models.tuition_discount_policy import TuitionDiscountPolicy
from app.services.fee_calculation_service import (
    FeeCalculationService,
    calculate_installment_amounts,
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
