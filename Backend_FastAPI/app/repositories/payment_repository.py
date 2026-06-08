# app/repositories/payment_repository.py
"""
Payment Repository - Data access layer for Payment operations.

Security Features:
- IDOR Protection: All queries filter through lead.unit_id
- Maker-Checker Support: Queries for pending verification
- Audit Trail: Payment transaction history

Architecture:
- Extends BaseRepository for common CRUD operations
- Implements custom queries for payment-specific operations
- Supports both online (PaymentIntent) and manual (Payment) flows
"""

from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Optional, Tuple

from sqlalchemy import select, and_, or_, func, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from app import models
from app.models.finance import (
    Payment,
    PaymentIntent,
    PaymentTransaction,
    RefundRequest,
    OverpaymentRecord,
    Fee,
    Invoice,
    PaymentMethod,
    PaymentStatusEnum,
    PaymentIntentStatusEnum,
    RefundStatusEnum,
    OverpaymentStatusEnum,
)
from app.repositories.base import BaseRepository


class PaymentRepository(BaseRepository[Payment]):
    """Repository for Payment model operations with IDOR protection."""

    def __init__(self, db: AsyncSession):
        """Initialize Payment repository."""
        super().__init__(db, Payment)

    async def get_by_id_with_relations(
        self,
        payment_id: int,
        unit_id: Optional[int] = None
    ) -> Optional[Payment]:
        """
        Get payment by ID with all related data.

        Args:
            payment_id: Payment ID
            unit_id: Filter by lead.unit_id (for IDOR protection)

        Returns:
            Payment with relations or None
        """
        query = (
            select(Payment)
            .join(Invoice)
            .join(Fee)
            .join(models.AdmissionProfile)
            .join(models.Lead)
            .options(
                joinedload(Payment.invoice).joinedload(Invoice.fee),
                joinedload(Payment.method),
                joinedload(Payment.intent),
                joinedload(Payment.created_by),
                joinedload(Payment.verified_by),
                selectinload(Payment.transactions),
            )
            .where(Payment.id == payment_id)
        )

        # IDOR Filter
        if unit_id is not None:
            query = query.where(models.Lead.unit_id == unit_id)

        result = await self.db.execute(query)
        return result.scalars().first()

    async def get_for_update(
        self,
        payment_id: int,
        unit_id: Optional[int] = None,
    ) -> Optional[Payment]:
        """Get a payment with a pessimistic row lock (SELECT FOR UPDATE).

        Used by refund creation to serialize concurrent requests against the
        same payment: the second request blocks until the first commits, then
        re-reads the committed-refund total and cannot over-commit. No nullable
        joinedloads (FOR UPDATE can't apply to the nullable side of an outer
        join); only the row's own columns (amount/status) are needed.
        """
        query = (
            select(Payment)
            .join(Invoice)
            .join(Fee)
            .join(models.AdmissionProfile)
            .join(models.Lead)
            .where(Payment.id == payment_id)
            .with_for_update(of=Payment)
        )
        if unit_id is not None:
            query = query.where(models.Lead.unit_id == unit_id)

        result = await self.db.execute(query)
        return result.scalars().first()

    async def get_by_invoice_id(
        self,
        invoice_id: int,
        unit_id: Optional[int] = None,
        status: Optional[str] = None
    ) -> List[Payment]:
        """
        Get all payments for an invoice.

        Args:
            invoice_id: Invoice ID
            unit_id: Filter by lead.unit_id (for IDOR protection)
            status: Optional filter by payment status

        Returns:
            List of payments
        """
        query = (
            select(Payment)
            .join(Invoice)
            .join(Fee)
            .join(models.AdmissionProfile)
            .join(models.Lead)
            .options(
                joinedload(Payment.method),
                joinedload(Payment.created_by),
            )
            .where(Payment.invoice_id == invoice_id)
        )

        # IDOR Filter
        if unit_id is not None:
            query = query.where(models.Lead.unit_id == unit_id)

        if status is not None:
            query = query.where(Payment.status == status)

        query = query.order_by(Payment.created_at.desc())

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_pending_verification(
        self,
        unit_id: Optional[int] = None,
        skip: int = 0,
        limit: int = 50
    ) -> Tuple[List[Payment], int]:
        """
        Get payments pending verification (maker-checker workflow).

        Args:
            unit_id: Filter by lead.unit_id (for IDOR protection)
            skip: Number of records to skip
            limit: Maximum records to return

        Returns:
            Tuple of (List of pending payments, total_count)
        """
        base_conditions = [
            Payment.status == PaymentStatusEnum.pending.value,
            Payment.intent_id.is_(None),  # Manual payments only
        ]

        # IDOR Filter
        if unit_id is not None:
            base_conditions.append(models.Lead.unit_id == unit_id)

        # Count query
        count_query = (
            select(func.count(Payment.id))
            .join(Invoice)
            .join(Fee)
            .join(models.AdmissionProfile)
            .join(models.Lead)
            .where(and_(*base_conditions))
        )
        count_result = await self.db.execute(count_query)
        total = count_result.scalar() or 0

        # Data query
        data_query = (
            select(Payment)
            .join(Invoice)
            .join(Fee)
            .join(models.AdmissionProfile)
            .join(models.Lead)
            .options(
                joinedload(Payment.invoice).joinedload(Invoice.fee),
                joinedload(Payment.method),
                joinedload(Payment.created_by),
            )
            .where(and_(*base_conditions))
            .offset(skip)
            .limit(limit)
            .order_by(Payment.created_at.asc())  # Oldest first
        )

        result = await self.db.execute(data_query)
        payments = list(result.scalars().all())

        return payments, total

    async def get_filtered(
        self,
        skip: int = 0,
        limit: int = 50,
        unit_id: Optional[int] = None,
        **filters
    ) -> List[Payment]:
        """
        Get filtered list of payments with pagination.

        Args:
            skip: Number of records to skip
            limit: Maximum records to return
            unit_id: Filter by lead.unit_id (for IDOR protection)
            **filters: Filter parameters (status, invoice_id, method_id)

        Returns:
            List of Payment instances
        """
        query = (
            select(Payment)
            .join(Invoice)
            .join(Fee)
            .join(models.AdmissionProfile)
            .join(models.Lead)
            .options(
                joinedload(Payment.invoice),
                joinedload(Payment.method),
                joinedload(Payment.created_by),
            )
            .offset(skip)
            .limit(limit)
        )

        # IDOR Filter
        if unit_id is not None:
            query = query.where(models.Lead.unit_id == unit_id)

        if filters.get("status"):
            query = query.where(Payment.status == filters["status"])

        if filters.get("invoice_id"):
            query = query.where(Payment.invoice_id == filters["invoice_id"])

        if filters.get("method_id"):
            query = query.where(Payment.method_id == filters["method_id"])

        if filters.get("created_by_id"):
            query = query.where(Payment.created_by_id == filters["created_by_id"])

        query = query.order_by(Payment.created_at.desc())

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_filtered_with_count(
        self,
        skip: int = 0,
        limit: int = 50,
        unit_id: Optional[int] = None,
        statuses: Optional[List[str]] = None,
        invoice_id: Optional[int] = None,
        method_id: Optional[int] = None,
    ) -> Tuple[List[Payment], int]:
        """
        Get filtered list of payments with pagination AND total count.

        Args:
            skip: Number of records to skip
            limit: Maximum records to return
            unit_id: Filter by lead.unit_id (for IDOR protection)
            statuses: List of statuses to filter
            invoice_id: Filter by invoice ID
            method_id: Filter by payment method ID

        Returns:
            Tuple of (List of Payment instances, total_count)
        """
        base_conditions = []

        # IDOR Filter
        if unit_id is not None:
            base_conditions.append(models.Lead.unit_id == unit_id)

        if statuses and len(statuses) > 0:
            base_conditions.append(Payment.status.in_(statuses))

        if invoice_id:
            base_conditions.append(Payment.invoice_id == invoice_id)

        if method_id:
            base_conditions.append(Payment.method_id == method_id)

        # Count query
        count_query = (
            select(func.count(Payment.id))
            .join(Invoice)
            .join(Fee)
            .join(models.AdmissionProfile)
            .join(models.Lead)
        )
        if base_conditions:
            count_query = count_query.where(and_(*base_conditions))

        count_result = await self.db.execute(count_query)
        total = count_result.scalar() or 0

        # Data query
        data_query = (
            select(Payment)
            .join(Invoice)
            .join(Fee)
            .join(models.AdmissionProfile)
            .join(models.Lead)
            .options(
                joinedload(Payment.invoice).joinedload(Invoice.fee).joinedload(
                    Fee.admission_profile
                ).joinedload(models.AdmissionProfile.lead),
                joinedload(Payment.method),
                joinedload(Payment.created_by),
            )
            .offset(skip)
            .limit(limit)
            .order_by(Payment.created_at.desc())
        )
        if base_conditions:
            data_query = data_query.where(and_(*base_conditions))

        result = await self.db.execute(data_query)
        payments = list(result.scalars().all())

        return payments, total

    async def check_self_approval(
        self,
        payment_id: int,
        verifier_id: int
    ) -> bool:
        """
        Check if verifier is trying to approve their own payment.

        Args:
            payment_id: Payment ID
            verifier_id: User ID attempting to verify

        Returns:
            True if self-approval attempt (should be blocked)
        """
        query = (
            select(Payment.created_by_id)
            .where(Payment.id == payment_id)
        )
        result = await self.db.execute(query)
        created_by_id = result.scalar()

        return created_by_id == verifier_id

    async def get_active_payment_methods(
        self,
        is_online: Optional[bool] = None
    ) -> List[PaymentMethod]:
        """
        Get active payment methods, optionally filtered by online/offline.

        Args:
            is_online: Filter by online (True) or offline (False) methods

        Returns:
            List of active PaymentMethod instances
        """
        query = (
            select(PaymentMethod)
            .where(PaymentMethod.is_active.is_(True))
            .order_by(PaymentMethod.display_order)
        )

        if is_online is not None:
            query = query.where(PaymentMethod.is_online == is_online)

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_total_refunds_for_payment(
        self,
        payment_id: int
    ) -> Decimal:
        """
        Get the total committed refund amount for a payment.

        Counts every non-rejected request (pending + approved + refunded) so
        that open requests are *reserved* against the payment. Used to enforce
        ``total_committed_refunds <= payment.amount`` — this prevents creating
        a second open refund whose amount would exceed what remains once the
        already-open requests are processed (Finance Phase 1 F2).

        Args:
            payment_id: Payment ID

        Returns:
            Total committed (non-rejected) refund amount
        """
        query = (
            select(func.coalesce(func.sum(RefundRequest.amount), 0))
            .where(
                and_(
                    RefundRequest.payment_id == payment_id,
                    RefundRequest.status != RefundStatusEnum.rejected.value
                )
            )
        )
        result = await self.db.execute(query)
        return Decimal(result.scalar() or 0)


