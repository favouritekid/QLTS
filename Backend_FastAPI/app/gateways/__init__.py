# app/gateways/__init__.py
"""
Payment Gateway Adapters for Finance Module.

This module provides adapters for various payment gateways:
- VNPay: Vietnam's leading payment gateway
- MoMo: Mobile money wallet

Architecture:
- All adapters implement BaseGatewayAdapter protocol
- Adapters are registered with PaymentIntentService at startup
- Gateway configuration from environment variables

Usage:
    from app.gateways import VNPayAdapter, MoMoAdapter

    vnpay = VNPayAdapter.from_settings(settings)
    payment_service.register_gateway("vnpay", vnpay)
"""

from app.gateways.base import BaseGatewayAdapter, GatewayResponse
from app.gateways.vnpay import VNPayAdapter
from app.gateways.momo import MoMoAdapter

__all__ = [
    "BaseGatewayAdapter",
    "GatewayResponse",
    "VNPayAdapter",
    "MoMoAdapter",
]
