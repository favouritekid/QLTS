# app/services/payment_import_service.py
"""
Payment Import Service (BV-2) - parse + resolve/validate + lưu batch preview.

Kế toán thu offline → import file mẫu → hệ thống đối chiếu từng dòng theo CCCD,
phân bổ FIFO (chỉ GỐC học phí) và phân loại MATCHED / WARNING / ERROR. BV-2 KHÔNG
ghi Payment — chỉ đọc + tính + lưu batch 'preview' để xem trước (pha commit ghi
tiền nằm ở BV-3).

Ref: Documents/BULK_PAYMENT_IMPORT_VERIFY_PLAN.md (DESIGN v2). Bất biến bắt buộc:
  1. đọc ``dtype=str`` CCCD/ref/amount (giữ số 0 đầu, không float)
  2. method 'cash'/'bank_transfer' (seed thực, KHÔNG 'bank')
  3. fee tuition active-only (NOT IN cancelled/waived) + đúng năm qua hồ sơ
  4. FIFO principal-first: principal_remaining = invoice.amount − paid_amount
     (KHÔNG remaining_amount vì gồm penalty)
  5. sổ phân bổ in-batch chống double-alloc khi 2 dòng cùng CCCD+kỳ
  6. IDOR unit-scope + bỏ lead xóa mềm + CCCD lỗi sạch
  7. resolve read-only thuần (không ghi gì trong resolve_and_validate)
"""
import csv
import hashlib
import io
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Callable, Dict, List, Optional, Tuple

import pandas as pd
import structlog
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.models.finance import (
    Fee,
    Invoice,
    FeeStatusEnum,
    InvoiceStatusEnum,
    PAYABLE_INVOICE_STATUSES,
    Payment,
    PaymentImportBatch,
    PaymentImportRow,
    PaymentImportBatchStatusEnum,
    PaymentImportRowStatusEnum,
    PaymentMethod,
    PaymentStatusEnum,
    PaymentTransaction,
    RefundRequest,
    RefundStatusEnum,
    TransactionTypeEnum,
)
from app.repositories.fee_repository import FeeRepository, InvoiceRepository
from app.utils.csv_helpers import sanitize_csv_row
from app.utils.exceptions import (
    BadRequest,
    BusinessRuleViolation,
    ConflictError,
    ResourceNotFoundError,
)

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
TEMPLATE_COLS = [
    COL_CCCD,
    COL_NAME,
    COL_AMOUNT,
    COL_DATE,
    COL_METHOD,
    COL_REF,
    COL_NOTE,
]

# Hình thức → PaymentMethod.code thực (seed fin20260131002): cash / bank_transfer.
# Input đã qua _norm_name (bỏ dấu + lower) TRƯỚC khi tra map → chỉ cần key KHÔNG dấu
# (key có dấu sẽ không bao giờ khớp).
METHOD_MAP = {
    "tien mat": "cash",
    "tm": "cash",
    "cash": "cash",
    "chuyen khoan": "bank_transfer",
    "ck": "bank_transfer",
    "bank_transfer": "bank_transfer",
}

CCCD_RE = re.compile(r"^\d{12}$")
MAX_IMPORT_ROWS = 5000
# Trần 1 khoản = max cột Numeric(15,2). Chặn ở parser để số quá lớn KHÔNG lọt
# xuống INSERT (payment_import_row.amount / Payment.amount) → DataError → 500.
MAX_AMOUNT = Decimal("9999999999999.99")
# Mã tham chiếu lưu vào Payment.reference_code / PaymentTransaction.external_reference
# = String(100). Ref dài hơn → DataError ở flush → 500 không bắt → chặn sớm thành
# lỗi dòng sạch.
MAX_REF_LEN = 100


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
    status: str  # matched | warned | error
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


def _check_thousands_groups(int_groups: List[str], raw: str) -> None:
    """Xác thực nhóm phân cách nghìn của PHẦN NGUYÊN: nhóm đầu 1-3 chữ số, các nhóm
    sau ĐÚNG 3. Chặn '1.23.456' / '1,23,456' (nhóm giữa sai) bị nối thầm thành số."""
    if not (
        int_groups
        and 1 <= len(int_groups[0]) <= 3
        and all(len(g) == 3 for g in int_groups[1:])
    ):
        raise ValueError(f"số tiền không hợp lệ: '{raw}'")


def parse_amount_vn(raw: str) -> Decimal:
    """Parse số tiền kiểu VN. '.' = phân cách nghìn, ',' = thập phân.

    "7.200.000" -> 7200000 · "7.200.000,50" -> 7200000.50 · "7200000.0" (float
    string từ Excel, nhóm cuối 1 chữ số) -> 7200000. Heuristic: dấu phân cách ĐƠN
    ('.' hoặc ',') với nhóm cuối ĐÚNG 3 chữ số = phân cách nghìn ("500.000" và
    "500,000" đều = 500000 vì VND nguyên); nhóm cuối 1-2 chữ số = thập phân
    ("7,50" -> 7.50). Nhiều dấu = phân cách nghìn (US "7,200,000").
    """
    # Bỏ MỌI khoảng trắng kể cả NBSP   / narrow   — file ngân hàng/Excel
    # hay ghi '7 200 000' với non-breaking space (re \s khớp Unicode whitespace).
    s = re.sub(r"\s", "", _norm(raw))
    if not s:
        raise ValueError("trống")
    has_dot = "." in s
    has_comma = "," in s
    if has_dot and has_comma:
        if s.rfind(",") > s.rfind("."):  # ',' bên phải = thập phân (VN 7.200.000,50)
            _check_thousands_groups(s.split(",")[0].split("."), raw)
            s = s.replace(".", "").replace(",", ".")
        else:  # '.' bên phải = thập phân (US 7,200,000.00)
            _check_thousands_groups(s.split(".")[0].split(","), raw)
            s = s.replace(",", "")
    elif has_comma:
        if s.count(",") > 1:  # nhiều ',' = phân cách nghìn (US 7,200,000)
            _check_thousands_groups(s.split(","), raw)
            s = s.replace(",", "")
        elif len(s.rsplit(",", 1)[1]) == 3:  # 1 ',' + nhóm cuối 3 số -> nghìn
            # Đối xứng nhánh '.': VND nguyên nên '500,000' = 500000, KHÔNG phải thập
            # phân 500,000 -> 500.00 (P1: ghi nhầm 500đ thay vì 500.000đ).
            _check_thousands_groups(s.split(","), raw)
            s = s.replace(",", "")
        else:  # 1 ',' + nhóm cuối 1-2 số = thập phân VN (7,50 -> 7.50)
            s = s.replace(",", ".")
    elif has_dot:  # '.' nhập nhằng
        if len(s.rsplit(".", 1)[1]) == 3:  # nhóm cuối 3 chữ số -> nghìn
            _check_thousands_groups(s.split("."), raw)
            s = s.replace(".", "")
        # else: '.' là thập phân (float string) -> giữ nguyên
    try:
        val = Decimal(s)
    except InvalidOperation:
        raise ValueError(f"số tiền không hợp lệ: '{raw}'")
    # Cột Numeric(15,2) → chuẩn hóa về 2 chữ số thập phân (VND thực tế là số nguyên).
    # Tránh '…,505' (3 chữ số thập phân) lọt xuống BV-3 → lỗi/làm tròn ngầm khi INSERT.
    val = val.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if val <= 0:
        raise ValueError("số tiền phải > 0")
    if val > MAX_AMOUNT:  # chặn tràn cột Numeric(15,2) → DataError/500 ở pha persist
        raise ValueError(f"số tiền vượt giới hạn cho phép ({_money(MAX_AMOUNT)} đ)")
    return val


