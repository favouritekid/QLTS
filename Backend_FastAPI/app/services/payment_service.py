# app/services/payment_service.py
"""
Payment Service - Business logic for manual payment processing.

Architecture Compliance:
- Service Layer: Pure business logic, no HTTP dependencies
- Security: IDOR checks via repository (unit_id filtering)
- Transactions: Services use db.add()/db.flush(), Router commits
- Error Handling: Raise custom exceptions (ResourceNotFoundError, etc.)

Payment Flow (Manual):
    record_payment() → status: pending
        ↓ (different user)
    verify_payment() → status: verified → updates invoice & fee
        ↓ (or)
    reject_payment() → status: rejected

Security (Section 3.9 C3):
- Maker-Checker: created_by_id != verified_by_id (DB constraint)
- Amount validation: amount > 0
- Invoice balance check: payment <= remaining balance
"""

from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Optional, Tuple, Callable
import structlog

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app import models
from app.models.finance import (
    Fee, Invoice, Payment, PaymentTransaction, PaymentMethod,
    PaymentStatusEnum, InvoiceStatusEnum, FeeStatusEnum,
    RefundRequest, RefundStatusEnum, TransactionTypeEnum,
    OverpaymentRecord, OverpaymentStatusEnum, ResolutionTypeEnum,
    PAYABLE_INVOICE_STATUSES,
)
from app.repositories.fee_repository import FeeRepository, InvoiceRepository
from app.repositories.payment_repository import (
    PaymentRepository,
    PaymentTransactionRepository,
)
from app.utils.exceptions import (
    ResourceNotFoundError,
    BadRequest,
    BusinessRuleViolation,
    ConflictError,
)
from app.config import settings

log = structlog.get_logger(__name__)


def apply_verified_payment_balances(
    *,
    invoice: Invoice,
    fee: Fee,
    amount: Decimal,
    now: datetime,
) -> Tuple[Decimal, Decimal]:
    """Áp money-math của 1 payment ĐÃ verified vào invoice + fee (cập nhật
    paid_amount/status + bump fee.version). Trả ``(fee_balance_before, fee_remaining)``
    cho audit transaction.

    NGUỒN SỰ THẬT DUY NHẤT cho việc "ghi 1 khoản verified vào invoice+fee", dùng
    chung bởi ``verify_payment`` (verify tay) và ``payment_import_service.
    auto_verify_payment`` (bulk import) — tránh 2 đường ghi tiền trôi dạt số liệu.

    Lưu ý: ``invoice.is_fully_paid`` GỒM penalty → trả đủ GỐC nhưng còn phạt thì
    invoice giữ 'partial'. fee chỉ lên 'partial' từ 'invoiced' (giữ nguyên các status
    khác như verify_payment lịch sử).
    """
    invoice.paid_amount = (invoice.paid_amount or Decimal("0")) + amount
    if invoice.is_fully_paid:
        invoice.status = InvoiceStatusEnum.paid.value
        invoice.paid_at = now
    elif invoice.paid_amount > 0:
        invoice.status = InvoiceStatusEnum.partial.value

    fee_balance_before = fee.final_amount - fee.paid_amount - fee.waived_amount
    fee.paid_amount = fee.paid_amount + amount
    fee.last_payment_at = now
    fee.version += 1
    fee_remaining = fee.final_amount - fee.paid_amount - fee.waived_amount
    if fee_remaining <= 0:
        fee.status = FeeStatusEnum.paid.value
    elif fee.paid_amount > 0 and fee.status == FeeStatusEnum.invoiced.value:
        fee.status = FeeStatusEnum.partial.value
    return fee_balance_before, fee_remaining


