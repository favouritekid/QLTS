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
from app.models.finance import Fee, Invoice, PAYABLE_INVOICE_STATUSES
from app.schemas import finance as finance_schemas
from app.utils.export_builder import build_simple_export
from app.utils.id_helpers import format_profile_code

# Nhãn cột file xuất công nợ.
# ⚠️ Hai cột tiền ghi rõ "(đợt còn nợ)": truy vấn CHỈ lấy hoá đơn còn dư nợ nên
# tiền của đợt đã trả xong không có ở đây. Nhãn cũ ("Phải thu"/"Đã thu") khiến
# người đọc tưởng là tổng của cả hồ sơ.
DEBT_REPORT_COLUMNS = [
    "Mã hồ sơ",                 # 0
    "Họ và tên",                # 1
    "Đơn vị",                   # 2
    "Năm học",                  # 3
    "Đợt tuyển sinh",           # 4
    "Loại phí",                 # 5
    "Số hoá đơn còn nợ",        # 6
    "Phải thu (đợt còn nợ)",    # 7
    "Đã thu (đợt còn nợ)",      # 8
    "Còn nợ",                   # 9
    "Số ngày quá hạn",          # 10
    "Nhóm tuổi nợ",             # 11
]
_DEBT_MONEY_INDEXES = {7, 8, 9}
_DEBT_TEXT_INDEXES = {1, 2, 5}
_DEBT_FORCE_TEXT_INDEXES = {0, 3}
_DEBT_COLUMN_WIDTHS = [12, 26, 20, 12, 16, 22, 18, 20, 20, 18, 16, 18]

_AGING_LABELS = {
    "0_30": "0–30 ngày",
    "31_60": "31–60 ngày",
    "over_60": "Trên 60 ngày",
    "current": "Chưa quá hạn",
}


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
                    # F7: only collectible invoices count as debt. Draft (generated
                    # but not issued) invoices cannot accept payment, so including
                    # them would overstate debtor balances.
                    Invoice.status.in_(PAYABLE_INVOICE_STATUSES),
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

        # Grain = (profile, academic_year). Grouping by profile alone would label a
        # multi-year debtor with one year while summing outstanding across years,
        # and break per-year filtering (#6).
        grouped: dict[tuple[int, int], _DebtAccumulator] = {}
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

            group_key = (profile.id, fee.academic_year)
            accumulator = grouped.get(group_key)
            if accumulator is None:
                accumulator = _DebtAccumulator(
                    admission_profile_id=profile.id,
                    profile_name=lead.full_name,
                    unit_id=lead.unit_id,
                    unit_name=lead.unit.name if getattr(lead, "unit", None) else None,
                    academic_year=fee.academic_year,
                    admission_round_id=parsed_round_id,
                )
                grouped[group_key] = accumulator

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

    async def build_debt_report_export(
        self,
        *,
        fmt: str,
        exporter_name: str,
        unit_id: Optional[int] = None,
        academic_year: Optional[int] = None,
        round_id: Optional[int] = None,
        fee_type: Optional[str] = None,
        aging: Optional[str] = None,
    ) -> tuple[bytes, str, str]:
        """Báo cáo công nợ → tệp xuất ``(content, media_type, filename)``.

        Gọi thẳng ``get_debt_report`` để file xuất và màn hình **không thể lệch
        nhau** — trước đây CSV được dựng ở trình duyệt từ dữ liệu đã tải, mà
        header là khoá kỹ thuật tiếng Anh, không có BOM (Excel tiếng Việt đọc
        mojibake) và ô tiền bị bọc thành chuỗi nên không cộng được.

        ⚠️ Nhãn hai cột tiền nói rõ "đợt còn nợ": truy vấn CHỈ lấy hoá đơn còn
        dư nợ, nên tiền của các đợt đã trả xong không nằm trong đây. Báo cáo tự
        nhất quán (phải thu − đã thu = còn nợ) nhưng nếu đọc "Đã thu" là "tổng
        đã thu của hồ sơ" thì sai.
        """
        report = await self.get_debt_report(
            unit_id=unit_id,
            academic_year=academic_year,
            round_id=round_id,
            fee_type=fee_type,
            aging=aging,
        )

        rows: list[list] = []
        for item in report.items:
            rows.append(
                [
                    item.profile_code,
                    item.profile_name,
                    item.unit_name or "",
                    item.academic_year,
                    item.admission_round_id if item.admission_round_id else "",
                    " | ".join(sorted(item.fee_types)),
                    item.invoice_count,
                    Decimal(item.total_expected),
                    Decimal(item.total_paid),
                    Decimal(item.total_outstanding),
                    item.days_overdue,
                    _AGING_LABELS.get(item.aging_bucket, item.aging_bucket),
                ]
            )

        applied_filters = {
            label: value
            for label, value in (
                ("Năm học", academic_year),
                ("Đợt tuyển sinh", round_id),
                ("Loại phí", fee_type),
                ("Nhóm tuổi nợ", _AGING_LABELS.get(aging or "", aging)),
            )
            if value not in (None, "")
        }

        return build_simple_export(
            columns=DEBT_REPORT_COLUMNS,
            rows=rows,
            money_indexes=_DEBT_MONEY_INDEXES,
            text_indexes=_DEBT_TEXT_INDEXES,
            force_text_indexes=_DEBT_FORCE_TEXT_INDEXES,
            fmt=fmt,
            filename_stem="bao_cao_cong_no",
            sheet_title="Bao cao cong no",
            exporter_name=exporter_name,
            applied_filters=applied_filters,
            column_widths=_DEBT_COLUMN_WIDTHS,
            notes=[
                (
                    "Phạm vi số liệu",
                    "Chỉ gồm các ĐỢT THU CÒN NỢ. Tiền của đợt đã trả xong không "
                    "nằm trong hai cột 'Phải thu' và 'Đã thu' — vì vậy 'Đã thu' "
                    "ở đây KHÔNG phải tổng đã thu của hồ sơ.",
                ),
            ],
        )

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
