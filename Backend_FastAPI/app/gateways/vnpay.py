# app/gateways/vnpay.py
"""
VNPay Payment Gateway Adapter.

VNPay is Vietnam's leading payment gateway supporting:
- ATM cards (domestic banks)
- International cards (Visa, Mastercard, JCB)
- QR Code payments
- Bank transfer

Documentation:
- https://sandbox.vnpayment.vn/apis/
- https://sandbox.vnpayment.vn/apis/docs/thanh-toan-pay/pay.html

Environment Configuration:
    VNPAY_TMN_CODE: Merchant terminal code (provided by VNPay)
    VNPAY_HASH_SECRET: Secret key for signature (provided by VNPay)
    VNPAY_PAYMENT_URL: Payment gateway URL
        - Sandbox: https://sandbox.vnpayment.vn/paymentv2/vpcpay.html
        - Production: https://pay.vnpay.vn/vpcpay.html
    VNPAY_API_URL: Query API URL (for transaction status)

Security:
- All requests signed with HMAC-SHA512
- Signature verified on all callbacks
- Amount validated to prevent tampering
"""

from datetime import datetime
from decimal import Decimal
import hashlib
import hmac
import urllib.parse
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

# VNPay response codes
VNPAY_SUCCESS_CODE = "00"
VNPAY_PENDING_CODES = ["07"]  # Transaction suspected
VNPAY_EXPIRED_CODES = ["24", "99"]  # Timeout or expired
VNPAY_CANCELLED_CODES = ["15"]  # User cancelled


