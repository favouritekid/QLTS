# app/models/finance/payment_method.py
"""
PaymentMethod Model - Payment method definitions.

Defines available payment methods:
- Offline: Cash, Bank Transfer (require maker-checker verification)
- Online: VNPay, MoMo, ZaloPay (auto-verified via gateway callback)

Seeded with default methods:
- bank_transfer: Manual bank transfer
- cash: Cash payment at counter
- vnpay: VNPay online gateway
- momo: MoMo e-wallet
- zalopay: ZaloPay e-wallet
"""
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class PaymentMethod(Base):
    """
    Payment method configuration.

    For online methods, `gateway_config` stores:
    - For VNPay: {"tmn_code": "...", "hash_secret": "...", "api_url": "..."}
    - For MoMo: {"partner_code": "...", "access_key": "...", "secret_key": "..."}

    Note: Sensitive config should be stored in environment variables and
    referenced here, not stored directly in the database.
    """
    __tablename__ = "payment_method"

    # Note: primary_key already creates an index, no need for explicit index=True
    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # Identification
    code: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        unique=True,
        comment="Unique method code (e.g., cash, bank_transfer, vnpay)"
    )
    name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="Display name"
    )
    description: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True
    )

    # Method type
    is_online: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        comment="True for online gateways (VNPay, MoMo)"
    )
    requires_verification: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
        comment="True for manual payments requiring maker-checker"
    )

    # Gateway configuration (for online methods)
    gateway_code: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
        comment="Gateway identifier for online methods (e.g., vnpay, momo)"
    )
    gateway_config: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=True,
        comment="Gateway-specific configuration"
    )

    # Status & display
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true"
    )
    display_order: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="Display order in UI (lower = first)"
    )

    # Timestamp
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc)
    )

    def __repr__(self) -> str:
        method_type = "online" if self.is_online else "offline"
        return f"<PaymentMethod {self.code} ({method_type})>"

    @property
    def needs_intent(self) -> bool:
        """Check if this method requires a PaymentIntent (online methods)."""
        return self.is_online

    @property
    def needs_verification(self) -> bool:
        """Check if payments with this method need manual verification."""
        return self.requires_verification and not self.is_online
