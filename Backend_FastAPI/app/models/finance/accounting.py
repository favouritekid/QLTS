# app/models/finance/accounting.py
"""
Accounting Models - Period tracking.

AccountingPeriod:
- Tracks monthly accounting periods
- When closed, no transactions can be recorded for that period
- Used for financial reporting and ledger integrity
"""
from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Dict, Optional

from sqlalchemy import (
    Boolean, DateTime, ForeignKey, Integer,
    Numeric, String, Text, UniqueConstraint
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.user import User


class AccountingPeriod(Base):
    """
    Ledger period tracking for financial reporting.

    Once a period is closed:
    - No new transactions can be recorded for that period
    - Existing transactions cannot be modified
    - Reversal transactions must be recorded in the current open period

    Business Rule (from Section 3.9 H7):
    - Previous period must be closed before opening a new one
    - Prevents ledger gaps
    """
    __tablename__ = "accounting_period"

    __table_args__ = (
        UniqueConstraint(
            'period_month', 'period_year',
            name='uq_accounting_period_month_year'
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # Period identification
    period_month: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="Month (1-12)"
    )
    period_year: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="Year (e.g., 2026)"
    )

    # Status
    is_closed: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        comment="True if period is closed (no more transactions allowed)"
    )
    closed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True
    )
    closed_by_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True,
        index=True
    )

    # Summary totals (updated when period is closed)
    total_revenue: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
        default=Decimal("0"),
        server_default="0",
        comment="Total revenue in this period"
    )
    total_payments: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
        default=Decimal("0"),
        server_default="0",
        comment="Total payments received"
    )
    total_refunds: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
        default=Decimal("0"),
        server_default="0",
        comment="Total refunds issued"
    )

    # Notes
    notes: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True
    )

    # Timestamp
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    closed_by: Mapped[Optional["User"]] = relationship(
        "User",
        foreign_keys=[closed_by_id]
    )

    def __repr__(self) -> str:
        status = "closed" if self.is_closed else "open"
        return f"<AccountingPeriod {self.period_year}-{self.period_month:02d} ({status})>"

    @property
    def period_key(self) -> str:
        """Get period key in YYYY-MM format."""
        return f"{self.period_year}-{self.period_month:02d}"

    @property
    def net_revenue(self) -> Decimal:
        """Calculate net revenue (payments - refunds)."""
        return self.total_payments - self.total_refunds

