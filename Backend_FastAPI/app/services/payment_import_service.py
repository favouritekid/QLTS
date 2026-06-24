# app/services/payment_import_service.py
"""
Payment Import Service (BV-2) - parse + resolve/validate (READ-ONLY preview).

Kế toán thu offline → import file mẫu → hệ thống đối chiếu từng dòng theo CCCD,
phân bổ FIFO (chỉ GỐC học phí) và phân loại MATCHED / WARNING / ERROR. BV-2 KHÔNG
ghi Payment — chỉ đọc + tính + (tùy chọn) lưu batch 'preview' để xem trước.

Ref: Documents/BULK_PAYMENT_IMPORT_VERIFY_PLAN.md (DESIGN v2). 7 điểm bắt buộc:
1. đọc dtype=str CCCD/ref/amount · 2. method 'bank_transfer' · 3. fee active-only
· 4. FIFO principal-first · 5. chống double-alloc trong batch · 6. IDOR + CCCD lỗi
sạch · 7. resolve read-only thuần.
"""
import hashlib
import io
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Dict, List, Optional

import pandas as pd
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.models.finance import (
    Fee, Invoice, PaymentMethod, FeeStatusEnum,
    InvoiceStatusEnum, PAYABLE_INVOICE_STATUSES,
    PaymentImportBatch, PaymentImportRow,
    PaymentImportBatchStatusEnum, PaymentImportRowStatusEnum,
)
from app.utils.csv_helpers import sanitize_csv_cell
from app.utils.exceptions import BadRequest

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Template columns (tiếng Việt — chốt 06-24) + mapping
# ---------------------------------------------------------------------------
COL_CCCD = "Số CCCD"
COL_NAME = "Họ và tên học sinh"
COL_AMOUNT = "Số tiền thu (VNĐ)"
COL_DATE = "Ngày thu"
COL_METHOD = "Hình thức"
COL_REF = "Mã tham chiếu"
COL_NOTE = "Ghi chú"

REQUIRED_COLS = [COL_CCCD, COL_AMOUNT, COL_DATE, COL_METHOD]
TEMPLATE_COLS = [COL_CCCD, COL_NAME, COL_AMOUNT, COL_DATE, COL_METHOD, COL_REF, COL_NOTE]

# Hình thức → PaymentMethod.code thực (seed fin20260131002): cash / bank_transfer.
METHOD_MAP = {
    "tiền mặt": "cash", "tien mat": "cash", "tm": "cash", "cash": "cash",
    "chuyển khoản": "bank_transfer", "chuyen khoan": "bank_transfer",
    "ck": "bank_transfer", "bank_transfer": "bank_transfer",
}

CCCD_RE = re.compile(r"^\d{12}$")
MAX_IMPORT_ROWS = 5000


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------
@dataclass
class RowDraft:
    """Một dòng file đã parse (chưa resolve)."""
    row_no: int
    citizen_id: str
    name: str
    amount: Optional[Decimal]
    payment_date: Optional[date]
    method_code: Optional[str]
    reference: str
    note: str
    raw: dict
    parse_error: Optional[str] = None


@dataclass
class Allocation:
    """Một phần phân bổ vào 1 invoice (đợt)."""
    invoice_id: int
    installment_no: int
    amount: Decimal


@dataclass
class RowResult:
    row_no: int
    status: str                       # matched | warned | error
    message: Optional[str] = None
    citizen_id: Optional[str] = None
    profile_id: Optional[int] = None
    fee_id: Optional[int] = None
    amount: Optional[Decimal] = None
    method_code: Optional[str] = None
    payment_date: Optional[date] = None
    reference: Optional[str] = None
    allocations: List[Allocation] = field(default_factory=list)
    raw: dict = field(default_factory=dict)


@dataclass
class PreviewResult:
    rows: List[RowResult]
    matched_count: int
    warned_count: int
    failed_count: int
    total_amount: Decimal


# ---------------------------------------------------------------------------
# Parse helpers
# ---------------------------------------------------------------------------
def _norm(s: Optional[str]) -> str:
    return (s or "").strip()


def _norm_name(s: Optional[str]) -> str:
    """Bỏ dấu + lower + gộp khoảng trắng để cross-check tên."""
    s = unicodedata.normalize("NFD", _norm(s))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return " ".join(s.lower().split())


def parse_amount_vn(raw: str) -> Decimal:
    """Parse số tiền kiểu VN. '.' = phân cách nghìn, ',' = thập phân.

    "7.200.000" -> 7200000 · "7.200.000,50" -> 7200000.50 · "7200000.0" (float
    string từ Excel, nhóm cuối 1 chữ số) -> 7200000. Heuristic: '.' với nhóm cuối
    đúng 3 chữ số = phân cách nghìn; nếu không -> thập phân.
    """
    s = _norm(raw).replace(" ", "").replace(" ", "")
    if not s:
        raise ValueError("trống")
    if "," in s:                                  # ',' = thập phân VN
        s = s.replace(".", "").replace(",", ".")
    elif "." in s:                                # '.' nhập nhằng
        if len(s.rsplit(".", 1)[1]) == 3:         # nhóm cuối 3 chữ số -> nghìn
            s = s.replace(".", "")
        # else: '.' là thập phân (float string) -> giữ nguyên
    try:
        val = Decimal(s)
    except InvalidOperation:
        raise ValueError(f"số tiền không hợp lệ: '{raw}'")
    if val <= 0:
        raise ValueError("số tiền phải > 0")
    return val


