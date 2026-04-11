# app/services/fee_calculation_service.py
"""
Fee Calculation Service - Business logic for fee calculation and lifecycle.

Architecture Compliance:
- Service Layer: Pure business logic, no HTTP dependencies
- Security: IDOR checks via repository (unit_id filtering)
- Transactions: Services use db.add()/db.flush(), Router commits
- Error Handling: Raise custom exceptions (ResourceNotFoundError, etc.)

Fee Lifecycle:
    pending → calculated → invoiced → partial → paid
                                   ↘ waived
                                   ↘ cancelled

Business Rules:
- Cannot recalculate if paid_amount > 0 (M10)
- Waive amount cannot exceed remaining balance (H5)
- Discount stacking: additive (capped at 100%)
- Version column for optimistic locking
"""

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import List, Optional, Tuple, Callable, Any
import structlog

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app import models
from app.models.finance import (
    Fee, FeeAppliedDiscount, Invoice, InstallmentPlan,
    FeeTypeEnum, FeeStatusEnum,
)
from app.models.tuition_discount_policy import TuitionDiscountPolicy
from app.repositories.fee_repository import FeeRepository, InvoiceRepository
from app.utils.exceptions import (
    ResourceNotFoundError,
    BadRequest,
    ConflictError,
    BusinessRuleViolation,
)
from app.config import settings

log = structlog.get_logger(__name__)


