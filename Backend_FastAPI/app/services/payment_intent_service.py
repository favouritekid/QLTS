# app/services/payment_intent_service.py
"""
PaymentIntent Service - Business logic for online payment processing.

Architecture Compliance:
- Service Layer: Pure business logic, no HTTP dependencies
- Security: IDOR checks via repository (unit_id filtering)
- Transactions: Services use db.add()/db.flush(), Router commits
- Error Handling: Raise custom exceptions (ResourceNotFoundError, etc.)

2-Phase Payment Pattern:
    1. create_intent() → status: created → returns pay_url
    2. process_callback() → status: completed → creates Payment record

Status Flow:
    created → pending → completed
                ↓
             failed/expired/cancelled

Security (Section 3.9 C1):
- Verify gateway signature before processing callback
- Match amount exactly with intent amount
- Verify gateway_ref matches our records
- Idempotency key prevents duplicate intents
"""

from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple, Callable
import structlog

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app import models
from app.models.finance import (
    Fee, Invoice, Payment, PaymentIntent, PaymentTransaction, PaymentMethod,
    PaymentIntentStatusEnum, PaymentStatusEnum, InvoiceStatusEnum,
    FeeStatusEnum, TransactionTypeEnum,
)
from app.gateways.base import BaseGatewayAdapter, GatewayStatusEnum, GatewayResponse
from app.repositories.fee_repository import FeeRepository, InvoiceRepository
from app.repositories.payment_repository import (
    PaymentRepository,
    PaymentIntentRepository,
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

# Default intent expiration (15 minutes)
DEFAULT_INTENT_EXPIRATION_MINUTES = 15


class PaymentIntentService:
    """
    Service for online payment intent management.

    Responsibilities:
    - Create payment intents with idempotency
    - Generate gateway payment URLs
    - Process gateway callbacks
    - Create Payment records on success
    - Handle expiration and cancellation
    """

    def __init__(self, db: AsyncSession):
        """Initialize with database session."""
        self.db = db
        self.fee_repo = FeeRepository(db)
        self.invoice_repo = InvoiceRepository(db)
        self.payment_repo = PaymentRepository(db)
        self.intent_repo = PaymentIntentRepository(db)
        self.transaction_repo = PaymentTransactionRepository(db)

        # Gateway adapters (registered dynamically)
        self._gateway_adapters: Dict[str, BaseGatewayAdapter] = {}

    def register_gateway(self, code: str, adapter: BaseGatewayAdapter) -> None:
        """Register a payment gateway adapter."""
        self._gateway_adapters[code] = adapter

    # ==========================================================================
    # CREATE INTENT
    # ==========================================================================

    async def create_intent(
        self,
        invoice_id: int,
        method_id: int,
        amount: Decimal,
        idempotency_key: str,
        return_url: str,
        unit_id: Optional[int] = None,
        expiration_minutes: int = DEFAULT_INTENT_EXPIRATION_MINUTES,
    ) -> Tuple[PaymentIntent, Optional[Callable]]:
        """
        Create a payment intent for online payment.

        Idempotency: If an intent with the same idempotency_key + invoice_id
        exists and is not terminal, returns the existing intent.

        Args:
            invoice_id: Invoice to pay
            method_id: Payment method (must be online gateway)
            amount: Payment amount
            idempotency_key: Client-provided UUID for idempotency
            return_url: URL to redirect after payment
            unit_id: Unit ID for IDOR protection
            expiration_minutes: Intent expiration time

        Returns:
            Tuple of (PaymentIntent, post_commit_callback)

        Raises:
            ResourceNotFoundError: If invoice or method not found
            BusinessRuleViolation: If amount exceeds remaining or invalid method
            BadRequest: If amount is not positive
        """
        # Validate amount
        if amount <= 0:
            raise BadRequest("Payment amount must be positive")

        if not idempotency_key:
            raise BadRequest("Idempotency key is required")

        # Check for existing intent with same idempotency key
        existing = await self.intent_repo.get_by_idempotency_key(
            idempotency_key, invoice_id
        )
        if existing:
            if not existing.is_terminal:
                log.info(
                    "intent_idempotency_hit",
                    intent_id=existing.id,
                    idempotency_key=idempotency_key,
                )
                return existing, None
            # Terminal intent - allow creating new one
            log.info(
                "intent_idempotency_terminal",
                old_intent_id=existing.id,
                old_status=existing.status,
            )

        # Get invoice
        invoice = await self.invoice_repo.get_by_id_with_relations(invoice_id, unit_id)
        if not invoice:
            raise ResourceNotFoundError("Invoice not found")

        # Check invoice status allows payment
        allowed_statuses = [
            InvoiceStatusEnum.issued.value,
            InvoiceStatusEnum.partial.value,
            InvoiceStatusEnum.overdue.value,
        ]
        if invoice.status not in allowed_statuses:
            raise BusinessRuleViolation(
                f"Cannot pay invoice with status '{invoice.status}'"
            )

        # Validate amount doesn't exceed remaining
        remaining = invoice.remaining_amount
        if amount > remaining:
            raise BusinessRuleViolation(
                f"Payment amount ({amount}) exceeds remaining balance ({remaining})"
            )

        # Get payment method
        method = await self._get_payment_method(method_id)
        if not method:
            raise ResourceNotFoundError("Payment method not found")

        if not method.is_active:
            raise BadRequest(f"Payment method '{method.name}' is not active")

        if not method.is_online:
            raise BadRequest(
                f"Payment method '{method.name}' is not an online payment method"
            )

        # Create intent
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=expiration_minutes)

        intent = PaymentIntent(
            invoice_id=invoice_id,
            method_id=method_id,
            amount=amount,
            currency="VND",
            idempotency_key=idempotency_key,
            status=PaymentIntentStatusEnum.created.value,
            return_url=return_url,
            expires_at=expires_at,
        )

        self.db.add(intent)
        await self.db.flush()
        await self.db.refresh(intent)

        # Generate gateway payment URL
        gateway_code = method.code
        if gateway_code in self._gateway_adapters:
            adapter = self._gateway_adapters[gateway_code]
            pay_url, gateway_ref = await adapter.create_payment_url(intent, return_url)
            intent.pay_url = pay_url
            intent.gateway_ref = gateway_ref
            intent.status = PaymentIntentStatusEnum.pending.value
            await self.db.flush()
        else:
            # No adapter - generate mock URL for testing
            intent.gateway_ref = f"MOCK-{intent.id}-{int(datetime.now().timestamp())}"
            intent.pay_url = f"https://payment.example.com/pay/{intent.gateway_ref}"
            log.warning(
                "gateway_adapter_not_found",
                gateway_code=gateway_code,
                using_mock=True,
            )

        log.info(
            "intent_created",
            intent_id=intent.id,
            invoice_id=invoice_id,
            amount=str(amount),
            method=method.code,
            expires_at=str(expires_at),
        )

        return intent, None

    async def create_or_get_intent(
        self,
        invoice_id: int,
        method_id: int,
        amount: Decimal,
        idempotency_key: str,
        return_url: Optional[str] = None,
        unit_id: Optional[int] = None,
    ) -> Tuple[PaymentIntent, bool]:
        """
        Create a new payment intent or return existing one.

        This is a wrapper for router use that returns (intent, is_existing).

        Args:
            invoice_id: Invoice to pay
            method_id: Payment method (must be online gateway)
            amount: Payment amount
            idempotency_key: Client-provided UUID for idempotency
            return_url: URL to redirect after payment
            unit_id: Unit ID for IDOR protection

        Returns:
            Tuple of (PaymentIntent, is_existing)
        """
        # Check for existing intent with same idempotency key
        existing = await self.intent_repo.get_by_idempotency_key(
            idempotency_key, invoice_id
        )
        if existing and not existing.is_terminal:
            return existing, True

        # Create new intent
        intent, _ = await self.create_intent(
            invoice_id=invoice_id,
            method_id=method_id,
            amount=amount,
            idempotency_key=idempotency_key,
            return_url=return_url or "",
            unit_id=unit_id,
        )

        return intent, False

    # ==========================================================================
    # PROCESS CALLBACK
    # ==========================================================================

    async def process_callback(
        self,
        gateway_code: str,
        callback_data: Dict[str, Any],
        unit_id: Optional[int] = None,
    ) -> Tuple[PaymentIntent, Optional[Payment], Optional[Callable]]:
        """
        Process gateway callback after payment attempt.

        Security (C1):
        1. Verify gateway signature
        2. Find intent by gateway_ref
        3. Validate amount matches
        4. Update intent status
        5. Create Payment record if successful

        Args:
            gateway_code: Gateway identifier (e.g., 'vnpay', 'momo')
            callback_data: Raw callback data from gateway
            unit_id: Unit ID for IDOR protection

        Returns:
            Tuple of (PaymentIntent, Payment or None, post_commit_callback)

        Raises:
            ResourceNotFoundError: If intent not found
            BusinessRuleViolation: If signature invalid or amount mismatch
        """
        # Get gateway adapter
        adapter = self._gateway_adapters.get(gateway_code)

        # Parse callback data
        if adapter:
            # Parse using adapter
            gateway_response = adapter.parse_callback(callback_data)
            gateway_ref = gateway_response.gateway_ref
            gateway_status = gateway_response.status
            callback_amount = gateway_response.amount

            # Verify signature using appropriate secret key
            if gateway_code == "vnpay":
                secret_key = settings.VNPAY_HASH_SECRET
            elif gateway_code == "momo":
                secret_key = settings.MOMO_SECRET_KEY
            else:
                secret_key = getattr(settings, f"GATEWAY_{gateway_code.upper()}_SECRET", "")

            if secret_key and not adapter.verify_signature(callback_data, secret_key):
                log.warning(
                    "callback_signature_invalid",
                    gateway_code=gateway_code,
                    gateway_ref=gateway_ref,
                )
                raise BusinessRuleViolation("Invalid gateway signature")
        else:
            # Mock parsing for testing
            gateway_ref = callback_data.get("gateway_ref") or callback_data.get("txn_ref")
            gateway_status_str = callback_data.get("status", "success")
            gateway_status = GatewayStatusEnum(gateway_status_str)
            callback_amount = Decimal(str(callback_data.get("amount", 0)))

        # Find intent by gateway_ref
        intent = await self.intent_repo.get_by_gateway_ref(gateway_ref)
        if not intent:
            log.warning(
                "callback_intent_not_found",
                gateway_ref=gateway_ref,
            )
            raise ResourceNotFoundError("Payment intent not found")

        # Check intent can process callback
        if not intent.can_process_callback:
            log.warning(
                "callback_intent_not_processable",
                intent_id=intent.id,
                status=intent.status,
                is_expired=intent.is_expired,
            )
            raise BusinessRuleViolation(
                f"Intent cannot process callback. Status: {intent.status}, "
                f"Expired: {intent.is_expired}"
            )

        # Verify amount matches (C1)
        if callback_amount != intent.amount:
            log.error(
                "callback_amount_mismatch",
                intent_id=intent.id,
                expected=str(intent.amount),
                received=str(callback_amount),
            )
            intent.status = PaymentIntentStatusEnum.failed.value
            intent.gateway_status = "amount_mismatch"
            intent.callback_received_at = datetime.now(timezone.utc)
            intent.callback_data = callback_data
            await self.db.flush()
            raise BusinessRuleViolation(
                f"Amount mismatch: expected {intent.amount}, received {callback_amount}"
            )

        # Update intent with callback data
        intent.callback_received_at = datetime.now(timezone.utc)
        intent.callback_data = callback_data
        intent.gateway_status = gateway_status.value
        intent.gateway_response = callback_data

        payment = None
        fee = None
        profile = None

        if gateway_status == GatewayStatusEnum.success:
            # Create verified payment (returns payment, fee, profile)
            payment, fee, profile = await self._create_payment_from_intent(
                intent, unit_id
            )
            intent.status = PaymentIntentStatusEnum.completed.value
            intent.completed_at = datetime.now(timezone.utc)
        elif gateway_status in [GatewayStatusEnum.failed, GatewayStatusEnum.expired]:
            intent.status = PaymentIntentStatusEnum.failed.value
        else:
            # Pending or other - keep as pending
            intent.status = PaymentIntentStatusEnum.pending.value

        await self.db.flush()

        log.info(
            "callback_processed",
            intent_id=intent.id,
            gateway_status=gateway_status.value,
            payment_id=payment.id if payment else None,
        )

        # Build PAYMENT_VERIFIED notification payload while the session is
        # still active. Dispatched from the post-commit closure below,
        # mirroring the manual verify_payment path at
        # payment_service.py:358-387. Only dispatched when an officer is
        # resolved for the lead — otherwise SpecificUsersResolver returns
        # an empty recipient list and zero notifications are silently
        # suppressed.
        _notify_payload: Optional[Dict[str, Any]] = None
        if payment is not None and fee is not None:
            _officer_id: Optional[int] = None
            if profile is not None and getattr(profile, "lead", None) is not None:
                _officer_id = profile.lead.assigned_officer_id
            _notify_payload = {
                "payment_id": payment.id,
                "invoice_id": intent.invoice_id,
                "fee_id": fee.id,
                "amount": str(intent.amount),
                "verified_by_id": None,  # auto-verified by gateway
                "verified_at": (
                    payment.verified_at.isoformat()
                    if payment.verified_at
                    else datetime.now(timezone.utc).isoformat()
                ),
                "admission_profile_id": fee.admission_profile_id,
                "lead_id": profile.lead_id if profile is not None else None,
                "unit_id": unit_id,
                "user_id": _officer_id,  # SpecificUsersResolver recipient
            }
        _db = self.db
        # Snapshot rooms pre-commit for scoped domain emit.
        from app.services.notification_dispatcher import _rooms_for_admission
        _rooms = _rooms_for_admission(profile) if profile is not None else None

        _fee_fully_paid_payload: Optional[Dict[str, Any]] = None
        if fee is not None and fee.is_fully_paid:
            _fee_fully_paid_payload = {
                "fee_id": fee.id,
                "amount": str(fee.final_amount),
                "semester_no": fee.semester_no,
                "admission_profile_id": fee.admission_profile_id,
                "lead_id": profile.lead_id if profile is not None else None,
                "unit_id": unit_id,
                "user_id": _officer_id,
            }

        async def post_commit():
            if _notify_payload is None or not _notify_payload.get("user_id"):
                return
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

        return intent, payment, post_commit

    async def process_gateway_callback(
        self,
        gateway_code: str,
        callback_data: Dict[str, Any],
    ) -> Tuple[Dict[str, Any], Optional[Callable]]:
        """
        Process gateway callback and return (result dict, post_commit callback).

        This is a simplified wrapper around process_callback for router use.
        The router must await the returned callback AFTER committing the
        business transaction, otherwise the PAYMENT_VERIFIED notification
        is silently dropped.

        Args:
            gateway_code: Gateway identifier (e.g., 'vnpay', 'momo')
            callback_data: Raw callback data from gateway

        Returns:
            Tuple of (result_dict, post_commit_callback_or_None). On error
            paths the callback is None because no dispatch is owed.
        """
        try:
            intent, payment, post_commit = await self.process_callback(
                gateway_code=gateway_code,
                callback_data=callback_data,
            )

            return {
                "success": payment is not None,
                "message": "Payment processed successfully" if payment else "Payment failed",
                "intent_id": intent.id,
                "payment_id": payment.id if payment else None,
                "status": intent.status,
            }, post_commit

        except ResourceNotFoundError as e:
            return {
                "success": False,
                "message": str(e),
                "intent_id": None,
            }, None
        except BusinessRuleViolation as e:
            return {
                "success": False,
                "message": str(e),
                "intent_id": None,
            }, None

    async def _create_payment_from_intent(
        self,
        intent: PaymentIntent,
        unit_id: Optional[int] = None,
    ) -> Tuple[Payment, "Fee", Optional["models.AdmissionProfile"]]:
        """
        Create Payment record from successful intent.

        Online payments are auto-verified (no maker-checker).

        Returns:
            Tuple of (payment, fee, profile_or_None). Profile is None when the
            fee has no admission_profile_id linkage. Callers use `fee` and
            `profile` for post-commit dispatch payload construction and lead
            pipeline sync (for tuition fees).
        """
        # Get invoice and fee with locks
        invoice = await self.invoice_repo.get_for_update(intent.invoice_id, unit_id)
        if not invoice:
            raise ResourceNotFoundError("Invoice not found")

        fee = await self.fee_repo.get_for_update(invoice.fee_id, unit_id)
        if not fee:
            raise ResourceNotFoundError("Fee not found")

        # Capture balance before
        fee_balance_before = fee.final_amount - fee.paid_amount - fee.waived_amount

        # Create payment (auto-verified for online payments).
        # Issue C fix: verified_by_id must be NULL, not the same as created_by_id,
        # otherwise chk_payment_no_self_approval fires. For the online path
        # there is no human checker — the gateway callback IS the verification.
        payment = Payment(
            invoice_id=intent.invoice_id,
            method_id=intent.method_id,
            intent_id=intent.id,
            amount=intent.amount,
            reference_code=intent.gateway_ref,
            status=PaymentStatusEnum.verified.value,  # Auto-verified
            payment_date=datetime.now(timezone.utc),
            verified_at=datetime.now(timezone.utc),
            created_by_id=1,   # System user for online payments
            verified_by_id=None,  # NULL: auto-verified by gateway, no human checker
        )

        self.db.add(payment)
        await self.db.flush()

        # Update invoice paid_amount
        invoice.paid_amount = invoice.paid_amount + intent.amount
        if invoice.is_fully_paid:
            invoice.status = InvoiceStatusEnum.paid.value
            invoice.paid_at = datetime.now(timezone.utc)
        elif invoice.paid_amount > 0:
            invoice.status = InvoiceStatusEnum.partial.value

        # ADR-002 PR 5: snapshot cleared state BEFORE fee mutation
        from app.services.fee_calculation_service import is_hk1_cleared
        was_hk1_cleared = is_hk1_cleared(
            fee.fee_type, fee.semester_no, fee.status, fee.paid_amount
        )

        # Update fee paid_amount
        fee.paid_amount = fee.paid_amount + intent.amount
        fee.last_payment_at = datetime.now(timezone.utc)
        fee.version += 1

        # Update fee status
        fee_remaining = fee.final_amount - fee.paid_amount - fee.waived_amount
        if fee_remaining <= 0:
            fee.status = FeeStatusEnum.paid.value
        elif fee.paid_amount > 0 and fee.status == FeeStatusEnum.invoiced.value:
            fee.status = FeeStatusEnum.partial.value

        # Create audit transaction
        transaction = PaymentTransaction(
            payment_id=payment.id,
            fee_id=fee.id,
            transaction_type=TransactionTypeEnum.payment.value,
            amount=intent.amount,
            balance_before=fee_balance_before,
            balance_after=fee_remaining,
            external_reference=intent.gateway_ref,
            gateway_response=intent.gateway_response,
            performed_by_id=1,  # System user
            notes=f"Online payment via {intent.method.code}. Invoice: {invoice.invoice_number}",
        )
        self.db.add(transaction)

        await self.db.flush()
        await self.db.refresh(payment)

        # Resolve admission profile (with lead eager-loaded) for post-commit
        # payload + lead sync. Mirrors payment_service._get_profile_for_fee
        # pattern; inlined here to avoid cross-service dependency.
        profile: Optional[models.AdmissionProfile] = None
        if fee.admission_profile_id:
            result = await self.db.execute(
                select(models.AdmissionProfile)
                .where(models.AdmissionProfile.id == fee.admission_profile_id)
                .options(selectinload(models.AdmissionProfile.lead))
            )
            profile = result.scalar_one_or_none()

        # ADR-002 PR 5: Sync lead only on HK1 cleared-state transition.
        now_hk1_cleared = is_hk1_cleared(
            fee.fee_type, fee.semester_no, fee.status, fee.paid_amount
        )
        if not was_hk1_cleared and now_hk1_cleared and profile is not None:
            from app.services.lead_admission_sync import sync_lead_tuition_paid
            await sync_lead_tuition_paid(
                db=self.db,
                profile=profile,
                transaction_id=payment.reference_code or f"PAY-{payment.id}",
                changed_by_user_id=1,
                reason=f"HK1 tuition cleared via online payment ({intent.method.code})",
            )

        return payment, fee, profile

    # ==========================================================================
    # INTENT LIFECYCLE
    # ==========================================================================

    async def cancel_intent(
        self,
        intent_id: int,
        reason: str,
        user_id: int,
        unit_id: Optional[int] = None,
    ) -> Tuple[PaymentIntent, Optional[Callable]]:
        """
        Cancel a payment intent.

        Can only cancel intents in created or pending status.

        Args:
            intent_id: Intent to cancel
            reason: Cancellation reason
            user_id: User cancelling
            unit_id: Unit ID for IDOR protection

        Returns:
            Tuple of (PaymentIntent, post_commit_callback)
        """
        intent = await self.intent_repo.get_by_id_with_relations(intent_id, unit_id)
        if not intent:
            raise ResourceNotFoundError("Payment intent not found")

        if intent.is_terminal:
            raise BusinessRuleViolation(
                f"Cannot cancel terminal intent. Status: {intent.status}"
            )

        intent.status = PaymentIntentStatusEnum.cancelled.value
        intent.gateway_response = {
            "cancelled_by": user_id,
            "reason": reason,
            "cancelled_at": datetime.now(timezone.utc).isoformat(),
        }

        await self.db.flush()

        log.info(
            "intent_cancelled",
            intent_id=intent_id,
            reason=reason,
            user_id=user_id,
        )

        return intent, None

    async def expire_intent(
        self,
        intent_id: int,
    ) -> PaymentIntent:
        """
        Mark an intent as expired.

        Called by scheduled job to expire old intents.
        """
        intent = await self.intent_repo.get_by_id_with_relations(intent_id)
        if not intent:
            raise ResourceNotFoundError("Payment intent not found")

        if intent.is_terminal:
            return intent  # Already terminal

        intent.status = PaymentIntentStatusEnum.expired.value
        await self.db.flush()

        log.info(
            "intent_expired",
            intent_id=intent_id,
        )

        return intent

    async def expire_old_intents(self) -> List[PaymentIntent]:
        """
        Expire all old intents (scheduled job).

        Returns list of expired intents.
        """
        expired_intents = await self.intent_repo.get_expired_intents()

        for intent in expired_intents:
            intent.status = PaymentIntentStatusEnum.expired.value

        await self.db.flush()

        if expired_intents:
            log.info(
                "intents_expired_batch",
                count=len(expired_intents),
            )

        return expired_intents

    # ==========================================================================
    # INTENT RETRIEVAL
    # ==========================================================================

    async def get_intent(
        self,
        intent_id: int,
        unit_id: Optional[int] = None,
    ) -> PaymentIntent:
        """Get payment intent by ID with all relations.

        Note: If the intent has expired but status is still 'created' or 'pending',
        the status is updated to 'expired' automatically.
        """
        intent = await self.intent_repo.get_by_id_with_relations(intent_id, unit_id)
        if not intent:
            raise ResourceNotFoundError("Payment intent not found")

        # Auto-expire stale intents on read
        if intent.is_expired and intent.status in (
            PaymentIntentStatusEnum.created.value,
            PaymentIntentStatusEnum.pending.value,
        ):
            intent.status = PaymentIntentStatusEnum.expired.value
            await self.db.flush()

        return intent

    async def get_intent_by_gateway_ref(
        self,
        gateway_ref: str,
    ) -> PaymentIntent:
        """Get payment intent by gateway reference."""
        intent = await self.intent_repo.get_by_gateway_ref(gateway_ref)
        if not intent:
            raise ResourceNotFoundError("Payment intent not found")
        return intent

    async def get_intents_for_invoice(
        self,
        invoice_id: int,
        unit_id: Optional[int] = None,
    ) -> List[PaymentIntent]:
        """Get all payment intents for an invoice."""
        return await self.intent_repo.get_filtered(
            unit_id=unit_id,
            invoice_id=invoice_id,
        )

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