class PaymentService:
    """
    Service for manual payment processing with maker-checker workflow.

    Responsibilities:
    - Record manual payments (pending verification)
    - Verify payments (by different user)
    - Reject payments with reason
    - Update invoice and fee balances
    - Create audit trail (PaymentTransaction)
    """

    def __init__(self, db: AsyncSession):
        """Initialize with database session."""
        self.db = db
        self.fee_repo = FeeRepository(db)
        self.invoice_repo = InvoiceRepository(db)
        self.payment_repo = PaymentRepository(db)
        self.transaction_repo = PaymentTransactionRepository(db)

    # ==========================================================================
    # RECORD PAYMENT (MAKER)
    # ==========================================================================

    async def record_manual_payment(
        self,
        invoice_id: int,
        method_id: int,
        amount: Decimal,
        user_id: int,
        unit_id: Optional[int] = None,
        payment_date: Optional[datetime] = None,
        reference_code: Optional[str] = None,
        payer_name: Optional[str] = None,
        payer_account: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> Tuple[Payment, Optional[Callable]]:
        """
        Record a manual payment (cash, bank transfer, etc.).

        Creates a payment in 'pending' status that requires verification
        by a different user (maker-checker pattern).

        Args:
            invoice_id: Invoice to apply payment to
            method_id: Payment method ID
            amount: Payment amount
            user_id: User recording payment (maker)
            unit_id: Unit ID for IDOR protection
            payment_date: Actual payment date (default: now)
            reference_code: Bank/transaction reference
            payer_name: Name of payer
            payer_account: Payer account number
            notes: Additional notes

        Returns:
            Tuple of (Payment, post_commit_callback)

        Raises:
            ResourceNotFoundError: If invoice or payment method not found
            BusinessRuleViolation: If amount exceeds remaining balance
            BadRequest: If amount is not positive
        """
        # Validate amount
        if amount <= 0:
            raise BadRequest("Payment amount must be positive")

        # Get invoice with lock
        invoice = await self.invoice_repo.get_for_update(invoice_id, unit_id)
        if not invoice:
            raise ResourceNotFoundError("Invoice not found")

        # Check invoice status allows payment (canonical payable set)
        if invoice.status not in PAYABLE_INVOICE_STATUSES:
            raise BusinessRuleViolation(
                f"Cannot record payment for invoice with status '{invoice.status}'. "
                f"Allowed: {list(PAYABLE_INVOICE_STATUSES)}"
            )

        # Validate amount doesn't exceed remaining
        remaining = invoice.remaining_amount
        if amount > remaining:
            raise BusinessRuleViolation(
                f"Payment amount ({amount}) exceeds remaining balance ({remaining})"
            )

        # Validate payment method
        method = await self._get_payment_method(method_id)
        if not method:
            raise ResourceNotFoundError("Payment method not found")

        if not method.is_active:
            raise BadRequest(f"Payment method '{method.name}' is not active")

        # Create payment (pending status)
        payment = Payment(
            invoice_id=invoice_id,
            method_id=method_id,
            amount=amount,
            reference_code=reference_code,
            payer_name=payer_name,
            payer_account=payer_account,
            status=PaymentStatusEnum.pending.value,
            payment_date=payment_date or datetime.now(timezone.utc),
            created_by_id=user_id,
            notes=notes,
        )

        self.db.add(payment)
        await self.db.flush()
        await self.db.refresh(payment)

        log.info(
            "payment_recorded",
            payment_id=payment.id,
            invoice_id=invoice_id,
            amount=str(amount),
            method=method.code,
            created_by=user_id,
        )

        # Resolve data for notification while session is active
        fee = await self.db.get(Fee, invoice.fee_id) if invoice.fee_id else None
        _profile_id = fee.admission_profile_id if fee else None
        _lead_id = None
        _officer_id = None
        if fee:
            profile = await self._get_profile_for_fee(fee)
            if profile:
                _lead_id = profile.lead_id
                if hasattr(profile, 'lead') and profile.lead:
                    _officer_id = profile.lead.assigned_officer_id

        _notify_payload = {
            "payment_id": payment.id,
            "invoice_id": invoice_id,
            "fee_id": fee.id if fee else None,
            "amount": str(amount),
            "payment_type": fee.fee_type if fee else "unknown",
            "admission_profile_id": _profile_id,
            "lead_id": _lead_id,
            "unit_id": unit_id,
            "user_id": _officer_id or user_id,
            "actor_id": user_id,
        }
        _db = self.db
        # Snapshot rooms pre-commit: profile may be unloaded after session close,
        # and fail-closed guard requires non-empty rooms for sensitive events.
        from app.services.notification_dispatcher import rooms_for_admission
        _rooms = rooms_for_admission(profile) if fee and profile else None

        async def post_commit():
            from app.services.notification_dispatcher import safe_dispatch
            from app.core.events import SystemEvents

            await safe_dispatch(
                db=_db,
                event=SystemEvents.PAYMENT_RECEIVED,
                payload=_notify_payload,
                rooms=_rooms,
            )

        return payment, post_commit

    # ==========================================================================
    # VERIFY PAYMENT (CHECKER)
    # ==========================================================================

    async def verify_payment(
        self,
        payment_id: int,
        verifier_id: int,
        unit_id: Optional[int] = None,
    ) -> Tuple[Payment, Optional[Callable]]:
        """
        Verify a pending payment (checker in maker-checker pattern).

        Verification:
        1. Validates verifier != creator (C3 rule)
        2. Updates payment status to 'verified'
        3. Updates invoice paid_amount
        4. Updates fee paid_amount
        5. Creates audit transaction

        Args:
            payment_id: Payment to verify
            verifier_id: User verifying payment (must be different from creator)
            unit_id: Unit ID for IDOR protection

        Returns:
            Tuple of (Payment, post_commit_callback)

        Raises:
            ResourceNotFoundError: If payment not found
            BusinessRuleViolation: If self-approval or not pending
        """
        payment = await self.payment_repo.get_by_id_with_relations(payment_id, unit_id)
        if not payment:
            raise ResourceNotFoundError("Payment not found")

        # Check payment is pending
        if payment.status != PaymentStatusEnum.pending.value:
            raise BusinessRuleViolation(
                f"Can only verify pending payments. Current status: {payment.status}"
            )

        # Manual-only: a gateway/online payment (intent_id set) is confirmed by
        # the provider callback (payment_intent_service.process_callback), never
        # by the maker-checker path. Verifying it by hand would record money the
        # gateway has not confirmed.
        if payment.intent_id is not None:
            raise BusinessRuleViolation(
                "Online payments are confirmed by the payment gateway, not "
                "manually."
            )

        # C3: No self-approval
        if payment.created_by_id == verifier_id:
            raise BusinessRuleViolation(
                "Cannot verify your own payment (maker-checker violation)"
            )

        # Get invoice with lock for balance update
        invoice = await self.invoice_repo.get_for_update(payment.invoice_id, unit_id)
        if not invoice:
            raise ResourceNotFoundError("Invoice not found")

        # Get fee with lock for balance update
        fee = await self.fee_repo.get_for_update(invoice.fee_id, unit_id)
        if not fee:
            raise ResourceNotFoundError("Fee not found")

        # Capture cleared state BEFORE mutation (PR 5 transition detection)
        from app.services.fee_calculation_service import is_hk1_cleared
        was_hk1_cleared = is_hk1_cleared(
            fee.fee_type, fee.semester_no, fee.status, fee.paid_amount
        )

        # Update payment status
        now = datetime.now(timezone.utc)
        payment.status = PaymentStatusEnum.verified.value
        payment.verified_at = now
        payment.verified_by_id = verifier_id

        # Apply money-math to invoice + fee (shared 1 nguồn sự thật với bulk
        # auto-verify) → fee_balance_before / fee_remaining cho audit transaction.
        fee_balance_before, fee_remaining = apply_verified_payment_balances(
            invoice=invoice, fee=fee, amount=payment.amount, now=now
        )

        # Create audit transaction
        transaction = PaymentTransaction(
            payment_id=payment.id,
            fee_id=fee.id,
            transaction_type=TransactionTypeEnum.payment.value,
            amount=payment.amount,
            balance_before=fee_balance_before,
            balance_after=fee_remaining,
            external_reference=payment.reference_code,
            performed_by_id=verifier_id,
            notes=f"Payment verified. Invoice: {invoice.invoice_number}",
        )
        self.db.add(transaction)

        await self.db.flush()

        # ADR-002 PR 5: Sync lead only on HK1 cleared-state transition.
        # "Cleared" = paid OR waived OR (partial + paid_amount > 0).
        # Only fires once: pre=not-cleared -> post=cleared.
        now_hk1_cleared = is_hk1_cleared(
            fee.fee_type, fee.semester_no, fee.status, fee.paid_amount
        )
        if not was_hk1_cleared and now_hk1_cleared:
            profile = await self._get_profile_for_fee(fee)
            if profile:
                from app.services.lead_admission_sync import sync_lead_tuition_paid
                await sync_lead_tuition_paid(
                    db=self.db,
                    profile=profile,
                    transaction_id=payment.reference_code or f"PAY-{payment.id}",
                    changed_by_user_id=verifier_id,
                    reason=f"HK1 tuition cleared. Payment: {payment.amount:,.0f} VND",
                )

        log.info(
            "payment_verified",
            payment_id=payment_id,
            invoice_id=invoice.id,
            fee_id=fee.id,
            amount=str(payment.amount),
            verifier_id=verifier_id,
            fee_remaining=str(fee_remaining),
        )

        # Resolve lead_id while session is still active
        profile = await self._get_profile_for_fee(fee)
        _lead_id = profile.lead_id if profile else None

        # Resolve lead's assigned officer for notification recipient
        _officer_id = None
        if profile and hasattr(profile, 'lead') and profile.lead:
            _officer_id = profile.lead.assigned_officer_id

        # ADR-002 D10: Under the per-semester model, each Fee is one semester.
        # fee_remaining <= 0 means "this semester's fee is fully paid", not
        # "all tuition fully paid". The lead sync above (gated via
        # is_hk1_cleared transition) handles the pipeline projection;
        # this notification payload is semester-scoped by construction.
        _notify_payload = {
            "payment_id": payment.id,
            "invoice_id": invoice.id,
            "fee_id": fee.id,
            "amount": str(payment.amount),
            "verified_by_id": verifier_id,
            "verified_at": (
                payment.verified_at.isoformat()
                if payment.verified_at
                else datetime.now(timezone.utc).isoformat()
            ),
            "admission_profile_id": fee.admission_profile_id,
            "lead_id": _lead_id,
            "unit_id": unit_id,
            # SpecificUsersResolver: notify lead's officer
            "user_id": _officer_id or verifier_id,
        }
        _db = self.db
        # Snapshot rooms pre-commit for scoped domain emit.
        from app.services.notification_dispatcher import rooms_for_admission
        _rooms = rooms_for_admission(profile) if profile else None

        _fee_fully_paid = fee_remaining <= 0
        _fee_fully_paid_payload = {
            "fee_id": fee.id,
            "amount": str(fee.final_amount),
            "semester_no": fee.semester_no,
            "admission_profile_id": fee.admission_profile_id,
            "lead_id": _lead_id,
            "unit_id": unit_id,
            "user_id": _officer_id or verifier_id,
        } if _fee_fully_paid else None

        async def post_commit():
            from app.services.notification_dispatcher import safe_dispatch
            from app.core.events import SystemEvents

            await safe_dispatch(
                db=_db,
                event=SystemEvents.PAYMENT_VERIFIED,
                payload=_notify_payload,
                rooms=_rooms,
            )

            if _fee_fully_paid_payload:
                await safe_dispatch(
                    db=_db,
                    event=SystemEvents.FEE_FULLY_PAID,
                    payload=_fee_fully_paid_payload,
                    rooms=_rooms,
                )

        return payment, post_commit

    async def reject_payment(
        self,
        payment_id: int,
        reason: str,
        rejector_id: int,
        unit_id: Optional[int] = None,
    ) -> Tuple[Payment, Optional[Callable]]:
        """
        Reject a pending payment.

        Args:
            payment_id: Payment to reject
            reason: Rejection reason (required)
            rejector_id: User rejecting payment
            unit_id: Unit ID for IDOR protection

        Returns:
            Tuple of (Payment, post_commit_callback)

        Raises:
            ResourceNotFoundError: If payment not found
            BusinessRuleViolation: If not pending
        """
        payment = await self.payment_repo.get_by_id_with_relations(payment_id, unit_id)
        if not payment:
            raise ResourceNotFoundError("Payment not found")

        if payment.status != PaymentStatusEnum.pending.value:
            raise BusinessRuleViolation(
                f"Can only reject pending payments. Current status: {payment.status}"
            )

        # Manual-only: a gateway/online payment (intent_id set) is settled by the
        # provider callback, not the maker-checker path (mirrors verify_payment).
        if payment.intent_id is not None:
            raise BusinessRuleViolation(
                "Online payments are settled by the payment gateway, not "
                "manually."
            )

        if not reason or not reason.strip():
            raise BadRequest("Rejection reason is required")

        # Update payment status
        payment.status = PaymentStatusEnum.rejected.value
        payment.rejected_at = datetime.now(timezone.utc)
        payment.rejected_by_id = rejector_id
        payment.rejection_reason = reason

        await self.db.flush()

        log.info(
            "payment_rejected",
            payment_id=payment_id,
            reason=reason,
            rejector_id=rejector_id,
        )

        # Build PAYMENT_REJECTED notification payload while session is
        # still active. payment.invoice.fee is joinedloaded by
        # get_by_id_with_relations (payment_repository.py:64-86), so no
        # extra queries are needed to reach the fee. The profile lookup
        # gives us the lead_id for scoping and admission_profile_id for
        # the payload.
        _fee = payment.invoice.fee if payment.invoice else None
        _profile = await self._get_profile_for_fee(_fee) if _fee else None
        _lead_id = _profile.lead_id if _profile else None

        _notify_payload = {
            "payment_id": payment.id,
            "invoice_id": payment.invoice_id,
            "fee_id": _fee.id if _fee else None,
            "amount": str(payment.amount),
            "rejection_reason": reason,
            "rejected_by_id": rejector_id,
            "created_by_id": payment.created_by_id,
            "admission_profile_id": _fee.admission_profile_id if _fee else None,
            "lead_id": _lead_id,
            "unit_id": unit_id,
            # SpecificUsersResolver: notify the maker who recorded the payment
            "user_id": payment.created_by_id,
        }
        _db = self.db
        # Snapshot rooms pre-commit for scoped domain emit.
        from app.services.notification_dispatcher import rooms_for_admission
        _rooms = rooms_for_admission(_profile) if _profile else None

        async def post_commit():
            from app.services.notification_dispatcher import safe_dispatch
            from app.core.events import SystemEvents
            await safe_dispatch(
                db=_db,
                event=SystemEvents.PAYMENT_REJECTED,
                payload=_notify_payload,
                rooms=_rooms,
            )

        return payment, post_commit

    # ==========================================================================
    # PAYMENT RETRIEVAL
    # ==========================================================================

    async def get_payment(
        self,
        payment_id: int,
        unit_id: Optional[int] = None,
    ) -> Payment:
        """Get payment by ID with all relations."""
        payment = await self.payment_repo.get_by_id_with_relations(payment_id, unit_id)
        if not payment:
            raise ResourceNotFoundError("Payment not found")
        return payment

    async def get_payments_for_invoice(
        self,
        invoice_id: int,
        unit_id: Optional[int] = None,
        status: Optional[str] = None,
    ) -> List[Payment]:
        """Get all payments for an invoice."""
        return await self.payment_repo.get_by_invoice_id(invoice_id, unit_id, status)

    async def get_pending_verification(
        self,
        unit_id: Optional[int] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> Tuple[List[Payment], int]:
        """
        Get payments pending verification.

        Returns payments that need maker-checker approval.
        """
        return await self.payment_repo.get_pending_verification(
            unit_id=unit_id,
            skip=skip,
            limit=limit,
        )

    async def get_transactions_for_fee(
        self,
        fee_id: int,
        unit_id: Optional[int] = None,
    ) -> List[PaymentTransaction]:
        """Get all transactions for a fee (audit trail)."""
        return await self.transaction_repo.get_by_fee_id(fee_id, unit_id)

    # ==========================================================================
    # OVERPAYMENT HANDLING
    # ==========================================================================

    async def check_overpayment(
        self,
        invoice_id: int,
        payment_amount: Decimal,
        unit_id: Optional[int] = None,
    ) -> Tuple[bool, Decimal]:
        """
        Check if payment would result in overpayment.

        Args:
            invoice_id: Invoice being paid
            payment_amount: Payment amount
            unit_id: Unit ID for IDOR protection

        Returns:
            Tuple of (is_overpayment, overpayment_amount)
        """
        invoice = await self.invoice_repo.get_by_id_with_relations(invoice_id, unit_id)
        if not invoice:
            raise ResourceNotFoundError("Invoice not found")

        remaining = invoice.remaining_amount
        if payment_amount > remaining:
            return True, payment_amount - remaining
        return False, Decimal("0")

    # ==========================================================================
    # HELPER METHODS
    # ==========================================================================

    async def _get_payment_method(
        self,
        method_id: int,
    ) -> Optional[PaymentMethod]:
        """Get payment method by ID."""
        query = select(PaymentMethod).where(PaymentMethod.id == method_id)
        result = await self.db.execute(query)
        return result.scalars().first()

    async def _get_profile_for_fee(
        self,
        fee: Fee,
    ) -> Optional[models.AdmissionProfile]:
        """Get admission profile for fee with Lead relationship loaded."""
        query = (
            select(models.AdmissionProfile)
            .options(selectinload(models.AdmissionProfile.lead))
            .where(models.AdmissionProfile.id == fee.admission_profile_id)
        )
        result = await self.db.execute(query)
        return result.scalars().first()

    async def _create_transaction(
        self,
        payment: Payment,
        fee: Fee,
        transaction_type: TransactionTypeEnum,
        user_id: int,
        notes: Optional[str] = None,
    ) -> PaymentTransaction:
        """Create audit transaction record."""
        balance_before = fee.final_amount - fee.paid_amount - fee.waived_amount

        # For payments, amount is positive (reduces balance)
        # For refunds, amount is negative (increases balance)
        if transaction_type == TransactionTypeEnum.payment:
            balance_after = balance_before - payment.amount
        elif transaction_type == TransactionTypeEnum.refund:
            balance_after = balance_before + payment.amount
        else:
            balance_after = balance_before

        transaction = PaymentTransaction(
            payment_id=payment.id,
            fee_id=fee.id,
            transaction_type=transaction_type.value,
            amount=payment.amount,
            balance_before=balance_before,
            balance_after=balance_after,
            external_reference=payment.reference_code,
            performed_by_id=user_id,
            notes=notes,
        )

        self.db.add(transaction)
        await self.db.flush()
        return transaction


class RefundService:
    """
    Service for refund request handling.

    Separate from PaymentService to keep responsibilities clear.
    Handles refund request workflow with approval.
    """

    def __init__(self, db: AsyncSession):
        """Initialize with database session."""
        self.db = db
        # Import here to avoid circular import
        from app.repositories.payment_repository import (
            RefundRepository,
            PaymentRepository,
        )
        self.refund_repo = RefundRepository(db)
        self.payment_repo = PaymentRepository(db)
        self.fee_repo = FeeRepository(db)

    async def request_refund(
        self,
        payment_id: int,
        amount: Decimal,
        reason: str,
        user_id: int,
        unit_id: Optional[int] = None,
    ) -> Tuple["RefundRequest", Optional[Callable]]:
        """
        Request a refund for a verified payment.

        Args:
            payment_id: Payment to refund
            amount: Refund amount (max: payment amount - already refunded)
            reason: Refund reason (required)
            user_id: User requesting refund
            unit_id: Unit ID for IDOR protection

        Returns:
            Tuple of (RefundRequest, post_commit_callback)

        Raises:
            ResourceNotFoundError: If payment not found
            BusinessRuleViolation: If amount exceeds available
        """
        # Lock the source payment row BEFORE computing committed refunds so two
        # concurrent requests on the same payment serialize: the second blocks
        # here until the first commits, then sees its reserved amount (race fix).
        payment = await self.payment_repo.get_for_update(payment_id, unit_id)
        if not payment:
            raise ResourceNotFoundError("Payment not found")

        if payment.status != PaymentStatusEnum.verified.value:
            raise BusinessRuleViolation(
                f"Can only refund verified payments. Current status: {payment.status}"
            )

        if amount <= 0:
            raise BadRequest("Refund amount must be positive")

        # Reserve already-committed refunds (pending + approved + refunded) so a
        # second open request cannot over-commit the payment (Finance Phase 1 F2).
        total_committed = await self.payment_repo.get_total_refunds_for_payment(
            payment_id
        )
        available = payment.amount - total_committed

        if amount > available:
            raise BusinessRuleViolation(
                f"Refund amount ({amount}) exceeds available ({available}). "
                f"Already committed (pending/approved/refunded): {total_committed}"
            )

        if not reason or not reason.strip():
            raise BadRequest("Refund reason is required")

        # Create refund request
        refund = RefundRequest(
            payment_id=payment_id,
            amount=amount,
            reason=reason,
            status=RefundStatusEnum.pending.value,
            requested_by_id=user_id,
            requested_at=datetime.now(timezone.utc),
        )

        self.db.add(refund)
        await self.db.flush()
        await self.db.refresh(refund)

        log.info(
            "refund_requested",
            refund_id=refund.id,
            payment_id=payment_id,
            amount=str(amount),
            user_id=user_id,
        )

        return refund, None

    async def approve_refund(
        self,
        refund_id: int,
        approver_id: int,
        unit_id: Optional[int] = None,
    ) -> Tuple["RefundRequest", Optional[Callable]]:
        """
        Approve a refund request.

        Args:
            refund_id: Refund request to approve
            approver_id: User approving refund
            unit_id: Unit ID for IDOR protection

        Returns:
            Tuple of (RefundRequest, post_commit_callback)
        """
        # Lock the refund row so concurrent lifecycle ops serialize and re-read
        # status after acquiring the lock (race fix).
        refund = await self.refund_repo.get_for_update(refund_id, unit_id)
        if not refund:
            raise ResourceNotFoundError("Refund request not found")

        if refund.status != RefundStatusEnum.pending.value:
            raise BusinessRuleViolation(
                f"Can only approve pending refunds. Current status: {refund.status}"
            )

        if refund.requested_by_id == approver_id:
            raise BusinessRuleViolation(
                "Cannot approve your own refund request (maker-checker violation)"
            )

        # Update refund status
        refund.status = RefundStatusEnum.approved.value
        refund.approved_by_id = approver_id
        refund.approved_at = datetime.now(timezone.utc)

        await self.db.flush()

        log.info(
            "refund_approved",
            refund_id=refund_id,
            approver_id=approver_id,
        )

        return refund, None

    async def reject_refund(
        self,
        refund_id: int,
        reason: str,
        rejector_id: int,
        unit_id: Optional[int] = None,
    ) -> Tuple["RefundRequest", Optional[Callable]]:
        """
        Reject a refund request.

        Args:
            refund_id: Refund request to reject
            reason: Rejection reason
            rejector_id: User rejecting refund
            unit_id: Unit ID for IDOR protection

        Returns:
            Tuple of (RefundRequest, post_commit_callback)
        """
        # Lock the refund row so concurrent lifecycle ops serialize and re-read
        # status after acquiring the lock (race fix).
        refund = await self.refund_repo.get_for_update(refund_id, unit_id)
        if not refund:
            raise ResourceNotFoundError("Refund request not found")

        if refund.status != RefundStatusEnum.pending.value:
            raise BusinessRuleViolation(
                f"Can only reject pending refunds. Current status: {refund.status}"
            )

        if not reason or not reason.strip():
            raise BadRequest("Rejection reason is required")

        # Update refund status
        refund.status = RefundStatusEnum.rejected.value
        refund.rejected_by_id = rejector_id
        refund.rejected_at = datetime.now(timezone.utc)
        refund.rejection_reason = reason

        await self.db.flush()

        log.info(
            "refund_rejected",
            refund_id=refund_id,
            reason=reason,
            rejector_id=rejector_id,
        )

        return refund, None

    async def process_approved_refund(
        self,
        refund_id: int,
        processor_id: int,
        refund_reference: Optional[str] = None,
        unit_id: Optional[int] = None,
    ) -> Tuple["RefundRequest", Optional[Callable]]:
        """
        Process an approved refund (execute the actual refund).

        This updates the payment status and fee balances.

        Args:
            refund_id: Approved refund to process
            processor_id: User processing refund
            refund_reference: External bank/gateway reference for the refund
            unit_id: Unit ID for IDOR protection

        Returns:
            Tuple of (RefundRequest, post_commit_callback)
        """
        # Lock the refund row FIRST so a second concurrent process blocks here,
        # then re-reads status after the first commits and sees 'refunded' →
        # raises below instead of double-processing (race fix).
        refund = await self.refund_repo.get_for_update(refund_id, unit_id)
        if not refund:
            raise ResourceNotFoundError("Refund request not found")

        if refund.status != RefundStatusEnum.approved.value:
            raise BusinessRuleViolation(
                f"Can only process approved refunds. Current status: {refund.status}"
            )

        payment = refund.payment
        invoice = payment.invoice
        fee = await self.fee_repo.get_for_update(invoice.fee_id, unit_id)
        if not fee:
            raise ResourceNotFoundError("Fee not found")

        # Capture balance before
        fee_balance_before = fee.final_amount - fee.paid_amount - fee.waived_amount

        # Update refund status
        refund.status = RefundStatusEnum.refunded.value
        refund.refunded_at = datetime.now(timezone.utc)
        refund.refund_reference = refund_reference

        # Update invoice paid_amount (decrease). A full refund (paid back to 0)
        # must return the invoice to 'issued', not leave it 'partial' with 0 paid
        # (which would block re-collection — can_record_payment keys on 'issued').
        invoice.paid_amount = invoice.paid_amount - refund.amount
        if invoice.paid_amount <= 0:
            invoice.paid_amount = Decimal("0")
            invoice.status = InvoiceStatusEnum.issued.value
            invoice.paid_at = None
        elif invoice.paid_amount < invoice.amount:
            invoice.status = InvoiceStatusEnum.partial.value
            invoice.paid_at = None

        # Update fee paid_amount (decrease)
        fee.paid_amount = fee.paid_amount - refund.amount
        fee.version += 1

        # Update fee status
        if fee.paid_amount < fee.final_amount - fee.waived_amount:
            if fee.paid_amount > 0:
                fee.status = FeeStatusEnum.partial.value
            else:
                fee.status = FeeStatusEnum.invoiced.value

        # Create audit transaction
        fee_balance_after = fee.final_amount - fee.paid_amount - fee.waived_amount
        transaction = PaymentTransaction(
            payment_id=payment.id,
            fee_id=fee.id,
            transaction_type=TransactionTypeEnum.refund.value,
            amount=-refund.amount,  # Negative for refund
            balance_before=fee_balance_before,
            balance_after=fee_balance_after,
            performed_by_id=processor_id,
            notes=f"Refund processed. Reason: {refund.reason}",
        )
        self.db.add(transaction)

        await self.db.flush()

        # F4: if this refund resolves a tracked overpayment, close that liability
        # now that the money-out is actually processed. The overpayment was kept
        # 'pending' (linked via refund_request_id) so a rejected/abandoned refund
        # leaves it re-resolvable; only a *processed* refund marks it 'refunded'.
        linked_overpayment = (
            await self.db.execute(
                select(OverpaymentRecord)
                .where(OverpaymentRecord.refund_request_id == refund.id)
                .with_for_update(of=OverpaymentRecord)
            )
        ).scalars().first()
        if (
            linked_overpayment is not None
            and linked_overpayment.status == OverpaymentStatusEnum.pending.value
        ):
            linked_overpayment.status = OverpaymentStatusEnum.refunded.value
            linked_overpayment.resolution_type = ResolutionTypeEnum.refund.value
            linked_overpayment.resolved_at = datetime.now(timezone.utc)
            linked_overpayment.resolved_by_id = processor_id
            await self.db.flush()

        # Hoist profile resolution BEFORE the tuition-only branch.
        # The notification payload below needs lead_id/admission_profile_id
        # regardless of fee_type; scoping the profile lookup inside the
        # tuition branch would leave `profile` unbound for non-tuition
        # refunds and crash with UnboundLocalError when we build the
        # payload. Same query is used by the inline lead sync below.
        profile = await self._get_profile_for_fee(fee)

        # ADR-002 PR 5 (D9): Only HK1 refund projects into admission pipeline.
        if fee.fee_type == "tuition" and fee.semester_no == 1 and profile is not None:
            from app.services.lead_admission_sync import sync_lead_tuition_refunded
            await sync_lead_tuition_refunded(
                db=self.db,
                profile=profile,
                refund_amount=str(refund.amount),
                changed_by_user_id=processor_id,
                reason=f"Tuition fee refunded: {refund.amount:,.0f} VND. Reason: {refund.reason}",
            )

        log.info(
            "refund_processed",
            refund_id=refund_id,
            payment_id=payment.id,
            amount=str(refund.amount),
            processor_id=processor_id,
        )

        # Build REFUND_PROCESSED notification payload. Recipients are the
        # assigned officer (when resolved) plus the processor. Finance
        # staff group and external applicant notification are deferred
        # (PR B + Zalo ZNS Phase 2 respectively — see events.py docstring).
        _officer_id: Optional[int] = None
        if profile is not None and getattr(profile, "lead", None) is not None:
            _officer_id = profile.lead.assigned_officer_id
        _recipient_ids = list({
            uid for uid in [_officer_id, processor_id] if uid
        })

        _notify_payload = {
            "refund_id": refund.id,
            "payment_id": payment.id,
            "invoice_id": invoice.id,
            "fee_id": fee.id,
            "amount": str(refund.amount),
            "reason": refund.reason,
            "processor_id": processor_id,
            "admission_profile_id": fee.admission_profile_id,
            "lead_id": profile.lead_id if profile is not None else None,
            "unit_id": unit_id,
            # SpecificUsersResolver: notify officer + processor.
            "user_ids": _recipient_ids,
        }
        _db = self.db
        # Snapshot rooms pre-commit for scoped domain emit.
        from app.services.notification_dispatcher import rooms_for_admission
        _rooms = rooms_for_admission(profile) if profile is not None else None

        async def post_commit():
            from app.services.notification_dispatcher import safe_dispatch
            from app.core.events import SystemEvents
            await safe_dispatch(
                db=_db,
                event=SystemEvents.REFUND_PROCESSED,
                payload=_notify_payload,
                rooms=_rooms,
            )

        return refund, post_commit

    async def get_refund(
        self,
        refund_id: int,
        unit_id: Optional[int] = None,
    ) -> "RefundRequest":
        """Get refund by ID with IDOR scope."""
        refund = await self.refund_repo.get_by_id_with_relations(refund_id, unit_id)
        if not refund:
            raise ResourceNotFoundError("Refund request not found")
        return refund

    async def list_refunds(
        self,
        skip: int = 0,
        limit: int = 50,
        unit_id: Optional[int] = None,
        statuses: Optional[List[str]] = None,
        payment_id: Optional[int] = None,
    ) -> Tuple[List["RefundRequest"], int]:
        """List refund requests with total count."""
        return await self.refund_repo.get_filtered_with_count(
            skip=skip,
            limit=limit,
            unit_id=unit_id,
            statuses=statuses,
            payment_id=payment_id,
        )

    async def _get_profile_for_fee(
        self,
        fee: Fee,
    ) -> Optional[models.AdmissionProfile]:
        """Get admission profile for fee with Lead relationship loaded."""
        query = (
            select(models.AdmissionProfile)
            .options(selectinload(models.AdmissionProfile.lead))
            .where(models.AdmissionProfile.id == fee.admission_profile_id)
        )
        result = await self.db.execute(query)
        return result.scalars().first()
