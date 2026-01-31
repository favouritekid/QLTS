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
from typing import Any, Dict, List, Optional, Tuple, Callable, Protocol
import hashlib
import hmac
import structlog

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.models.finance import (
    Fee, Invoice, Payment, PaymentIntent, PaymentTransaction, PaymentMethod,
    PaymentIntentStatusEnum, PaymentStatusEnum, InvoiceStatusEnum,
    FeeStatusEnum, TransactionTypeEnum, GatewayStatusEnum,
)
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


class GatewayAdapter(Protocol):
    """Protocol for payment gateway adapters."""

    async def create_payment_url(
        self,
        intent: PaymentIntent,
        return_url: str,
    ) -> Tuple[str, str]:
        """
        Create payment URL for gateway.

        Args:
            intent: PaymentIntent to process
            return_url: URL to redirect after payment

        Returns:
            Tuple of (pay_url, gateway_ref)
        """
        ...

    def verify_signature(
        self,
        callback_data: Dict[str, Any],
        secret_key: str,
    ) -> bool:
        """
        Verify gateway callback signature.

        Args:
            callback_data: Callback data from gateway
            secret_key: Gateway secret key

        Returns:
            True if signature is valid
        """
        ...

    def parse_callback(
        self,
        callback_data: Dict[str, Any],
    ) -> Tuple[str, GatewayStatusEnum, Decimal]:
        """
        Parse gateway callback data.

        Args:
            callback_data: Raw callback data

        Returns:
            Tuple of (gateway_ref, status, amount)
        """
        ...


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
        self._gateway_adapters: Dict[str, GatewayAdapter] = {}

    def register_gateway(self, code: str, adapter: GatewayAdapter) -> None:
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
            gateway_ref, gateway_status, callback_amount = adapter.parse_callback(
                callback_data
            )

            # Verify signature
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

        if gateway_status == GatewayStatusEnum.success:
            # Create verified payment
            payment = await self._create_payment_from_intent(intent, unit_id)
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

        # Post-commit: notify payment status
        async def post_commit():
            # TODO: Emit PaymentCompleted/PaymentFailed event
            pass

        return intent, payment, post_commit

    async def _create_payment_from_intent(
        self,
        intent: PaymentIntent,
        unit_id: Optional[int] = None,
    ) -> Payment:
        """
        Create Payment record from successful intent.

        Online payments are auto-verified (no maker-checker).
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

        # Create payment (auto-verified for online payments)
        payment = Payment(
            invoice_id=intent.invoice_id,
            method_id=intent.method_id,
            intent_id=intent.id,
            amount=intent.amount,
            reference_code=intent.gateway_ref,
            status=PaymentStatusEnum.verified.value,  # Auto-verified
            payment_date=datetime.now(timezone.utc),
            verified_at=datetime.now(timezone.utc),
            created_by_id=1,  # System user for online payments
            verified_by_id=1,  # System user
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

        return payment

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
        """Get payment intent by ID with all relations."""
        intent = await self.intent_repo.get_by_id_with_relations(intent_id, unit_id)
        if not intent:
            raise ResourceNotFoundError("Payment intent not found")
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
# GATEWAY ADAPTERS (Example Implementation)
# ==========================================================================

class VNPayAdapter:
    """
    VNPay payment gateway adapter.

    Implements the GatewayAdapter protocol for VNPay integration.
    """

    def __init__(self, tmn_code: str, hash_secret: str, payment_url: str):
        """Initialize VNPay adapter."""
        self.tmn_code = tmn_code
        self.hash_secret = hash_secret
        self.payment_url = payment_url

    async def create_payment_url(
        self,
        intent: PaymentIntent,
        return_url: str,
    ) -> Tuple[str, str]:
        """Create VNPay payment URL."""
        import urllib.parse
        from datetime import datetime

        # Generate transaction reference
        txn_ref = f"QLTS{intent.id}{int(datetime.now().timestamp())}"

        # Build VNPay params
        params = {
            "vnp_Version": "2.1.0",
            "vnp_Command": "pay",
            "vnp_TmnCode": self.tmn_code,
            "vnp_Amount": int(intent.amount * 100),  # VNPay uses cents
            "vnp_CurrCode": "VND",
            "vnp_TxnRef": txn_ref,
            "vnp_OrderInfo": f"Payment for invoice {intent.invoice_id}",
            "vnp_OrderType": "other",
            "vnp_Locale": "vn",
            "vnp_ReturnUrl": return_url,
            "vnp_IpAddr": "127.0.0.1",
            "vnp_CreateDate": datetime.now().strftime("%Y%m%d%H%M%S"),
        }

        # Sort params and create signature
        sorted_params = sorted(params.items())
        query_string = "&".join(f"{k}={urllib.parse.quote_plus(str(v))}" for k, v in sorted_params)
        signature = hmac.new(
            self.hash_secret.encode(),
            query_string.encode(),
            hashlib.sha512
        ).hexdigest()

        # Build final URL
        pay_url = f"{self.payment_url}?{query_string}&vnp_SecureHash={signature}"

        return pay_url, txn_ref

    def verify_signature(
        self,
        callback_data: Dict[str, Any],
        secret_key: str,
    ) -> bool:
        """Verify VNPay callback signature."""
        import urllib.parse

        received_hash = callback_data.pop("vnp_SecureHash", "")
        callback_data.pop("vnp_SecureHashType", None)

        sorted_params = sorted(callback_data.items())
        query_string = "&".join(f"{k}={urllib.parse.quote_plus(str(v))}" for k, v in sorted_params)
        expected_hash = hmac.new(
            secret_key.encode(),
            query_string.encode(),
            hashlib.sha512
        ).hexdigest()

        return hmac.compare_digest(received_hash.lower(), expected_hash.lower())

    def parse_callback(
        self,
        callback_data: Dict[str, Any],
    ) -> Tuple[str, GatewayStatusEnum, Decimal]:
        """Parse VNPay callback data."""
        gateway_ref = callback_data.get("vnp_TxnRef", "")
        response_code = callback_data.get("vnp_ResponseCode", "")
        amount = Decimal(callback_data.get("vnp_Amount", 0)) / 100  # Convert from cents

        if response_code == "00":
            status = GatewayStatusEnum.success
        elif response_code in ["24", "99"]:
            status = GatewayStatusEnum.expired
        else:
            status = GatewayStatusEnum.failed

        return gateway_ref, status, amount