def parse_date_vn(raw: str) -> date:
    """dd/mm/yyyy (hoặc dd-mm-yyyy)."""
    s = _norm(raw)
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"ngày không hợp lệ (cần dd/mm/yyyy): '{raw}'")


def file_sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def parse_template(content: bytes, filename: str) -> List[RowDraft]:
    """Đọc file mẫu → list RowDraft. CCCD/ref/amount đọc **dtype=str** (giữ số 0
    đầu / không float). Lỗi từng dòng ghi vào ``parse_error`` (không raise)."""
    ext = (filename.rsplit(".", 1)[-1] or "").lower()
    if ext not in ("csv", "xlsx"):
        raise BadRequest("Chỉ hỗ trợ file .xlsx hoặc .csv")
    if not content:
        raise BadRequest("File rỗng")
    try:
        if ext == "csv":
            df = pd.read_csv(io.BytesIO(content), dtype=str)
        else:
            df = pd.read_excel(io.BytesIO(content), engine="openpyxl", dtype=str)
    except Exception as exc:  # noqa: BLE001
        raise BadRequest(f"Không đọc được file: {exc}")

    df = df.fillna("")
    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        raise BadRequest(f"File thiếu cột bắt buộc: {', '.join(missing)}")

    if len(df) > MAX_IMPORT_ROWS:
        raise BadRequest(
            f"File {len(df)} dòng vượt giới hạn {MAX_IMPORT_ROWS} dòng/lần import.")

    drafts: List[RowDraft] = []
    for i, row in df.iterrows():
        row_no = int(i) + 1
        raw = {c: sanitize_csv_cell(row.get(c, "")) for c in df.columns}
        cccd = _norm(str(row.get(COL_CCCD, "")))
        name = _norm(str(row.get(COL_NAME, "")))
        ref = _norm(str(row.get(COL_REF, "")))
        note = _norm(str(row.get(COL_NOTE, "")))

        err = None
        amount = None
        try:
            amount = parse_amount_vn(str(row.get(COL_AMOUNT, "")))
        except ValueError as e:
            err = str(e)
        pay_date = None
        try:
            pay_date = parse_date_vn(str(row.get(COL_DATE, "")))
        except ValueError as e:
            err = err or str(e)
        method_raw = _norm_name(str(row.get(COL_METHOD, "")))
        method_code = METHOD_MAP.get(method_raw)
        if method_code is None:
            err = err or f"hình thức không hợp lệ: '{row.get(COL_METHOD, '')}'"

        drafts.append(RowDraft(
            row_no=row_no, citizen_id=cccd, name=name, amount=amount,
            payment_date=pay_date, method_code=method_code, reference=ref,
            note=note, raw=raw, parse_error=err,
        ))
    return drafts


