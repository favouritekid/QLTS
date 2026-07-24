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
    RefundRequest, RefundStatusEnum, RefundSourceEnum, TransactionTypeEnum,
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
from app.utils.admission_status import NON_PAYABLE_PROFILE_STATUSES
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


def reverse_payment_balances(
    *,
    invoice: Invoice,
    fee: Fee,
    amount: Decimal,
) -> Tuple[Decimal, Decimal]:
    """NGHỊCH ĐẢO ``apply_verified_payment_balances``: rút ``amount`` đã ghi khỏi
    invoice + fee (đảo/void 1 payment verified). Trả ``(fee_balance_before,
    fee_remaining)`` cho audit transaction.

    1 NGUỒN SỰ THẬT cho việc RÚT tiền: dùng chung bởi ``process_approved_refund``
    (hoàn lẻ) và void lô import bulk. paid về 0 → invoice 'issued' + paid_at=None (mở
    lại để thu tiếp), một phần → 'partial'; fee recompute status + bump version.
    """
    fee_balance_before = fee.final_amount - fee.paid_amount - fee.waived_amount
    invoice.paid_amount = (invoice.paid_amount or Decimal("0")) - amount
    if invoice.paid_amount <= 0:
        invoice.paid_amount = Decimal("0")
        invoice.status = InvoiceStatusEnum.issued.value
        invoice.paid_at = None
    elif invoice.paid_amount < invoice.amount:
        invoice.status = InvoiceStatusEnum.partial.value
        invoice.paid_at = None

    fee.paid_amount = fee.paid_amount - amount
    if fee.paid_amount < Decimal("0"):
        fee.paid_amount = Decimal("0")
    fee.version += 1
    fee_remaining = fee.final_amount - fee.paid_amount - fee.waived_amount
    if fee_remaining <= 0:
        fee.status = FeeStatusEnum.paid.value
    elif fee.paid_amount > 0:
        fee.status = FeeStatusEnum.partial.value
    else:
        fee.status = FeeStatusEnum.invoiced.value
    return fee_balance_before, fee_remaining


