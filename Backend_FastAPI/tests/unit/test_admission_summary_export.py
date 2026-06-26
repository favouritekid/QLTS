"""Pure-logic unit tests for the admission-summary Excel export (no DB).

Covers the DB-free logic: lead bucketing priority, officer short-name safety
(whitespace crash guard, CSV-injection sanitize, collision disambiguation),
and the workbook aggregation (exclusive 5-bucket funnel sums to total leads,
'Đã nộp' counts submitted-or-beyond).
"""

from app.services.admission_summary_export_service import (
    AdmissionSummaryExportService,
    _lead_bucket,
    _officer_short_names,
)


# ----------------------------------------------------------------- _lead_bucket
def test_lead_bucket_priority_money_first():
    # paid tuition wins even over a terminal consultation status
    assert _lead_bucket(True, True, "sts20") == "hocphi"
    assert _lead_bucket(True, False, "sts06") == "hocphi"
    # paid application (no tuition) → lephi, even over 'đã dừng'
    assert _lead_bucket(False, True, "sts20") == "lephi"


def test_lead_bucket_no_money_falls_to_status():
    assert _lead_bucket(False, False, "sts20") == "dung"
    assert _lead_bucket(False, False, "sts16") == "dung"
    assert _lead_bucket(False, False, "sts00") == "chua"
    assert _lead_bucket(False, False, "sts02") == "chua"
    assert _lead_bucket(False, False, None) == "chua"
    assert _lead_bucket(False, False, "sts06") == "dang"


# ------------------------------------------------------- _officer_short_names
def test_officer_short_name_whitespace_does_not_crash():
    # whitespace-only name is truthy but split() == [] → must not IndexError
    assert _officer_short_names({1: "   "}, [1]) == {1: "#1"}
    assert _officer_short_names({1: None}, [1]) == {1: "#1"}


def test_officer_short_name_sanitizes_formula_injection():
    out = _officer_short_names({1: "=cmd|'/c calc'!A1"}, [1])
    assert out[1].startswith("'")  # neutralized for Excel


def test_officer_short_name_disambiguates_collisions():
    out = _officer_short_names({1: "Nguyễn Văn An", 2: "Trần Thị An"}, [1, 2])
    # both last-token "An" → fall back to full names, must stay distinct
    assert out[1] != out[2]
    assert out[1] == "Nguyễn Văn An" and out[2] == "Trần Thị An"


def test_officer_short_name_plain_uses_last_token():
    assert _officer_short_names({5: "Nguyễn Văn An"}, [5]) == {5: "An"}


# ------------------------------------------------------------- _build_workbook
def _rows():
    leads = [
        # (bucket, hồ sơ)
        dict(
            id=1,
            pid=1,
            cs="sts06",
            off=10,
            source="website",
            referrer_id=None,
            pstatus="draft",
            has_app=False,
            has_tui=False,
        ),
        dict(
            id=2,
            pid=1,
            cs="sts13",
            off=10,
            source="website",
            referrer_id=None,
            pstatus="submitted",
            has_app=True,
            has_tui=False,
        ),
        # approved profile + paid tuition → hocphi + counts as 'đã nộp'
        dict(
            id=3,
            pid=1,
            cs="sts10",
            off=11,
            source="referral",
            referrer_id=None,
            pstatus="approved",
            has_app=True,
            has_tui=True,
        ),
        dict(
            id=4,
            pid=1,
            cs="sts20",
            off=12,
            source="website",
            referrer_id=None,
            pstatus=None,
            has_app=False,
            has_tui=False,
        ),
        # unassigned officer
        dict(
            id=5,
            pid=1,
            cs="sts00",
            off=None,
            source="website",
            referrer_id=None,
            pstatus=None,
            has_app=False,
            has_tui=False,
        ),
        # offering points to a major not in catalog → '(Chưa xác định ngành)'
        dict(
            id=6,
            pid=999,
            cs="sts06",
            off=10,
            source="website",
            referrer_id=None,
            pstatus=None,
            has_app=False,
            has_tui=False,
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
    # row 6 = TỔNG; col 6 = Tổng lead; cols 7..11 = 5 buckets; 12=Nháp 13=Đã nộp
    assert ws.cell(6, 6).value == len(leads)  # 6 leads
    bucket_sum = sum(ws.cell(6, c).value for c in range(7, 12))
    assert bucket_sum == len(leads)  # exclusive funnel reconciles
    assert ws.cell(6, 12).value == 1  # Nháp: only id=1 draft
    # Đã nộp counts submitted-or-beyond: id=2 submitted + id=3 approved
    assert ws.cell(6, 13).value == 2


def test_build_workbook_handles_zero_officers():
    leads, _, majors = _rows()
    svc = AdmissionSummaryExportService(db=None)
    # no officers in scope → sheet 2 still renders (title only), no crash
    wb = svc._build_workbook(2026, leads, [], majors)
    assert "Chia theo nhân viên" in wb.sheetnames
    assert wb["Số liệu chung"].cell(6, 6).value == len(leads)
