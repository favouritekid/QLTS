# tests/services/test_payment_import_service.py
"""
Tests for payment_import_service (BV-2): parse + resolve/validate + preview batch.

Phủ:
- Parse: VN-number, quantize 2 dp, ngày (text + chuỗi datetime Excel), CCCD giữ số 0
  đầu (dtype=str), map hình thức, row_no = dòng bảng tính, bỏ dòng trống.
- Resolve READ-ONLY: khớp/không thấy/fee cancelled/đợt draft/vượt tổng/FIFO nhiều
  đợt/trùng-trong-file/lệch tên/IDOR/lead xóa mềm/CMND 9 số/principal-first (bỏ phạt).
- create_preview_batch / preview_import: persist batch 'preview' + rows, CCCD lỗi →
  citizen_id NULL, thay preview cũ cùng file, file đã committed → ConflictError.

KHÔNG ghi Payment (đó là BV-3).
"""
import io
import itertools
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.models.finance import (
    Fee,
    Invoice,
    PaymentImportBatch,
    PaymentImportBatchStatusEnum,
    PaymentImportRow,
    PaymentImportRowStatusEnum,
)
from app.services import payment_import_service as pis
from app.utils.exceptions import BadRequest, ConflictError

MATCHED = PaymentImportRowStatusEnum.matched.value
WARNED = PaymentImportRowStatusEnum.warned.value
ERROR = PaymentImportRowStatusEnum.error.value

_phone_seq = itertools.count(1)


# =============================================================================
# Helpers
# =============================================================================
def _xlsx_bytes(rows: list) -> bytes:
    """rows[0] = header; phần còn lại = dữ liệu (ô có thể là date/datetime thật)."""
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _csv_bytes(rows: list) -> bytes:
    import csv

    buf = io.StringIO()
    w = csv.writer(buf)
    for r in rows:
        w.writerow(r)
    return buf.getvalue().encode("utf-8")


def _draft(
    citizen_id,
    amount,
    *,
    name="",
    row_no=2,
    method="cash",
    reference="",
    note="",
    payment_date=None,
    parse_error=None,
) -> "pis.RowDraft":
    return pis.RowDraft(
        row_no=row_no,
        citizen_id=citizen_id,
        name=name,
        amount=(Decimal(str(amount)) if amount is not None else None),
        payment_date=payment_date or date(2026, 9, 5),
        method_code=method,
        reference=reference,
        note=note,
        raw={pis.COL_CCCD: citizen_id, pis.COL_AMOUNT: str(amount)},
        parse_error=parse_error,
    )


async def _seed_tuition(
    db: AsyncSession,
    deps: dict,
    *,
    citizen_id: str,
    invoices: list,  # [(installment_no, amount, status, paid, penalty)]
    year: int = 2026,
    semester: int = 1,
    lead_name: str = "Nguyễn Văn An",
    unit_id: int = None,
    deleted_at: datetime = None,
):
    """Dựng chain Lead → AdmissionProfile(citizen_id) → Fee(tuition) → Invoice(s)."""
    lead = models.Lead(
        full_name=lead_name,
        phone=f"09{next(_phone_seq):08d}",
        source="bulk_test",
        unit_id=unit_id or deps["unit_id"],
        consultation_status_id=deps["initial_status_id"],
        deleted_at=deleted_at,
    )
    db.add(lead)
    await db.flush()

    profile = models.AdmissionProfile(
        lead_id=lead.id,
        status="submitted",
        academic_year=year,
        applied_rules={},
        citizen_id=citizen_id,
    )
    db.add(profile)
    await db.flush()

    fee = Fee(
        admission_profile_id=profile.id,
        fee_type="tuition",
        academic_year=year,
        semester_no=semester,
        base_amount=Decimal("100000000"),
        final_amount=Decimal("100000000"),
        status="invoiced",
    )
    db.add(fee)
    await db.flush()

    inv_objs = []
    for no, amount, st, paid, penalty in invoices:
        inv = Invoice(
            fee_id=fee.id,
            invoice_number=f"INV-T-{citizen_id}-{no}",
            installment_no=no,
            amount=Decimal(str(amount)),
            paid_amount=Decimal(str(paid)),
            penalty_amount=Decimal(str(penalty)),
            status=st,
            due_date=date(year, 9, 5),
        )
        db.add(inv)
        inv_objs.append(inv)
    await db.flush()
    return profile, fee, inv_objs


