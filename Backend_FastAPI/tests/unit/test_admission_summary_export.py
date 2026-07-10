"""Pure-logic unit tests for the admission-summary Excel export (no DB).

Covers the DB-free logic: officer short-name safety (whitespace crash guard,
CSV-injection sanitize, collision disambiguation) and the FUNNEL workbook
aggregation — each lead lands in exactly one of the 11 funnel columns
(Đang tư vấn / Hồ sơ / Lệ phí / Học phí) so they sum to Tổng lead; plus the
reference block (Tổng hồ sơ đã tạo) that counts every profile regardless of
funnel stage.
"""

from app.services.admission_summary_export_service import (
    AdmissionSummaryExportService,
    _officer_short_names,
)


# ------------------------------------------------------- _officer_short_names
def test_officer_short_name_whitespace_does_not_crash():
    assert _officer_short_names({1: "   "}, [1]) == {1: "#1"}
    assert _officer_short_names({1: None}, [1]) == {1: "#1"}


def test_officer_short_name_sanitizes_formula_injection():
    assert _officer_short_names({1: "=cmd"}, [1])[1].startswith("'")
    for nm in ("=1+1", "@SUM", "+x", "Trần |pipe"):
        v = _officer_short_names({9: nm}, [9])[9]
        assert v and v[0] not in ("=", "+", "-", "@", "|", "\t")


def test_officer_short_name_disambiguates_collisions():
    out = _officer_short_names({1: "Nguyễn Văn An", 2: "Trần Thị An"}, [1, 2])
    assert out[1] != out[2]
    assert out[1] == "Nguyễn Văn An" and out[2] == "Trần Thị An"


def test_officer_short_name_plain_uses_last_token():
    assert _officer_short_names({5: "Nguyễn Văn An"}, [5]) == {5: "An"}


# ------------------------------------------------------------- _build_workbook
def _lead(**kw):
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
        # Đang tư vấn (chưa có hồ sơ)
        _lead(id=1, cs="sts00", off=10),  # Chưa tiếp cận
        _lead(id=2, cs="sts04", off=10),  # Từ chối/Đã ngừng
        # Hồ sơ (có hồ sơ, chưa đóng phí nào)
        _lead(id=3, cs="sts06", off=11, pstatus="draft"),  # Chưa hoàn thiện
        _lead(
            id=4, cs="sts07", off=11, pstatus="submitted", has_doc_debt=True
        ),  # 1 phần
        _lead(id=5, cs="sts07", off=12, pstatus="submitted"),  # Đủ điều kiện
        # Lệ phí (đóng lệ phí, chưa học phí)
        _lead(id=6, cs="sts13", off=12, pstatus="submitted", has_app=True),
        # Học phí
        _lead(
            id=7,
            cs="sts14",
            off=10,
            pstatus="approved",
            has_app=True,
            hk1_partial=True,
            hk1_final=10_000_000,
            hk1_paid=3_000_000,
        ),  # Đóng một phần
        _lead(
            id=8,
            cs="sts10",
            off=11,
            pstatus="approved",
            has_app=True,
            hk1_settled=True,
            hk1_final=12_000_000,
            hk1_paid=12_000_000,
        ),  # Đóng đủ HK1
        # edge: partial VÀ settled → chỉ "Đóng đủ HK1"; pid ngoài catalog → NONE
        _lead(
            id=9,
            pid=999,
            cs="sts10",
            off=12,
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
        dict(id=11, nm="   "),
        dict(id=12, nm="Trần Thị An"),
        dict(id=13, nm="=cmd|calc"),
    ]
    majors = [dict(id=1, code="6480201", name="CNTT", degree_level="Cao đẳng")]
    return leads, officers, majors


def test_build_workbook_funnel_sums_to_total():
    leads, officers, majors = _rows()
    svc = AdmissionSummaryExportService(db=None)
    wb = svc._build_workbook(2026, leads, officers, majors)

    assert wb.sheetnames == [
        "Số liệu chung",
        "Chia theo nhân viên",
        "Quy ước & ghi chú",
    ]
    ws = wb["Số liệu chung"]
    # Cột: 6=Tổng lead | 7-11 Tư vấn | 12-14 Hồ sơ | 15 Lệ phí |
    #      16-17 Học phí (đếm) | 18-19 Học phí (tiền) | 20-23 Tham chiếu. TỔNG=row 7.
    assert ws.cell(7, 6).value == 9  # Tổng lead
    # Đang tư vấn
    assert ws.cell(7, 7).value == 1  # Chưa tiếp cận (sts00)
    assert ws.cell(7, 11).value == 1  # Từ chối/Đã ngừng (sts04)
    # Hồ sơ (chưa đóng phí)
    assert ws.cell(7, 12).value == 1  # Chưa hoàn thiện (draft)
    assert ws.cell(7, 13).value == 1  # Hoàn thiện 1 phần
    assert ws.cell(7, 14).value == 1  # Đủ điều kiện
    # Lệ phí
    assert ws.cell(7, 15).value == 1
    # Học phí (đếm) — id9 partial+settled chỉ vào "Đóng đủ HK1"
    assert ws.cell(7, 16).value == 1  # Đóng một phần (id7)
    assert ws.cell(7, 17).value == 2  # Đóng đủ HK1 (id8, id9)
    # PHỄU: 11 cột đếm (7-17) CỘNG = Tổng lead
    funnel = sum(ws.cell(7, c).value for c in range(7, 18))
    assert funnel == 9
    # Tiền
    assert ws.cell(7, 18).value == 27_000_000  # Tổng học phí (10+12+5)
    assert ws.cell(7, 19).value == 20_000_000  # Doanh thu (3+12+5)
    # Tham chiếu: tổng hồ sơ đã tạo = mọi profile (7), KHÁC nhóm Hồ sơ phễu (3)
    assert ws.cell(7, 20).value == 1  # ref Chưa hoàn thiện
    assert ws.cell(7, 21).value == 1  # ref Hoàn thiện 1 phần
    assert ws.cell(7, 22).value == 5  # ref Đủ điều kiện
    assert ws.cell(7, 23).value == 7  # ref Tổng hồ sơ (mọi giai đoạn)
    assert ws.cell(7, 23).value == (
        ws.cell(7, 20).value + ws.cell(7, 21).value + ws.cell(7, 22).value
    )


def test_build_workbook_handles_zero_officers():
    leads, _, majors = _rows()
    svc = AdmissionSummaryExportService(db=None)
    wb = svc._build_workbook(2026, leads, [], majors)
    assert "Chia theo nhân viên" in wb.sheetnames
    assert wb["Số liệu chung"].cell(7, 6).value == len(leads)