class PaymentIntentRepository(BaseRepository[PaymentIntent]):
    """Repository for PaymentIntent model operations."""

    def __init__(self, db: AsyncSession):
        """Initialize PaymentIntent repository."""
        super().__init__(db, PaymentIntent)

    async def get_by_id_with_relations(
        self,
        intent_id: int,
        unit_id: Optional[int] = None
    ) -> Optional[PaymentIntent]:
        """
        Get payment intent by ID with all related data.

        Args:
            intent_id: PaymentIntent ID
            unit_id: Filter by lead.unit_id (for IDOR protection)

        Returns:
            PaymentIntent with relations or None
        """
        query = (
            select(PaymentIntent)
            .join(Invoice)
            .join(Fee)
            .join(models.AdmissionProfile)
            .join(models.Lead)
            .options(
                joinedload(PaymentIntent.invoice).joinedload(Invoice.fee),
                joinedload(PaymentIntent.method),
                joinedload(PaymentIntent.payment),
            )
            .where(PaymentIntent.id == intent_id)
        )

        # IDOR Filter
        if unit_id is not None:
            query = query.where(models.Lead.unit_id == unit_id)

        result = await self.db.execute(query)
        return result.scalars().first()

    async def get_by_gateway_ref(
        self,
        gateway_ref: str
    ) -> Optional[PaymentIntent]:
        """
        Get payment intent by gateway reference.

        Used for processing gateway callbacks.

        Args:
            gateway_ref: Gateway transaction reference

        Returns:
            PaymentIntent or None
        """
        query = (
            select(PaymentIntent)
            .options(
                joinedload(PaymentIntent.invoice),
                joinedload(PaymentIntent.method),
            )
            .where(PaymentIntent.gateway_ref == gateway_ref)
        )

        result = await self.db.execute(query)
        return result.scalars().first()

    async def get_by_idempotency_key(
        self,
        idempotency_key: str,
        invoice_id: int
    ) -> Optional[PaymentIntent]:
        """
        Get payment intent by idempotency key and invoice.

        Used to prevent duplicate intent creation.

        Args:
            idempotency_key: Client-provided idempotency key
            invoice_id: Invoice ID

        Returns:
            PaymentIntent or None
        """
        query = (
            select(PaymentIntent)
            .where(
                and_(
                    PaymentIntent.idempotency_key == idempotency_key,
                    PaymentIntent.invoice_id == invoice_id
                )
            )
        )

        result = await self.db.execute(query)
        return result.scalars().first()

    async def get_expired_intents(
        self,
        before_datetime: Optional[datetime] = None
    ) -> List[PaymentIntent]:
        """
        Get expired payment intents for cleanup.

        Args:
            before_datetime: Consider expired before this time (default: now)

        Returns:
            List of expired intents
        """
        check_time = before_datetime or datetime.now(timezone.utc)

        query = (
            select(PaymentIntent)
            .where(
                and_(
                    PaymentIntent.expires_at < check_time,
                    PaymentIntent.status.in_([
                        PaymentIntentStatusEnum.created.value,
                        PaymentIntentStatusEnum.pending.value
                    ])
                )
            )
        )

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_filtered(
        self,
        skip: int = 0,
        limit: int = 50,
        unit_id: Optional[int] = None,
        **filters
    ) -> List[PaymentIntent]:
        """
        Get filtered list of payment intents with pagination.

        Args:
            skip: Number of records to skip
            limit: Maximum records to return
            unit_id: Filter by lead.unit_id (for IDOR protection)
            **filters: Filter parameters (status, invoice_id)

        Returns:
            List of PaymentIntent instances
        """
        query = (
            select(PaymentIntent)
            .join(Invoice)
            .join(Fee)
            .join(models.AdmissionProfile)
            .join(models.Lead)
            .options(
                joinedload(PaymentIntent.invoice),
                joinedload(PaymentIntent.method),
            )
            .offset(skip)
            .limit(limit)
        )

        # IDOR Filter
        if unit_id is not None:
            query = query.where(models.Lead.unit_id == unit_id)

        if filters.get("status"):
            query = query.where(PaymentIntent.status == filters["status"])

        if filters.get("invoice_id"):
            query = query.where(PaymentIntent.invoice_id == filters["invoice_id"])

        query = query.order_by(PaymentIntent.created_at.desc())

        result = await self.db.execute(query)
        return list(result.scalars().all())


