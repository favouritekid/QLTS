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
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Dict, List, Optional, Tuple

import pandas as pd
import structlog
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.models.finance import (
    Fee,
    Invoice,
    FeeStatusEnum,
    PAYABLE_INVOICE_STATUSES,
    PaymentImportBatch,
    PaymentImportRow,
    PaymentImportBatchStatusEnum,
    PaymentImportRowStatusEnum,
)
from app.utils.csv_helpers import sanitize_csv_cell
from app.utils.exceptions import BadRequest, ConflictError

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


def parse_amount_vn(raw: str) -> Decimal:
    """Parse số tiền kiểu VN. '.' = phân cách nghìn, ',' = thập phân.

    "7.200.000" -> 7200000 · "7.200.000,50" -> 7200000.50 · "7200000.0" (float
    string từ Excel, nhóm cuối 1 chữ số) -> 7200000. Heuristic: '.' với nhóm cuối
    đúng 3 chữ số = phân cách nghìn; nếu không -> thập phân.
    """
    # Bỏ MỌI khoảng trắng kể cả NBSP   / narrow   — file ngân hàng/Excel
    # hay ghi '7 200 000' với non-breaking space (re \s khớp Unicode whitespace).
    s = re.sub(r"\s", "", _norm(raw))
    if not s:
        raise ValueError("trống")
    if "," in s:  # ',' = thập phân VN
        s = s.replace(".", "").replace(",", ".")
    elif "." in s:  # '.' nhập nhằng
        if len(s.rsplit(".", 1)[1]) == 3:  # nhóm cuối 3 chữ số -> nghìn
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
        raw = {c: sanitize_csv_cell(row.get(c, "")) for c in df.columns}
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
    invoices_by_fee = await _fetch_payable_invoices(db, [f.id for f in fees.values()])

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
            res.message = f"không có học phí HK{semester_no} đang hiệu lực"
            results.append(res)
            continue
        res.fee_id = fee.id

        # (4/5) phân bổ FIFO principal-first, trừ sổ in-batch — prefetch
        warnings: List[str] = []
        invoices = invoices_by_fee.get(fee.id, [])
        if not invoices:
            res.message = "chưa phát hành hóa đơn (đợt còn nháp) hoặc đã thu đủ"
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
