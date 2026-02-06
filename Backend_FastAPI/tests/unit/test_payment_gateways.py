# tests/unit/test_payment_gateways.py
"""
Unit Tests for Payment Gateway Adapters (Phase 5).

Tests the VNPay and MoMo payment gateway integrations:
- URL generation
- Signature verification
- Callback parsing
- Error handling

Run: pytest tests/unit/test_payment_gateways.py -v
"""

import pytest
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, AsyncMock
import hashlib
import hmac
import urllib.parse

from app.gateways.base import (
    BaseGatewayAdapter,
    GatewayResponse,
    GatewayStatusEnum,
    GatewayError,
    GatewayConnectionError,
    GatewaySignatureError,
)
from app.gateways.vnpay import VNPayAdapter
from app.gateways.momo import MoMoAdapter


# =============================================================================
# BASE GATEWAY TESTS
# =============================================================================

class TestGatewayStatusEnum:
    """Tests for GatewayStatusEnum."""

    def test_status_values(self):
        """All status values should be defined."""
        assert GatewayStatusEnum.success.value == "success"
        assert GatewayStatusEnum.failed.value == "failed"
        assert GatewayStatusEnum.pending.value == "pending"
        assert GatewayStatusEnum.expired.value == "expired"
        assert GatewayStatusEnum.cancelled.value == "cancelled"


class TestGatewayResponse:
    """Tests for GatewayResponse dataclass."""

    def test_gateway_response_creation(self):
        """GatewayResponse should store all fields."""
        response = GatewayResponse(
            gateway_ref="TXN123",
            status=GatewayStatusEnum.success,
            amount=Decimal("1000000"),
            raw_response_code="00",
            message="Giao dịch thành công",
        )

        assert response.gateway_ref == "TXN123"
        assert response.status == GatewayStatusEnum.success
        assert response.amount == Decimal("1000000")

    def test_gateway_response_extra_data(self):
        """GatewayResponse should handle extra_data."""
        response = GatewayResponse(
            gateway_ref="TXN123",
            status=GatewayStatusEnum.success,
            amount=Decimal("1000000"),
            extra_data={"bank_code": "VCB", "card_type": "ATM"},
        )

        assert response.extra_data["bank_code"] == "VCB"

    def test_gateway_response_default_extra_data(self):
        """GatewayResponse should default extra_data to empty dict."""
        response = GatewayResponse(
            gateway_ref="TXN123",
            status=GatewayStatusEnum.success,
            amount=Decimal("1000000"),
        )

        assert response.extra_data == {}


class TestGatewayErrors:
    """Tests for gateway exception classes."""

    def test_gateway_error(self):
        """GatewayError should store details."""
        error = GatewayError(
            message="Connection failed",
            gateway_code="vnpay",
            response_code="99",
            raw_response={"error": "timeout"},
        )

        assert str(error) == "Connection failed"
        assert error.gateway_code == "vnpay"
        assert error.response_code == "99"

    def test_gateway_connection_error(self):
        """GatewayConnectionError should be a GatewayError."""
        error = GatewayConnectionError("Cannot connect to gateway")
        assert isinstance(error, GatewayError)

    def test_gateway_signature_error(self):
        """GatewaySignatureError should be a GatewayError."""
        error = GatewaySignatureError("Invalid signature")
        assert isinstance(error, GatewayError)


# =============================================================================
# VNPAY ADAPTER TESTS
# =============================================================================