# =============================================================================
# Parse helpers (pure — no DB)
# =============================================================================
class TestParseAmount:
    def test_thousands_dot_separator(self):
        assert pis.parse_amount_vn("7.200.000") == Decimal("7200000")

    def test_decimal_comma(self):
        assert pis.parse_amount_vn("7.200.000,50") == Decimal("7200000.50")

    def test_float_string_from_excel(self):
        # "7200000.0" — nhóm cuối 1 chữ số → '.' là thập phân, không phải nghìn
        assert pis.parse_amount_vn("7200000.0") == Decimal("7200000.00")

    def test_quantize_three_decimals(self):
        # Finding 4: >2 chữ số thập phân phải quantize về 2 dp (cột Numeric(15,2))
        v = pis.parse_amount_vn("7.200.000,505")
        assert v == Decimal("7200000.51")
        assert v.as_tuple().exponent == -2

    def test_rejects_zero(self):
        with pytest.raises(ValueError):
            pis.parse_amount_vn("0")

    def test_rejects_negative(self):
        with pytest.raises(ValueError):
            pis.parse_amount_vn("-5000")

    def test_rejects_garbage(self):
        with pytest.raises(ValueError):
            pis.parse_amount_vn("abc")

    def test_nbsp_whitespace_separator(self):
        # File ngân hàng/Excel: '7 200 000' với non-breaking space (NBSP   /
        # narrow  ) — phải bỏ HẾT whitespace, không chỉ space thường.
        assert pis.parse_amount_vn("7 200 000") == Decimal("7200000")
        assert pis.parse_amount_vn("7 200 000") == Decimal("7200000")
        assert pis.parse_amount_vn("7 200 000") == Decimal("7200000")


class TestParseDate:
    def test_vn_slash(self):
        assert pis.parse_date_vn("05/09/2026") == date(2026, 9, 5)

    def test_vn_dash(self):
        assert pis.parse_date_vn("05-09-2026") == date(2026, 9, 5)

    def test_iso(self):
        assert pis.parse_date_vn("2026-09-05") == date(2026, 9, 5)

    def test_excel_datetime_string(self):
        # Finding 1: ô Date Excel đọc dtype=str → "2026-09-05 00:00:00" (kèm giờ)
        assert pis.parse_date_vn("2026-09-05 00:00:00") == date(2026, 9, 5)

    def test_excel_iso_t_separator(self):
        assert pis.parse_date_vn("2026-09-05T00:00:00") == date(2026, 9, 5)

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            pis.parse_date_vn("")

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            pis.parse_date_vn("hôm qua")

    def test_two_digit_year_rejected(self):
        # strptime %Y nuốt năm 2 số → 0026; phải chặn (BV-3 sẽ ghi Payment năm 0026).
        with pytest.raises(ValueError):
            pis.parse_date_vn("05/09/26")

    def test_out_of_range_year_rejected(self):
        with pytest.raises(ValueError):
            pis.parse_date_vn("05/09/1999")


