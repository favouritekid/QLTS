# app/services/payment_intent_service.py
"""
PaymentIntent Service - Business logic for online payment processing.

Architecture Compliance:
- Service Layer: Pure business logic, no HTTP dependencies
- Security: IDOR checks via repository (unit_id filtering)
- Transactions: Services use db.add()/db.flush(), Router commits

⚠️ Chiếu tài chính → lead (``_create_payment_from_intent`` →
``sync_lead_tuition_paid``): hợp đồng CHUẨN ở
``services/lead_admission_sync.py`` (docstring đầu tệp).
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
from app.services.payment_service import (
    apply_verified_payment_balances,
    assert_payable_target,
    mo_so_tien_thua,
)
from app.utils.exceptions import (
    ResourceNotFoundError,
    BadRequest,
    BusinessRuleViolation,
    ConflictError,
)
from app.config import settings
from urllib.parse import urlparse

log = structlog.get_logger(__name__)


def build_safe_return_url(return_url: Optional[str]) -> str:
    """Allowlist + normalize the client-supplied post-payment return URL
    (open-redirect / SSRF guard — PR1 Commit 5).

    - None/empty → canonical default ``{FRONTEND_URL}/finance/payments/return``
      so callers that pass no return_url keep working (backward-compatible).
    - Same scheme+host as ``settings.FRONTEND_URL`` → kept as-is.
    - Any other origin → ``BusinessRuleViolation`` (mapped to HTTP 400 by the
      payments router). The gateway echoes this URL back to the user, so an
      attacker-controlled value would be an open redirect.
    """
    base = settings.FRONTEND_URL.rstrip("/")
    default_url = f"{base}/finance/payments/return"
    if not return_url:
        return default_url
    allowed = urlparse(settings.FRONTEND_URL)
    candidate = urlparse(return_url)
    allowed_origin = (allowed.scheme, allowed.netloc)
    if (candidate.scheme, candidate.netloc) != allowed_origin:
        raise BusinessRuleViolation("return_url is not an allowed origin")
    return return_url


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

    @staticmethod
    def _mock_callback_allowed() -> bool:
        """Nhánh "Mock parsing" của callback có được phép chạy không.

        HAI TẦNG, cố ý — một biến môi trường đặt nhầm không được phép mở lại
        nhánh này trên production:

          1. ``APP_ENV == "test"`` — nhánh chỉ tồn tại cho test;
          2. ``PAYMENT_CALLBACK_MOCK_ENABLED`` — và phải bật TƯỜNG MINH.

        Cùng khuôn với ``CSRF_PROTECTION_IN_TEST`` (``app/middleware/csrf.py``)
        và luật cờ ở ``app/services/finance_killswitch.py``: cờ mang nghĩa
        "CHO PHÉP", mặc định False.
        """
        return settings.APP_ENV == "test" and bool(
            settings.PAYMENT_CALLBACK_MOCK_ENABLED
        )

    # ==========================================================================
    # CREATE INTENT
    # ==========================================================================

    async def _find_replay_in_scope(
        self,
        invoice_id: int,
        idempotency_key: str,
        unit_id: Optional[int],
    ) -> Tuple[Invoice, Optional[PaymentIntent]]:
        """Kiểm phạm vi hoá đơn TRƯỚC, rồi mới tra intent cũ theo idempotency.

        Đây là TẦNG CHỦ SỞ HỮU của bất biến: *không intent nào — cũ hay mới —
        được trả cho người gọi khi hoá đơn nằm ngoài phạm vi tài chính của họ*.
        ``unit_id`` là phạm vi do ``deps.finance_scope_unit_id`` phân giải
        (admin/accountant ⇒ ``None`` = toàn hệ thống; vai khác ⇒ đơn vị của
        mình). Phép lọc thật là ``InvoiceRepository.get_by_id_with_relations``
        (``Lead.unit_id``), cùng khuôn với ``get_intent``/``cancel_intent``.

        Vì sao phải là MỘT hàm, và phép kiểm phải đứng TRƯỚC:
        ``PaymentIntentRepository.get_by_idempotency_key`` KHÔNG lọc đơn vị.
        Trước bản vá có HAI đường tra nó trước khi kiểm hoá đơn —
        ``create_or_get_intent`` (đường của ``POST /api/payments/intents``) và
        nhánh trả sớm của ``create_intent`` — nên ai biết ``invoice_id`` +
        ``idempotency_key`` của đơn vị khác đều nhận được ``pay_url`` của họ.
        Cả hai đường nay chỉ chạm được phép tra ấy qua hàm này.

        Ngoài phạm vi và không tồn tại ném CÙNG một lỗi (``Invoice not found``
        → 404): 404 không được phân biệt "có mà không được xem" với "không có".

        Returns:
            ``(invoice, existing)`` — ``existing`` là intent cùng khoá trên hoá
            đơn này (có thể đã ở trạng thái kết thúc), hoặc ``None``. Người gọi
            tự quyết replay hay tạo mới.
        """
        invoice = await self.invoice_repo.get_by_id_with_relations(invoice_id, unit_id)
        if not invoice:
            raise ResourceNotFoundError("Invoice not found")

        existing = await self.intent_repo.get_by_idempotency_key(
            idempotency_key, invoice_id
        )
        return invoice, existing

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
            ResourceNotFoundError: If invoice or method not found, or the
                invoice is outside ``unit_id`` scope (checked BEFORE the
                idempotency replay — see ``_find_replay_in_scope``)
            BusinessRuleViolation: If amount exceeds remaining or invalid method
            BadRequest: If amount is not positive
        """
        # Validate amount
        if amount <= 0:
            raise BadRequest("Payment amount must be positive")

        if not idempotency_key:
            raise BadRequest("Idempotency key is required")

        # Invoice scope FIRST, idempotency replay second — the replay below must
        # never hand an out-of-scope caller another unit's intent (IDOR).
        invoice, existing = await self._find_replay_in_scope(
            invoice_id, idempotency_key, unit_id
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

        # Serialize against cancel_fee, which holds the fee row lock: acquire it
        # before creating the intent and refuse if the fee is cancelled. This
        # closes the race where an intent is created on a fee being cancelled —
        # the gateway could later collect money the callback must refuse
        # (reconciliation hole). cancel_fee blocks while an active intent exists,
        # so with this lock the two operations cannot interleave: either the
        # intent exists when cancel_fee checks (it blocks), or the fee is already
        # cancelled when we check here (we refuse). create_intent takes only the
        # fee lock (no invoice lock) → no ABBA with verify/callback (invoice→fee).
        fee = await self.fee_repo.get_for_update(invoice.fee_id, unit_id)
        if fee is None:
            raise ResourceNotFoundError("Fee not found")
        # Resolve the profile so the guard can also refuse creating an intent on
        # a withdrawn/rejected/refund-pending profile (not just a cancelled fee).
        _intent_profile = None
        if fee.admission_profile_id:
            _intent_profile = (
                await self.db.execute(
                    select(models.AdmissionProfile).where(
                        models.AdmissionProfile.id == fee.admission_profile_id
                    )
                )
            ).scalar_one_or_none()
        assert_payable_target(
            fee, invoice, _intent_profile, action="tạo giao dịch thanh toán"
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

        # Create intent. PR1 Commit 5: allowlist/normalize the return_url
        # before storing it or handing it to a gateway adapter.
        safe_return_url = build_safe_return_url(return_url)
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=expiration_minutes)

        intent = PaymentIntent(
            invoice_id=invoice_id,
            method_id=method_id,
            amount=amount,
            currency="VND",
            idempotency_key=idempotency_key,
            status=PaymentIntentStatusEnum.created.value,
            return_url=safe_return_url,
            expires_at=expires_at,
        )

        self.db.add(intent)
        await self.db.flush()
        await self.db.refresh(intent)

        # Generate gateway payment URL
        gateway_code = method.code
        if gateway_code in self._gateway_adapters:
            adapter = self._gateway_adapters[gateway_code]
            pay_url, gateway_ref = await adapter.create_payment_url(
                intent, safe_return_url
            )
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

        Raises:
            ResourceNotFoundError: Invoice not found OR outside ``unit_id``
                scope — checked BEFORE the idempotency replay, so a caller from
                another unit who knows ``invoice_id`` + ``idempotency_key`` gets
                404, never the existing intent's ``pay_url``.
        """
        # Invoice scope FIRST, idempotency replay second (IDOR) — this is the
        # path of POST /api/payments/intents.
        _, existing = await self._find_replay_in_scope(
            invoice_id, idempotency_key, unit_id
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

            # FAIL-CLOSED. Bản trước viết `if secret_key and not verify(...)`:
            # secret RỖNG thì phép kiểm chữ ký bị BỎ QUA, không phải bị từ
            # chối — tức cấu hình thiếu lại thành cấu hình cho qua. Endpoint
            # này không đòi auth, nên "cho qua" nghĩa là ai cũng ghi được
            # trạng thái thanh toán.
            #
            # Từ chối TRƯỚC khi gọi `verify_signature`, không đưa secret rỗng
            # vào mã mật mã rồi trông chờ nó trả False.
            if not secret_key:
                log.warning(
                    "callback_secret_not_configured",
                    gateway_code=gateway_code,
                )
                raise BusinessRuleViolation(
                    "Gateway secret is not configured; callback refused"
                )

            if not adapter.verify_signature(callback_data, secret_key):
                log.warning(
                    "callback_signature_invalid",
                    gateway_code=gateway_code,
                    gateway_ref=gateway_ref,
                )
                raise BusinessRuleViolation("Invalid gateway signature")
        elif not self._mock_callback_allowed():
            # FAIL-CLOSED. Không tra được adapter nghĩa là KHÔNG CÓ CÁCH NÀO
            # xác thực callback này. Bản trước rơi thẳng xuống nhánh "Mock
            # parsing" và đọc `gateway_ref`/`status`/`amount` từ THÂN REQUEST
            # — trên một endpoint POST không auth. Vì `register_default_gateways`
            # không có call-site sản xuất nào, đó là đường đi của 100% callback
            # trên production.
            log.warning(
                "callback_gateway_adapter_not_registered",
                gateway_code=gateway_code,
            )
            raise BusinessRuleViolation(
                f"No gateway adapter registered for '{gateway_code}'; callback refused"
            )
        else:
            # Nhánh mock — CHỈ sống khi `_mock_callback_allowed()` (xem hàm
            # đó: đòi cả `APP_ENV == "test"` lẫn cờ bật tường minh).
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

        # Cổng của ROUTE phải khớp PHƯƠNG THỨC của intent.
        #
        # Thiếu phép này, `gateway_ref` là thứ DUY NHẤT ràng buộc callback với
        # intent — mà nó do gateway sinh ra và, ở đường không-adapter, mang
        # dạng đoán được `MOCK-{id}-{epoch}`. Một callback gửi tới
        # `/callback/<cổng bất kỳ>` vẫn khớp trúng intent của cổng khác.
        #
        # ⚠️ So với `PaymentMethod.code`, KHÔNG phải `PaymentMethod.gateway_code`:
        # `create_intent` dùng `gateway_code = method.code` để tra adapter, nên
        # `.code` mới là thứ nằm trên đường này. `get_by_gateway_ref` đã
        # `joinedload(PaymentIntent.method)` nên phép so này không tốn query.
        intent_gateway_code = intent.method.code if intent.method else None
        if intent_gateway_code != gateway_code:
            log.warning(
                "callback_gateway_mismatch",
                intent_id=intent.id,
                gateway_code_route=gateway_code,
                gateway_code_intent=intent_gateway_code,
            )
            raise BusinessRuleViolation(
                "Callback gateway does not match the payment intent method"
            )

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
        #
        # KHÔNG GHI GÌ trên nhánh này. Bản trước đặt `status=failed`,
        # `gateway_status='amount_mismatch'`, `callback_received_at` và
        # `callback_data = THÂN REQUEST THÔ`, rồi `flush()`, RỒI MỚI `raise`.
        # `process_gateway_callback` nuốt ngoại lệ (không re-raise, không
        # rollback) và router `await db.commit()` vô điều kiện ⇒ phép ghi ấy
        # thành VĨNH VIỄN. Mà `failed` nằm trong `is_terminal` ⇒
        # `can_process_callback` False mãi mãi ⇒ callback THẬT sau đó bị từ
        # chối: tiền vào cổng mà hệ không ghi nhận.
        #
        # Từ chối mà không ghi thì intent giữ nguyên trạng thái, vẫn nhận được
        # callback đúng sau đó, hoặc hết hạn tự nhiên.
        if callback_amount != intent.amount:
            log.error(
                "callback_amount_mismatch",
                intent_id=intent.id,
                expected=str(intent.amount),
                received=str(callback_amount),
            )
            raise BusinessRuleViolation(
                f"Amount mismatch: expected {intent.amount}, received {callback_amount}"
            )

        payment = None
        fee = None
        profile = None

        if gateway_status == GatewayStatusEnum.success:
            # Create verified payment (returns payment, fee, profile)
            payment, fee, profile = await self._create_payment_from_intent(
                intent, unit_id, verified_gateway_response=callback_data
            )
            new_status = PaymentIntentStatusEnum.completed.value
        elif gateway_status in [GatewayStatusEnum.failed, GatewayStatusEnum.expired]:
            new_status = PaymentIntentStatusEnum.failed.value
        else:
            # Pending or other - keep as pending
            new_status = PaymentIntentStatusEnum.pending.value

        # Ghi SAU khi mọi phép có thể ném đã đi qua.
        #
        # `_create_payment_from_intent` ném được (`assert_payable_target`, fee
        # hoặc hoá đơn đã huỷ...). Bản trước gán bốn trường TRƯỚC lời gọi đó,
        # nên khi nó ném thì wrapper nuốt, router commit, và thân request CHƯA
        # XÁC THỰC nằm lại trên một intent VẪN CÒN SỐNG.
        intent.callback_received_at = datetime.now(timezone.utc)
        intent.callback_data = callback_data
        intent.gateway_status = gateway_status.value
        intent.gateway_response = callback_data
        intent.status = new_status
        if new_status == PaymentIntentStatusEnum.completed.value:
            intent.completed_at = datetime.now(timezone.utc)

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
        from app.services.notification_dispatcher import rooms_for_admission
        _rooms = rooms_for_admission(profile) if profile is not None else None

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
            await self._rollback_callback_partial_write()
            return {
                "success": False,
                "message": str(e),
                "intent_id": None,
            }, None
        except BusinessRuleViolation as e:
            await self._rollback_callback_partial_write()
            return {
                "success": False,
                "message": str(e),
                "intent_id": None,
            }, None

    async def _rollback_callback_partial_write(self) -> None:
        """Cuộn lại mọi phép ghi dang dở của một callback BỊ TỪ CHỐI.

        Hàm này là ngoại lệ có chủ đích của luật "service chỉ flush, router
        commit" (``MASTER_ARCHITECTURE.md``). Lý do: ``process_gateway_callback``
        chính là RANH GIỚI LỖI của đường callback — nó nuốt
        ``BusinessRuleViolation``/``ResourceNotFoundError`` và trả về một dict
        thay vì ném tiếp, nên router **không thể biết** đã có lỗi và vẫn
        ``await db.commit()`` vô điều kiện. Chỗ duy nhất còn biết sự thật là
        đây.

        ⚠️ CHỈ gọi trong hai khối ``except``, TUYỆT ĐỐI không đặt ở nhánh
        ``return`` thành công. Một callback hợp lệ báo ``failed``/``expired``
        đi qua nhánh đó và phép ghi ``status = failed`` của nó là CÓ CHỦ ĐÍCH;
        rollback ở đấy sẽ xoá mất nó. Dấu phân biệt: nhánh thành công trả
        ``intent_id`` khác None, hai nhánh ``except`` trả None.

        Vì sao cần dù hiện chưa nổ: sau ``db.add(payment)`` trong
        ``_create_payment_from_intent``, hôm nay KHÔNG chuỗi gọi nào ném hai
        lớp trên (``apply_verified_payment_balances``, ``mo_so_tien_thua``,
        ``sync_lead_tuition_paid`` đều không ném domain), và mọi lớp khác đã
        được router cuộn lại. Lỗ hổng vì thế là TIỀM ẨN — nó mở ra ngay khi ai
        đó thêm một ``raise BusinessRuleViolation`` vào bất kỳ đâu sau phép ghi
        đầu tiên. Đóng trước thì rẻ hơn nhiều so với đóng sau khi mất tiền.
        """
        await self.db.rollback()

    async def _create_payment_from_intent(
        self,
        intent: PaymentIntent,
        unit_id: Optional[int] = None,
        verified_gateway_response: Optional[Dict[str, Any]] = None,
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

        # Resolve admission profile (with lead eager-loaded) BEFORE the payable
        # guard so a late gateway success is refused on a withdrawn/rejected/
        # refund-pending profile too, not only a cancelled fee/invoice. Reused
        # below for post-commit payload + HK1 lead sync.
        profile: Optional[models.AdmissionProfile] = None
        if fee.admission_profile_id:
            result = await self.db.execute(
                select(models.AdmissionProfile)
                .where(models.AdmissionProfile.id == fee.admission_profile_id)
                .options(selectinload(models.AdmissionProfile.lead))
            )
            profile = result.scalar_one_or_none()

        # Defense-in-depth (Nhóm B): never write money onto a dead target.
        # cancel_fee blocks while an active intent exists, so the normal path
        # can't reach here; this also closes the manual cancel-invoice /
        # cancel-intent surface. A late gateway success on a dead target is
        # refused — the caller marks the intent failed; reconcile out-of-band.
        assert_payable_target(fee, invoice, profile, action="ghi nhận thanh toán")

        # Create payment (auto-verified for online payments).
        # Issue C fix: verified_by_id must be NULL, not the same as created_by_id,
        # otherwise chk_payment_no_self_approval fires. For the online path
        # there is no human checker — the gateway callback IS the verification.
        # Đổi ngành: snapshot ngành ghi nhận doanh thu (bất biến) — gateway auto-
        # verify NÊN stamp ngay (tuition-only). fee đã load ở trên.
        from app.services.fee_calculation_service import (
            recognized_major_id_for_fee,
        )
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
            recognized_major_id=recognized_major_id_for_fee(fee),
        )

        self.db.add(payment)
        await self.db.flush()

        # ADR-002 PR 5: snapshot settled state BEFORE fee mutation
        from app.services.fee_calculation_service import is_hk1_settled_fee
        was_hk1_settled = is_hk1_settled_fee(fee)

        # 🔴 Money-math đi qua ĐÚNG hàm dùng chung với ghi tay và nhập lô.
        #
        # Trước đây khối này chép tay lại toàn bộ phép cộng (invoice.paid_amount,
        # fee.paid_amount, hai nhánh status, fee.version) — bản sao thứ BA của
        # cùng một công thức. Hệ quả không phải "lệch vài dòng" mà là: khi hàm
        # chung học được cách mở sổ tiền thừa, đường online vẫn im lặng, và một
        # callback trả dư vẫn đẩy số dư xuống âm mà không ai ghi nợ.
        _now = datetime.now(timezone.utc)
        fee_balance_before, fee_remaining, excess = apply_verified_payment_balances(
            invoice=invoice, fee=fee, amount=intent.amount, now=_now
        )

        # Gateway trả dư thì cũng là tiền thật của người học. Ở đây KHÔNG có
        # maker-checker để chặn trước, nên sổ thừa là chỗ duy nhất giữ dấu.
        await mo_so_tien_thua(
            self.db,
            payment=payment,
            invoice=invoice,
            admission_profile_id=fee.admission_profile_id,
            excess=excess,
        )

        # Create audit transaction
        transaction = PaymentTransaction(
            payment_id=payment.id,
            fee_id=fee.id,
            transaction_type=TransactionTypeEnum.payment.value,
            amount=intent.amount,
            balance_before=fee_balance_before,
            balance_after=fee_remaining,
            external_reference=intent.gateway_ref,
            # Snapshot gateway lấy từ THAM SỐ, không đọc `intent.gateway_response`.
            #
            # Trường đó cố ý chỉ được gán SAU lời gọi này (để một lần ném ở đây
            # không để lại thân request trên một intent còn sống), nên đọc nó ở
            # đây sẽ chụp giá trị CŨ/RỖNG: giao dịch thành công lưu snapshot
            # rỗng trong khi intent lại có dữ liệu — hai nguồn lệch nhau đúng ở
            # bản ghi dùng để ĐỐI SOÁT.
            gateway_response=(
                verified_gateway_response
                if verified_gateway_response is not None
                else intent.gateway_response
            ),
            performed_by_id=1,  # System user
            notes=f"Online payment via {intent.method.code}. Invoice: {invoice.invoice_number}",
        )
        self.db.add(transaction)

        await self.db.flush()
        await self.db.refresh(payment)

        # ADR-002 PR 5: Sync lead only on HK1 SETTLED-state transition
        # (remaining<=0). Partial online payment leaves lead at sts14.
        now_hk1_settled = is_hk1_settled_fee(fee)
        if not was_hk1_settled and now_hk1_settled and profile is not None:
            from app.services.lead_admission_sync import sync_lead_tuition_paid
            await sync_lead_tuition_paid(
                db=self.db,
                profile=profile,
                transaction_id=payment.reference_code or f"PAY-{payment.id}",
                changed_by_user_id=1,
                reason=f"HK1 tuition settled via online payment ({intent.method.code})",
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
            # PR1 Commit 5: wire the canonical backend base so the IPN URL is
            # built from it, NOT the client return_url. This is the real
            # runtime registration path (from_settings is a separate ctor).
            public_backend_url=settings.PUBLIC_BACKEND_URL,
        )
        service.register_gateway("momo", momo)
        log.info("momo_gateway_registered")