class TestVNPayAdapter:
    """Tests for VNPay payment gateway adapter."""

    @pytest.fixture
    def vnpay_adapter(self):
        """Create VNPay adapter with test credentials."""
        return VNPayAdapter(
            tmn_code="DEMO_TMN",
            hash_secret="DEMO_SECRET_KEY_12345",
            payment_url="https://sandbox.vnpayment.vn/paymentv2/vpcpay.html",
        )

    @pytest.fixture
    def mock_payment_intent(self):
        """Create mock payment intent."""
        intent = MagicMock()
        intent.id = 123
        intent.invoice_id = 456
        intent.amount = Decimal("1000000")
        intent.invoice = MagicMock()
        intent.invoice.invoice_number = "INV-2025-0001"
        return intent

    def test_gateway_code(self, vnpay_adapter):
        """VNPay adapter should return 'vnpay' as gateway code."""
        assert vnpay_adapter.gateway_code == "vnpay"

    def test_gateway_name(self, vnpay_adapter):
        """VNPay adapter should return 'VNPay' as gateway name."""
        assert vnpay_adapter.gateway_name == "VNPay"

    @pytest.mark.asyncio
    async def test_create_payment_url(self, vnpay_adapter, mock_payment_intent):
        """create_payment_url should generate valid VNPay URL."""
        return_url = "https://app.example.com/payment/return"

        pay_url, txn_ref = await vnpay_adapter.create_payment_url(
            intent=mock_payment_intent,
            return_url=return_url,
        )

        # URL should contain required params
        assert "vnp_TmnCode=DEMO_TMN" in pay_url
        assert "vnp_Amount=100000000" in pay_url  # VNPay uses amount * 100
        assert "vnp_ReturnUrl=" in pay_url
        assert "vnp_SecureHash=" in pay_url

        # Transaction ref should include intent ID
        assert "QLTS123" in txn_ref

    @pytest.mark.asyncio
    async def test_create_payment_url_without_config_raises_error(self, mock_payment_intent):
        """create_payment_url should raise error if not configured."""
        adapter = VNPayAdapter(
            tmn_code="",
            hash_secret="",
        )

        with pytest.raises(GatewayError) as exc_info:
            await adapter.create_payment_url(
                intent=mock_payment_intent,
                return_url="https://example.com/return",
            )

        assert "not configured" in str(exc_info.value)

    def test_verify_signature_valid(self, vnpay_adapter):
        """verify_signature should return True for valid signature."""
        # Build valid callback data with signature
        params = {
            "vnp_TxnRef": "QLTS123456",
            "vnp_Amount": "100000000",
            "vnp_ResponseCode": "00",
            "vnp_TransactionNo": "123456789",
        }

        # Calculate signature
        sorted_params = sorted(params.items())
        query_string = "&".join(
            f"{k}={urllib.parse.quote_plus(str(v))}"
            for k, v in sorted_params
        )
        signature = hmac.new(
            "DEMO_SECRET_KEY_12345".encode("utf-8"),
            query_string.encode("utf-8"),
            hashlib.sha512
        ).hexdigest()

        params["vnp_SecureHash"] = signature

        is_valid = vnpay_adapter.verify_signature(
            callback_data=params,
            secret_key="DEMO_SECRET_KEY_12345",
        )

        assert is_valid is True

    def test_verify_signature_invalid(self, vnpay_adapter):
        """verify_signature should return False for invalid signature."""
        params = {
            "vnp_TxnRef": "QLTS123456",
            "vnp_Amount": "100000000",
            "vnp_ResponseCode": "00",
            "vnp_SecureHash": "invalid_signature_here",
        }

        is_valid = vnpay_adapter.verify_signature(
            callback_data=params,
            secret_key="DEMO_SECRET_KEY_12345",
        )

        assert is_valid is False

    def test_verify_signature_missing(self, vnpay_adapter):
        """verify_signature should return False if signature missing."""
        params = {
            "vnp_TxnRef": "QLTS123456",
            "vnp_Amount": "100000000",
        }

        is_valid = vnpay_adapter.verify_signature(
            callback_data=params,
            secret_key="DEMO_SECRET_KEY_12345",
        )

        assert is_valid is False

    def test_parse_callback_success(self, vnpay_adapter):
        """parse_callback should parse successful response."""
        callback_data = {
            "vnp_TxnRef": "QLTS123456",
            "vnp_ResponseCode": "00",
            "vnp_Amount": "100000000",  # 1,000,000 VND (VNPay format)
            "vnp_TransactionNo": "987654321",
            "vnp_PayDate": "20250131120000",
            "vnp_BankCode": "VCB",
        }

        response = vnpay_adapter.parse_callback(callback_data)

        assert response.gateway_ref == "QLTS123456"
        assert response.status == GatewayStatusEnum.success
        assert response.amount == Decimal("1000000")  # Converted back
        assert response.raw_response_code == "00"
        assert response.extra_data["vnp_BankCode"] == "VCB"

    def test_parse_callback_failed(self, vnpay_adapter):
        """parse_callback should parse failed response."""
        callback_data = {
            "vnp_TxnRef": "QLTS123456",
            "vnp_ResponseCode": "51",  # Insufficient funds
            "vnp_Amount": "100000000",
        }

        response = vnpay_adapter.parse_callback(callback_data)

        assert response.status == GatewayStatusEnum.failed
        assert response.raw_response_code == "51"

    def test_parse_callback_expired(self, vnpay_adapter):
        """parse_callback should parse expired response."""
        callback_data = {
            "vnp_TxnRef": "QLTS123456",
            "vnp_ResponseCode": "24",  # User cancelled / timeout
            "vnp_Amount": "100000000",
        }

        response = vnpay_adapter.parse_callback(callback_data)

        assert response.status == GatewayStatusEnum.expired

    def test_parse_callback_with_transaction_time(self, vnpay_adapter):
        """parse_callback should parse transaction time."""
        callback_data = {
            "vnp_TxnRef": "QLTS123456",
            "vnp_ResponseCode": "00",
            "vnp_Amount": "100000000",
            "vnp_PayDate": "20250131143000",
        }

        response = vnpay_adapter.parse_callback(callback_data)

        assert response.transaction_time is not None
        assert response.transaction_time.year == 2025
        assert response.transaction_time.month == 1
        assert response.transaction_time.day == 31

    def test_from_settings(self):
        """from_settings should create adapter from settings object."""
        mock_settings = MagicMock()
        mock_settings.VNPAY_TMN_CODE = "TEST_TMN"
        mock_settings.VNPAY_HASH_SECRET = "TEST_SECRET"
        mock_settings.VNPAY_PAYMENT_URL = "https://test.vnpay.vn"
        mock_settings.VNPAY_API_URL = "https://api.vnpay.vn"

        adapter = VNPayAdapter.from_settings(mock_settings)

        assert adapter.tmn_code == "TEST_TMN"
        assert adapter.hash_secret == "TEST_SECRET"


