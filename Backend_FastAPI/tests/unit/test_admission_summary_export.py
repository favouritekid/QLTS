"""Pure-logic unit tests for the admission-summary Excel export (no DB).

Covers the DB-free logic: officer short-name safety (whitespace crash guard,
CSV-injection sanitize, collision disambiguation) and the workbook aggregation
for the 14-column "PHÂN LOẠI" layout (Đang tư vấn / Hồ sơ / Lệ phí / Học phí).
"""

from app.services.admission_summary_export_service import (
    AdmissionSummaryExportService,
    _officer_short_names,
)


# ------------------------------------------------------- _officer_short_names
def test_officer_short_name_whitespace_does_not_crash():
    # whitespace-only name is truthy but split() == [] → must not IndexError
    assert _officer_short_names({1: "   "}, [1]) == {1: "#1"}
    assert _officer_short_names({1: None}, [1]) == {1: "#1"}


def test_officer_short_name_sanitizes_formula_injection():
    # single-token formula → prefixed with ' (neutralized for Excel)
    assert _officer_short_names({1: "=cmd"}, [1])[1].startswith("'")
    # output must never begin with a formula-trigger char
    for nm in ("=1+1", "@SUM", "+x", "Trần |pipe"):
        v = _officer_short_names({9: nm}, [9])[9]
        assert v and v[0] not in ("=", "+", "-", "@", "|", "\t")


def test_officer_short_name_disambiguates_collisions():
    out = _officer_short_names({1: "Nguyễn Văn An", 2: "Trần Thị An"}, [1, 2])
    # both last-token "An" → fall back to full names, must stay distinct
    assert out[1] != out[2]
    assert out[1] == "Nguyễn Văn An" and out[2] == "Trần Thị An"


def test_officer_short_name_plain_uses_last_token():
    assert _officer_short_names({5: "Nguyễn Văn An"}, [5]) == {5: "An"}


# ------------------------------------------------------------- _build_workbook
def _lead(**kw):
    """Row shape the workbook reads — defaults = 'không hoạt động gì'."""
    base = dict(
        id=0,
        pid=1,
        cs=None,
        off=None,
        pstatus=None,
        has_doc_debt=False,
        has_app=False,
        hk1_partial=False,
        hk1_settled=False,
        hk1_final=0,
        hk1_paid=0,
    )
    base.update(kw)
    return base


def _rows():
    leads = [
        # đang tư vấn sts00 (Chưa tiếp cận), chưa có hồ sơ
        _lead(id=1, cs="sts00", off=10),
        # hồ sơ nháp (Chưa hoàn thiện) + đã đóng lệ phí; cs sts06 → Đồng ý/Hẹn
        _lead(id=2, cs="sts06", off=10, pstatus="draft", has_app=True),
        # đã nộp + NỢ giấy tờ (Hoàn thiện 1 phần) + lệ phí + học phí partial
        _lead(
            id=3,
            cs="sts13",
            off=11,
            pstatus="submitted",
            has_doc_debt=True,
            has_app=True,
            hk1_partial=True,
            hk1_final=10_000_000,
            hk1_paid=3_000_000,
        ),
        # đã nộp + đủ giấy tờ (Đủ điều kiện) + lệ phí + đóng đủ HK1
        _lead(
            id=4,
            cs="sts10",
            off=12,
            pstatus="approved",
            has_app=True,
            hk1_settled=True,
            hk1_final=12_000_000,
            hk1_paid=12_000_000,
        ),
        # tư vấn sts04 (Từ chối/Ngừng), officer chưa phân công
        _lead(id=5, cs="sts04", off=None),
        # pid ngoài catalog → '(Chưa xác định ngành)'; partial VÀ settled cùng lúc
        # → chỉ được đếm ở "Đóng đủ HK1", KHÔNG đếm lại ở "Đóng một phần".
        _lead(
            id=6,
            pid=999,
            cs="sts02",
            off=10,
            pstatus="submitted",
            has_app=True,
            hk1_partial=True,
            hk1_settled=True,
            hk1_final=5_000_000,
            hk1_paid=5_000_000,
        ),
    ]
    officers = [
        dict(id=10, nm="Nguyễn Văn An"),
        dict(id=11, nm="   "),  # whitespace → must not crash
        dict(id=12, nm="Trần Thị An"),  # last-name collision with id 10
        dict(id=13, nm="=cmd|calc"),  # injection → sanitized header
    ]
    majors = [dict(id=1, code="6480201", name="CNTT", degree_level="Cao đẳng")]
    return leads, officers, majors


def test_build_workbook_structure_and_totals():
    leads, officers, majors = _rows()
    svc = AdmissionSummaryExportService(db=None)
    wb = svc._build_workbook(2026, leads, officers, majors)

    assert wb.sheetnames == [
        "Số liệu chung",
        "Chia theo nhân viên",
        "Quy ước & ghi chú",
    ]
    ws = wb["Số liệu chung"]
    # Layout: cột 6 = Tổng lead; 7-11 = Đang tư vấn; 12-15 = Hồ sơ;
    # 16 = Lệ phí; 17-20 = Học phí. Hàng 7 = TỔNG CỘNG.
    assert ws.cell(7, 6).value == 6  # Tổng lead
    # Đang tư vấn (chỉ lead đang ở phase tư vấn — id3/id4 đã sang phase khác)
    assert ws.cell(7, 7).value == 1  # Chưa tiếp cận (sts00)
    assert ws.cell(7, 8).value == 1  # Đã kết nối (sts02, id6)
    assert ws.cell(7, 10).value == 1  # Đồng ý tư vấn/Hẹn liên hệ (sts06)
    assert ws.cell(7, 11).value == 1  # Từ chối/Đã ngừng (sts04)
    # Hồ sơ
    assert ws.cell(7, 12).value == 1  # Chưa hoàn thiện (draft: id2)
    assert ws.cell(7, 13).value == 1  # Hoàn thiện 1 phần (nộp+nợ: id3)
    assert ws.cell(7, 14).value == 2  # Đủ điều kiện (id4, id6)
    assert ws.cell(7, 15).value == 4  # Tổng hồ sơ
    # Tổng hồ sơ == cộng 3 cột con
    assert ws.cell(7, 15).value == (
        ws.cell(7, 12).value + ws.cell(7, 13).value + ws.cell(7, 14).value
    )
    # Lệ phí (id2,3,4,6)
    assert ws.cell(7, 16).value == 4
    # Học phí: Đóng một phần loại trừ Đóng đủ HK1 (id6 partial+settled → chỉ đủ)
    assert ws.cell(7, 17).value == 1  # Đóng một phần (chỉ id3)
    assert ws.cell(7, 18).value == 2  # Đóng đủ HK1 (id4, id6)
    assert ws.cell(7, 19).value == 27_000_000  # Tổng học phí (10+12+5)
    assert ws.cell(7, 20).value == 20_000_000  # Doanh thu (3+12+5)


def test_build_workbook_handles_zero_officers():
    leads, _, majors = _rows()
    svc = AdmissionSummaryExportService(db=None)
    # no officers in scope → sheet 2 still renders (Chưa PC only), no crash
    wb = svc._build_workbook(2026, leads, [], majors)
    assert "Chia theo nhân viên" in wb.sheetnames
    assert wb["Số liệu chung"].cell(7, 6).value == len(leads)