# ==========================================================================
# GATEWAY REGISTRATION HELPER
# ==========================================================================

def register_default_gateways(service: PaymentIntentService) -> None:
    """
    Register default payment gateways from settings.

    Call this during application startup to configure gateways.

    Usage:
        from app.services.payment_intent_service import (
            PaymentIntentService,
            register_default_gateways
        )

        service = PaymentIntentService(db)
        register_default_gateways(service)
    """
    from app.gateways import VNPayAdapter, MoMoAdapter

    # Register VNPay if configured
    if settings.VNPAY_TMN_CODE and settings.VNPAY_HASH_SECRET:
        vnpay = VNPayAdapter(
            tmn_code=settings.VNPAY_TMN_CODE,
            hash_secret=settings.VNPAY_HASH_SECRET,
            payment_url=settings.VNPAY_PAYMENT_URL,
            api_url=settings.VNPAY_API_URL,
        )
        service.register_gateway("vnpay", vnpay)
        log.info("vnpay_gateway_registered")

    # Register MoMo if configured
    if settings.MOMO_PARTNER_CODE and settings.MOMO_SECRET_KEY:
        momo = MoMoAdapter(
            partner_code=settings.MOMO_PARTNER_CODE,
            access_key=settings.MOMO_ACCESS_KEY,
            secret_key=settings.MOMO_SECRET_KEY,
            endpoint=settings.MOMO_ENDPOINT,
        )
        service.register_gateway("momo", momo)
        log.info("momo_gateway_registered")