# =============================================================================
# parse_template (builds real files)
# =============================================================================
class TestParseTemplate:
    def _header(self):
        return pis.TEMPLATE_COLS

    def test_cccd_leading_zero_preserved(self):
        # CCCD text "001234567890" KHÔNG bị cắt thành 1234567890
        content = _xlsx_bytes(
            [
                self._header(),
                [
                    "001234567890",
                    "Nguyễn Văn An",
                    "7.200.000",
                    "05/09/2026",
                    "TM",
                    "",
                    "",
                ],
            ]
        )
        drafts = pis.parse_template(content, "f.xlsx")
        assert len(drafts) == 1
        assert drafts[0].citizen_id == "001234567890"
        assert drafts[0].amount == Decimal("7200000")
        assert drafts[0].parse_error is None

    def test_excel_real_date_cell(self):
        # Finding 1 (regression chính): ô Date THẬT của Excel → không false-error
        content = _xlsx_bytes(
            [
                self._header(),
                ["001234567890", "An", "7.200.000", date(2026, 9, 5), "CK", "", ""],
            ]
        )
        drafts = pis.parse_template(content, "f.xlsx")
        assert drafts[0].parse_error is None
        assert drafts[0].payment_date == date(2026, 9, 5)
        assert drafts[0].method_code == "bank_transfer"

    def test_method_mapping(self):
        rows = [self._header()]
        for m in ("TM", "CK", "Chuyển khoản", "tiền mặt"):
            rows.append(["001234567890", "An", "1.000.000", "05/09/2026", m, "", ""])
        drafts = pis.parse_template(_xlsx_bytes(rows), "f.xlsx")
        assert [d.method_code for d in drafts] == [
            "cash",
            "bank_transfer",
            "bank_transfer",
            "cash",
        ]

    def test_invalid_method_sets_parse_error(self):
        content = _xlsx_bytes(
            [
                self._header(),
                ["001234567890", "An", "1.000.000", "05/09/2026", "Bitcoin", "", ""],
            ]
        )
        drafts = pis.parse_template(content, "f.xlsx")
        assert drafts[0].method_code is None
        assert "hình thức" in drafts[0].parse_error

    def test_row_no_matches_spreadsheet_and_skips_blank(self):
        # Finding 5: header = dòng 1; dòng trống bị bỏ; row_no khớp Excel
        content = _xlsx_bytes(
            [
                self._header(),
                ["", "", "", "", "", "", ""],  # dòng 2 — trống → bỏ
                [
                    "001234567890",
                    "An",
                    "1.000.000",
                    "05/09/2026",
                    "TM",
                    "",
                    "",
                ],  # dòng 3
            ]
        )
        drafts = pis.parse_template(content, "f.xlsx")
        assert len(drafts) == 1
        assert drafts[0].row_no == 3

    def test_missing_required_column_raises(self):
        content = _xlsx_bytes(
            [
                [pis.COL_CCCD, pis.COL_AMOUNT, pis.COL_DATE],  # thiếu "Hình thức"
                ["001234567890", "1.000.000", "05/09/2026"],
            ]
        )
        with pytest.raises(BadRequest):
            pis.parse_template(content, "f.xlsx")

    def test_csv_also_supported(self):
        content = _csv_bytes(
            [
                self._header(),
                [
                    "001234567890",
                    "An",
                    "1.000.000",
                    "05/09/2026",
                    "TM",
                    "PT-1",
                    "ghi chú",
                ],
            ]
        )
        drafts = pis.parse_template(content, "f.csv")
        assert drafts[0].citizen_id == "001234567890"
        assert drafts[0].reference == "PT-1"


# =============================================================================
# resolve_and_validate (DB, READ-ONLY)
# =============================================================================
class TestBuildTemplate:
    """Generator file mẫu (build_template) — pure, không qua DB."""

    def test_csv_has_bom_and_parses_back(self):
        content, media, fname = pis.build_template("csv")
        assert content[:3] == b"\xef\xbb\xbf"  # BOM utf-8-sig cho Excel VN
        assert fname.endswith(".csv")
        drafts = pis.parse_template(content, "t.csv")
        assert drafts[0].citizen_id == "001234567890"  # round-trip giữ số 0 đầu

    def test_xlsx_parses_back_with_text_cccd(self):
        content, media, fname = pis.build_template("xlsx")
        assert fname.endswith(".xlsx")
        assert "spreadsheet" in media
        drafts = pis.parse_template(content, "t.xlsx")
        assert len(drafts) == 1
        assert drafts[0].citizen_id == "001234567890"
        assert drafts[0].payment_date == date(2026, 9, 5)
        assert drafts[0].method_code == "cash"

    def test_xlsx_cccd_text_format_covers_full_range(self):
        # Finding 3: number_format='@' phải phủ tới HẾT MAX_IMPORT_ROWS (không chỉ
        # ~1000 dòng đầu) — nếu không file > N dòng mất số 0 đầu CCCD.
        import io as _io

        from openpyxl import load_workbook

        content, _, _ = pis.build_template("xlsx")
        ws = load_workbook(_io.BytesIO(content)).active
        cccd_col = pis.TEMPLATE_COLS.index(pis.COL_CCCD) + 1
        letter = ws.cell(row=1, column=cccd_col).column_letter
        last = pis.MAX_IMPORT_ROWS + 1  # dòng dữ liệu cuối cùng
        assert ws[f"{letter}{last}"].number_format == "@"

    def test_default_format_is_xlsx(self):
        _, _, fname = pis.build_template("")
        assert fname.endswith(".xlsx")


