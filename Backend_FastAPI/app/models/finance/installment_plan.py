# app/models/finance/installment_plan.py
"""
InstallmentPlan Model - Payment schedule configurations.

Defines how fees can be split into multiple installments.
Each plan specifies:
- Number of installments
- Schedule (due dates, percentages per installment)
- Late payment penalty configuration

Default Plans (seeded):
- FULL: Single payment (100%)
- TWO_TERM: Two payments (50% each)
- QUARTERLY: Four payments (25% each)
"""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy import Boolean, DateTime, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class InstallmentPlan(Base):
    """
    Payment installment plan configuration.

    The `schedule` field is a JSON array defining each installment:
    [
        {
            "installment_no": 1,
            "due_days_offset": 0,      # Days from fee creation
            "percent": 50.0,           # Percentage of total fee
            "description": "Đợt 1"
        },
        {
            "installment_no": 2,
            "due_days_offset": 90,
            "percent": 50.0,
            "description": "Đợt 2"
        }
    ]
    """
    __tablename__ = "installment_plan"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # Identification
    code: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        unique=True,
        comment="Unique plan code (e.g., FULL, TWO_TERM, QUARTERLY)"
    )
    name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        comment="Display name"
    )
    description: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True
    )

    # Schedule configuration
    installment_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
        comment="Number of installments (1-12)"
    )
    schedule: Mapped[List[Dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=False,
        comment="JSON array of installment schedule"
    )

    # Penalty configuration
    penalty_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="percentage",
        server_default="percentage",
        comment="Penalty type: percentage|fixed"
    )
    penalty_rate: Mapped[Decimal] = mapped_column(
        Numeric(5, 2),
        nullable=False,
        default=Decimal("0"),
        server_default="0",
        comment="Penalty rate (% for percentage type, VND for fixed)"
    )
    grace_period_days: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=7,
        server_default="7",
        comment="Days after due date before penalty applies"
    )

    # Status
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true"
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc)
    )

    def __repr__(self) -> str:
        return f"<InstallmentPlan {self.code}: {self.installment_count} installments>"

    def get_installment_schedule(
        self,
        total_amount: Decimal,
        anchor_date: Optional[date] = None,
    ) -> List[Dict[str, Any]]:
        """
        Calculate actual amounts for each installment based on total fee.

        Uses remainder-to-last strategy to avoid rounding issues.

        Args:
            total_amount: Total fee amount
            anchor_date: Optional reference date for computing due_date per
                installment. When provided, each item gains a ``due_date``
                field = ``anchor_date + timedelta(days=due_days_offset)``.
                When None (default), output is unchanged from prior behavior
                (backward compat). Per ADR-002 Decision 3: for HK1 the
                anchor_date is the admission approval timestamp; for HK2+
                it is the semester start date.

        Returns:
            List of installment details with calculated amounts
        """
        if self.installment_count == 1:
            entry: Dict[str, Any] = {
                "installment_no": 1,
                "amount": total_amount,
                "due_days_offset": 0,
                "percent": Decimal("100.0"),
            }
            if anchor_date is not None:
                entry["due_date"] = anchor_date.isoformat()
            return [entry]

        result = []
        cumulative = Decimal("0")

        for i, item in enumerate(self.schedule):
            if i < len(self.schedule) - 1:
                amount = (total_amount * Decimal(str(item.get("percent", 0))) / 100).quantize(
                    Decimal("1")  # Round to VND
                )
            else:
                amount = total_amount - cumulative

            offset = item.get("due_days_offset", 0)
            cumulative += amount
            entry = {
                "installment_no": item.get("installment_no", i + 1),
                "amount": amount,
                "due_days_offset": offset,
                "percent": Decimal(str(item.get("percent", 0))),
                "description": item.get("description", f"Đợt {i + 1}"),
            }
            if anchor_date is not None:
                entry["due_date"] = (anchor_date + timedelta(days=offset)).isoformat()
            result.append(entry)

        # Defense-in-depth: tổng % các đợt vượt 100 → đợt cuối (remainder-to-last)
        # ra ÂM → Invoice amount âm. Schema validate sum==100 ở biên API, nhưng
        # plan dị dạng (sửa JSONB/seed tay) có thể lọt vào runtime — fail-fast.
        # Domain exception (→400) thay vì ValueError (→500 không bắt) để caller
        # (generate_invoices_for_fee / recalculate_fee) trả lỗi sạch.
        if any(e["amount"] < 0 for e in result):
            from app.utils.exceptions import BusinessRuleViolation

            raise BusinessRuleViolation(
                f"Lịch trả góp lỗi (plan id={self.id}): tổng phần trăm các đợt "
                "vượt 100% khiến đợt cuối âm."
            )

        return result
