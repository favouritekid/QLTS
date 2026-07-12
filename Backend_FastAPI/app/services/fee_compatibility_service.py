# app/services/fee_compatibility_service.py
"""
Fee Compatibility Service - Phase 0 dual-source reads.

This service provides a compatibility layer for reading fee data from either:
1. New fee table (preferred when USE_NEW_FEE_TABLE=True)
2. Legacy applied_rules JSONB (fallback)

This allows gradual migration from JSONB to relational tables without
breaking existing functionality.

Architecture:
- Pure Python service (no FastAPI imports)
- Uses repository pattern for data access
- Feature flag controlled via settings

Usage:
    from app.services.fee_compatibility_service import FeeCompatibilityService

    service = FeeCompatibilityService(db)
    fee_status = await service.get_application_fee_status(profile_id)
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional, Dict, Any, List
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app import models
from app.models.finance import Fee, Invoice, Payment, FeeStatusEnum
from app.config import settings


@dataclass
class ApplicationFeeStatus:
    """Application fee status response."""
    profile_id: int
    has_fee: bool
    is_required: bool
    fee_amount: Decimal
    paid_amount: Decimal
    status: str  # 'pending', 'paid', 'exempt', 'not_required'
    paid_at: Optional[datetime]
    payment_reference: Optional[str]
    source: str  # 'new_table' or 'legacy_jsonb'


class FeeCompatibilityService:
    """
    Compatibility service for reading fee data during Phase 0 migration.

    Provides unified interface for fee data regardless of storage location
    (new table vs legacy JSONB).
    """

    def __init__(self, db: AsyncSession):
        """Initialize with database session."""
        self.db = db

    async def get_application_fee_status(
        self,
        profile_id: int,
        prefer_new_table: Optional[bool] = None
    ) -> ApplicationFeeStatus:
        """
        Get application fee status from either new table or legacy JSONB.

        Args:
            profile_id: Admission profile ID
            prefer_new_table: Override settings.USE_NEW_FEE_TABLE

        Returns:
            ApplicationFeeStatus with unified fee information

        Raises:
            ResourceNotFoundError: If profile not found
        """
        use_new = prefer_new_table if prefer_new_table is not None else settings.USE_NEW_FEE_TABLE

        if use_new:
            # Try new table first
            result = await self._get_from_new_table(profile_id)
            if result:
                return result
            # Fall back to JSONB if not in new table
            return await self._get_from_legacy_jsonb(profile_id)
        else:
            # Use legacy JSONB
            return await self._get_from_legacy_jsonb(profile_id)

    async def _get_from_new_table(
        self,
        profile_id: int
    ) -> Optional[ApplicationFeeStatus]:
        """
        Get application fee status from new fee table.

        Args:
            profile_id: Admission profile ID

        Returns:
            ApplicationFeeStatus or None if not found in new table
        """
        query = (
            select(Fee)
            .options(
                selectinload(Fee.invoices).selectinload(Invoice.payments)
            )
            .where(
                Fee.admission_profile_id == profile_id,
                Fee.fee_type == 'application'
            )
        )

        result = await self.db.execute(query)
        fee = result.scalars().first()

        if not fee:
            return None

        # Get payment info from first invoice
        paid_at = None
        payment_reference = None
        if fee.invoices:
            for invoice in fee.invoices:
                for payment in invoice.payments:
                    if payment.status == 'verified':
                        paid_at = payment.verified_at or payment.payment_date
                        payment_reference = payment.reference_code
                        break

        # Determine status
        if fee.status == FeeStatusEnum.paid.value:
            status = 'paid'
        elif fee.waived_amount >= fee.final_amount:
            status = 'exempt'
        elif fee.final_amount == 0:
            status = 'not_required'
        else:
            status = 'pending'

        return ApplicationFeeStatus(
            profile_id=profile_id,
            has_fee=True,
            is_required=fee.final_amount > 0,
            fee_amount=fee.final_amount,
            paid_amount=fee.paid_amount,
            status=status,
            paid_at=paid_at,
            payment_reference=payment_reference,
            source='new_table'
        )

    async def _get_from_legacy_jsonb(
        self,
        profile_id: int
    ) -> ApplicationFeeStatus:
        """
        Get application fee status from legacy applied_rules JSONB.

        Args:
            profile_id: Admission profile ID

        Returns:
            ApplicationFeeStatus

        Raises:
            ResourceNotFoundError: If profile not found
        """
        query = (
            select(models.AdmissionProfile)
            .where(models.AdmissionProfile.id == profile_id)
        )

        result = await self.db.execute(query)
        profile = result.scalars().first()

        if not profile:
            from app.utils.exceptions import ResourceNotFoundError
            raise ResourceNotFoundError("Admission profile not found")

        applied_rules = profile.applied_rules or {}

        # Extract fee data from JSONB
        application_fee = Decimal(str(applied_rules.get('application_fee', 0)))
        requires_fee = applied_rules.get('requires_application_fee', False)
        fee_status = applied_rules.get('fee_status', 'pending')
        fee_paid_at_str = applied_rules.get('fee_paid_at')
        fee_payment_data = applied_rules.get('fee_payment_data', {})

        # Parse paid_at timestamp
        paid_at = None
        if fee_paid_at_str:
            try:
                paid_at = datetime.fromisoformat(fee_paid_at_str.replace('Z', '+00:00'))
            except (ValueError, AttributeError):
                pass

        # Determine paid amount
        paid_amount = Decimal('0')
        if fee_status == 'paid':
            paid_amount = Decimal(str(fee_payment_data.get('amount', application_fee)))

        # Normalize status
        if fee_status == 'paid':
            status = 'paid'
        elif fee_status == 'exempt':
            status = 'exempt'
        elif not requires_fee or application_fee == 0:
            status = 'not_required'
        else:
            status = 'pending'

        return ApplicationFeeStatus(
            profile_id=profile_id,
            has_fee=requires_fee and application_fee > 0,
            is_required=requires_fee and application_fee > 0,
            fee_amount=application_fee,
            paid_amount=paid_amount,
            status=status,
            paid_at=paid_at,
            payment_reference=fee_payment_data.get('transaction_id'),
            source='legacy_jsonb'
        )

    async def check_application_fee_paid(
        self,
        profile_id: int
    ) -> bool:
        """
        Check if application fee is paid or not required.

        This is the main gate check for admission workflow.

        Args:
            profile_id: Admission profile ID

        Returns:
            True if fee is paid, exempt, or not required
        """
        status = await self.get_application_fee_status(profile_id)
        return status.status in ('paid', 'exempt', 'not_required')

    async def get_profile_fee_summary(
        self,
        profile_id: int,
        unit_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Get comprehensive fee summary for a profile.

        Combines data from new tables (if available) with legacy data.

        Args:
            profile_id: Admission profile ID
            unit_id: Filter by unit_id for IDOR protection

        Returns:
            Dictionary with fee summary
        """
        summary = {
            'profile_id': profile_id,
            'fees': [],
            'total_amount': Decimal('0'),
            'total_paid': Decimal('0'),
            'total_remaining': Decimal('0'),
            'has_overdue': False,
        }

        # Get all fees from new table
        query = (
            select(Fee)
            .join(models.AdmissionProfile)
            .join(models.Lead)
            .options(
                selectinload(Fee.invoices)
            )
            .where(Fee.admission_profile_id == profile_id)
        )

        if unit_id is not None:
            query = query.where(models.Lead.unit_id == unit_id)

        result = await self.db.execute(query)
        fees = result.scalars().all()

        for fee in fees:
            remaining = fee.final_amount - fee.paid_amount - fee.waived_amount
            summary['fees'].append({
                'id': fee.id,
                'type': fee.fee_type,
                'amount': fee.final_amount,
                'paid': fee.paid_amount,
                'remaining': remaining,
                'status': fee.status,
            })
            # F14: keep parity with FeeCalculationService.get_fee_summary —
            # exclude CANCELLED fees from the money aggregates (a cancelled fee
            # is void, final_amount>0/paid==0, so counting its remaining would
            # surface a phantom "Còn nợ"). Still listed in ['fees'] for history.
            _fee_status = (
                fee.status.value if hasattr(fee.status, "value") else fee.status
            )
            if _fee_status == "cancelled":
                continue
            summary['total_amount'] += fee.final_amount
            summary['total_paid'] += fee.paid_amount
            summary['total_remaining'] += remaining

            # Check for overdue invoices
            for invoice in fee.invoices:
                if invoice.is_overdue:
                    summary['has_overdue'] = True

        return summary

    async def is_finance_module_enabled(self) -> bool:
        """Check if finance module is enabled."""
        return settings.FINANCE_MODULE_ENABLED

    async def should_use_new_fee_table(self) -> bool:
        """Check if new fee table should be used."""
        return settings.USE_NEW_FEE_TABLE