class RefundRepository(BaseRepository[RefundRequest]):
    """Repository for RefundRequest model operations."""

    def __init__(self, db: AsyncSession):
        """Initialize RefundRequest repository."""
        super().__init__(db, RefundRequest)

    async def get_by_id_with_relations(
        self,
        refund_id: int,
        unit_id: Optional[int] = None
    ) -> Optional[RefundRequest]:
        """
        Get refund request by ID with all related data.

        Args:
            refund_id: RefundRequest ID
            unit_id: Filter by lead.unit_id (for IDOR protection)

        Returns:
            RefundRequest with relations or None
        """
        query = (
            select(RefundRequest)
            .join(Payment)
            .join(Invoice)
            .join(Fee)
            .join(models.AdmissionProfile)
            .join(models.Lead)
            .options(
                joinedload(RefundRequest.payment).joinedload(Payment.invoice),
                joinedload(RefundRequest.requested_by),
                joinedload(RefundRequest.approved_by),
            )
            .where(RefundRequest.id == refund_id)
        )

        # IDOR Filter
        if unit_id is not None:
            query = query.where(models.Lead.unit_id == unit_id)

        result = await self.db.execute(query)
        return result.scalars().first()

    async def get_for_update(
        self,
        refund_id: int,
        unit_id: Optional[int] = None,
    ) -> Optional[RefundRequest]:
        """Get a refund request with a pessimistic row lock (SELECT FOR UPDATE).

        Used by approve/reject/process so concurrent lifecycle ops on the same
        refund serialize: the second op blocks until the first commits, then
        re-reads the (now-changed) status and is rejected. Locks only the
        refund row (``of=RefundRequest``); payment→invoice are inner-joined and
        eager-loaded so process can update balances without a lazy load.
        """
        query = (
            select(RefundRequest)
            .join(Payment)
            .join(Invoice)
            .join(Fee)
            .join(models.AdmissionProfile)
            .join(models.Lead)
            .options(
                joinedload(RefundRequest.payment).joinedload(Payment.invoice),
            )
            .where(RefundRequest.id == refund_id)
            .with_for_update(of=RefundRequest)
        )
        if unit_id is not None:
            query = query.where(models.Lead.unit_id == unit_id)

        result = await self.db.execute(query)
        return result.scalars().first()

    async def get_pending_approval(
        self,
        unit_id: Optional[int] = None,
        skip: int = 0,
        limit: int = 50
    ) -> Tuple[List[RefundRequest], int]:
        """
        Get refund requests pending approval.

        Args:
            unit_id: Filter by lead.unit_id (for IDOR protection)
            skip: Number of records to skip
            limit: Maximum records to return

        Returns:
            Tuple of (List of pending refunds, total_count)
        """
        base_conditions = [
            RefundRequest.status == RefundStatusEnum.pending.value,
        ]

        # IDOR Filter
        if unit_id is not None:
            base_conditions.append(models.Lead.unit_id == unit_id)

        # Count query
        count_query = (
            select(func.count(RefundRequest.id))
            .join(Payment)
            .join(Invoice)
            .join(Fee)
            .join(models.AdmissionProfile)
            .join(models.Lead)
            .where(and_(*base_conditions))
        )
        count_result = await self.db.execute(count_query)
        total = count_result.scalar() or 0

        # Data query
        data_query = (
            select(RefundRequest)
            .join(Payment)
            .join(Invoice)
            .join(Fee)
            .join(models.AdmissionProfile)
            .join(models.Lead)
            .options(
                joinedload(RefundRequest.payment),
                joinedload(RefundRequest.requested_by),
            )
            .where(and_(*base_conditions))
            .offset(skip)
            .limit(limit)
            .order_by(RefundRequest.requested_at.asc())
        )

        result = await self.db.execute(data_query)
        refunds = list(result.scalars().all())

        return refunds, total

    async def get_filtered(
        self,
        skip: int = 0,
        limit: int = 50,
        unit_id: Optional[int] = None,
        **filters
    ) -> List[RefundRequest]:
        """
        Get filtered list of refund requests with pagination.

        Args:
            skip: Number of records to skip
            limit: Maximum records to return
            unit_id: Filter by lead.unit_id (for IDOR protection)
            **filters: Filter parameters (status, payment_id)

        Returns:
            List of RefundRequest instances
        """
        query = (
            select(RefundRequest)
            .join(Payment)
            .join(Invoice)
            .join(Fee)
            .join(models.AdmissionProfile)
            .join(models.Lead)
            .options(
                joinedload(RefundRequest.payment),
                joinedload(RefundRequest.requested_by),
            )
            .offset(skip)
            .limit(limit)
        )

        # IDOR Filter
        if unit_id is not None:
            query = query.where(models.Lead.unit_id == unit_id)

        if filters.get("status"):
            query = query.where(RefundRequest.status == filters["status"])

        if filters.get("payment_id"):
            query = query.where(RefundRequest.payment_id == filters["payment_id"])

        query = query.order_by(RefundRequest.created_at.desc())

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_filtered_with_count(
        self,
        skip: int = 0,
        limit: int = 50,
        unit_id: Optional[int] = None,
        statuses: Optional[List[str]] = None,
        payment_id: Optional[int] = None,
    ) -> Tuple[List[RefundRequest], int]:
        """Get filtered refund requests with total count and IDOR scope."""
        base_conditions = []

        if unit_id is not None:
            base_conditions.append(models.Lead.unit_id == unit_id)

        if statuses:
            base_conditions.append(RefundRequest.status.in_(statuses))

        if payment_id:
            base_conditions.append(RefundRequest.payment_id == payment_id)

        count_query = (
            select(func.count(RefundRequest.id))
            .join(Payment)
            .join(Invoice)
            .join(Fee)
            .join(models.AdmissionProfile)
            .join(models.Lead)
        )
        if base_conditions:
            count_query = count_query.where(and_(*base_conditions))

        count_result = await self.db.execute(count_query)
        total = count_result.scalar() or 0

        data_query = (
            select(RefundRequest)
            .join(Payment)
            .join(Invoice)
            .join(Fee)
            .join(models.AdmissionProfile)
            .join(models.Lead)
            .options(
                joinedload(RefundRequest.payment)
                .joinedload(Payment.invoice)
                .joinedload(Invoice.fee),
                joinedload(RefundRequest.requested_by),
                joinedload(RefundRequest.approved_by),
                joinedload(RefundRequest.rejected_by),
            )
            .offset(skip)
            .limit(limit)
            .order_by(RefundRequest.created_at.desc())
        )
        if base_conditions:
            data_query = data_query.where(and_(*base_conditions))

        result = await self.db.execute(data_query)
        return list(result.scalars().all()), total