# =============================================================================
# MOMO ADAPTER TESTS
# =============================================================================

class TestMoMoAdapter:
    """Tests for MoMo payment gateway adapter."""

    @pytest.fixture
    def momo_adapter(self):
        """Create MoMo adapter with test credentials."""
        return MoMoAdapter(
            partner_code="DEMO_PARTNER",
            access_key="DEMO_ACCESS_KEY",
            secret_key="DEMO_SECRET_KEY_12345",
            endpoint="https://test-payment.momo.vn/v2/gateway/api/create",
        )

    @pytest.fixture
    def mock_payment_intent(self):
        """Create mock payment intent."""
        intent = MagicMock()
        intent.id = 123
        intent.invoice_id = 456
        intent.amount = Decimal("1000000")
        intent.invoice = MagicMock()
        intent.invoice.invoice_number = "INV-2025-0001"
        return intent

    def test_gateway_code(self, momo_adapter):
        """MoMo adapter should return 'momo' as gateway code."""
        assert momo_adapter.gateway_code == "momo"

    def test_gateway_name(self, momo_adapter):
        """MoMo adapter should return 'MoMo' as gateway name."""
        assert momo_adapter.gateway_name == "MoMo"

    @pytest.mark.asyncio
    async def test_create_payment_url(self, momo_adapter, mock_payment_intent):
        """create_payment_url should generate valid MoMo URL."""
        return_url = "https://app.example.com/payment/return"

        pay_url, request_id = await momo_adapter.create_payment_url(
            intent=mock_payment_intent,
            return_url=return_url,
        )

        # URL should be MoMo payment URL
        assert "momo.vn" in pay_url
        assert "requestId=" in pay_url

        # Request ID should include intent ID
        assert "QLTS123" in request_id

    @pytest.mark.asyncio
    async def test_create_payment_url_without_config_raises_error(self, mock_payment_intent):
        """create_payment_url should raise error if not configured."""
        adapter = MoMoAdapter(
            partner_code="",
            access_key="",
            secret_key="",
        )

        with pytest.raises(GatewayError) as exc_info:
            await adapter.create_payment_url(
                intent=mock_payment_intent,
                return_url="https://example.com/return",
            )

        assert "not configured" in str(exc_info.value)

    def test_verify_signature_valid(self, momo_adapter):
        """verify_signature should return True for valid signature."""
        # Build valid callback data
        callback_data = {
            "amount": "1000000",
            "extraData": "",
            "message": "Giao dịch thành công",
            "orderId": "ORDER123",
            "orderInfo": "Test payment",
            "orderType": "momo_wallet",
            "partnerCode": "DEMO_PARTNER",
            "payType": "qr",
            "requestId": "REQ123",
            "responseTime": "1706698800000",
            "resultCode": "0",
            "transId": "TXN123",
        }

        # Calculate signature
        raw_signature = (
            f"accessKey={momo_adapter.access_key}"
            f"&amount={callback_data['amount']}"
            f"&extraData={callback_data['extraData']}"
            f"&message={callback_data['message']}"
            f"&orderId={callback_data['orderId']}"
            f"&orderInfo={callback_data['orderInfo']}"
            f"&orderType={callback_data['orderType']}"
            f"&partnerCode={callback_data['partnerCode']}"
            f"&payType={callback_data['payType']}"
            f"&requestId={callback_data['requestId']}"
            f"&responseTime={callback_data['responseTime']}"
            f"&resultCode={callback_data['resultCode']}"
            f"&transId={callback_data['transId']}"
        )

        signature = hmac.new(
            "DEMO_SECRET_KEY_12345".encode("utf-8"),
            raw_signature.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()

        callback_data["signature"] = signature

        is_valid = momo_adapter.verify_signature(
            callback_data=callback_data,
            secret_key="DEMO_SECRET_KEY_12345",
        )

        assert is_valid is True

    def test_verify_signature_invalid(self, momo_adapter):
        """verify_signature should return False for invalid signature."""
        callback_data = {
            "amount": "1000000",
            "extraData": "",
            "message": "Test",
            "orderId": "ORDER123",
            "orderInfo": "Test",
            "orderType": "momo_wallet",
            "partnerCode": "DEMO_PARTNER",
            "payType": "qr",
            "requestId": "REQ123",
            "responseTime": "1706698800000",
            "resultCode": "0",
            "transId": "TXN123",
            "signature": "invalid_signature",
        }

        is_valid = momo_adapter.verify_signature(
            callback_data=callback_data,
            secret_key="DEMO_SECRET_KEY_12345",
        )

        assert is_valid is False

    def test_verify_signature_missing(self, momo_adapter):
        """verify_signature should return False if signature missing."""
        callback_data = {
            "amount": "1000000",
            "requestId": "REQ123",
        }

        is_valid = momo_adapter.verify_signature(
            callback_data=callback_data,
            secret_key="DEMO_SECRET_KEY_12345",
        )

        assert is_valid is False

    def test_parse_callback_success(self, momo_adapter):
        """parse_callback should parse successful response."""
        callback_data = {
            "requestId": "REQ123",
            "resultCode": 0,
            "message": "Giao dịch thành công",
            "amount": "1000000",
            "transId": "TXN123456",
            "responseTime": "1706698800000",  # Timestamp in ms
            "orderType": "momo_wallet",
            "payType": "qr",
            "orderId": "ORDER123",
        }

        response = momo_adapter.parse_callback(callback_data)

        assert response.gateway_ref == "REQ123"
        assert response.status == GatewayStatusEnum.success
        assert response.amount == Decimal("1000000")
        assert response.extra_data["transId"] == "TXN123456"

    def test_parse_callback_9000_success(self, momo_adapter):
        """parse_callback should treat 9000 as success."""
        callback_data = {
            "requestId": "REQ123",
            "resultCode": 9000,
            "amount": "1000000",
        }

        response = momo_adapter.parse_callback(callback_data)
        assert response.status == GatewayStatusEnum.success

    def test_parse_callback_pending(self, momo_adapter):
        """parse_callback should parse pending response."""
        callback_data = {
            "requestId": "REQ123",
            "resultCode": 8000,  # Processing
            "amount": "1000000",
        }

        response = momo_adapter.parse_callback(callback_data)
        assert response.status == GatewayStatusEnum.pending

    def test_parse_callback_failed(self, momo_adapter):
        """parse_callback should parse failed response."""
        callback_data = {
            "requestId": "REQ123",
            "resultCode": 1001,  # Insufficient funds
            "message": "Số dư không đủ",
            "amount": "1000000",
        }

        response = momo_adapter.parse_callback(callback_data)

        assert response.status == GatewayStatusEnum.failed
        assert response.raw_response_code == "1001"

    def test_parse_callback_cancelled(self, momo_adapter):
        """parse_callback should parse cancelled response."""
        callback_data = {
            "requestId": "REQ123",
            "resultCode": 1005,
            "amount": "1000000",
        }

        response = momo_adapter.parse_callback(callback_data)
        assert response.status == GatewayStatusEnum.cancelled

    def test_parse_callback_expired(self, momo_adapter):
        """parse_callback should parse expired response."""
        callback_data = {
            "requestId": "REQ123",
            "resultCode": 1004,  # Expired
            "amount": "1000000",
        }

        response = momo_adapter.parse_callback(callback_data)
        assert response.status == GatewayStatusEnum.expired

    def test_from_settings(self):
        """from_settings should create adapter from settings object."""
        mock_settings = MagicMock()
        mock_settings.MOMO_PARTNER_CODE = "TEST_PARTNER"
        mock_settings.MOMO_ACCESS_KEY = "TEST_ACCESS"
        mock_settings.MOMO_SECRET_KEY = "TEST_SECRET"
        mock_settings.MOMO_ENDPOINT = "https://test.momo.vn"

        adapter = MoMoAdapter.from_settings(mock_settings)

        assert adapter.partner_code == "TEST_PARTNER"
        assert adapter.secret_key == "TEST_SECRET"


# =============================================================================
# BASE ADAPTER TESTS
# =============================================================================

class TestBaseGatewayAdapter:
    """Tests for BaseGatewayAdapter abstract methods."""

    def test_is_success_response(self):
        """is_success_response should check for success status."""
        adapter = VNPayAdapter("test", "test")

        success_response = GatewayResponse(
            gateway_ref="TXN123",
            status=GatewayStatusEnum.success,
            amount=Decimal("1000000"),
        )
        assert adapter.is_success_response(success_response) is True

        failed_response = GatewayResponse(
            gateway_ref="TXN123",
            status=GatewayStatusEnum.failed,
            amount=Decimal("1000000"),
        )
        assert adapter.is_success_response(failed_response) is False

    def test_is_final_response(self):
        """is_final_response should check for terminal states."""
        adapter = VNPayAdapter("test", "test")

        # Final states
        for status in [
            GatewayStatusEnum.success,
            GatewayStatusEnum.failed,
            GatewayStatusEnum.expired,
            GatewayStatusEnum.cancelled,
        ]:
            response = GatewayResponse(
                gateway_ref="TXN123",
                status=status,
                amount=Decimal("1000000"),
            )
            assert adapter.is_final_response(response) is True

        # Non-final state
        pending_response = GatewayResponse(
            gateway_ref="TXN123",
            status=GatewayStatusEnum.pending,
            amount=Decimal("1000000"),
        )
        assert adapter.is_final_response(pending_response) is False


# =============================================================================
# INTEGRATION TESTS
# =============================================================================

class TestGatewayIntegration:
    """Integration tests for gateway adapters."""

    @pytest.mark.asyncio
    async def test_vnpay_full_flow(self):
        """Test VNPay create URL -> callback flow."""
        adapter = VNPayAdapter(
            tmn_code="DEMO_TMN",
            hash_secret="DEMO_SECRET_KEY_12345",
        )

        # 1. Create payment URL
        mock_intent = MagicMock()
        mock_intent.id = 1
        mock_intent.invoice_id = 100
        mock_intent.amount = Decimal("500000")

        pay_url, txn_ref = await adapter.create_payment_url(
            intent=mock_intent,
            return_url="https://app.example.com/return",
        )

        assert txn_ref.startswith("QLTS1")

        # 2. Simulate callback
        callback_data = {
            "vnp_TxnRef": txn_ref,
            "vnp_ResponseCode": "00",
            "vnp_Amount": "50000000",  # VNPay format
            "vnp_TransactionNo": "123456",
        }

        response = adapter.parse_callback(callback_data)

        assert response.gateway_ref == txn_ref
        assert response.status == GatewayStatusEnum.success
        assert response.amount == Decimal("500000")

    @pytest.mark.asyncio
    async def test_momo_full_flow(self):
        """Test MoMo create URL -> callback flow."""
        adapter = MoMoAdapter(
            partner_code="DEMO_PARTNER",
            access_key="DEMO_ACCESS",
            secret_key="DEMO_SECRET_KEY_12345",
        )

        # 1. Create payment URL
        mock_intent = MagicMock()
        mock_intent.id = 1
        mock_intent.invoice_id = 100
        mock_intent.amount = Decimal("500000")

        pay_url, request_id = await adapter.create_payment_url(
            intent=mock_intent,
            return_url="https://app.example.com/return",
        )

        assert request_id.startswith("QLTS1")

        # 2. Simulate callback
        callback_data = {
            "requestId": request_id,
            "resultCode": 0,
            "amount": "500000",
            "message": "Success",
        }

        response = adapter.parse_callback(callback_data)

        assert response.gateway_ref == request_id
        assert response.status == GatewayStatusEnum.success
        assert response.amount == Decimal("500000")