class TestResolveValidate:
    async def test_matched_single_invoice(self, db, seeded_dependencies):
        await _seed_tuition(
            db,
            seeded_dependencies,
            citizen_id="001234567890",
            invoices=[(1, "10000000", "issued", "0", "0")],
        )
        res = await pis.resolve_and_validate(
            db, [_draft("001234567890", "10000000")], 2026, 1, None
        )
        row = res.rows[0]
        assert row.status == MATCHED
        assert res.matched_count == 1 and res.failed_count == 0
        assert len(row.allocations) == 1
        assert row.allocations[0].amount == Decimal("10000000")
        assert res.total_amount == Decimal("10000000")

    async def test_cccd_not_found(self, db, seeded_dependencies):
        res = await pis.resolve_and_validate(
            db, [_draft("009999999999", "1000000")], 2026, 1, None
        )
        assert res.rows[0].status == ERROR
        assert "không tìm thấy" in res.rows[0].message

    async def test_cmnd_9_digits_is_error(self, db, seeded_dependencies):
        res = await pis.resolve_and_validate(
            db, [_draft("123456789", "1000000")], 2026, 1, None
        )
        assert res.rows[0].status == ERROR
        assert "12 chữ số" in res.rows[0].message

    async def test_fee_cancelled_only_is_error(self, db, seeded_dependencies):
        # Finding 3: fee cancelled vẫn giữ slot index → phải lọc status
        _, fee, _ = await _seed_tuition(
            db,
            seeded_dependencies,
            citizen_id="001234567890",
            invoices=[(1, "10000000", "issued", "0", "0")],
        )
        fee.status = "cancelled"
        await db.flush()
        res = await pis.resolve_and_validate(
            db, [_draft("001234567890", "1000000")], 2026, 1, None
        )
        assert res.rows[0].status == ERROR
        assert "học phí" in res.rows[0].message

    async def test_only_draft_invoice_is_error(self, db, seeded_dependencies):
        # Finding 12: đợt draft chưa phát hành → không payable → LỖI
        await _seed_tuition(
            db,
            seeded_dependencies,
            citizen_id="001234567890",
            invoices=[(1, "10000000", "draft", "0", "0")],
        )
        res = await pis.resolve_and_validate(
            db, [_draft("001234567890", "1000000")], 2026, 1, None
        )
        assert res.rows[0].status == ERROR
        assert "chưa phát hành" in res.rows[0].message

    async def test_overpay_total_principal_is_error(self, db, seeded_dependencies):
        await _seed_tuition(
            db,
            seeded_dependencies,
            citizen_id="001234567890",
            invoices=[(1, "10000000", "issued", "0", "0")],
        )
        res = await pis.resolve_and_validate(
            db, [_draft("001234567890", "10000001")], 2026, 1, None
        )
        assert res.rows[0].status == ERROR
        assert "vượt tổng còn nợ" in res.rows[0].message

    async def test_fifo_two_invoices_warns(self, db, seeded_dependencies):
        await _seed_tuition(
            db,
            seeded_dependencies,
            citizen_id="001234567890",
            invoices=[
                (1, "4000000", "issued", "0", "0"),
                (2, "6000000", "issued", "0", "0"),
            ],
        )
        res = await pis.resolve_and_validate(
            db, [_draft("001234567890", "7000000")], 2026, 1, None
        )
        row = res.rows[0]
        assert row.status == WARNED
        assert len(row.allocations) == 2
        assert row.allocations[0].amount == Decimal("4000000")  # đợt 1 đầy trước
        assert row.allocations[1].amount == Decimal("3000000")  # tràn 3tr sang đợt 2
        assert "phân bổ" in row.message

    async def test_duplicate_in_file_second_sees_reduced(self, db, seeded_dependencies):
        # Finding 9: 2 dòng cùng CCCD+kỳ → dòng 2 thấy số dư đã trừ
        await _seed_tuition(
            db,
            seeded_dependencies,
            citizen_id="001234567890",
            invoices=[(1, "10000000", "issued", "0", "0")],
        )
        res = await pis.resolve_and_validate(
            db,
            [
                _draft("001234567890", "6000000", row_no=2),
                _draft("001234567890", "6000000", row_no=3),
            ],
            2026,
            1,
            None,
        )
        assert res.rows[0].status == MATCHED
        assert res.rows[1].status == ERROR  # 6tr > 4tr còn lại
        assert "vượt tổng còn nợ" in res.rows[1].message

    async def test_name_mismatch_warns(self, db, seeded_dependencies):
        await _seed_tuition(
            db,
            seeded_dependencies,
            citizen_id="001234567890",
            lead_name="Nguyễn Văn An",
            invoices=[(1, "10000000", "issued", "0", "0")],
        )
        res = await pis.resolve_and_validate(
            db, [_draft("001234567890", "1000000", name="Trần Thị Bích")], 2026, 1, None
        )
        row = res.rows[0]
        assert row.status == WARNED
        assert "tên lệch" in row.message

    async def test_principal_first_ignores_penalty(self, db, seeded_dependencies):
        # Finding 8: principal_rem = amount − paid (KHÔNG ăn penalty).
        # invoice amount=10tr, penalty=1tr → remaining_amount(property)=11tr nhưng
        # bulk chỉ tính 10tr gốc.
        await _seed_tuition(
            db,
            seeded_dependencies,
            citizen_id="001234567890",
            invoices=[(1, "10000000", "issued", "0", "1000000")],
        )
        # trả đúng 10tr gốc → matched (1 alloc = 10tr)
        ok = await pis.resolve_and_validate(
            db, [_draft("001234567890", "10000000")], 2026, 1, None
        )
        assert ok.rows[0].status == MATCHED
        assert ok.rows[0].allocations[0].amount == Decimal("10000000")
        # trả 10tr + 1đ → vượt gốc 10tr (dù remaining gồm penalty là 11tr) → ERROR
        await _seed_tuition(
            db,
            seeded_dependencies,
            citizen_id="001234567891",
            invoices=[(1, "10000000", "issued", "0", "1000000")],
        )
        over = await pis.resolve_and_validate(
            db, [_draft("001234567891", "10000001")], 2026, 1, None
        )
        assert over.rows[0].status == ERROR
        assert "vượt tổng còn nợ" in over.rows[0].message

    async def test_partial_paid_principal_remaining(self, db, seeded_dependencies):
        # đã trả 4tr gốc → còn 6tr; trả 6tr → matched, trả 6tr+1 → error
        await _seed_tuition(
            db,
            seeded_dependencies,
            citizen_id="001234567890",
            invoices=[(1, "10000000", "partial", "4000000", "0")],
        )
        res = await pis.resolve_and_validate(
            db, [_draft("001234567890", "6000000")], 2026, 1, None
        )
        assert res.rows[0].status == MATCHED
        assert res.rows[0].allocations[0].amount == Decimal("6000000")

    async def test_idor_other_unit_not_found(
        self, db, seeded_dependencies, second_unit
    ):
        await _seed_tuition(
            db,
            seeded_dependencies,
            citizen_id="001234567890",
            unit_id=second_unit.id,
            invoices=[(1, "10000000", "issued", "0", "0")],
        )
        # kế toán unit 1001 → không thấy hồ sơ unit 2001
        scoped = await pis.resolve_and_validate(
            db,
            [_draft("001234567890", "1000000")],
            2026,
            1,
            seeded_dependencies["unit_id"],
        )
        assert scoped.rows[0].status == ERROR
        assert "không tìm thấy" in scoped.rows[0].message
        # admin (unit_id=None) → thấy
        glob = await pis.resolve_and_validate(
            db, [_draft("001234567890", "1000000")], 2026, 1, None
        )
        assert glob.rows[0].status == MATCHED

    async def test_soft_deleted_lead_not_found(self, db, seeded_dependencies):
        # Finding 2: hồ sơ của lead đã xóa mềm KHÔNG được khớp
        await _seed_tuition(
            db,
            seeded_dependencies,
            citizen_id="001234567890",
            deleted_at=datetime.now(timezone.utc),
            invoices=[(1, "10000000", "issued", "0", "0")],
        )
        res = await pis.resolve_and_validate(
            db, [_draft("001234567890", "1000000")], 2026, 1, None
        )
        assert res.rows[0].status == ERROR
        assert "không tìm thấy" in res.rows[0].message

    async def test_wrong_semester_is_error(self, db, seeded_dependencies):
        await _seed_tuition(
            db,
            seeded_dependencies,
            citizen_id="001234567890",
            semester=1,
            invoices=[(1, "10000000", "issued", "0", "0")],
        )
        res = await pis.resolve_and_validate(
            db, [_draft("001234567890", "1000000")], 2026, 2, None
        )  # hỏi HK2
        assert res.rows[0].status == ERROR
        assert "không có học phí" in res.rows[0].message


