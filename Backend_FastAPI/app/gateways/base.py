# app/gateways/base.py
"""
Base Gateway Adapter - Protocol definition for payment gateways.

All payment gateway adapters must implement this protocol to ensure
consistent behavior across different payment providers.

Security Requirements (from Section 3.9):
- C1: Verify gateway signatures before processing callbacks
- C2: Validate amounts match exactly with intent
- M14: Idempotent callback processing

Gateway Flow:
    1. create_payment_url() - Generate payment URL for redirect
    2. verify_signature() - Validate callback authenticity
    3. parse_callback() - Extract data from gateway response
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, Optional, Protocol, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.finance import PaymentIntent


class GatewayStatusEnum(str, Enum):
    """Gateway callback status values."""
    success = "success"
    failed = "failed"
    pending = "pending"
    expired = "expired"
    cancelled = "cancelled"


@dataclass
class GatewayResponse:
    """
    Parsed gateway callback response.

    Attributes:
        gateway_ref: Transaction reference from gateway
        status: Parsed status (success, failed, etc.)
        amount: Transaction amount
        raw_response_code: Original response code from gateway
        message: Human-readable status message
        transaction_time: When transaction was processed by gateway
        extra_data: Additional gateway-specific data
    """
    gateway_ref: str
    status: GatewayStatusEnum
    amount: Decimal
    raw_response_code: str = ""
    message: str = ""
    transaction_time: Optional[datetime] = None
    extra_data: Dict[str, Any] = None

    def __post_init__(self):
        if self.extra_data is None:
            self.extra_data = {}


class BaseGatewayAdapter(ABC):
    """
    Abstract base class for payment gateway adapters.

    All gateway implementations must inherit from this class
    and implement the required abstract methods.

    Security:
    - Never log sensitive data (card numbers, secrets)
    - Always verify signatures before processing
    - Validate amount matches exactly

    Example:
        class VNPayAdapter(BaseGatewayAdapter):
            def __init__(self, tmn_code: str, hash_secret: str):
                self.tmn_code = tmn_code
                self.hash_secret = hash_secret

            async def create_payment_url(self, intent, return_url):
                # Build VNPay URL...
                return pay_url, txn_ref
    """

    @property
    @abstractmethod
    def gateway_code(self) -> str:
        """
        Unique gateway identifier (e.g., 'vnpay', 'momo').
        Used for routing callbacks and configuration lookup.
        """
        pass

    @property
    @abstractmethod
    def gateway_name(self) -> str:
        """Human-readable gateway name for display."""
        pass

    @abstractmethod
    async def create_payment_url(
        self,
        intent: "PaymentIntent",
        return_url: str,
    ) -> Tuple[str, str]:
        """
        Create payment URL for gateway redirect.

        Args:
            intent: PaymentIntent containing amount, invoice info
            return_url: URL to redirect after payment completion

        Returns:
            Tuple of (payment_url, gateway_reference)
            - payment_url: URL to redirect user to gateway
            - gateway_reference: Unique transaction ID for tracking

        Raises:
            GatewayError: If URL creation fails
        """
        pass

    @abstractmethod
    def verify_signature(
        self,
        callback_data: Dict[str, Any],
        secret_key: str,
    ) -> bool:
        """
        Verify callback signature from gateway.

        This is CRITICAL for security - never process callbacks
        without signature verification.

        Args:
            callback_data: Raw callback data from gateway
            secret_key: Secret key for HMAC verification

        Returns:
            True if signature is valid, False otherwise
        """
        pass

    @abstractmethod
    def parse_callback(
        self,
        callback_data: Dict[str, Any],
    ) -> GatewayResponse:
        """
        Parse raw callback data into structured response.

        Args:
            callback_data: Raw callback data from gateway

        Returns:
            GatewayResponse with parsed status, amount, etc.
        """
        pass

    def is_success_response(self, response: GatewayResponse) -> bool:
        """Check if gateway response indicates success."""
        return response.status == GatewayStatusEnum.success

    def is_final_response(self, response: GatewayResponse) -> bool:
        """
        Check if response is final (no more updates expected).

        Final states: success, failed, expired, cancelled
        Non-final: pending (may get updated later)
        """
        return response.status in [
            GatewayStatusEnum.success,
            GatewayStatusEnum.failed,
            GatewayStatusEnum.expired,
            GatewayStatusEnum.cancelled,
        ]


class GatewayError(Exception):
    """Base exception for gateway errors."""

    def __init__(
        self,
        message: str,
        gateway_code: str = "",
        response_code: str = "",
        raw_response: Dict[str, Any] = None,
    ):
        super().__init__(message)
        self.gateway_code = gateway_code
        self.response_code = response_code
        self.raw_response = raw_response or {}


class GatewayConnectionError(GatewayError):
    """Error connecting to gateway."""
    pass


class GatewaySignatureError(GatewayError):
    """Invalid signature in gateway callback."""
    pass


class GatewayAmountMismatchError(GatewayError):
    """Amount in callback doesn't match intent."""
    pass
