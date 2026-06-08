"""Finance reporting services."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app import models
from app.models.finance import Fee, Invoice, InvoiceStatusEnum
from app.schemas import finance as finance_schemas
from app.utils.id_helpers import format_profile_code


@dataclass
class _DebtAccumulator:
    admission_profile_id: int
    profile_name: str
    unit_id: Optional[int]
    unit_name: Optional[str]
    academic_year: int
    admission_round_id: Optional[int]
    fee_types: set[str] = field(default_factory=set)
    invoice_count: int = 0
    total_expected: Decimal = Decimal("0")
    total_paid: Decimal = Decimal("0")
    total_outstanding: Decimal = Decimal("0")
    days_overdue: int = 0


class FinanceReportService:
    """Read-only finance report queries."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_debt_report(
        self,
        unit_id: Optional[int] = None,
        academic_year: Optional[int] = None,
        round_id: Optional[int] = None,
        fee_type: Optional[str] = None,
        aging: Optional[str] = None,
    ) -> finance_schemas.DebtReportResponse:
        today = date.today()
        query = (
            select(Invoice)
            .join(Fee)
            .join(models.AdmissionProfile)
            .join(models.Lead)
            .options(
                joinedload(Invoice.fee)
                .joinedload(Fee.admission_profile)
                .joinedload(models.AdmissionProfile.lead)
                .joinedload(models.Lead.unit),
            )
            .where(
                and_(
                    Invoice.status.notin_(
                        [
                            InvoiceStatusEnum.paid.value,
                            InvoiceStatusEnum.cancelled.value,
                        ]
                    ),
                    (Invoice.amount + Invoice.penalty_amount - Invoice.paid_amount) > 0,
                )
            )
        )

        if unit_id is not None:
            query = query.where(models.Lead.unit_id == unit_id)
        if academic_year is not None:
            query = query.where(Fee.academic_year == academic_year)
        if round_id is not None:
            query = query.where(
                models.AdmissionProfile.applied_rules["admission_round_id"].astext
                == str(round_id)
            )
        if fee_type:
            query = query.where(Fee.fee_type == fee_type)

        query = query.order_by(Invoice.due_date.asc(), Invoice.id.asc())
        result = await self.db.execute(query)
        invoices = list(result.scalars().all())

        grouped: dict[int, _DebtAccumulator] = {}
        for invoice in invoices:
            fee = invoice.fee
            if not fee or not fee.admission_profile:
                continue
            profile = fee.admission_profile
            lead = profile.lead
            if not lead:
                continue

            rules = profile.applied_rules or {}
            round_value = rules.get("admission_round_id")
            parsed_round_id: Optional[int]
            try:
                parsed_round_id = int(round_value) if round_value is not None else None
            except (TypeError, ValueError):
                parsed_round_id = None

            accumulator = grouped.get(profile.id)
            if accumulator is None:
                accumulator = _DebtAccumulator(
                    admission_profile_id=profile.id,
                    profile_name=lead.full_name,
                    unit_id=lead.unit_id,
                    unit_name=lead.unit.name if getattr(lead, "unit", None) else None,
                    academic_year=fee.academic_year,
                    admission_round_id=parsed_round_id,
                )
                grouped[profile.id] = accumulator

            outstanding = invoice.remaining_amount
            accumulator.invoice_count += 1
            accumulator.total_expected += invoice.total_due
            accumulator.total_paid += invoice.paid_amount
            accumulator.total_outstanding += outstanding
            accumulator.fee_types.add(str(fee.fee_type))

            if invoice.due_date and invoice.due_date < today:
                accumulator.days_overdue = max(
                    accumulator.days_overdue,
                    (today - invoice.due_date).days,
                )

        rows = [
            self._build_row(accumulator)
            for accumulator in grouped.values()
            if self._matches_aging(accumulator.days_overdue, aging)
        ]
        rows.sort(
            key=lambda row: (
                -row.days_overdue,
                row.profile_name,
                row.admission_profile_id,
            )
        )

        summary = self._build_summary(rows)
        return finance_schemas.DebtReportResponse(items=rows, summary=summary)

    @staticmethod
    def _build_row(accumulator: _DebtAccumulator) -> finance_schemas.DebtReportRow:
        return finance_schemas.DebtReportRow(
            admission_profile_id=accumulator.admission_profile_id,
            profile_code=format_profile_code(accumulator.admission_profile_id),
            profile_name=accumulator.profile_name,
            unit_id=accumulator.unit_id,
            unit_name=accumulator.unit_name,
            academic_year=accumulator.academic_year,
            admission_round_id=accumulator.admission_round_id,
            fee_types=sorted(accumulator.fee_types),
            invoice_count=accumulator.invoice_count,
            total_expected=accumulator.total_expected,
            total_paid=accumulator.total_paid,
            total_outstanding=accumulator.total_outstanding,
            days_overdue=accumulator.days_overdue,
            aging_bucket=FinanceReportService._aging_bucket(accumulator.days_overdue),
        )

    @staticmethod
    def _aging_bucket(days_overdue: int) -> str:
        if days_overdue > 60:
            return "over_60"
        if days_overdue > 30:
            return "31_60"
        return "0_30"

    @staticmethod
    def _matches_aging(days_overdue: int, aging: Optional[str]) -> bool:
        if not aging:
            return True
        return FinanceReportService._aging_bucket(days_overdue) == aging

    @staticmethod
    def _build_summary(
        rows: list[finance_schemas.DebtReportRow],
    ) -> finance_schemas.DebtReportSummary:
        summary = finance_schemas.DebtReportSummary(
            debtor_count=len(rows),
            total_expected=Decimal("0"),
            total_paid=Decimal("0"),
            total_outstanding=Decimal("0"),
        )
        for row in rows:
            summary.total_expected += row.total_expected
            summary.total_paid += row.total_paid
            summary.total_outstanding += row.total_outstanding
            if row.aging_bucket == "over_60":
                summary.bucket_over_60 += row.total_outstanding
            elif row.aging_bucket == "31_60":
                summary.bucket_31_60 += row.total_outstanding
            else:
                summary.bucket_0_30 += row.total_outstanding
        return summary