class VNPayAdapter(BaseGatewayAdapter):
    """
    VNPay payment gateway adapter implementation.

    Features:
    - Payment URL generation with secure hash
    - Callback signature verification
    - Response code parsing

    Usage:
        adapter = VNPayAdapter(
            tmn_code="DEMO_TMN",
            hash_secret="DEMO_SECRET",
            payment_url="https://sandbox.vnpayment.vn/paymentv2/vpcpay.html",
        )

        # Create payment URL
        pay_url, txn_ref = await adapter.create_payment_url(intent, return_url)

        # Verify callback
        if adapter.verify_signature(callback_data, hash_secret):
            response = adapter.parse_callback(callback_data)
    """

    def __init__(
        self,
        tmn_code: str,
        hash_secret: str,
        payment_url: str = "https://sandbox.vnpayment.vn/paymentv2/vpcpay.html",
        api_url: str = "https://sandbox.vnpayment.vn/merchant_webapi/api/transaction",
        version: str = "2.1.0",
        locale: str = "vn",
    ):
        """
        Initialize VNPay adapter.

        Args:
            tmn_code: Merchant terminal code from VNPay
            hash_secret: Secret key for HMAC signing
            payment_url: VNPay payment gateway URL
            api_url: VNPay query API URL
            version: API version (default: 2.1.0)
            locale: Language locale (vn, en)
        """
        self.tmn_code = tmn_code
        self.hash_secret = hash_secret
        self.payment_url = payment_url
        self.api_url = api_url
        self.version = version
        self.locale = locale

    @property
    def gateway_code(self) -> str:
        return "vnpay"

    @property
    def gateway_name(self) -> str:
        return "VNPay"

    @classmethod
    def from_settings(cls, settings) -> "VNPayAdapter":
        """
        Create adapter from application settings.

        Args:
            settings: Application settings object

        Returns:
            Configured VNPayAdapter instance
        """
        return cls(
            tmn_code=getattr(settings, "VNPAY_TMN_CODE", ""),
            hash_secret=getattr(settings, "VNPAY_HASH_SECRET", ""),
            payment_url=getattr(
                settings,
                "VNPAY_PAYMENT_URL",
                "https://sandbox.vnpayment.vn/paymentv2/vpcpay.html"
            ),
            api_url=getattr(
                settings,
                "VNPAY_API_URL",
                "https://sandbox.vnpayment.vn/merchant_webapi/api/transaction"
            ),
        )

    async def create_payment_url(
        self,
        intent: "PaymentIntent",
        return_url: str,
    ) -> Tuple[str, str]:
        """
        Create VNPay payment URL.

        Builds URL with all required parameters and secure hash.

        Args:
            intent: PaymentIntent with amount and invoice info
            return_url: URL to redirect after payment

        Returns:
            Tuple of (payment_url, txn_ref)

        Raises:
            GatewayError: If configuration is invalid
        """
        if not self.tmn_code or not self.hash_secret:
            raise GatewayError(
                "VNPay not configured: missing TMN_CODE or HASH_SECRET",
                gateway_code=self.gateway_code,
            )

        # Generate unique transaction reference
        # Format: QLTS{intent_id}{timestamp}
        timestamp = int(datetime.now().timestamp())
        txn_ref = f"QLTS{intent.id}{timestamp}"

        # Get IP address (use placeholder for server-to-server)
        ip_addr = "127.0.0.1"

        # Build order info
        order_info = f"Thanh toan hoa don #{intent.invoice_id}"
        if hasattr(intent, 'invoice') and intent.invoice:
            order_info = f"Thanh toan {intent.invoice.invoice_number}"

        # VNPay uses integer amount in VND (no decimals)
        # Multiply by 100 as VNPay expects amount in "đồng" unit
        amount_int = int(intent.amount * 100)

        # Build params dict
        params = {
            "vnp_Version": self.version,
            "vnp_Command": "pay",
            "vnp_TmnCode": self.tmn_code,
            "vnp_Amount": amount_int,
            "vnp_CurrCode": "VND",
            "vnp_TxnRef": txn_ref,
            "vnp_OrderInfo": order_info,
            "vnp_OrderType": "other",
            "vnp_Locale": self.locale,
            "vnp_ReturnUrl": return_url,
            "vnp_IpAddr": ip_addr,
            "vnp_CreateDate": datetime.now().strftime("%Y%m%d%H%M%S"),
        }

        # Sort params alphabetically and build query string
        sorted_params = sorted(params.items())
        hash_data = "&".join(
            f"{k}={urllib.parse.quote_plus(str(v))}"
            for k, v in sorted_params
        )

        # Generate HMAC-SHA512 signature
        signature = hmac.new(
            self.hash_secret.encode("utf-8"),
            hash_data.encode("utf-8"),
            hashlib.sha512
        ).hexdigest()

        # Build final payment URL
        payment_url = f"{self.payment_url}?{hash_data}&vnp_SecureHash={signature}"

        log.info(
            "vnpay_payment_url_created",
            intent_id=intent.id,
            txn_ref=txn_ref,
            amount=str(intent.amount),
        )

        return payment_url, txn_ref

    def verify_signature(
        self,
        callback_data: Dict[str, Any],
        secret_key: str,
    ) -> bool:
        """
        Verify VNPay callback signature.

        CRITICAL: Never process callbacks without verification.

        Args:
            callback_data: Raw callback data (will be modified - hash removed)
            secret_key: HMAC secret key

        Returns:
            True if signature is valid
        """
        # Extract received hash
        received_hash = callback_data.get("vnp_SecureHash", "")
        if not received_hash:
            log.warning("vnpay_callback_no_signature")
            return False

        # Remove hash fields from data for verification
        data_copy = dict(callback_data)
        data_copy.pop("vnp_SecureHash", None)
        data_copy.pop("vnp_SecureHashType", None)

        # Sort params and build hash data
        sorted_params = sorted(data_copy.items())
        hash_data = "&".join(
            f"{k}={urllib.parse.quote_plus(str(v))}"
            for k, v in sorted_params
        )

        # Calculate expected hash
        expected_hash = hmac.new(
            secret_key.encode("utf-8"),
            hash_data.encode("utf-8"),
            hashlib.sha512
        ).hexdigest()

        # Constant-time comparison to prevent timing attacks
        is_valid = hmac.compare_digest(
            received_hash.lower(),
            expected_hash.lower()
        )

        if not is_valid:
            log.warning(
                "vnpay_callback_signature_mismatch",
                received_hash=received_hash[:16] + "...",
            )

        return is_valid

    def parse_callback(
        self,
        callback_data: Dict[str, Any],
    ) -> GatewayResponse:
        """
        Parse VNPay callback data.

        VNPay Response Codes:
        - 00: Success
        - 07: Suspected transaction (pending)
        - 09: Card not registered for online payment
        - 10: Invalid card
        - 11: Card expired
        - 12: Card locked
        - 13: Wrong OTP
        - 24: Transaction cancelled by customer
        - 51: Insufficient funds
        - 65: Transaction limit exceeded
        - 75: Bank under maintenance
        - 79: Wrong PIN (exceeded limit)
        - 99: Other errors

        Args:
            callback_data: Raw callback data from VNPay

        Returns:
            GatewayResponse with parsed data
        """
        # Extract required fields
        txn_ref = callback_data.get("vnp_TxnRef", "")
        response_code = callback_data.get("vnp_ResponseCode", "")
        transaction_no = callback_data.get("vnp_TransactionNo", "")

        # VNPay amount is in "đồng * 100", convert back
        amount_raw = callback_data.get("vnp_Amount", "0")
        try:
            amount = Decimal(str(amount_raw)) / 100
        except (ValueError, TypeError):
            amount = Decimal("0")

        # Parse transaction time
        pay_date_str = callback_data.get("vnp_PayDate", "")
        transaction_time = None
        if pay_date_str:
            try:
                transaction_time = datetime.strptime(pay_date_str, "%Y%m%d%H%M%S")
            except ValueError:
                pass

        # Map response code to status
        if response_code == VNPAY_SUCCESS_CODE:
            status = GatewayStatusEnum.success
            message = "Giao dịch thành công"
        elif response_code in VNPAY_PENDING_CODES:
            status = GatewayStatusEnum.pending
            message = "Giao dịch đang chờ xử lý"
        elif response_code in VNPAY_EXPIRED_CODES:
            status = GatewayStatusEnum.expired
            message = "Giao dịch hết hạn hoặc bị hủy do timeout"
        elif response_code in VNPAY_CANCELLED_CODES:
            status = GatewayStatusEnum.cancelled
            message = "Giao dịch bị hủy bởi khách hàng"
        else:
            status = GatewayStatusEnum.failed
            message = self._get_error_message(response_code)

        return GatewayResponse(
            gateway_ref=txn_ref,
            status=status,
            amount=amount,
            raw_response_code=response_code,
            message=message,
            transaction_time=transaction_time,
            extra_data={
                "vnp_TransactionNo": transaction_no,
                "vnp_BankCode": callback_data.get("vnp_BankCode", ""),
                "vnp_BankTranNo": callback_data.get("vnp_BankTranNo", ""),
                "vnp_CardType": callback_data.get("vnp_CardType", ""),
            }
        )

    def _get_error_message(self, response_code: str) -> str:
        """Get human-readable error message for response code."""
        messages = {
            "01": "Giao dịch đã tồn tại",
            "02": "Merchant không hợp lệ",
            "03": "Dữ liệu gửi sang không đúng định dạng",
            "04": "Khởi tạo GD không thành công do Website đang bị tạm khoá",
            "05": "Giao dịch không thành công do: Quý khách nhập sai mật khẩu thanh toán",
            "06": "Giao dịch không thành công do Quý khách nhập sai mật khẩu xác thực",
            "07": "Giao dịch đang được xử lý",
            "09": "Thẻ/Tài khoản chưa đăng ký dịch vụ Internet Banking",
            "10": "Thẻ không hợp lệ hoặc hết hạn",
            "11": "Thẻ/Tài khoản đã hết hạn sử dụng",
            "12": "Thẻ/Tài khoản đang bị khóa",
            "13": "Quý khách nhập sai OTP",
            "24": "Giao dịch bị hủy bởi khách hàng",
            "51": "Tài khoản không đủ số dư để thực hiện giao dịch",
            "65": "Tài khoản vượt quá hạn mức giao dịch trong ngày",
            "75": "Ngân hàng thanh toán đang bảo trì",
            "79": "Nhập sai mật khẩu quá số lần quy định",
            "99": "Lỗi không xác định",
        }
        return messages.get(response_code, f"Lỗi không xác định (code: {response_code})")

    async def query_transaction(
        self,
        txn_ref: str,
        txn_date: str,
    ) -> Dict[str, Any]:
        """
        Query transaction status from VNPay.

        Used to verify payment status for reconciliation.

        Args:
            txn_ref: Transaction reference (vnp_TxnRef)
            txn_date: Transaction date in format YYYYMMDDHHMMSS

        Returns:
            Transaction status response

        Note:
            This method requires httpx or similar async HTTP client.
            Not implemented in base version - extend as needed.
        """
        # Implementation would use VNPay Query API
        # This is a placeholder for future implementation
        raise NotImplementedError(
            "Transaction query not implemented. "
            "Use VNPay merchant portal for reconciliation."
        )