# ---------------------------------------------------------------------------
# Resolve + validate (READ-ONLY — không ghi Payment)
# ---------------------------------------------------------------------------
async def resolve_and_validate(
    db: AsyncSession,
    drafts: List[RowDraft],
    academic_year: int,
    semester_no: int,
    unit_id: Optional[int],
) -> PreviewResult:
    """Đối chiếu từng dòng → MATCHED/WARNING/ERROR. KHÔNG ghi gì.

    - khóa = CCCD + academic_year (unique) + IDOR unit-scope
    - fee tuition kỳ S, status NOT IN (cancelled, waived)
    - FIFO principal-first: principal_remaining = invoice.amount - paid (KHÔNG
      remaining_amount vì gồm penalty)
    - sổ phân bổ in-batch per-invoice → chống double-alloc khi 2 dòng cùng CCCD+kỳ
    """
    # Sổ phân bổ trong batch: invoice_id -> tổng đã phân bổ ở các dòng TRƯỚC.
    batch_alloc: Dict[int, Decimal] = {}
    results: List[RowResult] = []

    for d in drafts:
        res = RowResult(
            row_no=d.row_no, status=PaymentImportRowStatusEnum.error.value,
            citizen_id=d.citizen_id, amount=d.amount, method_code=d.method_code,
            payment_date=d.payment_date, reference=d.reference or None, raw=d.raw,
        )

        # (0) lỗi parse
        if d.parse_error:
            res.message = d.parse_error
            results.append(res)
            continue
        # (6) CCCD định dạng
        if not CCCD_RE.match(d.citizen_id):
            res.message = (
                "CCCD phải đúng 12 chữ số" if d.citizen_id
                else "thiếu CCCD")
            results.append(res)
            continue

        # (2/6) hồ sơ theo CCCD + năm + IDOR unit-scope
        profile = await _resolve_profile(db, d.citizen_id, academic_year, unit_id)
        if profile is None:
            res.message = f"không tìm thấy hồ sơ CCCD {d.citizen_id} (năm {academic_year})"
            results.append(res)
            continue
        res.profile_id = profile.id

        # (3) học phí kỳ S, active-only
        fee = await _resolve_tuition_fee(db, profile.id, semester_no, unit_id)
        if fee is None:
            res.message = f"không có học phí HK{semester_no} đang hiệu lực"
            results.append(res)
            continue
        res.fee_id = fee.id

        # (4/5) phân bổ FIFO principal-first, trừ sổ in-batch
        warnings: List[str] = []
        invoices = await _payable_invoices(db, fee.id, unit_id)
        if not invoices:
            res.message = "chưa phát hành hóa đơn (đợt còn nháp) hoặc đã thu đủ"
            results.append(res)
            continue

        remaining_total = Decimal("0")
        avail: List[tuple] = []  # (invoice, available_principal)
        for inv in invoices:
            principal_rem = (inv.amount or Decimal("0")) - (inv.paid_amount or Decimal("0"))
            principal_rem -= batch_alloc.get(inv.id, Decimal("0"))
            if principal_rem < 0:
                principal_rem = Decimal("0")
            avail.append((inv, principal_rem))
            remaining_total += principal_rem

        if d.amount > remaining_total:
            res.message = (
                f"thu {_money(d.amount)} vượt tổng còn nợ gốc HK{semester_no} "
                f"({_money(remaining_total)})")
            results.append(res)
            continue

        # cross-check tên (warning)
        if d.name and _norm_name(d.name) != _norm_name(profile.lead.full_name if profile.lead else ""):
            warnings.append(
                f"tên lệch: file '{d.name}' vs hồ sơ "
                f"'{profile.lead.full_name if profile.lead else ''}'")

        # FIFO allocate
        left = d.amount
        for inv, principal_rem in avail:
            if left <= 0:
                break
            if principal_rem <= 0:
                continue
            take = min(left, principal_rem)
            res.allocations.append(
                Allocation(invoice_id=inv.id, installment_no=inv.installment_no, amount=take))
            batch_alloc[inv.id] = batch_alloc.get(inv.id, Decimal("0")) + take
            left -= take

        if len(res.allocations) > 1:
            warnings.append(f"thu phân bổ {len(res.allocations)} đợt")

        if warnings:
            res.status = PaymentImportRowStatusEnum.warned.value
            res.message = " · ".join(warnings)
        else:
            res.status = PaymentImportRowStatusEnum.matched.value
        results.append(res)

    matched = sum(1 for r in results if r.status == PaymentImportRowStatusEnum.matched.value)
    warned = sum(1 for r in results if r.status == PaymentImportRowStatusEnum.warned.value)
    failed = sum(1 for r in results if r.status == PaymentImportRowStatusEnum.error.value)
    total = sum(
        (r.amount or Decimal("0")) for r in results
        if r.status != PaymentImportRowStatusEnum.error.value)
    return PreviewResult(
        rows=results, matched_count=matched, warned_count=warned,
        failed_count=failed, total_amount=total)


async def _resolve_profile(
    db: AsyncSession, citizen_id: str, academic_year: int, unit_id: Optional[int],
) -> Optional[models.AdmissionProfile]:
    """CCCD + năm → hồ sơ (unique), IDOR unit-scope, eager lead cho cross-check tên."""
    from sqlalchemy.orm import selectinload
    stmt = (
        select(models.AdmissionProfile)
        .join(models.Lead)
        .options(selectinload(models.AdmissionProfile.lead))
        .where(
            models.AdmissionProfile.citizen_id == citizen_id,
            models.AdmissionProfile.academic_year == academic_year,
        )
    )
    if unit_id is not None:
        stmt = stmt.where(models.Lead.unit_id == unit_id)
    return (await db.execute(stmt)).scalar_one_or_none()


async def _resolve_tuition_fee(
    db: AsyncSession, profile_id: int, semester_no: int, unit_id: Optional[int],
) -> Optional[Fee]:
    """Học phí (tuition) kỳ S, status active (NOT cancelled/waived)."""
    stmt = (
        select(Fee)
        .where(
            Fee.admission_profile_id == profile_id,
            Fee.fee_type == "tuition",
            Fee.semester_no == semester_no,
            Fee.status.notin_(
                [FeeStatusEnum.cancelled.value, FeeStatusEnum.waived.value]),
        )
    )
    return (await db.execute(stmt)).scalars().first()


async def _payable_invoices(
    db: AsyncSession, fee_id: int, unit_id: Optional[int],
) -> List[Invoice]:
    """Đợt PAYABLE (issued/partial/overdue) sắp theo installment_no."""
    stmt = (
        select(Invoice)
        .where(
            Invoice.fee_id == fee_id,
            Invoice.status.in_(list(PAYABLE_INVOICE_STATUSES)),
        )
        .order_by(Invoice.installment_no)
    )
    return list((await db.execute(stmt)).scalars().all())


def _money(v: Decimal) -> str:
    return f"{v:,.0f}".replace(",", ".")