def parse_date_vn(raw: str) -> date:
    """Parse ngày thu. Chấp nhận:
    - text VN: ``dd/mm/yyyy`` / ``dd-mm-yyyy``
    - ISO: ``yyyy-mm-dd``
    - chuỗi datetime của Excel khi đọc ``dtype=str``: ``2026-09-05 00:00:00``
      (openpyxl trả ô Date thật → pandas str-hóa kèm giờ). Kế toán rất hay để
      Excel tự định dạng ô ngày → PHẢI cắt phần giờ, nếu không HÀNG LOẠT dòng
      bị false-error "ngày không hợp lệ".
    """
    s = _norm(raw)
    if not s:
        raise ValueError("thiếu ngày thu")
    s = re.split(r"[ T]", s, maxsplit=1)[0]  # bỏ phần giờ '... 00:00:00' / '...T...'
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            d = datetime.strptime(s, fmt).date()
        except ValueError:
            continue
        # strptime %Y nuốt năm 1–4 chữ số: '05/09/26' → năm 0026 âm thầm. BV-2 KHÔNG
        # lộ (row không có cột ngày → vẫn MATCHED) nhưng BV-3 ghi Payment năm 0026.
        if not (2000 <= d.year <= 2100):
            raise ValueError(f"năm phải đủ 4 chữ số (2000–2100): '{raw}'")
        return d
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
            df.columns = [str(c).strip() for c in df.columns]
        else:
            # Đọc MỌI sheet rồi chọn sheet ĐẦU TIÊN đủ cột bắt buộc — tránh chỉ đọc
            # sheet 0 (im lặng bỏ data khi nằm ở sheet sau, sau sheet "Hướng dẫn").
            sheets = pd.read_excel(
                io.BytesIO(content), engine="openpyxl", dtype=str, sheet_name=None
            )
            df = None
            for sheet_df in sheets.values():
                sheet_df.columns = [str(c).strip() for c in sheet_df.columns]
                if all(c in sheet_df.columns for c in REQUIRED_COLS):
                    df = sheet_df
                    break
            if df is None:  # không sheet nào đủ cột → lấy sheet đầu để báo lỗi cột
                df = next(iter(sheets.values()), pd.DataFrame())
    except Exception as exc:  # noqa: BLE001
        raise BadRequest(f"Không đọc được file: {exc}")

    df = df.fillna("")
    # Header hay thừa khoảng trắng (' '/' ') → strip để không trượt so khớp
    # cột bắt buộc rồi từ chối nhầm cả file (CSV đã strip ở trên; lặp lại vô hại).
    df.columns = [str(c).strip() for c in df.columns]
    # Strip có thể làm 2 cột khác nhau (vd 'Số CCCD' và 'Số CCCD ') TRÙNG tên →
    # row.get(col) trả pandas Series → rác vào amount/CCCD/raw. Từ chối rõ ràng thay
    # vì âm thầm parse sai (file cột trùng = nhập nhằng, kế toán phải sửa).
    _cols = list(df.columns)
    _dups = sorted({c for c in _cols if _cols.count(c) > 1})
    if _dups:
        raise BadRequest(
            f"File có cột trùng tên (sau khi bỏ khoảng trắng): {', '.join(_dups)}"
        )
    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        raise BadRequest(f"File thiếu cột bắt buộc: {', '.join(missing)}")

    if len(df) > MAX_IMPORT_ROWS:
        raise BadRequest(
            f"File {len(df)} dòng vượt giới hạn {MAX_IMPORT_ROWS} dòng/lần import."
        )

    drafts: List[RowDraft] = []
    for i, row in df.iterrows():
        # row_no = SỐ DÒNG trên bảng tính kế toán nhìn thấy: header = dòng 1, nên
        # dòng dữ liệu đầu (index 0) = dòng 2 → báo lỗi khớp đúng vị trí trong Excel.
        row_no = int(i) + 2
        cells = {c: _norm(str(row.get(c, ""))) for c in df.columns}
        # Bỏ qua dòng TRỐNG HOÀN TOÀN (Excel hay để dòng trống ở cuối) → tránh
        # false-error "thiếu CCCD" hàng loạt.
        if not any(cells.values()):
            continue
        # raw = giá trị gốc (đã chuẩn hóa chuỗi) cho audit + pha commit re-parse.
        # KHÔNG sanitize-CSV ở ingest: sanitize là việc của tầng EXPORT — làm ở đây
        # sẽ chèn dấu ' vào reference/method → lệch preview vs tiền THỰC ghi (BV-3).
        raw = dict(cells)
        cccd = cells.get(COL_CCCD, "")
        name = cells.get(COL_NAME, "")
        ref = cells.get(COL_REF, "")
        note = cells.get(COL_NOTE, "")

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
        # Ref dài hơn cột String(100) → DataError ở commit → 500. Chặn sớm = lỗi dòng.
        if len(ref) > MAX_REF_LEN:
            err = err or f"mã tham chiếu quá dài (tối đa {MAX_REF_LEN} ký tự)"

        drafts.append(
            RowDraft(
                row_no=row_no,
                citizen_id=cccd,
                name=name,
                amount=amount,
                payment_date=pay_date,
                method_code=method_code,
                reference=ref,
                note=note,
                raw=raw,
                parse_error=err,
            )
        )
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

    - khóa = CCCD + academic_year (unique) + IDOR unit-scope + bỏ lead xóa mềm
    - fee tuition kỳ S, status NOT IN (cancelled, waived)
    - FIFO principal-first: principal_remaining = invoice.amount - paid (KHÔNG
      remaining_amount vì gồm penalty)
    - sổ phân bổ in-batch per-invoice → chống double-alloc khi 2 dòng cùng CCCD+kỳ
    """
    # --- Prefetch theo lô: 3 query thay vì 3N (tránh N+1 giữ 1 connection lâu +
    # cạn pool; dedup CCCD trùng miễn phí). (citizen_id, năm) & (profile, tuition,
    # kỳ) đều UNIQUE nên map 1-1 an toàn. ---
    cccds = {
        d.citizen_id
        for d in drafts
        if not d.parse_error and CCCD_RE.match(d.citizen_id or "")
    }
    profiles = await _fetch_profiles(db, cccds, academic_year, unit_id)
    fees = await _fetch_tuition_fees(db, [p.id for p in profiles.values()], semester_no)
    fee_ids = [f.id for f in fees.values()]
    invoices_by_fee = await _fetch_payable_invoices(db, fee_ids)
    # Chỉ cần status-set cho fee KHÔNG có hóa đơn payable (nhánh hiếm "đợt nháp / đã thu
    # đủ / chưa có đợt"). File bình thường mọi fee đều payable → list rỗng → helper
    # return {} ngay, KHÔNG tốn query trên đường happy-path.
    no_payable_fee_ids = [fid for fid in fee_ids if fid not in invoices_by_fee]
    invoice_statuses = await _fetch_invoice_status_sets(db, no_payable_fee_ids)

    # G2 — code hình thức ĐANG hoạt động (mirror commit:1017). Parser đã loại method
    # text lạ (:346); đây bắt method map-OK nhưng PaymentMethod inactive/missing → ERROR
    # ngay ở preview (đối xứng commit, hết "khớp giả" rồi commit fail).
    active_methods = {
        c
        for (c,) in (
            await db.execute(
                select(PaymentMethod.code).where(
                    PaymentMethod.code.in_(["cash", "bank_transfer"]),
                    PaymentMethod.is_active.is_(True),
                )
            )
        ).all()
    }
    # G1 — đếm CCCD trùng (và CCCD+tiền trùng) trong file. Cái chốt money DUY NHẤT
    # ("không thu vượt nợ gốc") KHÔNG bắt được trùng-còn-trong-nợ → thu khống. Cảnh báo
    # (WARNING, không chặn — thu nhiều đợt là hợp lệ; kế toán quyết).
    _valid = [
        d for d in drafts
        if not d.parse_error and CCCD_RE.match(d.citizen_id or "")
    ]
    cccd_counts = Counter(d.citizen_id for d in _valid)
    cccd_amount_counts = Counter((d.citizen_id, d.amount) for d in _valid)

    # Sổ phân bổ trong batch: invoice_id -> tổng đã phân bổ ở các dòng TRƯỚC.
    batch_alloc: Dict[int, Decimal] = {}
    results: List[RowResult] = []

    for d in drafts:
        res = RowResult(
            row_no=d.row_no,
            status=PaymentImportRowStatusEnum.error.value,
            citizen_id=d.citizen_id,
            amount=d.amount,
            method_code=d.method_code,
            payment_date=d.payment_date,
            reference=d.reference or None,
            raw=d.raw,
        )

        # (0) lỗi parse
        if d.parse_error:
            res.message = d.parse_error
            results.append(res)
            continue
        # (6) CCCD định dạng
        if not CCCD_RE.match(d.citizen_id):
            res.message = "CCCD phải đúng 12 chữ số" if d.citizen_id else "thiếu CCCD"
            results.append(res)
            continue
        # (G2) hình thức đã map (parser) nhưng PaymentMethod inactive/missing → ERROR
        # sớm (commit:1017 cũng chặn → tránh "khớp giả" ở preview).
        if d.method_code not in active_methods:
            res.message = "hình thức chưa được kích hoạt trong hệ thống"
            results.append(res)
            continue

        # (2/6) hồ sơ theo CCCD + năm + IDOR unit-scope (bỏ lead xóa mềm) — prefetch
        profile = profiles.get(d.citizen_id)
        if profile is None:
            res.message = (
                f"không tìm thấy hồ sơ CCCD {d.citizen_id} (năm {academic_year})"
            )
            results.append(res)
            continue
        res.profile_id = profile.id

        # (3) học phí kỳ S, active-only — prefetch
        fee = fees.get(profile.id)
        if fee is None:
            res.message = f"hồ sơ chưa được thiết lập học phí HK{semester_no}"
            results.append(res)
            continue
        res.fee_id = fee.id

        # (4/5) phân bổ FIFO principal-first, trừ sổ in-batch — prefetch
        warnings: List[str] = []
        invoices = invoices_by_fee.get(fee.id, [])
        if not invoices:
            # Tách rõ hành động cho kế toán (thay vì gộp 'nháp hoặc đã thu đủ').
            # Ưu tiên 'nháp' khi vừa có đợt nháp vừa có đợt đã thu đủ — vì còn việc
            # phải làm: phát hành đợt nháp để thu tiếp.
            statuses = invoice_statuses.get(fee.id, set())
            if InvoiceStatusEnum.draft.value in statuses:
                res.message = "đợt còn nháp — kế toán cần phát hành hóa đơn trước"
            elif InvoiceStatusEnum.paid.value in statuses:
                res.message = "học phí đã thu đủ"
            else:
                res.message = "chưa có đợt hóa đơn để thu"
            results.append(res)
            continue

        remaining_total = Decimal("0")
        avail: List[Tuple[Invoice, Decimal]] = []  # (invoice, available_principal)
        for inv in invoices:
            principal_rem = (inv.amount or Decimal("0")) - (
                inv.paid_amount or Decimal("0")
            )
            principal_rem -= batch_alloc.get(inv.id, Decimal("0"))
            if principal_rem < 0:
                principal_rem = Decimal("0")
            avail.append((inv, principal_rem))
            remaining_total += principal_rem

        if d.amount > remaining_total:
            res.message = (
                f"thu {_money(d.amount)} vượt tổng còn nợ gốc HK{semester_no} "
                f"({_money(remaining_total)})"
            )
            results.append(res)
            continue

        # cross-check tên (warning)
        if d.name and _norm_name(d.name) != _norm_name(
            profile.lead.full_name if profile.lead else ""
        ):
            warnings.append(
                f"tên lệch: file '{d.name}' vs hồ sơ "
                f"'{profile.lead.full_name if profile.lead else ''}'"
            )

        # cảnh báo ngày thu lệch xa năm học (gõ nhầm năm '2027' thay '2026', hoặc
        # nhầm dd/mm vs mm/dd) — surface ở preview để kế toán soát, KHÔNG chặn cứng
        # (thu sớm/muộn trong khoảng [năm học, +1] là hợp lệ).
        if d.payment_date and abs(d.payment_date.year - academic_year) > 1:
            warnings.append(
                f"ngày thu {d.payment_date:%d/%m/%Y} lệch xa năm học {academic_year}"
            )

        # (G1) CCCD xuất hiện nhiều dòng trong file → cảnh báo (không chặn). Nhấn
        # mạnh khi CÙNG số tiền (nghi copy nhầm → thu khống), vì chốt "không vượt
        # nợ" không bắt được.
        dup_n = cccd_counts.get(d.citizen_id, 0)
        if dup_n > 1:
            if cccd_amount_counts.get((d.citizen_id, d.amount), 0) > 1:
                warnings.append(
                    f"CCCD xuất hiện {dup_n} dòng — CÙNG số tiền, nghi copy nhầm"
                )
            else:
                warnings.append(
                    f"CCCD xuất hiện {dup_n} dòng trong file — kiểm tra trùng "
                    "(nếu thu nhiều đợt thì bỏ qua)"
                )

        # FIFO allocate
        left = d.amount
        for inv, principal_rem in avail:
            if left <= 0:
                break
            if principal_rem <= 0:
                continue
            take = min(left, principal_rem)
            res.allocations.append(
                Allocation(
                    invoice_id=inv.id, installment_no=inv.installment_no, amount=take
                )
            )
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

    matched = sum(
        1 for r in results if r.status == PaymentImportRowStatusEnum.matched.value
    )
    warned = sum(
        1 for r in results if r.status == PaymentImportRowStatusEnum.warned.value
    )
    failed = sum(
        1 for r in results if r.status == PaymentImportRowStatusEnum.error.value
    )
    total = sum(
        (r.amount or Decimal("0"))
        for r in results
        if r.status != PaymentImportRowStatusEnum.error.value
    )
    return PreviewResult(
        rows=results,
        matched_count=matched,
        warned_count=warned,
        failed_count=failed,
        total_amount=total,
    )


async def _fetch_profiles(
    db: AsyncSession,
    citizen_ids: set,
    academic_year: int,
    unit_id: Optional[int],
) -> Dict[str, models.AdmissionProfile]:
    """Lô CCCD → {citizen_id: hồ sơ} trong 1 query (thay N). IDOR unit-scope, bỏ
    lead xóa mềm, eager lead cho cross-check tên. (citizen_id, academic_year) UNIQUE
    → mỗi CCCD tối đa 1 hồ sơ/năm nên map 1-1 an toàn.

    Lọc ``Lead.deleted_at IS NULL`` — nếu không, hồ sơ của lead đã xóa mềm vẫn khớp
    CCCD → false MATCH → BV-3 ghi tiền vào hồ sơ "ma".
    """
    from sqlalchemy.orm import selectinload

    if not citizen_ids:
        return {}
    stmt = (
        select(models.AdmissionProfile)
        .join(models.Lead)
        .options(selectinload(models.AdmissionProfile.lead))
        .where(
            models.AdmissionProfile.citizen_id.in_(list(citizen_ids)),
            models.AdmissionProfile.academic_year == academic_year,
            models.Lead.deleted_at.is_(None),
        )
    )
    if unit_id is not None:
        stmt = stmt.where(models.Lead.unit_id == unit_id)
    rows = (await db.execute(stmt)).scalars().all()
    return {p.citizen_id: p for p in rows}


async def _fetch_tuition_fees(
    db: AsyncSession,
    profile_ids: List[int],
    semester_no: int,
) -> Dict[int, Fee]:
    """Lô profile_id → {profile_id: fee} (tuition kỳ S, active-only) trong 1 query.
    (profile, fee_type=tuition, semester_no) UNIQUE → mỗi profile tối đa 1 fee kỳ S.

    Không cần lọc unit: hồ sơ đã resolve dưới unit-scope nên fee đã trong phạm vi.
    """
    if not profile_ids:
        return {}
    stmt = select(Fee).where(
        Fee.admission_profile_id.in_(profile_ids),
        Fee.fee_type == "tuition",
        Fee.semester_no == semester_no,
        Fee.status.notin_([FeeStatusEnum.cancelled.value, FeeStatusEnum.waived.value]),
    )
    rows = (await db.execute(stmt)).scalars().all()
    return {f.admission_profile_id: f for f in rows}


async def _fetch_payable_invoices(
    db: AsyncSession,
    fee_ids: List[int],
) -> Dict[int, List[Invoice]]:
    """Lô fee_id → {fee_id: [invoice PAYABLE]} sắp installment_no, trong 1 query."""
    if not fee_ids:
        return {}
    stmt = (
        select(Invoice)
        .where(
            Invoice.fee_id.in_(fee_ids),
            Invoice.status.in_(list(PAYABLE_INVOICE_STATUSES)),
        )
        .order_by(Invoice.fee_id, Invoice.installment_no)
    )
    by_fee: Dict[int, List[Invoice]] = {}
    for inv in (await db.execute(stmt)).scalars().all():
        by_fee.setdefault(inv.fee_id, []).append(inv)
    return by_fee


async def _fetch_invoice_status_sets(
    db: AsyncSession,
    fee_ids: List[int],
) -> Dict[int, set]:
    """Lô fee_id → {fee_id: set(status MỌI invoice)} (1 query). Phân biệt nhánh
    KHÔNG-payable: đợt còn nháp (draft → cần phát hành) vs đã thu đủ (paid) vs chưa
    có đợt → message preview rõ hành động thay vì gộp 'nháp hoặc đã thu đủ'."""
    if not fee_ids:
        return {}
    stmt = select(Invoice.fee_id, Invoice.status).where(Invoice.fee_id.in_(fee_ids))
    out: Dict[int, set] = {}
    for fee_id, status in (await db.execute(stmt)).all():
        out.setdefault(fee_id, set()).add(status)
    return out


def _money(v: Decimal) -> str:
    return f"{v:,.0f}".replace(",", ".")


# ---------------------------------------------------------------------------
# Persist preview batch + orchestrator (BV-2)
# ---------------------------------------------------------------------------
async def preview_import(
    db: AsyncSession,
    *,
    content: bytes,
    filename: str,
    academic_year: int,
    semester_no: int,
    created_by_id: int,
    unit_id: Optional[int],
) -> Tuple[PaymentImportBatch, PreviewResult]:
    """Pha 1 (dry-run): parse → resolve/validate READ-ONLY → lưu batch 'preview'.

    KHÔNG ghi Payment. Trả ``(batch, preview)`` để router build response giàu thông
    tin (kèm phân bổ FIFO dự kiến — chỉ in-memory, KHÔNG persist vào row).
    """
    drafts = parse_template(content, filename)
    preview = await resolve_and_validate(
        db, drafts, academic_year, semester_no, unit_id
    )
    batch = await create_preview_batch(
        db,
        preview=preview,
        academic_year=academic_year,
        semester_no=semester_no,
        file_name=filename,
        file_sha256_hex=file_sha256(content),
        created_by_id=created_by_id,
    )
    return batch, preview


async def create_preview_batch(
    db: AsyncSession,
    *,
    preview: PreviewResult,
    academic_year: int,
    semester_no: int,
    file_name: str,
    file_sha256_hex: str,
    created_by_id: int,
) -> PaymentImportBatch:
    """Lưu kết quả preview thành 1 ``PaymentImportBatch`` 'preview' + các
    ``PaymentImportRow`` (audit + để pha commit tham chiếu ``batch_id``).

    Tôn trọng partial-unique ``uq_payment_import_batch_active_file`` (tối đa 1 batch
    còn-hiệu-lực / file):
    - cùng sha256 đã ``committed`` → ``ConflictError`` (chống double-count; phải đảo
      (void) lô đó trước khi import lại).
    - ``preview`` cũ cùng sha256 → xóa & tạo lại (DB có thể đã đổi giữa 2 lần xem).
    """
    existing = (
        await db.execute(
            select(PaymentImportBatch).where(
                PaymentImportBatch.file_sha256 == file_sha256_hex,
                PaymentImportBatch.status != PaymentImportBatchStatusEnum.void.value,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        if existing.status == PaymentImportBatchStatusEnum.committed.value:
            ngay = (
                f" ngày {existing.committed_at:%d/%m/%Y}"
                if existing.committed_at
                else ""
            )
            raise ConflictError(
                f"File này đã được import và ghi nhận ở lô #{existing.id}{ngay}. "
                "Hãy đảo (void) lô đó trước nếu muốn import lại."
            )
        # preview cũ cùng file → thay thế (cascade xóa rows) rồi tạo lại
        await db.delete(existing)
        await db.flush()

    batch = PaymentImportBatch(
        academic_year=academic_year,
        semester_no=semester_no,
        file_name=(file_name or "")[:255],
        file_sha256=file_sha256_hex,
        row_count=len(preview.rows),
        matched_count=preview.matched_count,
        warned_count=preview.warned_count,
        failed_count=preview.failed_count,
        total_amount=preview.total_amount,
        status=PaymentImportBatchStatusEnum.preview.value,
        created_by_id=created_by_id,
    )
    db.add(batch)
    try:
        await db.flush()
    except IntegrityError as exc:
        # Race: 2 upload cùng file đồng thời lọt qua pre-check → partial-unique chặn.
        await db.rollback()
        raise ConflictError(
            "File đang được xử lý bởi một thao tác khác. Vui lòng thử lại."
        ) from exc

    for r in preview.rows:
        # citizen_id cột String(12): chỉ lưu khi đúng 12 số, ngược lại None (CMND 9
        # số / rác dài hơn sẽ tràn cột) — giá trị gốc vẫn nằm trong ``raw`` để đối soát.
        cid = r.citizen_id if (r.citizen_id and CCCD_RE.match(r.citizen_id)) else None
        db.add(
            PaymentImportRow(
                batch_id=batch.id,
                row_no=r.row_no,
                citizen_id=cid,
                raw=r.raw or {},
                resolved_profile_id=r.profile_id,
                resolved_fee_id=r.fee_id,
                status=r.status,
                message=r.message,
                amount=r.amount,
                payment_ids=None,
            )
        )
    await db.flush()
    return batch


# ---------------------------------------------------------------------------
# Template generation (BV-2) — ở SERVICE để router chỉ stream bytes (CLAUDE.md:
# "Router: Input/Output ONLY") + test được generator.
# ---------------------------------------------------------------------------
_TEMPLATE_EXAMPLE = [
    "001234567890",  # Số CCCD (text, giữ số 0 đầu)
    "Nguyễn Văn An",  # Họ và tên học sinh
    "7.200.000",  # Số tiền thu (VNĐ) — GỐC học phí
    "05/09/2026",  # Ngày thu dd/mm/yyyy
    "TM",  # Hình thức: TM=tiền mặt / CK=chuyển khoản
    "PT-2026-0001",  # Mã tham chiếu (tùy chọn)
    "Thu học phí HK1",  # Ghi chú (tùy chọn)
]
_TEMPLATE_DESCRIPTIONS = [
    "Số CCCD 12 chữ số — ĐỊNH DẠNG TEXT (giữ số 0 đầu). Bắt buộc.",
    "Họ và tên học sinh (để đối chiếu — lệch chỉ cảnh báo).",
    "Số tiền đã thu (VNĐ), GỐC học phí. VD: 7.200.000. Bắt buộc.",
    "Ngày thu, định dạng dd/mm/yyyy. Bắt buộc.",
    "Hình thức: TM = tiền mặt, CK = chuyển khoản. Bắt buộc.",
    "Mã tham chiếu phiếu thu/UNC (tùy chọn) — định dạng TEXT.",
    "Ghi chú (tùy chọn).",
]
_XLSX_MEDIA = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def build_template(fmt: str) -> Tuple[bytes, str, str]:
    """Sinh file mẫu import → ``(content, media_type, filename)``.

    - CSV: prepend BOM (``\\ufeff``) → Excel locale VN không đọc mojibake header
      tiếng Việt (không BOM → ANSI → kế toán điền & upload lại → lệch cột → lỗi).
    - XLSX: cột CCCD + Mã tham chiếu ``number_format='@'`` (TEXT) tới HẾT vùng nhập
      (``MAX_IMPORT_ROWS``) — không chỉ vài dòng đầu, nếu không file > N dòng sẽ mất
      số 0 đầu CCCD từ vùng chưa định dạng → khớp nhầm người.
    """
    if (fmt or "").lower() == "csv":
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(TEMPLATE_COLS)
        writer.writerow(_TEMPLATE_EXAMPLE)
        # BOM (utf-8-sig) để Excel locale VN không đọc mojibake header tiếng Việt.
        content = ("﻿" + buf.getvalue()).encode("utf-8")
        return content, "text/csv; charset=utf-8", "mau_import_thu_hoc_phi.csv"

    from openpyxl import Workbook
    from openpyxl.comments import Comment
    from openpyxl.styles import Alignment, Font, PatternFill

    wb = Workbook()
    ws = wb.active
    ws.title = "Thu hoc phi"
    ws.append(TEMPLATE_COLS)

    header_fill = PatternFill(
        start_color="2F5496", end_color="2F5496", fill_type="solid"
    )
    header_font = Font(color="FFFFFF", bold=True)
    for idx, cell in enumerate(ws[1]):
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.comment = Comment(_TEMPLATE_DESCRIPTIONS[idx], "QLTS")

    ws.append(_TEMPLATE_EXAMPLE)

    # number_format='@' (TEXT) cho cột CCCD + Mã tham chiếu tới HẾT vùng nhập.
    cccd_col = TEMPLATE_COLS.index(COL_CCCD) + 1
    ref_col = TEMPLATE_COLS.index(COL_REF) + 1
    for col_idx in (cccd_col, ref_col):
        letter = ws.cell(row=1, column=col_idx).column_letter
        for r in range(2, MAX_IMPORT_ROWS + 2):
            ws[f"{letter}{r}"].number_format = "@"

    widths = [16, 22, 18, 14, 12, 18, 24]
    for i, w in enumerate(widths):
        ws.column_dimensions[ws.cell(row=1, column=i + 1).column_letter].width = w

    out = io.BytesIO()
    wb.save(out)
    return out.getvalue(), _XLSX_MEDIA, "mau_import_thu_hoc_phi.xlsx"


# ---------------------------------------------------------------------------
# BV-3 — Ghi tiền (auto-verify) + commit lô
#
# ``get_system_user`` + ``auto_verify_payment`` là GENERIC (đặt tạm ở đây; tách sang
# payment_service.py khi refactor lệ-phí dùng chung — plan §8). auto_verify KHÔNG
# dispatch notification / lead-sync → ``commit_batch`` GỘP 1 lần/hồ-sơ (tránh fan-out
# 3N của verify_payment per-row).
# ---------------------------------------------------------------------------
async def get_system_user(db: AsyncSession) -> "models.User":
    """Tài khoản kỹ thuật 'system' (checker cho auto-verify by policy).

    DÙNG CHUNG resolver canonical ``_get_system_application_fee_user``
    (admission_service) → **1 NGUỒN** fingerprint cho mọi luồng auto-verify by-policy
    (lệ phí + bulk import), hết drift. Canonical chặt hơn (thêm check không có
    UserUnitAssignment active + reuse ``_is_bcrypt_hash``). Maker-checker thỏa vì
    importer (kế toán) ≠ system_user (``chk_payment_no_self_approval``).

    (Eventual home: ``payment_service`` — plan §8.)
    """
    from app.services.admission_service import _get_system_application_fee_user

    return await _get_system_application_fee_user(db)


async def auto_verify_payment(
    db: AsyncSession,
    *,
    invoice: Invoice,
    fee: Fee,
    method_id: int,
    amount: Decimal,
    payment_date: datetime,
    reference: Optional[str],
    importer_id: int,
    system_user: "models.User",
    idempotency_key: str,
) -> Optional[Payment]:
    """Tạo Payment 'verified' (maker=importer, checker=system_user) áp vào ``invoice``
    ĐÃ TỒN TẠI + cập nhật invoice/fee + PaymentTransaction (audit, neo idempotency).

    Replicate money-math của ``verify_payment`` (payment_service.py:296-335) nhưng tạo
    Payment verified NGAY (không từ pending) và KHÔNG dispatch/lead-sync. Idempotent:
    idempotency_key đã có → trả ``None`` (re-commit an toàn).

    ⚠️ Caller PHẢI đã get_for_update + refresh ``invoice`` rồi ``fee`` (lock order
    invoice→fee, khớp verify_payment → tránh deadlock).
    """
    dup = (
        await db.execute(
            select(PaymentTransaction.id).where(
                PaymentTransaction.idempotency_key == idempotency_key
            )
        )
    ).scalar_one_or_none()
    if dup is not None:
        return None

    now = datetime.now(timezone.utc)
    payment = Payment(
        invoice_id=invoice.id,
        method_id=method_id,
        amount=amount,
        reference_code=reference,
        status=PaymentStatusEnum.verified.value,
        payment_date=payment_date,
        verified_at=now,
        created_by_id=importer_id,
        verified_by_id=system_user.id,
        intent_id=None,
        notes="Bulk import thu học phí — auto-verify (system_user)",
    )
    db.add(payment)
    await db.flush()

    # Money-math GỐC = verify_payment (1 nguồn sự thật chung, tránh 2 đường ghi tiền
    # trôi dạt). is_fully_paid GỒM penalty → trả đủ GỐC nhưng còn phạt thì 'partial'.
    from app.services.payment_service import apply_verified_payment_balances

    fee_balance_before, fee_remaining = apply_verified_payment_balances(
        invoice=invoice, fee=fee, amount=amount, now=now
    )

    db.add(
        PaymentTransaction(
            payment_id=payment.id,
            fee_id=fee.id,
            transaction_type=TransactionTypeEnum.payment.value,
            amount=amount,
            balance_before=fee_balance_before,
            balance_after=fee_remaining,
            external_reference=reference,
            gateway_response={
                "verification_mode": "bulk_import",
                "idempotency_key": idempotency_key,
                "importer_id": importer_id,
                "verified_by_id": system_user.id,
            },
            idempotency_key=idempotency_key,
            performed_by_id=system_user.id,
            notes=f"Bulk import payment. Invoice: {invoice.invoice_number}",
        )
    )
    await db.flush()
    return payment


async def _load_profile_with_lead(
    db: AsyncSession, profile_id: int
) -> "Optional[models.AdmissionProfile]":
    from sqlalchemy.orm import selectinload

    return (
        await db.execute(
            select(models.AdmissionProfile)
            .options(selectinload(models.AdmissionProfile.lead))
            .where(models.AdmissionProfile.id == profile_id)
        )
    ).scalar_one_or_none()


@dataclass
class CommitResult:
    batch_id: int
    committed_count: int  # số dòng ghi được
    failed_count: int  # số dòng lỗi tại commit (TOCTOU/đổi số dư)
    payment_count: int  # tổng Payment tạo
    total_amount: Decimal  # tổng tiền đã ghi


async def _assert_batch_creator_in_unit(
    db: AsyncSession, batch: PaymentImportBatch, unit_id: Optional[int]
) -> None:
    """IDOR unit-scope theo ĐƠN VỊ người tạo lô: manager (unit_id!=None) chỉ thao tác lô
    do user CÙNG đơn vị tạo; admin/accountant (unit_id=None) → mọi lô. Ngoài scope → 404
    (không lộ tồn tại). 1 NGUỒN quy tắc dùng chung commit/void/detail (tránh drift
    quyền)."""
    if unit_id is None:
        return
    creator_unit = (
        await db.execute(
            select(models.User.unit_id).where(models.User.id == batch.created_by_id)
        )
    ).scalar_one_or_none()
    if creator_unit != unit_id:
        raise ResourceNotFoundError("Không tìm thấy lô import")


async def commit_batch(
    db: AsyncSession,
    *,
    batch_id: int,
    importer_id: int,
    unit_id: Optional[int],
) -> Tuple[CommitResult, Callable]:
    """Pha 2 — GHI TIỀN. RE-VALIDATE TOCTOU dưới khóa + savepoint per-row + idempotency
    + GỘP lead-sync 1 lần/hồ-sơ. Trả ``(CommitResult, post_commit)``.

    - Khóa lô (FOR UPDATE) → serialize commit đồng thời cùng lô.
    - Lock order invoice→fee (khớp verify_payment → tránh deadlock với verify tay).
    - KHÔNG dùng snapshot preview để ghi: re-fetch fee/invoice HIỆN TẠI (số dư có thể
      đổi giữa preview→commit). Cuối vòng còn ``left>0`` = vượt nợ hiện tại → raise →
      savepoint rollback CẢ dòng (không ghi nửa vời).
    - 1 dòng lỗi không abort cả lô (savepoint per-row).
    """
    from app.services.fee_calculation_service import is_hk1_settled_fee
    from app.services.lead_admission_sync import sync_lead_tuition_paid

    batch = (
        await db.execute(
            select(PaymentImportBatch)
            .where(PaymentImportBatch.id == batch_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if batch is None:
        raise ResourceNotFoundError("Không tìm thấy lô import")
    # P1 IDOR: committer unit-scope — chặn manager commit/poison lô đơn vị khác.
    await _assert_batch_creator_in_unit(db, batch, unit_id)
    if batch.status != PaymentImportBatchStatusEnum.preview.value:
        raise ConflictError(
            f"Lô #{batch_id} không ở trạng thái preview (hiện: {batch.status})"
        )

    system_user = await get_system_user(db)
    if system_user.id == importer_id:
        raise BusinessRuleViolation(
            "Tài khoản import trùng system_user — vi phạm maker-checker"
        )

    method_ids = {
        code: mid
        for code, mid in (
            await db.execute(
                select(PaymentMethod.code, PaymentMethod.id).where(
                    PaymentMethod.code.in_(["cash", "bank_transfer"]),
                    PaymentMethod.is_active.is_(True),
                )
            )
        ).all()
    }

    fee_repo = FeeRepository(db)
    inv_repo = InvoiceRepository(db)

    rows = list(
        (
            await db.execute(
                select(PaymentImportRow)
                .where(
                    PaymentImportRow.batch_id == batch_id,
                    PaymentImportRow.status.in_(
                        [
                            PaymentImportRowStatusEnum.matched.value,
                            PaymentImportRowStatusEnum.warned.value,
                        ]
                    ),
                )
                .order_by(PaymentImportRow.row_no)
            )
        )
        .scalars()
        .all()
    )

    committed_count = 0
    failed_count = 0
    payment_count = 0
    total_amount = Decimal("0")
    cleared_profiles: Dict[int, str] = {}

    for row in rows:
        row_payment_ids: List[int] = []
        row_total = Decimal("0")  # row-local (Bug 1: cộng tổng SAU khi savepoint OK)
        row_cleared: Optional[tuple] = None
        try:
            async with db.begin_nested():
                raw = row.raw or {}
                method_code = METHOD_MAP.get(_norm_name(str(raw.get(COL_METHOD, ""))))
                method_id = method_ids.get(method_code)
                if method_id is None:
                    raise BusinessRuleViolation("hình thức không hợp lệ")
                pay_date = parse_date_vn(str(raw.get(COL_DATE, "")))
                # date → datetime tz-aware (cột Payment.payment_date DateTime(tz)).
                pay_dt = datetime(
                    pay_date.year, pay_date.month, pay_date.day, tzinfo=timezone.utc
                )
                reference = _norm(str(raw.get(COL_REF, ""))) or None
                # Defense: ref > String(100) → DataError ở flush không bắt được → 500
                # cả lô. Bắt thành lỗi DÒNG (preview cũng đã chặn ở parse_template).
                if reference is not None and len(reference) > MAX_REF_LEN:
                    raise BusinessRuleViolation(
                        f"mã tham chiếu quá dài (tối đa {MAX_REF_LEN} ký tự)"
                    )
                amount = row.amount
                if amount is None or amount <= 0:
                    raise BusinessRuleViolation("số tiền không hợp lệ")
                if row.resolved_fee_id is None:
                    raise BusinessRuleViolation("thiếu học phí đã resolve")

                # payable invoices HIỆN TẠI (sắp installment_no asc).
                payable = (
                    await _fetch_payable_invoices(db, [row.resolved_fee_id])
                ).get(row.resolved_fee_id, [])
                if not payable:
                    raise BusinessRuleViolation(
                        "không còn đợt hóa đơn payable (đã thu đủ / đổi giữa 2 pha)"
                    )

                # Bug 3: lock TẤT CẢ invoice (asc) RỒI mới fee — khớp lock-order
                # verify_payment (invoice→fee) cho dòng trải nhiều đợt → tránh deadlock
                # ABBA (fee KHÔNG bị khóa GIỮA các invoice).
                locked = []
                for inv in payable:
                    li = await inv_repo.get_for_update(inv.id, unit_id)
                    if li is None:
                        continue
                    await db.refresh(li)
                    locked.append(li)
                if not locked:
                    raise BusinessRuleViolation(
                        "không tìm thấy hóa đơn (IDOR / đổi giữa 2 pha)"
                    )
                fee = await fee_repo.get_for_update(locked[0].fee_id, unit_id)
                if fee is None:
                    raise BusinessRuleViolation("không tìm thấy học phí")
                await db.refresh(fee)
                if fee.status in (
                    FeeStatusEnum.cancelled.value,
                    FeeStatusEnum.waived.value,
                ):
                    raise BusinessRuleViolation(
                        f"học phí đã {fee.status} (đổi giữa 2 pha)"
                    )
                # Re-check lead chưa xóa mềm: preview lọc Lead.deleted_at IS NULL nhưng
                # get_for_update KHÔNG lọc → chặn ghi tiền vào hồ sơ bị xóa mềm giữa
                # preview→commit (mirror filter của _fetch_profiles).
                lead_deleted = (
                    await db.execute(
                        select(models.Lead.deleted_at)
                        .join(
                            models.AdmissionProfile,
                            models.AdmissionProfile.lead_id == models.Lead.id,
                        )
                        .where(models.AdmissionProfile.id == fee.admission_profile_id)
                    )
                ).scalar_one_or_none()
                if lead_deleted is not None:
                    raise BusinessRuleViolation(
                        "hồ sơ đã bị xóa giữa preview→commit"
                    )
                was_hk1 = is_hk1_settled_fee(fee)

                left = amount
                for li in locked:
                    if left <= 0:
                        break
                    if li.status not in PAYABLE_INVOICE_STATUSES:
                        continue  # đổi trạng thái sau khi khóa
                    principal_rem = (li.amount or Decimal("0")) - (
                        li.paid_amount or Decimal("0")
                    )
                    if principal_rem <= 0:
                        continue
                    take = min(left, principal_rem)
                    idem = f"bulkimport:{batch_id}:{row.row_no}:{li.id}"
                    payment = await auto_verify_payment(
                        db,
                        invoice=li,
                        fee=fee,
                        method_id=method_id,
                        amount=take,
                        payment_date=pay_dt,
                        reference=reference,
                        importer_id=importer_id,
                        system_user=system_user,
                        idempotency_key=idem,
                    )
                    if payment is not None:
                        row_payment_ids.append(payment.id)
                        row_total += take
                    left -= take

                if left > 0:
                    raise BusinessRuleViolation(
                        f"thu {_money(amount)} vượt còn nợ gốc HIỆN TẠI "
                        "(số dư đổi giữa preview→commit)"
                    )

                if not was_hk1:
                    now_hk1 = is_hk1_settled_fee(fee)
                    if now_hk1:
                        row_cleared = (
                            fee.admission_profile_id,
                            reference or f"BULK-{batch_id}-{row.row_no}",
                        )
                row.payment_ids = row_payment_ids
            # savepoint committed → giờ mới cộng tổng (raise giữa chừng đã rollback DB).
            committed_count += 1
            payment_count += len(row_payment_ids)
            total_amount += row_total
            if row_cleared:
                cleared_profiles[row_cleared[0]] = row_cleared[1]
        except (
            BusinessRuleViolation,
            ResourceNotFoundError,
            ValueError,
            ConflictError,
        ) as exc:
            # Lỗi nghiệp vụ/giá trị → message đã sạch (tiếng Việt) → hiện thẳng cho
            # kế toán.
            failed_count += 1
            row.status = PaymentImportRowStatusEnum.error.value
            row.message = str(exc)[:500]
        except Exception as exc:  # noqa: BLE001 — lỗi KHÔNG lường (DB/IntegrityError)
            # KHÔNG nhét dump SQLAlchemy/asyncpg cho kế toán (xấu + lộ chi tiết kỹ
            # thuật) → message generic + LOG đầy đủ cho dev. Savepoint per-row đã
            # rollback dòng này nên các dòng khác vẫn ghi (lô ROBUST: lỗi-lạ 1 dòng
            # không abort cả lô).
            log.error(
                "bulk_commit_row_unexpected_error",
                batch_id=batch_id,
                row_no=row.row_no,
                error=str(exc),
            )
            failed_count += 1
            row.status = PaymentImportRowStatusEnum.error.value
            row.message = "lỗi hệ thống khi ghi dòng này — vui lòng liên hệ kỹ thuật"

    # GỘP lead-sync (projection) 1 lần/hồ-sơ HK1 vừa cleared. Bug 2: bọc savepoint +
    # try/except MỖI hồ-sơ — lỗi projection 1 hồ-sơ KHÔNG được hủy tiền đã ghi của CẢ
    # lô (sync chạy trong body trước router commit; raise → outer rollback → mất tiền).
    for profile_id, ref in cleared_profiles.items():
        try:
            async with db.begin_nested():
                profile = await _load_profile_with_lead(db, profile_id)
                if profile is not None:
                    await sync_lead_tuition_paid(
                        db=db,
                        profile=profile,
                        transaction_id=ref,
                        changed_by_user_id=importer_id,
                        reason=f"Thu học phí qua import lô #{batch_id}",
                    )
        except Exception as exc:  # noqa: BLE001
            # KHÔNG hủy tiền đã ghi vì lỗi projection 1 hồ-sơ, NHƯNG log ERROR + stack
            # trace (backend chưa có Sentry) để lỗi projection HỆ THỐNG không ẩn mình:
            # tiền đã ghi mà lead đứng yên sts cũ phải lộ ra để truy.
            log.error(
                "bulk_commit_lead_sync_failed",
                batch_id=batch_id,
                profile_id=profile_id,
                error=str(exc),
                exc_info=True,
            )

    # Recompute counter theo trạng thái dòng THỰC TẾ sau commit (dòng có thể flip
    # matched/warned → error lúc commit) để lịch sử lô khớp tiền THỰC ghi, không giữ
    # số preview (overstate). `rows` chỉ gồm dòng matched/warned ở preview; preview-
    # errors nằm ngoài nên cộng vào failed_count cũ.
    batch.matched_count = sum(
        1 for r in rows if r.status == PaymentImportRowStatusEnum.matched.value
    )
    batch.warned_count = sum(
        1 for r in rows if r.status == PaymentImportRowStatusEnum.warned.value
    )
    batch.failed_count = batch.failed_count + failed_count
    batch.total_amount = total_amount
    # Chỉ đánh dấu 'committed' khi THỰC SỰ ghi được tiền. 0 dòng ghi (tất cả fail
    # TOCTOU) → GIỮ 'preview' để re-import được (chưa có endpoint void; tránh khóa
    # file vĩnh viễn qua partial-unique).
    if committed_count > 0:
        batch.status = PaymentImportBatchStatusEnum.committed.value
        batch.committed_at = datetime.now(timezone.utc)
    await db.flush()

    result = CommitResult(
        batch_id=batch_id,
        committed_count=committed_count,
        failed_count=failed_count,
        payment_count=payment_count,
        total_amount=total_amount,
    )

    async def post_commit() -> None:
        # QUYẾT ĐỊNH SẢN PHẨM (đã chốt): bulk import KHÔNG gửi notification per-row
        # (tránh fan-out 3N) — KHÁC verify tay (fire PAYMENT_RECEIVED mỗi payment).
        # Lead-sync (projection) đã làm trong body. Nếu sau cần báo phụ huynh: thêm 1
        # notif GỘP per-hồ-sơ + PHẢI seed notification_rule (nếu không sẽ fire-zero
        # theo fail-closed dispatcher). Để trống là CỐ Ý, không phải thiếu sót.
        return None

    return result, post_commit


# ---------------------------------------------------------------------------
# BV-3.5 — Void (đảo) lô đã committed: rút lại tiền + mở lại file để re-import
# ---------------------------------------------------------------------------
@dataclass
class VoidResult:
    batch_id: int
    reversed_count: int  # số Payment đã đảo (rút lại)
    reversed_amount: Decimal  # tổng tiền đã rút


async def void_batch(
    db: AsyncSession,
    *,
    batch_id: int,
    user_id: int,
    unit_id: Optional[int],
    reason: str,
) -> Tuple[VoidResult, Callable]:
    """Đảo (void) 1 lô đã ``committed`` — rút lại MỌI Payment bulk đã ghi.

    Mỗi Payment 'verified' của lô → reverse invoice/fee.paid_amount (về 'issued' nếu
    hết, 'partial' nếu còn) + ``PaymentTransaction(type=reversal, amount âm)`` +
    Payment → 'refunded' (constraint chỉ có refunded; ``type=reversal`` phân biệt với
    customer-refund ở ledger). Batch → 'void' → file_sha256 thoát partial-unique →
    re-import được.

    ATOMIC (KHÔNG savepoint per-row): void phải đảo TRỌN lô — 1 lỗi → rollback cả
    (router get_db không commit). Lock TẤT CẢ invoice (asc id) RỒI fee (asc id) —
    khớp lock-order invoice→fee, tránh deadlock ABBA với verify/commit đồng thời.

    Lead-status: void TỰ lùi lead khỏi sts10 ("Đã hoàn tất học phí") về status TRƯỚC
    (đối xứng forward sync) cho hồ sơ HK1 KHÔNG còn cleared sau đảo — qua
    ``revert_lead_tuition_paid`` (đọc LeadStatusHistory). Best-effort: chỉ khi lead
    ĐANG ở sts10 (đã chuyển tiếp/nhập học → giữ nguyên, không kéo lùi). KHÔNG đẩy
    sts18 (đó là refund THẬT — ``sync_lead_tuition_refunded``).
    """
    from app.services.payment_service import reverse_payment_balances

    batch = (
        await db.execute(
            select(PaymentImportBatch)
            .where(PaymentImportBatch.id == batch_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if batch is None:
        raise ResourceNotFoundError("Không tìm thấy lô import")
    # IDOR: void unit-scope theo đơn vị NGƯỜI TẠO (accountant đã bị Casbin chặn).
    await _assert_batch_creator_in_unit(db, batch, unit_id)
    if batch.status != PaymentImportBatchStatusEnum.committed.value:
        raise ConflictError(
            f"Chỉ đảo (void) được lô đã committed (hiện: {batch.status})"
        )

    fee_repo = FeeRepository(db)
    inv_repo = InvoiceRepository(db)

    rows = list(
        (
            await db.execute(
                select(PaymentImportRow).where(PaymentImportRow.batch_id == batch_id)
            )
        )
        .scalars()
        .all()
    )
    payment_ids = sorted({pid for r in rows for pid in (r.payment_ids or [])})
    # Lock Payment rows FOR UPDATE (asc id) TRƯỚC khi check refund + đảo — serialize
    # với refund-creation (request_refund cũng khóa Payment, of=Payment): refund tạo
    # đồng thời phải CHỜ → sau void thấy status='refunded' → bị chặn (chỉ refund
    # 'verified'). order_by(id) cho thứ tự khóa xác định (chống void↔void deadlock).
    payments = (
        list(
            (
                await db.execute(
                    select(Payment)
                    .where(Payment.id.in_(payment_ids))
                    .order_by(Payment.id)
                    .with_for_update()
                )
            )
            .scalars()
            .all()
        )
        if payment_ids
        else []
    )

    # Lock TẤT CẢ invoice (asc id) RỒI TẤT CẢ fee (asc id) — deadlock-safe (không giữ
    # khóa fee khi đi xin khóa invoice). KHÔNG db.refresh: void không pre-load (Payment.
    # invoice lazy='select') nên get_for_update là lần nạp ĐẦU → cột đã tươi.
    invoice_ids = sorted({p.invoice_id for p in payments})
    inv_by_id: Dict[int, Invoice] = {}
    for iid in invoice_ids:
        li = await inv_repo.get_for_update(iid, unit_id)
        if li is None:
            raise BusinessRuleViolation(
                f"không khóa được hóa đơn #{iid} (IDOR / đã đổi)"
            )
        inv_by_id[iid] = li
    fee_ids = sorted({inv.fee_id for inv in inv_by_id.values()})
    fee_by_id: Dict[int, Fee] = {}
    for fid in fee_ids:
        lf = await fee_repo.get_for_update(fid, unit_id)
        if lf is None:
            raise BusinessRuleViolation(f"không khóa được học phí #{fid}")
        fee_by_id[fid] = lf

    # (#3) Guard out-of-band: invoice/fee bị HỦY/MIỄN giữa commit→void (vd luồng gộp
    # đợt SQL) → KHÔNG resurrect (reverse_payment_balances set 'issued'/'partial' vô
    # điều kiện → hồi sinh hóa đơn đã hủy / IntegrityError). Refuse → xử lý thủ công.
    for inv in inv_by_id.values():
        if inv.status == InvoiceStatusEnum.cancelled.value:
            raise BusinessRuleViolation(
                f"hóa đơn #{inv.id} đã bị hủy giữa commit→void — xử lý thủ công"
            )
    for fee in fee_by_id.values():
        if fee.status in (
            FeeStatusEnum.cancelled.value,
            FeeStatusEnum.waived.value,
        ):
            raise BusinessRuleViolation(
                f"học phí #{fee.id} đã {fee.status} giữa commit→void — xử lý thủ công"
            )

    # (P1) Guard refund: payment trong lô đã/đang được hoàn lẻ (RefundRequest non-
    # rejected) → KHÔNG đảo (trừ tiền 2 LẦN — refund đã rút phần đó). Dưới khóa fee nên
    # refund-processing đồng thời (cũng khóa fee) bị serialize. Khe tạo refund SAU check
    # bị chặn bởi guard payment.status='verified' ở process_approved_refund.
    if payment_ids:
        live_refund = (
            await db.execute(
                select(RefundRequest.id)
                .where(
                    RefundRequest.payment_id.in_(payment_ids),
                    RefundRequest.status != RefundStatusEnum.rejected.value,
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if live_refund is not None:
            raise ConflictError(
                "Lô có payment đã/đang được hoàn tiền (refund) — xử lý refund "
                "trước khi đảo lô"
            )

    now = datetime.now(timezone.utc)
    reversed_count = 0
    reversed_amount = Decimal("0")
    for p in payments:
        # Idempotent: Payment đã 'refunded' (đã đảo/hoàn lẻ trước) → bỏ qua (không
        # đảo 2 lần).
        if p.status != PaymentStatusEnum.verified.value:
            continue
        inv = inv_by_id.get(p.invoice_id)
        fee = fee_by_id.get(inv.fee_id) if inv is not None else None
        if inv is None or fee is None:
            raise BusinessRuleViolation(f"thiếu hóa đơn/học phí cho payment #{p.id}")
        bal_before, fee_remaining = reverse_payment_balances(
            invoice=inv, fee=fee, amount=p.amount
        )
        p.status = PaymentStatusEnum.refunded.value
        db.add(
            PaymentTransaction(
                payment_id=p.id,
                fee_id=fee.id,
                transaction_type=TransactionTypeEnum.reversal.value,
                amount=-p.amount,
                balance_before=bal_before,
                balance_after=fee_remaining,
                external_reference=p.reference_code,
                gateway_response={
                    "verification_mode": "bulk_void",
                    "batch_id": batch_id,
                    "voided_by_id": user_id,
                },
                idempotency_key=f"bulkvoid:{batch_id}:{p.id}",
                performed_by_id=user_id,
                notes=f"Void lô import #{batch_id}. Lý do: {reason}"[:1000],
            )
        )
        reversed_count += 1
        reversed_amount += p.amount

    # ⚠️ Flush việc đảo tiền xuống DB TRƯỚC vòng lùi-lead. autoflush=False (database.py)
    # → các UPDATE/INSERT đảo tiền ở trên còn PENDING; nếu không flush ở đây, lần flush
    # ĐẦU TIÊN là `db.flush()` BÊN TRONG savepoint của revert → revert lỗi → ROLLBACK TO
    # SAVEPOINT cuốn theo cả đảo tiền (mất tiền đã đảo dù lô vẫn chuyển 'void'). Flush
    # NGOÀI savepoint = đảo tiền bền trong outer txn; revert lỗi chỉ mất projection.
    await db.flush()

    # Lùi lead (projection) cho hồ sơ HK1 KHÔNG còn cleared sau khi đảo tiền — đối
    # xứng forward sync ở commit. Void = SỬA NHẦM ghi nhận (KHÔNG phải học sinh rút)
    # → lùi về status TRƯỚC sts10, KHÔNG đẩy sts18 (đó là refund thật). Bọc savepoint
    # + try/except MỖI hồ-sơ: lỗi projection KHÔNG hủy đảo tiền cả lô (tiền đã đảo giữ).
    from app.services.fee_calculation_service import is_hk1_settled_fee
    from app.services.lead_admission_sync import revert_lead_tuition_paid

    reverted_leads = 0
    for fee in fee_by_id.values():
        if fee.fee_type != "tuition" or fee.semester_no != 1:
            continue  # chỉ HK1 đụng pipeline lead
        if is_hk1_settled_fee(fee):
            continue  # HK1 vẫn settled (nguồn thu khác) → giữ lead ở sts10
        try:
            async with db.begin_nested():
                profile = await _load_profile_with_lead(db, fee.admission_profile_id)
                if profile is not None and await revert_lead_tuition_paid(
                    db=db,
                    profile=profile,
                    changed_by_user_id=user_id,
                    reason=f"Đảo (void) lô import #{batch_id}",
                ):
                    reverted_leads += 1
        except Exception as exc:  # noqa: BLE001
            log.error(
                "bulk_void_lead_revert_failed",
                batch_id=batch_id,
                profile_id=fee.admission_profile_id,
                error=str(exc),
                exc_info=True,
            )
    if reverted_leads:
        log.info(
            "bulk_void_leads_reverted", batch_id=batch_id, count=reverted_leads
        )

    batch.status = PaymentImportBatchStatusEnum.void.value
    batch.voided_at = now
    batch.void_reason = (reason or "")[:1000]
    # (#4) Lịch sử lô phản ánh tiền THỰC còn lại = đã thu − đã đảo (full void → 0),
    # tránh batch 'void' vẫn hiện total như còn thu đủ.
    batch.total_amount = batch.total_amount - reversed_amount
    if batch.total_amount < Decimal("0"):
        batch.total_amount = Decimal("0")
    await db.flush()

    result = VoidResult(
        batch_id=batch_id,
        reversed_count=reversed_count,
        reversed_amount=reversed_amount,
    )

    async def post_commit() -> None:
        return None

    return result, post_commit


# ---------------------------------------------------------------------------
# Read helpers (response build + lịch sử lô)
# ---------------------------------------------------------------------------
async def load_batch_with_rows(
    db: AsyncSession, batch_id: int
) -> Tuple[Optional[PaymentImportBatch], List[PaymentImportRow]]:
    """Lô + các dòng (sắp row_no) cho response build. ``(None, [])`` nếu không có."""
    batch = (
        await db.execute(
            select(PaymentImportBatch).where(PaymentImportBatch.id == batch_id)
        )
    ).scalar_one_or_none()
    if batch is None:
        return None, []
    rows = list(
        (
            await db.execute(
                select(PaymentImportRow)
                .where(PaymentImportRow.batch_id == batch_id)
                .order_by(PaymentImportRow.row_no)
            )
        )
        .scalars()
        .all()
    )
    return batch, rows


async def list_batches(
    db: AsyncSession, *, unit_id: Optional[int], skip: int = 0, limit: int = 50
) -> Tuple[List[PaymentImportBatch], int]:
    """Lịch sử lô import (mới nhất trước), phân trang.

    P1 IDOR: unit-scope (manager) chỉ thấy lô do user CÙNG ĐƠN VỊ tạo; admin/accountant
    (unit_id=None) → toàn hệ.
    """
    count_q = select(func.count()).select_from(PaymentImportBatch)
    list_q = select(PaymentImportBatch)
    if unit_id is not None:
        count_q = count_q.join(
            models.User, PaymentImportBatch.created_by_id == models.User.id
        ).where(models.User.unit_id == unit_id)
        list_q = list_q.join(
            models.User, PaymentImportBatch.created_by_id == models.User.id
        ).where(models.User.unit_id == unit_id)
    total = (await db.execute(count_q)).scalar_one()
    items = list(
        (
            await db.execute(
                list_q.order_by(
                    PaymentImportBatch.created_at.desc(),
                    PaymentImportBatch.id.desc(),
                )
                .offset(skip)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return items, total


# ---------------------------------------------------------------------------
# BV-5 R2/R1 — xem lại per-row + xuất file kết quả
# ---------------------------------------------------------------------------
async def get_batch_detail_scoped(
    db: AsyncSession, batch_id: int, unit_id: Optional[int]
) -> Tuple[PaymentImportBatch, List[PaymentImportRow]]:
    """Lô + dòng, có IDOR unit-scope (mirror commit:998). Ngoài scope / không tồn tại
    → ``ResourceNotFoundError`` (404, không lộ tồn tại)."""
    batch, rows = await load_batch_with_rows(db, batch_id)
    if batch is None:
        raise ResourceNotFoundError("Không tìm thấy lô import")
    await _assert_batch_creator_in_unit(db, batch, unit_id)
    return batch, rows


def _result_status_label(batch_status: str, row_status: str) -> str:
    """Nhãn Trạng thái cho file kết quả — theo LÔ × DÒNG (P2: void KHÔNG "Thành
    công")."""
    if row_status == PaymentImportRowStatusEnum.error.value:
        if batch_status == PaymentImportBatchStatusEnum.committed.value:
            return "Lỗi (không ghi)"
        return "Lỗi"
    # matched / warned
    if batch_status == PaymentImportBatchStatusEnum.void.value:
        return "Đã đảo"
    if batch_status == PaymentImportBatchStatusEnum.committed.value:
        return "Đã ghi"
    return "Dự kiến ghi"  # preview


# "(hệ thống)" trong nhãn để tránh trùng nếu file có sẵn cột tên "Tên hồ sơ".
COL_PROFILE_NAME = "Tên hồ sơ (hệ thống)"  # tên hệ thống (Lead.full_name)
_RESULT_EXTRA_COLS = ["Trạng thái", "Lý do", "Mã Payment", "Đã ghi (đồng)"]


async def build_result_file(
    db: AsyncSession, batch_id: int, fmt: str, unit_id: Optional[int]
) -> Tuple[bytes, str, str]:
    """File kết quả = NGUYÊN dòng gốc (`raw`) + cột Trạng thái/Lý do/Mã Payment/Đã ghi
    → ``(content, media_type, filename)``. IDOR scope.

    🔴 P1 chống formula injection: MỌI ô (raw = user nhập + header cột do file quyết) qua
    ``sanitize_csv_cell`` (CSV + XLSX); XLSX thêm ``number_format='@'`` (text) phòng
    openpyxl diễn giải chuỗi mở đầu '=' thành công thức.
    """
    batch, rows = await get_batch_detail_scoped(db, batch_id, unit_id)
    committed_v = PaymentImportBatchStatusEnum.committed.value
    written_statuses = (
        PaymentImportRowStatusEnum.matched.value,
        PaymentImportRowStatusEnum.warned.value,
    )
    # Cột "Tên hồ sơ" = tên hệ thống để kế toán đối chiếu cạnh "Họ và tên học sinh"
    # của file (file có thể ghi lệch). Batch-query 1 lần (anti-N+1); dòng không
    # resolve được hồ sơ → "(không có hồ sơ)".
    profile_ids = {
        r.resolved_profile_id for r in rows if r.resolved_profile_id is not None
    }
    profile_names: Dict[int, str] = {}
    if profile_ids:
        name_rows = await db.execute(
            select(models.AdmissionProfile.id, models.Lead.full_name)
            .join(models.Lead, models.AdmissionProfile.lead_id == models.Lead.id)
            .where(models.AdmissionProfile.id.in_(profile_ids))
        )
        profile_names = {pid: (name or "") for pid, name in name_rows.all()}

    def _profile_name(r: PaymentImportRow) -> str:
        pid = r.resolved_profile_id
        if pid is None:
            return "(không có hồ sơ)"
        return profile_names.get(pid) or "(không có hồ sơ)"

    # Header = cột gốc của file + cột kết quả. JSONB KHÔNG giữ thứ tự key → sắp theo
    # TEMPLATE_COLS (cột template, đúng thứ tự file mẫu) rồi cột lạ (nếu có) ở cuối.
    # Cột gốc do FILE quyết → cũng phải sanitize.
    first_raw = rows[0].raw if rows and rows[0].raw else {}
    if first_raw:
        raw_keys = [c for c in TEMPLATE_COLS if c in first_raw] + [
            k for k in first_raw if k not in TEMPLATE_COLS
        ]
    else:
        raw_keys = list(TEMPLATE_COLS)
    # Chèn "Tên hồ sơ" NGAY SAU "Họ và tên học sinh" (đối chiếu cạnh nhau); file thiếu
    # cột tên → đặt cuối phần cột gốc, ngay trước cột kết quả.
    name_pos = raw_keys.index(COL_NAME) + 1 if COL_NAME in raw_keys else len(raw_keys)
    display_cols = raw_keys[:name_pos] + [COL_PROFILE_NAME] + raw_keys[name_pos:]
    header = display_cols + _RESULT_EXTRA_COLS

    def _row_cells(r: PaymentImportRow) -> List[str]:
        raw = r.raw or {}
        label = _result_status_label(batch.status, r.status)
        pay = ", ".join(str(p) for p in (r.payment_ids or []))
        written = (
            f"{r.amount:.0f}"  # VND nguyên — bỏ đuôi '.00' của Numeric(15,2)
            if (
                batch.status == committed_v
                and r.status in written_statuses
                and r.amount is not None
            )
            else ""
        )
        base = [raw.get(k, "") for k in raw_keys]
        base = base[:name_pos] + [_profile_name(r)] + base[name_pos:]
        cells = base + [label, r.message or "", pay, written]
        return sanitize_csv_row(cells)  # = [sanitize_csv_cell(c) for c in cells]

    fname = f"ket_qua_import_lo_{batch_id}"
    if (fmt or "").lower() == "csv":
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(sanitize_csv_row(header))
        for r in rows:
            writer.writerow(_row_cells(r))
        content = ("﻿" + buf.getvalue()).encode("utf-8")  # BOM
        return content, "text/csv; charset=utf-8", f"{fname}.csv"

    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Ket qua"
    ws.append(sanitize_csv_row(header))
    for r in rows:
        ws.append(_row_cells(r))
    # Force TEXT mọi ô (chống injection + giữ số 0 đầu CCCD).
    for ws_row in ws.iter_rows():
        for cell in ws_row:
            cell.number_format = "@"
    bio = io.BytesIO()
    wb.save(bio)
    return bio.getvalue(), _XLSX_MEDIA, f"{fname}.xlsx"