class FeeCalculationService:
    """
    Service for fee calculation and lifecycle management.

    Responsibilities:
    - Calculate fees with discount application
    - Generate invoices based on installment plans
    - Handle fee waiving
    - Block recalculation when paid
    """

    def __init__(self, db: AsyncSession):
        """Initialize with database session."""
        self.db = db
        self.fee_repo = FeeRepository(db)
        self.invoice_repo = InvoiceRepository(db)

    # ==========================================================================
    # FEE CALCULATION
    # ==========================================================================

    async def calculate_fee(
        self,
        admission_profile_id: int,
        fee_type: FeeTypeEnum,
        base_amount: Decimal,
        academic_year: str,
        discount_policy_ids: Optional[List[int]] = None,
        installment_plan_id: Optional[int] = None,
        user_id: Optional[int] = None,
        unit_id: Optional[int] = None,
    ) -> Tuple[Fee, Optional[Callable]]:
        """
        Calculate fee for an admission profile.

        Args:
            admission_profile_id: Profile to create fee for
            fee_type: Type of fee (application, tuition, etc.)
            base_amount: Base fee amount before discounts
            academic_year: Academic year (e.g., "2024-2025")
            discount_policy_ids: List of discount policy IDs to apply
            installment_plan_id: Installment plan for payment scheduling
            user_id: User performing calculation (for audit)
            unit_id: Unit ID for IDOR protection

        Returns:
            Tuple of (Fee, post_commit_callback)

        Raises:
            ResourceNotFoundError: If profile not found
            BadRequest: If fee already exists for this profile/type/year
        """
        # Validate profile exists and is accessible
        profile = await self._get_profile(admission_profile_id, unit_id)
        if not profile:
            raise ResourceNotFoundError("Admission profile not found")

        # Check for duplicate fee
        existing = await self.fee_repo.check_duplicate(
            admission_profile_id, fee_type.value, academic_year
        )
        if existing:
            raise BadRequest(
                f"Fee of type '{fee_type.value}' already exists for academic year {academic_year}"
            )

        # Calculate discounts
        total_discount, applied_discounts = await self._calculate_discounts(
            base_amount, discount_policy_ids or []
        )

        # Calculate final amount
        final_amount = max(Decimal("0"), base_amount - total_discount)

        # Get installment plan
        installment_plan = None
        if installment_plan_id:
            installment_plan = await self._get_installment_plan(installment_plan_id)

        # Convert academic_year to int (model stores as Integer)
        if isinstance(academic_year, str):
            academic_year_int = int(academic_year.split("-")[0])
        else:
            academic_year_int = academic_year

        # Create fee record
        fee = Fee(
            admission_profile_id=admission_profile_id,
            fee_type=fee_type.value,
            academic_year=academic_year_int,
            installment_plan_id=installment_plan_id,
            base_amount=base_amount,
            total_discount=total_discount,
            final_amount=final_amount,
            paid_amount=Decimal("0"),
            waived_amount=Decimal("0"),
            status=FeeStatusEnum.calculated.value,
            calculated_by_id=user_id,
            calculated_at=datetime.now(timezone.utc),
            version=1,
        )

        self.db.add(fee)
        await self.db.flush()
        await self.db.refresh(fee)

        # Create applied discount records
        for order, (policy_id, discount_amount, snapshot) in enumerate(applied_discounts, 1):
            discount_record = FeeAppliedDiscount(
                fee_id=fee.id,
                policy_id=policy_id,
                discount_amount=discount_amount,
                calculation_snapshot=snapshot,
                application_order=order,
            )
            self.db.add(discount_record)

        await self.db.flush()

        log.info(
            "fee_calculated",
            fee_id=fee.id,
            profile_id=admission_profile_id,
            fee_type=fee_type.value,
            base_amount=str(base_amount),
            total_discount=str(total_discount),
            final_amount=str(final_amount),
            user_id=user_id,
        )

        # ✅ SYNC LEAD STATUS: For tuition fee, move lead to sts14 (Chờ học phí)
        # This keeps Lead consultation status in sync with Finance phase
        if fee_type == FeeTypeEnum.tuition:
            from app.services.lead_admission_sync import sync_lead_tuition_calculated
            await sync_lead_tuition_calculated(
                db=self.db,
                profile=profile,
                fee_amount=str(final_amount),
                changed_by_user_id=user_id,
                reason=f"Tuition fee calculated: {final_amount:,.0f} VND",
            )

        # Post-commit callback (no events to emit — fee calculation is a
        # pure service-internal flow, not a cross-module notification. See ADR-001.)
        async def post_commit():
            pass

        return fee, post_commit

    async def recalculate_fee(
        self,
        fee_id: int,
        new_base_amount: Decimal,
        reason: str,
        user_id: int,
        unit_id: Optional[int] = None,
    ) -> Tuple[Fee, Optional[Callable]]:
        """
        Recalculate an existing fee with new base amount.

        Business Rule M10: Cannot recalculate if paid_amount > 0

        Args:
            fee_id: Fee to recalculate
            new_base_amount: New base amount
            reason: Reason for recalculation (audit)
            user_id: User performing recalculation
            unit_id: Unit ID for IDOR protection

        Returns:
            Tuple of (Fee, post_commit_callback)

        Raises:
            ResourceNotFoundError: If fee not found
            BusinessRuleViolation: If fee has payments
        """
        fee = await self.fee_repo.get_by_id_with_relations(fee_id, unit_id)
        if not fee:
            raise ResourceNotFoundError("Fee not found")

        # M10: Block recalculation if paid
        if fee.paid_amount > 0:
            raise BusinessRuleViolation(
                f"Cannot recalculate fee with existing payments. "
                f"Paid amount: {fee.paid_amount} VND"
            )

        # Get existing discount policy IDs
        existing_policy_ids = [
            ad.policy_id for ad in fee.applied_discounts if ad.policy_id
        ]

        # Recalculate discounts with new base
        total_discount, applied_discounts = await self._calculate_discounts(
            new_base_amount, existing_policy_ids
        )

        # Update fee
        old_base = fee.base_amount
        old_final = fee.final_amount

        fee.base_amount = new_base_amount
        fee.total_discount = total_discount
        fee.final_amount = max(Decimal("0"), new_base_amount - total_discount)
        fee.version += 1
        fee.notes = f"{fee.notes or ''}\n[{datetime.now(timezone.utc).isoformat()}] " \
                    f"Recalculated by user {user_id}: {old_base} → {new_base_amount}. " \
                    f"Reason: {reason}"

        await self.db.flush()

        log.info(
            "fee_recalculated",
            fee_id=fee_id,
            old_base=str(old_base),
            new_base=str(new_base_amount),
            old_final=str(old_final),
            new_final=str(fee.final_amount),
            reason=reason,
            user_id=user_id,
        )

        return fee, None

    async def waive_fee(
        self,
        fee_id: int,
        waive_amount: Decimal,
        reason: str,
        user_id: int,
        unit_id: Optional[int] = None,
    ) -> Tuple[Fee, Optional[Callable]]:
        """
        Waive part of the fee amount.

        Business Rule H5: waive_amount cannot exceed remaining balance

        Args:
            fee_id: Fee to waive
            waive_amount: Amount to waive
            reason: Reason for waiving (required)
            user_id: User performing waive
            unit_id: Unit ID for IDOR protection

        Returns:
            Tuple of (Fee, post_commit_callback)

        Raises:
            ResourceNotFoundError: If fee not found
            BusinessRuleViolation: If waive exceeds remaining
        """
        fee = await self.fee_repo.get_for_update(fee_id, unit_id)
        if not fee:
            raise ResourceNotFoundError("Fee not found")

        remaining = fee.final_amount - fee.paid_amount - fee.waived_amount

        # H5: Validate waive amount
        if waive_amount > remaining:
            raise BusinessRuleViolation(
                f"Waive amount ({waive_amount}) exceeds remaining balance ({remaining})"
            )

        if waive_amount <= 0:
            raise BadRequest("Waive amount must be positive")

        # Apply waive
        fee.waived_amount = fee.waived_amount + waive_amount
        fee.version += 1

        # Update status if fully waived
        new_remaining = fee.final_amount - fee.paid_amount - fee.waived_amount
        fee_became_paid = False
        if new_remaining <= 0:
            fee.status = FeeStatusEnum.paid.value  # Treat as paid
            fee_became_paid = True

        fee.notes = f"{fee.notes or ''}\n[{datetime.now(timezone.utc).isoformat()}] " \
                    f"Waived {waive_amount} VND by user {user_id}. Reason: {reason}"

        await self.db.flush()

        # ✅ SYNC LEAD STATUS: If tuition fee is now fully waived, move lead to sts10
        if fee_became_paid and fee.fee_type == FeeTypeEnum.tuition.value:
            # Need to load profile with lead for sync
            profile = await self._get_profile(fee.admission_profile_id, unit_id)
            if profile:
                from app.services.lead_admission_sync import sync_lead_tuition_paid
                await sync_lead_tuition_paid(
                    db=self.db,
                    profile=profile,
                    transaction_id=f"WAIVER-{fee_id}",
                    changed_by_user_id=user_id,
                    reason=f"Tuition fee waived: {waive_amount:,.0f} VND. Reason: {reason}",
                )

        log.info(
            "fee_waived",
            fee_id=fee_id,
            waive_amount=str(waive_amount),
            new_remaining=str(new_remaining),
            reason=reason,
            user_id=user_id,
        )

        return fee, None

    async def cancel_fee(
        self,
        fee_id: int,
        reason: str,
        user_id: int,
        unit_id: Optional[int] = None,
    ) -> Tuple[Fee, Optional[Callable]]:
        """
        Cancel a fee (only if no payments made).

        Args:
            fee_id: Fee to cancel
            reason: Cancellation reason
            user_id: User performing cancellation
            unit_id: Unit ID for IDOR protection

        Returns:
            Tuple of (Fee, post_commit_callback)

        Raises:
            ResourceNotFoundError: If fee not found
            BusinessRuleViolation: If fee has payments
        """
        fee = await self.fee_repo.get_for_update(fee_id, unit_id)
        if not fee:
            raise ResourceNotFoundError("Fee not found")

        if fee.paid_amount > 0:
            raise BusinessRuleViolation(
                f"Cannot cancel fee with existing payments. "
                f"Paid amount: {fee.paid_amount} VND"
            )

        fee.status = FeeStatusEnum.cancelled.value
        fee.version += 1
        fee.notes = f"{fee.notes or ''}\n[{datetime.now(timezone.utc).isoformat()}] " \
                    f"Cancelled by user {user_id}. Reason: {reason}"

        await self.db.flush()

        log.info(
            "fee_cancelled",
            fee_id=fee_id,
            reason=reason,
            user_id=user_id,
        )

        return fee, None

    # ==========================================================================
    # FEE RETRIEVAL
    # ==========================================================================

    async def get_fee(
        self,
        fee_id: int,
        unit_id: Optional[int] = None,
    ) -> Fee:
        """Get fee by ID with all relations."""
        fee = await self.fee_repo.get_by_id_with_relations(fee_id, unit_id)
        if not fee:
            raise ResourceNotFoundError("Fee not found")
        return fee

    async def get_fees_for_profile(
        self,
        profile_id: int,
        unit_id: Optional[int] = None,
        fee_type: Optional[str] = None,
    ) -> List[Fee]:
        """Get all fees for an admission profile."""
        return await self.fee_repo.get_by_profile_id(
            profile_id, unit_id, fee_type
        )

    async def get_fee_summary(
        self,
        profile_id: int,
        unit_id: Optional[int] = None,
    ) -> dict:
        """
        Get financial summary for a profile.

        Returns:
            Dict with total_fees, total_paid, total_remaining, fees list
        """
        fees = await self.fee_repo.get_by_profile_id(profile_id, unit_id)

        total_fees = sum(f.final_amount for f in fees)
        total_paid = sum(f.paid_amount for f in fees)
        total_waived = sum(f.waived_amount for f in fees)
        total_remaining = total_fees - total_paid - total_waived

        return {
            "profile_id": profile_id,
            "total_fees": total_fees,
            "total_paid": total_paid,
            "total_waived": total_waived,
            "total_remaining": total_remaining,
            "fee_count": len(fees),
            "fees": fees,
        }

    # ==========================================================================
    # HELPER METHODS
    # ==========================================================================

    async def _get_profile(
        self,
        profile_id: int,
        unit_id: Optional[int] = None,
    ) -> Optional[models.AdmissionProfile]:
        """Get admission profile with IDOR check and Lead relationship loaded."""
        query = (
            select(models.AdmissionProfile)
            .join(models.Lead)
            .options(
                selectinload(models.AdmissionProfile.lead),
                selectinload(models.AdmissionProfile.offering_admission_config)
                .selectinload(models.OfferingAdmissionConfig.academic_info),
            )
            .where(models.AdmissionProfile.id == profile_id)
        )

        if unit_id is not None:
            query = query.where(models.Lead.unit_id == unit_id)

        result = await self.db.execute(query)
        return result.scalars().first()

    async def _get_installment_plan(
        self,
        plan_id: int,
    ) -> Optional[InstallmentPlan]:
        """Get installment plan by ID."""
        query = select(InstallmentPlan).where(
            InstallmentPlan.id == plan_id,
            InstallmentPlan.is_active == True,
        )
        result = await self.db.execute(query)
        return result.scalars().first()

    async def _calculate_discounts(
        self,
        base_amount: Decimal,
        policy_ids: List[int],
    ) -> Tuple[Decimal, List[Tuple[int, Decimal, dict]]]:
        """
        Calculate total discount using additive stacking.

        Policy H4: Additive stacking, capped at 100%

        Args:
            base_amount: Base fee amount
            policy_ids: List of discount policy IDs

        Returns:
            Tuple of (total_discount, list of (policy_id, amount, snapshot))
        """
        if not policy_ids:
            return Decimal("0"), []

        # Get discount policies
        query = select(TuitionDiscountPolicy).where(
            TuitionDiscountPolicy.id.in_(policy_ids),
            TuitionDiscountPolicy.is_active == True,
        )
        result = await self.db.execute(query)
        policies = list(result.scalars().all())

        if not policies:
            return Decimal("0"), []

        # Calculate each discount
        applied_discounts = []
        total_percent = Decimal("0")

        for policy in policies:
            if policy.discount_type == "percent":
                percent = Decimal(str(policy.discount_value))
                total_percent += percent
                discount_amount = (base_amount * percent / 100).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )
            else:  # fixed amount
                discount_amount = Decimal(str(policy.discount_value))

            snapshot = {
                "policy_name": policy.name,
                "discount_type": policy.discount_type,
                "discount_value": str(policy.discount_value),
                "calculated_at": datetime.now(timezone.utc).isoformat(),
            }

            applied_discounts.append((policy.id, discount_amount, snapshot))

        # Cap at 100% (H4)
        if total_percent > 100:
            log.warning(
                "discount_capped",
                original_percent=str(total_percent),
                capped_to=100,
            )

        total_discount = sum(d[1] for d in applied_discounts)

        # Cap discount at base amount
        if total_discount > base_amount:
            total_discount = base_amount

        return total_discount, applied_discounts


# ==========================================================================
# HELPER FUNCTIONS (Module-level)
# ==========================================================================

def calculate_installment_amounts(
    total_amount: Decimal,
    installment_count: int,
) -> List[Decimal]:
    """
    Calculate installment amounts with proper rounding.

    Uses remainder-in-last strategy: base amount for first n-1 installments,
    remainder goes to last installment. Ensures sum equals total.

    Args:
        total_amount: Total fee amount
        installment_count: Number of installments

    Returns:
        List of amounts per installment
    """
    if installment_count <= 0:
        raise ValueError("Installment count must be positive")

    if installment_count == 1:
        return [total_amount]

    # Calculate base amount (floor division)
    base_amount = (total_amount / installment_count).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )

    # First n-1 installments get base amount
    amounts = [base_amount] * (installment_count - 1)

    # Last installment gets remainder
    remainder = total_amount - (base_amount * (installment_count - 1))
    amounts.append(remainder)

    # Verify sum equals total
    assert sum(amounts) == total_amount, \
        f"Installment sum {sum(amounts)} != total {total_amount}"

    return amounts
