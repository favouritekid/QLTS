# app/gateways/momo.py
"""
MoMo Payment Gateway Adapter.

MoMo is Vietnam's leading mobile wallet supporting:
- MoMo Wallet payments
- ATM/Credit card payments via MoMo
- QR Code payments

Documentation:
- https://developers.momo.vn/v3/docs/payment/api/collection-link/
- https://developers.momo.vn/v3/docs/payment/api/collection-link/specifications/

Environment Configuration:
    MOMO_PARTNER_CODE: Partner code (provided by MoMo)
    MOMO_ACCESS_KEY: Access key for API authentication
    MOMO_SECRET_KEY: Secret key for signature
    MOMO_ENDPOINT: MoMo API endpoint
        - Sandbox: https://test-payment.momo.vn/v2/gateway/api/create
        - Production: https://payment.momo.vn/v2/gateway/api/create

Security:
- All requests signed with HMAC-SHA256
- Signature verified on all callbacks
- Amount validated to prevent tampering
"""

from datetime import datetime
from decimal import Decimal
import hashlib
import hmac
import json
import uuid
from typing import Any, Dict, Optional, Tuple, TYPE_CHECKING

import structlog

from app.gateways.base import (
    BaseGatewayAdapter,
    GatewayResponse,
    GatewayStatusEnum,
    GatewayError,
)

if TYPE_CHECKING:
    from app.models.finance import PaymentIntent

log = structlog.get_logger(__name__)

# MoMo result codes
MOMO_SUCCESS_CODE = 0
MOMO_PENDING_CODES = [1000, 8000]  # Processing states (8000 = being processed)
MOMO_FAILED_CODES = [1001, 1002, 1007]  # Failure (insufficient funds, rejected, fraud)
MOMO_EXPIRED_CODES = [1003, 1004]  # Timeout
MOMO_CANCELLED_CODES = [1005, 1006]  # User cancelled