class OverpaymentRepository(BaseRepository[OverpaymentRecord]):
    """Repository for OverpaymentRecord model operations."""

    def __init__(self, db: AsyncSession):
        """Initialize OverpaymentRecord repository."""
        super().__init__(db, OverpaymentRecord)

    async def get_by_id_with_relations(
        self,
        overpayment_id: int,
        unit_id: Optional[int] = None
    ) -> Optional[OverpaymentRecord]:
        """Get overpayment by ID with all related data and IDOR scope."""
        query = (
            select(OverpaymentRecord)
            .join(models.AdmissionProfile)
            .join(models.Lead)
            .options(
                joinedload(OverpaymentRecord.payment),
                joinedload(OverpaymentRecord.invoice).joinedload(Invoice.fee),
                joinedload(OverpaymentRecord.admission_profile).joinedload(
                    models.AdmissionProfile.lead
                ),
                joinedload(OverpaymentRecord.resolved_by),
                joinedload(OverpaymentRecord.applied_to_invoice),
                joinedload(OverpaymentRecord.refund_request),
            )
            .where(OverpaymentRecord.id == overpayment_id)
        )

        if unit_id is not None:
            query = query.where(models.Lead.unit_id == unit_id)

        result = await self.db.execute(query)
        return result.scalars().first()

    async def get_for_update(
        self,
        overpayment_id: int,
        unit_id: Optional[int] = None,
    ) -> Optional[OverpaymentRecord]:
        """Get an overpayment with a pessimistic row lock (SELECT FOR UPDATE).

        Used by every resolution path (apply/refund/write-off) so two concurrent
        requests cannot both pass the pending check and double-resolve the same
        liability (Finance Phase 1 F6). No nullable joinedloads here — FOR UPDATE
        cannot be applied to the nullable side of an outer join; relations are
        re-fetched separately by the service.
        """
        query = (
            select(OverpaymentRecord)
            .join(models.AdmissionProfile)
            .join(models.Lead)
            .where(OverpaymentRecord.id == overpayment_id)
            .with_for_update(of=OverpaymentRecord)
        )
        if unit_id is not None:
            query = query.where(models.Lead.unit_id == unit_id)

        result = await self.db.execute(query)
        return result.scalars().first()

    async def get_pending_for_profile(
        self,
        profile_id: int,
        unit_id: Optional[int] = None
    ) -> List[OverpaymentRecord]:
        """
        Get pending overpayments for an admission profile.

        Args:
            profile_id: Admission profile ID
            unit_id: Filter by lead.unit_id (for IDOR protection)

        Returns:
            List of pending overpayment records
        """
        query = (
            select(OverpaymentRecord)
            .join(models.AdmissionProfile)
            .join(models.Lead)
            .options(
                joinedload(OverpaymentRecord.payment),
                joinedload(OverpaymentRecord.invoice),
            )
            .where(
                and_(
                    OverpaymentRecord.admission_profile_id == profile_id,
                    OverpaymentRecord.status == OverpaymentStatusEnum.pending.value
                )
            )
        )

        # IDOR Filter
        if unit_id is not None:
            query = query.where(models.Lead.unit_id == unit_id)

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_filtered(
        self,
        skip: int = 0,
        limit: int = 50,
        unit_id: Optional[int] = None,
        **filters
    ) -> List[OverpaymentRecord]:
        """
        Get filtered list of overpayment records with pagination.

        Args:
            skip: Number of records to skip
            limit: Maximum records to return
            unit_id: Filter by lead.unit_id (for IDOR protection)
            **filters: Filter parameters (status, profile_id)

        Returns:
            List of OverpaymentRecord instances
        """
        query = (
            select(OverpaymentRecord)
            .join(models.AdmissionProfile)
            .join(models.Lead)
            .options(
                joinedload(OverpaymentRecord.payment),
                joinedload(OverpaymentRecord.invoice),
            )
            .offset(skip)
            .limit(limit)
        )

        # IDOR Filter
        if unit_id is not None:
            query = query.where(models.Lead.unit_id == unit_id)

        if filters.get("status"):
            query = query.where(OverpaymentRecord.status == filters["status"])

        if filters.get("profile_id"):
            query = query.where(
                OverpaymentRecord.admission_profile_id == filters["profile_id"]
            )

        query = query.order_by(OverpaymentRecord.created_at.desc())

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_filtered_with_count(
        self,
        skip: int = 0,
        limit: int = 50,
        unit_id: Optional[int] = None,
        statuses: Optional[List[str]] = None,
        profile_id: Optional[int] = None,
    ) -> Tuple[List[OverpaymentRecord], int]:
        """Get filtered overpayments with total count and IDOR scope."""
        base_conditions = []

        if unit_id is not None:
            base_conditions.append(models.Lead.unit_id == unit_id)

        if statuses:
            base_conditions.append(OverpaymentRecord.status.in_(statuses))

        if profile_id:
            base_conditions.append(OverpaymentRecord.admission_profile_id == profile_id)

        count_query = (
            select(func.count(OverpaymentRecord.id))
            .join(models.AdmissionProfile)
            .join(models.Lead)
        )
        if base_conditions:
            count_query = count_query.where(and_(*base_conditions))

        count_result = await self.db.execute(count_query)
        total = count_result.scalar() or 0

        data_query = (
            select(OverpaymentRecord)
            .join(models.AdmissionProfile)
            .join(models.Lead)
            .options(
                joinedload(OverpaymentRecord.payment),
                joinedload(OverpaymentRecord.invoice).joinedload(Invoice.fee),
                joinedload(OverpaymentRecord.admission_profile).joinedload(
                    models.AdmissionProfile.lead
                ),
                joinedload(OverpaymentRecord.resolved_by),
                joinedload(OverpaymentRecord.applied_to_invoice),
                joinedload(OverpaymentRecord.refund_request),
            )
            .offset(skip)
            .limit(limit)
            .order_by(OverpaymentRecord.created_at.desc())
        )
        if base_conditions:
            data_query = data_query.where(and_(*base_conditions))

        result = await self.db.execute(data_query)
        return list(result.scalars().all()), total