# =============================================================================
# create_preview_batch / preview_import (DB persistence)
# =============================================================================
class TestPreviewBatch:
    async def test_preview_import_persists_batch_and_rows(
        self, db, seeded_dependencies, admin_user
    ):
        await _seed_tuition(
            db,
            seeded_dependencies,
            citizen_id="001234567890",
            invoices=[(1, "10000000", "issued", "0", "0")],
        )
        content = _csv_bytes(
            [
                pis.TEMPLATE_COLS,
                [
                    "001234567890",
                    "Nguyễn Văn An",
                    "10.000.000",
                    "05/09/2026",
                    "TM",
                    "",
                    "",
                ],  # matched (tên khớp seed)
                ["009999999999", "X", "1.000.000", "05/09/2026", "TM", "", ""],  # error
            ]
        )
        batch, preview = await pis.preview_import(
            db,
            content=content,
            filename="thu.csv",
            academic_year=2026,
            semester_no=1,
            created_by_id=admin_user.id,
            unit_id=None,
        )
        await db.commit()

        assert batch.status == PaymentImportBatchStatusEnum.preview.value
        assert batch.row_count == 2
        assert batch.matched_count == 1 and batch.failed_count == 1
        assert batch.total_amount == Decimal("10000000")

        rows = (
            (
                await db.execute(
                    select(PaymentImportRow)
                    .where(PaymentImportRow.batch_id == batch.id)
                    .order_by(PaymentImportRow.row_no)
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 2
        assert rows[0].status == MATCHED and rows[0].citizen_id == "001234567890"
        assert rows[0].resolved_profile_id is not None
        assert rows[1].status == ERROR

    async def test_invalid_cccd_row_stores_null_citizen_id(
        self, db, seeded_dependencies, admin_user
    ):
        # CCCD 9 số (CMND) → cột String(12) lưu NULL, raw giữ giá trị gốc
        content = _csv_bytes(
            [
                pis.TEMPLATE_COLS,
                ["123456789", "X", "1.000.000", "05/09/2026", "TM", "", ""],
            ]
        )
        batch, _ = await pis.preview_import(
            db,
            content=content,
            filename="thu.csv",
            academic_year=2026,
            semester_no=1,
            created_by_id=admin_user.id,
            unit_id=None,
        )
        await db.commit()
        row = (
            await db.execute(
                select(PaymentImportRow).where(PaymentImportRow.batch_id == batch.id)
            )
        ).scalar_one()
        assert row.status == ERROR
        assert row.citizen_id is None  # không tràn cột String(12)
        assert row.raw.get(pis.COL_CCCD) == "123456789"  # gốc vẫn audit được

    async def test_replaces_stale_preview_same_file(
        self, db, seeded_dependencies, admin_user
    ):
        sha = "a" * 64
        p1 = pis.PreviewResult(
            rows=[pis.RowResult(row_no=2, status=ERROR, raw={})],
            matched_count=0,
            warned_count=0,
            failed_count=1,
            total_amount=Decimal("0"),
        )
        b1 = await pis.create_preview_batch(
            db,
            preview=p1,
            academic_year=2026,
            semester_no=1,
            file_name="f.csv",
            file_sha256_hex=sha,
            created_by_id=admin_user.id,
        )
        await db.flush()
        b1_id = b1.id

        # preview lại CÙNG file (sha) — nội dung khác (2 dòng) → thay batch cũ
        p2 = pis.PreviewResult(
            rows=[
                pis.RowResult(row_no=2, status=ERROR, raw={}),
                pis.RowResult(row_no=3, status=ERROR, raw={}),
            ],
            matched_count=0,
            warned_count=0,
            failed_count=2,
            total_amount=Decimal("0"),
        )
        b2 = await pis.create_preview_batch(
            db,
            preview=p2,
            academic_year=2026,
            semester_no=1,
            file_name="f.csv",
            file_sha256_hex=sha,
            created_by_id=admin_user.id,
        )
        await db.commit()

        batches = (
            (
                await db.execute(
                    select(PaymentImportBatch).where(
                        PaymentImportBatch.file_sha256 == sha
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(batches) == 1  # batch cũ đã bị thay
        assert batches[0].id == b2.id
        assert batches[0].row_count == 2
        # child rows của batch cũ phải bị cascade-xóa (không để mồ côi)
        old_rows = (
            (
                await db.execute(
                    select(PaymentImportRow).where(PaymentImportRow.batch_id == b1_id)
                )
            )
            .scalars()
            .all()
        )
        assert old_rows == []

    async def test_committed_file_conflicts(self, db, seeded_dependencies, admin_user):
        sha = "b" * 64
        committed = PaymentImportBatch(
            academic_year=2026,
            semester_no=1,
            file_name="old.csv",
            file_sha256=sha,
            status=PaymentImportBatchStatusEnum.committed.value,
            committed_at=datetime.now(timezone.utc),
            row_count=1,
            matched_count=1,
            warned_count=0,
            failed_count=0,
            total_amount=Decimal("1000000"),
            created_by_id=admin_user.id,
        )
        db.add(committed)
        await db.flush()

        p = pis.PreviewResult(
            rows=[],
            matched_count=0,
            warned_count=0,
            failed_count=0,
            total_amount=Decimal("0"),
        )
        with pytest.raises(ConflictError):
            await pis.create_preview_batch(
                db,
                preview=p,
                academic_year=2026,
                semester_no=1,
                file_name="new.csv",
                file_sha256_hex=sha,
                created_by_id=admin_user.id,
            )

    async def test_integrity_error_maps_to_conflict(
        self, db, seeded_dependencies, admin_user, monkeypatch
    ):
        # Test-gap #7: nhánh race 2 upload cùng file lọt pre-check → partial-unique
        # nổ ở flush → service phải rollback + ConflictError (KHÔNG để thành 500).
        # Mô phỏng bằng cách ép flush ném IntegrityError.
        from sqlalchemy.exc import IntegrityError

        async def _boom(*a, **k):
            raise IntegrityError("INSERT", {}, Exception("dup file_sha256"))

        monkeypatch.setattr(db, "flush", _boom)
        p = pis.PreviewResult(
            rows=[],
            matched_count=0,
            warned_count=0,
            failed_count=0,
            total_amount=Decimal("0"),
        )
        with pytest.raises(ConflictError):
            await pis.create_preview_batch(
                db,
                preview=p,
                academic_year=2026,
                semester_no=1,
                file_name="race.csv",
                file_sha256_hex="c" * 64,
                created_by_id=admin_user.id,
            )
