"""Overpayment resolution service for finance workflows."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Optional, Tuple

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.finance import (
    FeeStatusEnum,
    InvoiceStatusEnum,
    OverpaymentRecord,
    OverpaymentStatusEnum,
    PaymentTransaction,
    ResolutionTypeEnum,
    TransactionTypeEnum,
)
from app.repositories.fee_repository import FeeRepository, InvoiceRepository
from app.repositories.payment_repository import OverpaymentRepository
from app.services.payment_service import RefundService
from app.utils.exceptions import (
    BadRequest,
    BusinessRuleViolation,
    ResourceNotFoundError,
)


class OverpaymentService:
    """Business logic for resolving tracked overpayment liabilities."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.overpayment_repo = OverpaymentRepository(db)
        self.invoice_repo = InvoiceRepository(db)
        self.fee_repo = FeeRepository(db)
        self.refund_service = RefundService(db)

    async def get_overpayment(
        self,
        overpayment_id: int,
        unit_id: Optional[int] = None,
    ) -> OverpaymentRecord:
        overpayment = await self.overpayment_repo.get_by_id_with_relations(
            overpayment_id,
            unit_id,
        )
        if not overpayment:
            raise ResourceNotFoundError("Overpayment not found")
        return overpayment

    async def list_overpayments(
        self,
        skip: int = 0,
        limit: int = 50,
        unit_id: Optional[int] = None,
        statuses: Optional[List[str]] = None,
        profile_id: Optional[int] = None,
    ) -> Tuple[List[OverpaymentRecord], int]:
        return await self.overpayment_repo.get_filtered_with_count(
            skip=skip,
            limit=limit,
            unit_id=unit_id,
            statuses=statuses,
            profile_id=profile_id,
        )

    async def apply_to_invoice(
        self,
        overpayment_id: int,
        target_invoice_id: int,
        user_id: int,
        amount: Optional[Decimal] = None,
        notes: Optional[str] = None,
        unit_id: Optional[int] = None,
    ) -> Tuple[OverpaymentRecord, None]:
        overpayment = await self.get_overpayment(overpayment_id, unit_id)
        self._ensure_pending(overpayment)

        target_invoice = await self.invoice_repo.get_for_update(
            target_invoice_id,
            unit_id,
        )
        if not target_invoice:
            raise ResourceNotFoundError("Target invoice not found")

        target_fee = await self.fee_repo.get_for_update(target_invoice.fee_id, unit_id)
        if not target_fee:
            raise ResourceNotFoundError("Target fee not found")

        if target_fee.admission_profile_id != overpayment.admission_profile_id:
            raise BusinessRuleViolation(
                "Overpayment can only be applied to an invoice on the same profile"
            )

        apply_amount = amount or overpayment.overpayment_amount
        if apply_amount <= 0:
            raise BadRequest("Applied amount must be positive")
        if apply_amount != overpayment.overpayment_amount:
            raise BusinessRuleViolation(
                "Partial overpayment application is not supported; "
                "apply the full amount"
            )
        if apply_amount > target_invoice.remaining_amount:
            raise BusinessRuleViolation(
                "Overpayment amount exceeds target invoice remaining balance"
            )

        fee_balance_before = (
            target_fee.final_amount - target_fee.paid_amount - target_fee.waived_amount
        )

        target_invoice.paid_amount += apply_amount
        if target_invoice.is_fully_paid:
            target_invoice.status = InvoiceStatusEnum.paid.value
            target_invoice.paid_at = datetime.now(timezone.utc)
        elif target_invoice.paid_amount > 0:
            target_invoice.status = InvoiceStatusEnum.partial.value

        target_fee.paid_amount += apply_amount
        target_fee.last_payment_at = datetime.now(timezone.utc)
        target_fee.version += 1

        fee_remaining = (
            target_fee.final_amount - target_fee.paid_amount - target_fee.waived_amount
        )
        if fee_remaining <= 0:
            target_fee.status = FeeStatusEnum.paid.value
        elif target_fee.paid_amount > 0:
            target_fee.status = FeeStatusEnum.partial.value

        overpayment.status = OverpaymentStatusEnum.applied.value
        overpayment.resolution_type = ResolutionTypeEnum.apply_to_next.value
        overpayment.resolved_at = datetime.now(timezone.utc)
        overpayment.resolved_by_id = user_id
        overpayment.resolution_notes = notes
        overpayment.applied_to_invoice_id = target_invoice_id
        overpayment.applied_amount = apply_amount

        default_note = (
            f"Applied overpayment {overpayment.id} "
            f"to invoice {target_invoice.invoice_number}"
        )
        transaction = PaymentTransaction(
            payment_id=overpayment.payment_id,
            fee_id=target_fee.id,
            transaction_type=TransactionTypeEnum.adjustment.value,
            amount=apply_amount,
            balance_before=fee_balance_before,
            balance_after=fee_remaining,
            external_reference=f"OVERPAY-{overpayment.id}",
            performed_by_id=user_id,
            notes=notes or default_note,
        )
        self.db.add(transaction)

        await self.db.flush()
        return overpayment, None

    async def refund_overpayment(
        self,
        overpayment_id: int,
        user_id: int,
        notes: Optional[str] = None,
        unit_id: Optional[int] = None,
    ) -> Tuple[OverpaymentRecord, None]:
        overpayment = await self.get_overpayment(overpayment_id, unit_id)
        self._ensure_pending(overpayment)

        refund, _ = await self.refund_service.request_refund(
            payment_id=overpayment.payment_id,
            amount=overpayment.overpayment_amount,
            reason=notes or f"Refund overpayment {overpayment.id}",
            user_id=user_id,
            unit_id=unit_id,
        )

        overpayment.status = OverpaymentStatusEnum.refunded.value
        overpayment.resolution_type = ResolutionTypeEnum.refund.value
        overpayment.resolved_at = datetime.now(timezone.utc)
        overpayment.resolved_by_id = user_id
        overpayment.resolution_notes = notes
        overpayment.refund_request_id = refund.id

        await self.db.flush()
        return overpayment, None

    async def write_off(
        self,
        overpayment_id: int,
        reason: str,
        user_id: int,
        unit_id: Optional[int] = None,
    ) -> Tuple[OverpaymentRecord, None]:
        overpayment = await self.get_overpayment(overpayment_id, unit_id)
        self._ensure_pending(overpayment)

        if not reason or not reason.strip():
            raise BadRequest("Write-off reason is required")

        overpayment.status = OverpaymentStatusEnum.cancelled.value
        overpayment.resolution_type = ResolutionTypeEnum.write_off.value
        overpayment.resolved_at = datetime.now(timezone.utc)
        overpayment.resolved_by_id = user_id
        overpayment.resolution_notes = reason

        await self.db.flush()
        return overpayment, None

    @staticmethod
    def _ensure_pending(overpayment: OverpaymentRecord) -> None:
        if overpayment.status != OverpaymentStatusEnum.pending.value:
            raise BusinessRuleViolation(
                "Can only resolve pending overpayments. "
                f"Current status: {overpayment.status}"
            )