class PaymentTransactionRepository(BaseRepository[PaymentTransaction]):
    """Repository for PaymentTransaction model operations (audit trail)."""

    def __init__(self, db: AsyncSession):
        """Initialize PaymentTransaction repository."""
        super().__init__(db, PaymentTransaction)

    async def get_by_fee_id(
        self,
        fee_id: int,
        unit_id: Optional[int] = None
    ) -> List[PaymentTransaction]:
        """
        Get all transactions for a fee (audit trail).

        Args:
            fee_id: Fee ID
            unit_id: Filter by lead.unit_id (for IDOR protection)

        Returns:
            List of transactions ordered by created_at
        """
        query = (
            select(PaymentTransaction)
            .join(Fee)
            .join(models.AdmissionProfile)
            .join(models.Lead)
            .options(
                joinedload(PaymentTransaction.payment),
                joinedload(PaymentTransaction.performed_by),
            )
            .where(PaymentTransaction.fee_id == fee_id)
        )

        # IDOR Filter
        if unit_id is not None:
            query = query.where(models.Lead.unit_id == unit_id)

        query = query.order_by(PaymentTransaction.created_at)

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_filtered(
        self,
        skip: int = 0,
        limit: int = 50,
        unit_id: Optional[int] = None,
        **filters
    ) -> List[PaymentTransaction]:
        """
        Get filtered list of transactions with pagination.

        Args:
            skip: Number of records to skip
            limit: Maximum records to return
            unit_id: Filter by lead.unit_id (for IDOR protection)
            **filters: Filter parameters (fee_id, transaction_type, period_id)

        Returns:
            List of PaymentTransaction instances
        """
        query = (
            select(PaymentTransaction)
            .join(Fee)
            .join(models.AdmissionProfile)
            .join(models.Lead)
            .options(
                joinedload(PaymentTransaction.payment),
                joinedload(PaymentTransaction.performed_by),
            )
            .offset(skip)
            .limit(limit)
        )

        # IDOR Filter
        if unit_id is not None:
            query = query.where(models.Lead.unit_id == unit_id)

        if filters.get("fee_id"):
            query = query.where(PaymentTransaction.fee_id == filters["fee_id"])

        if filters.get("transaction_type"):
            query = query.where(
                PaymentTransaction.transaction_type == filters["transaction_type"]
            )

        if filters.get("period_id"):
            query = query.where(PaymentTransaction.period_id == filters["period_id"])

        query = query.order_by(PaymentTransaction.created_at.desc())

        result = await self.db.execute(query)
        return list(result.scalars().all())