class MoMoAdapter(BaseGatewayAdapter):
    """
    MoMo payment gateway adapter implementation.

    Features:
    - Payment URL generation (payWithMethod)
    - Callback signature verification
    - Response code parsing

    Payment Types:
    - captureWallet: Pay with MoMo wallet
    - payWithATM: Pay with ATM card
    - payWithCC: Pay with credit card

    Usage:
        adapter = MoMoAdapter(
            partner_code="MOMO_PARTNER",
            access_key="ACCESS_KEY",
            secret_key="SECRET_KEY",
        )

        # Create payment URL
        pay_url, request_id = await adapter.create_payment_url(intent, return_url)

        # Verify callback
        if adapter.verify_signature(callback_data, secret_key):
            response = adapter.parse_callback(callback_data)
    """

    def __init__(
        self,
        partner_code: str,
        access_key: str,
        secret_key: str,
        endpoint: str = "https://test-payment.momo.vn/v2/gateway/api/create",
        request_type: str = "payWithMethod",
        auto_capture: bool = True,
        public_backend_url: str = "",
    ):
        """
        Initialize MoMo adapter.

        Args:
            partner_code: Partner code from MoMo
            access_key: API access key from MoMo
            secret_key: Secret key for HMAC signing
            endpoint: MoMo API endpoint URL
            request_type: Payment type (payWithMethod, captureWallet, etc.)
            auto_capture: Whether to auto-capture payment
            public_backend_url: Canonical backend base for the IPN URL
        """
        self.partner_code = partner_code
        self.access_key = access_key
        self.secret_key = secret_key
        self.endpoint = endpoint
        self.request_type = request_type
        self.auto_capture = auto_capture
        # PR1 Commit 5: canonical backend base for the MoMo IPN URL (no longer
        # derived from the client-supplied return_url).
        self.public_backend_url = public_backend_url

    @property
    def gateway_code(self) -> str:
        return "momo"

    @property
    def gateway_name(self) -> str:
        return "MoMo"

    def _build_ipn_url(self) -> str:
        """Server-to-server IPN (callback) URL MoMo notifies. PR1 Commit 5:
        built from the trusted PUBLIC_BACKEND_URL, never the client-supplied
        return_url, so an attacker can't redirect MoMo's IPN to their host."""
        base = self.public_backend_url.rstrip("/")
        return f"{base}/api/payments/callback/momo"

    @classmethod
    def from_settings(cls, settings) -> "MoMoAdapter":
        """
        Create adapter from application settings.

        Args:
            settings: Application settings object

        Returns:
            Configured MoMoAdapter instance
        """
        return cls(
            partner_code=getattr(settings, "MOMO_PARTNER_CODE", ""),
            access_key=getattr(settings, "MOMO_ACCESS_KEY", ""),
            secret_key=getattr(settings, "MOMO_SECRET_KEY", ""),
            endpoint=getattr(
                settings,
                "MOMO_ENDPOINT",
                "https://test-payment.momo.vn/v2/gateway/api/create"
            ),
            public_backend_url=getattr(settings, "PUBLIC_BACKEND_URL", ""),
        )

    async def create_payment_url(
        self,
        intent: "PaymentIntent",
        return_url: str,
    ) -> Tuple[str, str]:
        """
        Create MoMo payment URL.

        Note: This method prepares the request but does NOT call MoMo API.
        In production, you would use httpx to make the actual API call.
        This implementation returns mock data for testing.

        Args:
            intent: PaymentIntent with amount and invoice info
            return_url: URL to redirect after payment

        Returns:
            Tuple of (payment_url, request_id)

        Raises:
            GatewayError: If configuration is invalid
        """
        if not self.partner_code or not self.secret_key:
            raise GatewayError(
                "MoMo not configured: missing PARTNER_CODE or SECRET_KEY",
                gateway_code=self.gateway_code,
            )

        # Generate unique request ID
        request_id = f"QLTS{intent.id}{uuid.uuid4().hex[:8].upper()}"
        order_id = f"ORDER{intent.id}{int(datetime.now().timestamp())}"

        # MoMo uses integer amount in VND
        amount = int(intent.amount)

        # Build order info
        order_info = f"Thanh toan hoa don #{intent.invoice_id}"
        if hasattr(intent, 'invoice') and intent.invoice:
            order_info = f"Thanh toan {intent.invoice.invoice_number}"

        # IPN (server-to-server callback) URL — from PUBLIC_BACKEND_URL, never
        # the client return_url (SSRF / redirect guard). See _build_ipn_url.
        ipn_url = self._build_ipn_url()

        # Create raw signature string (MoMo format)
        raw_signature = (
            f"accessKey={self.access_key}"
            f"&amount={amount}"
            f"&extraData="
            f"&ipnUrl={ipn_url}"
            f"&orderId={order_id}"
            f"&orderInfo={order_info}"
            f"&partnerCode={self.partner_code}"
            f"&redirectUrl={return_url}"
            f"&requestId={request_id}"
            f"&requestType={self.request_type}"
        )

        # Generate HMAC-SHA256 signature
        signature = hmac.new(
            self.secret_key.encode("utf-8"),
            raw_signature.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()

        # Build request body (for actual API call)
        request_body = {
            "partnerCode": self.partner_code,
            "partnerName": "QLTS",
            "storeId": self.partner_code,
            "requestId": request_id,
            "amount": amount,
            "orderId": order_id,
            "orderInfo": order_info,
            "redirectUrl": return_url,
            "ipnUrl": ipn_url,
            "requestType": self.request_type,
            "extraData": "",
            "autoCapture": self.auto_capture,
            "lang": "vi",
            "signature": signature,
        }

        # In production, make actual API call:
        # async with httpx.AsyncClient() as client:
        #     response = await client.post(self.endpoint, json=request_body)
        #     data = response.json()
        #     return data["payUrl"], request_id

        # For now, return mock URL (sandbox testing)
        mock_pay_url = (
            f"https://test-payment.momo.vn/v2/gateway/pay?"
            f"requestId={request_id}&orderId={order_id}"
        )

        log.info(
            "momo_payment_url_created",
            intent_id=intent.id,
            request_id=request_id,
            order_id=order_id,
            amount=str(intent.amount),
        )

        return mock_pay_url, request_id

    def verify_signature(
        self,
        callback_data: Dict[str, Any],
        secret_key: str,
    ) -> bool:
        """
        Verify MoMo callback signature.

        MoMo IPN signature format:
        accessKey=$accessKey&amount=$amount&extraData=$extraData
        &message=$message&orderId=$orderId&orderInfo=$orderInfo
        &orderType=$orderType&partnerCode=$partnerCode&payType=$payType
        &requestId=$requestId&responseTime=$responseTime
        &resultCode=$resultCode&transId=$transId

        Args:
            callback_data: Raw callback data from MoMo
            secret_key: HMAC secret key

        Returns:
            True if signature is valid
        """
        received_signature = callback_data.get("signature", "")
        if not received_signature:
            log.warning("momo_callback_no_signature")
            return False

        # Build raw signature string in MoMo's required order
        raw_signature = (
            f"accessKey={self.access_key}"
            f"&amount={callback_data.get('amount', '')}"
            f"&extraData={callback_data.get('extraData', '')}"
            f"&message={callback_data.get('message', '')}"
            f"&orderId={callback_data.get('orderId', '')}"
            f"&orderInfo={callback_data.get('orderInfo', '')}"
            f"&orderType={callback_data.get('orderType', '')}"
            f"&partnerCode={callback_data.get('partnerCode', '')}"
            f"&payType={callback_data.get('payType', '')}"
            f"&requestId={callback_data.get('requestId', '')}"
            f"&responseTime={callback_data.get('responseTime', '')}"
            f"&resultCode={callback_data.get('resultCode', '')}"
            f"&transId={callback_data.get('transId', '')}"
        )

        # Calculate expected signature
        expected_signature = hmac.new(
            secret_key.encode("utf-8"),
            raw_signature.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()

        # Constant-time comparison
        is_valid = hmac.compare_digest(
            received_signature.lower(),
            expected_signature.lower()
        )

        if not is_valid:
            log.warning(
                "momo_callback_signature_mismatch",
                received_signature=received_signature[:16] + "...",
            )

        return is_valid

    def parse_callback(
        self,
        callback_data: Dict[str, Any],
    ) -> GatewayResponse:
        """
        Parse MoMo callback data.

        MoMo Result Codes:
        - 0: Success
        - 9000: Transaction authorized successfully
        - 8000: Transaction being processed
        - 1001: Failed due to insufficient funds
        - 1002: Transaction rejected by issuer
        - 1003: Transaction cancelled
        - 1004: Transaction expired
        - 1005: Transaction rejected due to OTP failure
        - 1006: Transaction rejected due to limit exceeded

        Args:
            callback_data: Raw callback data from MoMo

        Returns:
            GatewayResponse with parsed data
        """
        # Extract fields
        request_id = callback_data.get("requestId", "")
        result_code = callback_data.get("resultCode", -1)
        message = callback_data.get("message", "")
        trans_id = callback_data.get("transId", "")

        # Parse amount
        amount_raw = callback_data.get("amount", "0")
        try:
            amount = Decimal(str(amount_raw))
        except (ValueError, TypeError):
            amount = Decimal("0")

        # Parse response time
        response_time = callback_data.get("responseTime", "")
        transaction_time = None
        if response_time:
            try:
                # MoMo uses millisecond timestamp
                ts = int(response_time) / 1000
                transaction_time = datetime.fromtimestamp(ts)
            except (ValueError, TypeError):
                pass

        # Map result code to status
        if result_code == MOMO_SUCCESS_CODE or result_code == 9000:
            status = GatewayStatusEnum.success
        elif result_code in MOMO_PENDING_CODES:
            status = GatewayStatusEnum.pending
        elif result_code in MOMO_FAILED_CODES:
            status = GatewayStatusEnum.failed
        elif result_code in MOMO_EXPIRED_CODES:
            status = GatewayStatusEnum.expired
        elif result_code in MOMO_CANCELLED_CODES:
            status = GatewayStatusEnum.cancelled
        else:
            # Unknown codes treated as failed
            status = GatewayStatusEnum.failed

        return GatewayResponse(
            gateway_ref=request_id,
            status=status,
            amount=amount,
            raw_response_code=str(result_code),
            message=message,
            transaction_time=transaction_time,
            extra_data={
                "transId": trans_id,
                "orderType": callback_data.get("orderType", ""),
                "payType": callback_data.get("payType", ""),
                "orderId": callback_data.get("orderId", ""),
            }
        )

    def _get_error_message(self, result_code: int) -> str:
        """Get human-readable error message for result code."""
        messages = {
            0: "Thành công",
            9000: "Giao dịch được xác thực thành công",
            8000: "Giao dịch đang được xử lý",
            1001: "Giao dịch thất bại do không đủ số dư",
            1002: "Giao dịch bị từ chối bởi ngân hàng phát hành",
            1003: "Giao dịch đã bị huỷ",
            1004: "Giao dịch hết hạn",
            1005: "Giao dịch thất bại do OTP sai",
            1006: "Giao dịch thất bại do vượt hạn mức",
            1007: "Giao dịch bị từ chối do nghi ngờ gian lận",
            4001: "Giao dịch thất bại do yêu cầu không hợp lệ",
            4100: "Giao dịch thất bại do tài khoản không tồn tại",
        }
        return messages.get(result_code, f"Lỗi không xác định (code: {result_code})")

    async def query_transaction(
        self,
        request_id: str,
        order_id: str,
    ) -> Dict[str, Any]:
        """
        Query transaction status from MoMo.

        Used to verify payment status for reconciliation.

        Args:
            request_id: Request ID from create_payment_url
            order_id: Order ID from create_payment_url

        Returns:
            Transaction status response

        Note:
            This method requires httpx or similar async HTTP client.
            Not implemented in base version - extend as needed.
        """
        raise NotImplementedError(
            "Transaction query not implemented. "
            "Use MoMo merchant portal for reconciliation."
        )