def assert_payable_target(
    fee: Optional[Fee],
    invoice: Optional[Invoice],
    profile: Optional["models.AdmissionProfile"],
    *,
    action: str,
) -> None:
    """Refuse to write money onto a dead target — the shared invariant the
    money-touching entries run right after locking the fee+invoice: manual
    record, manual verify, online callback, intent creation, and overpayment
    apply. The ONE exception is bulk import, which inlines an equivalent
    per-row check (routing each row through here would force a per-row
    ``selectinload``); keep the two in sync. Centralising it means a future
    entry point can reuse one guard instead of re-deriving the checks.
    ``action`` customises the Vietnamese message.

    Two dead-target classes are refused:
      1. **Cancelled fee/invoice** — the fee or its invoice was cancelled
         (``cancel_fee`` / cancel-invoice) after this operation started.
      2. **Non-payable profile** — the admission profile was withdrawn /
         rejected / is awaiting refund (``NON_PAYABLE_PROFILE_STATUSES``).
         The invoice can still be ``issued`` on a withdrawn profile (withdraw
         does not cancel fees today), so the invoice-status check alone would
         let money land on a profile that is on its way out.

    ``profile`` is REQUIRED (pass ``None`` explicitly when the fee has no
    admission-profile linkage) so every caller consciously resolves it — a
    silent default would re-open exactly the hole this guard closes.
    """
    if (fee is not None and fee.status == FeeStatusEnum.cancelled.value) or (
        invoice is not None
        and invoice.status == InvoiceStatusEnum.cancelled.value
    ):
        raise BusinessRuleViolation(
            f"Không thể {action}: khoản phí/hoá đơn đã bị huỷ."
        )
    if profile is not None and profile.status in NON_PAYABLE_PROFILE_STATUSES:
        raise BusinessRuleViolation(
            f"Không thể {action}: hồ sơ đã rút/từ chối/đang chờ hoàn tiền."
        )


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

        # P0: never even stage a pending payment on a withdrawn/rejected/
        # refund-pending profile. The invoice can still be `issued` on such a
        # profile (withdraw does not cancel fees), so the payable-status check
        # above is not enough — resolve the fee/profile ONCE here, refuse up
        # front, and reuse them for the notification payload below.
        fee = await self.db.get(Fee, invoice.fee_id) if invoice.fee_id else None
        profile = (
            await self._get_profile_for_fee(fee) if fee is not None else None
        )
        if fee is not None:
            assert_payable_target(fee, invoice, profile, action="ghi nhận thanh toán")

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

        # Notification payload (fee/profile already resolved above for the guard)
        _profile_id = fee.admission_profile_id if fee else None
        _lead_id = None
        _officer_id = None
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

        # Defense-in-depth: the fee/invoice may have been cancelled (cancel_fee)
        # AFTER this pending payment was recorded but BEFORE verification, or the
        # profile may have been withdrawn/rejected in the meantime. Refuse to
        # write money onto a dead target — the pending payment is left for
        # rejection. cancel_fee blocks while a pending payment exists, so the
        # cancelled-target case only fires for the narrow record-during-cancel
        # race; the profile check closes the withdrawn-but-fee-still-issued hole.
        profile = await self._get_profile_for_fee(fee)
        assert_payable_target(fee, invoice, profile, action="xác minh thanh toán")

        # Capture settled state BEFORE mutation (PR 5 transition detection)
        from app.services.fee_calculation_service import is_hk1_settled_fee
        was_hk1_settled = is_hk1_settled_fee(fee)

        # Update payment status
        now = datetime.now(timezone.utc)
        payment.status = PaymentStatusEnum.verified.value
        payment.verified_at = now
        payment.verified_by_id = verifier_id
        # Đổi ngành: snapshot ngành ghi nhận doanh thu (bất biến) TẠI verify —
        # tuition-only, đọc fee.resolved_major_id lúc này (xem
        # recognized_major_id_for_fee). Reprice sau này KHÔNG đụng field này.
        from app.services.fee_calculation_service import (
            recognized_major_id_for_fee,
        )
        payment.recognized_major_id = recognized_major_id_for_fee(fee)

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

        # ADR-002 PR 5: Sync lead only on HK1 SETTLED-state transition.
        # "Settled" = paid OR waived OR remaining<=0. A PARTIAL payment
        # (remaining>0) is NOT settled — lead stays at sts14, not sts10.
        # Only fires once: pre=not-settled -> post=settled.
        now_hk1_settled = is_hk1_settled_fee(fee)
        if not was_hk1_settled and now_hk1_settled:
            profile = await self._get_profile_for_fee(fee)
            if profile:
                from app.services.lead_admission_sync import sync_lead_tuition_paid
                await sync_lead_tuition_paid(
                    db=self.db,
                    profile=profile,
                    transaction_id=payment.reference_code or f"PAY-{payment.id}",
                    changed_by_user_id=verifier_id,
                    reason=f"HK1 tuition settled. Payment: {payment.amount:,.0f} VND",
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
        # is_hk1_settled transition) handles the pipeline projection;
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
        source: str = RefundSourceEnum.manual.value,
    ) -> Tuple["RefundRequest", Optional[Callable]]:
        """
        Request a refund for a verified payment.

        Args:
            payment_id: Payment to refund
            amount: Refund amount (max: payment amount - already refunded)
            reason: Refund reason (required)
            user_id: User requesting refund
            unit_id: Unit ID for IDOR protection
            source: Origin of the request (``manual`` by default). The withdraw
                orchestrator passes ``withdrawal`` and overpayment refunds pass
                ``overpayment`` so ``reject_open_refunds_for_profile`` can target
                only auto-filed withdrawal refunds.

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
            source=source,
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
        *,
        allow_withdrawal_pending: bool = False,
    ) -> Tuple["RefundRequest", Optional[Callable]]:
        """
        Reject a refund request.

        Args:
            refund_id: Refund request to reject
            reason: Rejection reason
            rejector_id: User rejecting refund
            unit_id: Unit ID for IDOR protection
            allow_withdrawal_pending: bypass the F1 guard below — set ONLY by
                ``reject_open_refunds_for_profile`` (cancel-withdrawal), which
                rejects ALL withdrawal refunds atomically and reverts the profile
                to draft, so the strand-in-``withdrawal_pending`` risk cannot
                occur there.

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

        # F1: a withdrawal-sourced refund on a profile still in
        # 'withdrawal_pending' must NOT be rejected individually — rejecting one
        # of several strands the profile forever (the finalize gate
        # sum_unrefunded_refundable_paid never reaches 0, money stays held). The
        # admin must use cancel-withdrawal, which rejects ALL withdrawal refunds
        # atomically and reverts the profile to draft.
        if (
            not allow_withdrawal_pending
            and refund.source == RefundSourceEnum.withdrawal.value
        ):
            _prof_status = (
                await self.db.execute(
                    select(models.AdmissionProfile.status)
                    .join(Fee, Fee.admission_profile_id == models.AdmissionProfile.id)
                    .join(Invoice, Invoice.fee_id == Fee.id)
                    .join(Payment, Payment.invoice_id == Invoice.id)
                    .where(Payment.id == refund.payment_id)
                )
            ).scalar_one_or_none()
            if _prof_status == "withdrawal_pending":
                raise BusinessRuleViolation(
                    "Không thể từ chối lẻ yêu cầu hoàn của hồ sơ đang rút "
                    "(sẽ kẹt hồ sơ ở trạng thái chờ hoàn). Dùng 'Hủy quy trình "
                    "rút' để hủy toàn bộ và đưa hồ sơ về nháp."
                )

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

    async def reject_open_refunds_for_profile(
        self,
        profile_id: int,
        *,
        reason: str,
        rejector_id: int,
    ) -> int:
        """Reject every open WITHDRAWAL-sourced refund of a profile (PR-B F1).

        Used when a withdrawal is cancelled/rolled back (``withdrawal_pending →
        draft``): the withdraw orchestrator auto-files refund requests, and if
        those are left open they could later be processed — returning money on a
        profile that has since been re-activated (draft → … → enrolled). This
        rejects the pending ones so they can never be processed. Only
        ``source='withdrawal'`` refunds are touched — a manual or overpayment
        refund is independently managed and left as-is.

        Raises ``BusinessRuleViolation`` if any refund is already APPROVED
        (awaiting processing): that cannot be silently cancelled here — the
        operator must process or reject it first — so the caller (cancel/rollback)
        surfaces a 400 instead of orphaning an in-flight refund. Returns the
        number of refunds rejected.
        """
        stmt = (
            select(RefundRequest)
            .join(Payment, RefundRequest.payment_id == Payment.id)
            .join(Invoice, Payment.invoice_id == Invoice.id)
            .join(Fee, Invoice.fee_id == Fee.id)
            .where(
                Fee.admission_profile_id == profile_id,
                # Only the refunds THIS withdraw orchestrator auto-filed. A
                # pre-existing manual (finance-created) or overpayment refund is
                # independently managed and must survive the withdrawal rollback
                # — rejecting it here would silently kill an unrelated refund and
                # (for overpayment) re-open a liability that was being settled.
                RefundRequest.source == RefundSourceEnum.withdrawal.value,
                RefundRequest.status.in_([
                    RefundStatusEnum.pending.value,
                    RefundStatusEnum.approved.value,
                ]),
            )
        )
        open_refunds = list((await self.db.execute(stmt)).scalars().all())

        if any(
            r.status == RefundStatusEnum.approved.value for r in open_refunds
        ):
            raise BusinessRuleViolation(
                "Không thể hủy quy trình rút: còn yêu cầu hoàn tiền ĐÃ DUYỆT "
                "đang chờ xử lý. Hãy xử lý (hoặc từ chối) yêu cầu hoàn đó trước."
            )

        count = 0
        for r in open_refunds:
            await self.reject_refund(
                r.id, reason=reason, rejector_id=rejector_id,
                allow_withdrawal_pending=True,  # F1: this IS the safe bulk path
            )
            count += 1
        return count

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

        # P1 (BV-3.5): re-check payment.status SAU khóa fee (void lô import khóa CÙNG
        # fee → serialize) + refresh (payment eager-load qua refund_repo joinedload có
        # thể STALE so với void vừa commit). Chặn hoàn payment đã bị ĐẢO (→'refunded')
        # → tránh trừ tiền 2 LẦN. KHÔNG lock payment ở đây (void khóa payment→fee; nếu
        # process khóa fee rồi payment sẽ ABBA-deadlock với void).
        await self.db.refresh(payment)
        if payment.status != PaymentStatusEnum.verified.value:
            raise BusinessRuleViolation(
                f"Chỉ hoàn được payment đã verified (hiện: {payment.status}). "
                "Payment có thể đã bị đảo qua void lô import."
            )

        # Update refund status
        refund.status = RefundStatusEnum.refunded.value
        refund.refunded_at = datetime.now(timezone.utc)
        refund.refund_reference = refund_reference

        # F2: snapshot BEFORE reverse — reverse_payment_balances recomputes
        # fee.status from paid_amount and reopens the invoice to 'issued'. If the
        # fee was already CANCELLED (e.g. a prior withdrawal finalize voided it),
        # processing this (overpayment/manual) refund would un-cancel it and
        # resurrect a phantom receivable on a withdrawn profile — re-void below.
        _fee_was_cancelled = fee.status == FeeStatusEnum.cancelled.value

        # Rút tiền khỏi invoice + fee — 1 NGUỒN SỰ THẬT chung với void lô import
        # (reverse_payment_balances). paid về 0 → invoice 'issued' (mở lại để thu),
        # fee recompute status + bump version.
        fee_balance_before, fee_balance_after = reverse_payment_balances(
            invoice=invoice, fee=fee, amount=refund.amount
        )
        if _fee_was_cancelled:
            # F2: keep the void — money still returned, but the fee/invoice stay
            # cancelled so no payable surface / "Còn nợ" reappears.
            fee.status = FeeStatusEnum.cancelled.value
            invoice.status = InvoiceStatusEnum.cancelled.value

        # Create audit transaction
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
        # PR-B (blocker 1): while a withdrawal is pending, the lead is HELD — do
        # NOT push it to sts18 here; the finalize below moves it to sts08 once
        # the refund completes. Refunds OUTSIDE a withdrawal still project sts18.
        if (
            fee.fee_type == "tuition"
            and fee.semester_no == 1
            and profile is not None
            and profile.status != "withdrawal_pending"
        ):
            from app.services.lead_admission_sync import sync_lead_tuition_refunded
            await sync_lead_tuition_refunded(
                db=self.db,
                profile=profile,
                refund_amount=str(refund.amount),
                changed_by_user_id=processor_id,
                reason=f"Tuition fee refunded: {refund.amount:,.0f} VND. Reason: {refund.reason}",
            )

        # PR-B: finalize the withdrawal once the LAST refundable payment is
        # returned. reverse_payment_balances above already decremented this
        # fee's paid_amount, so sum_unrefunded_refundable_paid reflects the
        # post-refund balance. Gate on status==withdrawal_pending so ordinary
        # refunds are untouched.
        withdraw_finalize_cb = None
        if profile is not None and profile.status == "withdrawal_pending":
            # F5: LOCK the profile row so two concurrent last-refunds serialize.
            # Without the lock each reads the other's not-yet-committed balance as
            # >0 → NEITHER finalizes → the profile is stranded in
            # withdrawal_pending with money fully refunded. Re-read status under
            # the lock (an admin cancel-withdrawal may have moved it to draft).
            locked_profile = (
                await self.db.execute(
                    select(models.AdmissionProfile)
                    .where(models.AdmissionProfile.id == profile.id)
                    .options(selectinload(models.AdmissionProfile.lead))
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if (
                locked_profile is not None
                and locked_profile.status == "withdrawal_pending"
            ):
                from app.repositories.fee_repository import FeeRepository
                _remaining = await FeeRepository(
                    self.db
                ).sum_unrefunded_refundable_paid(locked_profile.id)
                if _remaining <= 0:
                    import app.services.admission_service as admission_service
                    _processor = await self.db.get(models.User, processor_id)
                    profile, withdraw_finalize_cb = (
                        await admission_service._finalize_withdrawn(
                            self.db,
                            locked_profile,
                            _processor,
                            from_status="withdrawal_pending",
                            reason=(
                                "Hoàn tất hoàn tiền — chốt rút hồ sơ "
                                f"#{locked_profile.id}"
                            ),
                        )
                    )
                    # (Phantom-invoice cleanup lives INSIDE _finalize_withdrawn,
                    # gated on from_status=='withdrawal_pending' — Issue 1/#7.)

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
            # PR-B: run the withdraw-finalize bundle (milestone + APPLICATION/
            # LEAD status-changed) AFTER the refund notification, in the same
            # post-commit frame.
            if withdraw_finalize_cb is not None:
                await withdraw_finalize_cb()

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
        """Get admission profile for fee with Lead relationship loaded.

        RefundService's own copy — ``process_approved_refund`` resolves the
        profile via ``self``. Deliberately NOT shared with
        ``PaymentService._get_profile_for_fee``: they are the same body on two
        separate service classes, not a duplicate to dedupe.
        """
        query = (
            select(models.AdmissionProfile)
            .options(selectinload(models.AdmissionProfile.lead))
            .where(models.AdmissionProfile.id == fee.admission_profile_id)
        )
        result = await self.db.execute(query)
        return result.scalars().first()
